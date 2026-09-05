import gzip
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import event as sqlalchemy_event
from sqlalchemy.orm import sessionmaker

from app.db.base import Base
from app.digests.config import parse_digest_task_config
from app.digests.runner import determine_digest_window
from app.models.digest import DigestItem, DigestLog
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.sync.client import CurlTransport, run_once
from app.sync.importer import import_file
from app.sync.receipts import make_receipt, receipt_path
from app.sync.receiver import app
from app.sync.transfer import SyncError, _sign, build_batch, import_batch, read_batch, write_batch
from tests.test_sync_transfer import _document

SECRET = "test-sync-secret"
SOURCE = "oci-overseas"
T0 = datetime(2026, 8, 31, tzinfo=timezone.utc)
T1 = T0 + timedelta(days=1)
T2 = T1 + timedelta(hours=1)


@pytest.fixture
def destination(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'destination.db'}")

    @sqlalchemy_event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine)

    @contextmanager
    def session_factory():
        with factory.begin() as db:
            yield db

    yield session_factory
    engine.dispose()


def add_graph(session):
    doc = _document()
    session.add(doc)
    session.flush()
    event = NormalizedEvent(
        event_id="event-1",
        document_id=doc.document_id,
        title=doc.title,
        event_type="policy_change",
        severity="medium",
        sentiment="neutral",
        actionability="monitor",
        detected_at=doc.observed_at,
        created_at=doc.created_at,
    )
    session.add(event)
    session.flush()
    return doc, event


def add_digest(session, event=None, digest_id="late-digest"):
    digest = DigestLog(
        digest_id=digest_id,
        digest_type="important_daily",
        outlet_id=digest_id,
        channel="none",
        title="Late daily digest",
        body="Original",
        status="skipped",
        window_start=T0,
        window_end=T1,
        created_at=T1,
        updated_at=T1,
    )
    session.add(digest)
    session.flush()
    if event:
        session.add(
            DigestItem(
                digest_id=digest_id, event_id=event.event_id, rank=1, priority="p2", created_at=T1
            )
        )
        session.flush()
    return digest


def test_late_digest_and_empty_digest_have_independent_cursor(session, destination):
    doc, event = add_graph(session)
    initial = build_batch(session, secret=SECRET, until=T1, digest_until=T1)
    with destination() as target:
        import_batch(target, initial, secret=SECRET)
    add_digest(session, event)
    add_digest(session, digest_id="empty-digest")
    batch = build_batch(
        session, secret=SECRET, since=T1, until=T2, digest_since=T1, digest_until=T2
    )
    assert len(batch["payload"]["digests"]) == 2
    assert [d["document_id"] for d in batch["payload"]["documents"]] == [doc.document_id]
    with destination() as target:
        counts = import_batch(target, batch, secret=SECRET)
        assert counts["documents_existing"] == 1
        assert counts["digests_added"] == 2
        assert target.query(DigestItem).count() == 1
    with destination() as target:
        import_batch(target, batch, secret=SECRET)
        assert target.query(DigestLog).count() == 2
        assert target.query(NormalizedEvent).count() == 1
        assert target.query(DigestItem).count() == 1


def test_late_normalization_includes_old_document(session):
    doc, event = add_graph(session)
    event.created_at = T1
    session.flush()
    batch = build_batch(session, secret=SECRET, since=T1, until=T2, digest_since=T1)
    assert len(batch["payload"]["documents"]) == 1
    assert len(batch["payload"]["events"]) == 1


def test_digest_update_is_monotonic_and_does_not_advance_local_window(session, destination):
    digest = add_digest(session)
    first = build_batch(session, secret=SECRET, until=T2)
    with destination() as target:
        import_batch(target, first, secret=SECRET)
        local_start, _ = determine_digest_window(
            target, "important_daily", T2, parse_digest_task_config({})
        )
        assert local_start < T0.replace(tzinfo=None)
    digest.body, digest.updated_at = "Corrected", T2
    session.flush()
    second = build_batch(
        session, secret=SECRET, since=T2, until=T2 + timedelta(hours=1), digest_since=T2
    )
    with destination() as target:
        counts = import_batch(target, second, secret=SECRET)
        assert counts["digests_updated"] == 1
    with destination() as target:
        import_batch(target, first, secret=SECRET)
        assert target.query(DigestLog).one().body == "Corrected"
        assert target.query(DigestLog).one().source_instance == SOURCE


def test_sender_waits_for_actual_import_and_reuses_batch(
    session, destination, tmp_path, monkeypatch
):
    add_graph(session)
    inbox = tmp_path / "receiver" / "inbox"
    receipts = inbox.parent / "receipts"
    monkeypatch.setenv("WORLDNET_SYNC_SECRET", SECRET)
    monkeypatch.setenv("WORLDNET_SYNC_INBOX_DIRECTORY", str(inbox))
    exports = []

    def export(**windows):
        exports.append(windows)
        return build_batch(session, secret=SECRET, **windows)

    with TestClient(app) as client:

        def transport(method, batch_id, path=None):
            headers = {"Authorization": f"Bearer {SECRET}", "X-WorldNet-Source-Instance": SOURCE}
            response = (
                client.post("/upload", content=path.read_bytes(), headers=headers)
                if method == "POST"
                else client.get(f"/batches/{batch_id}", headers=headers)
            )
            assert response.is_success
            return response.json()

        sender = tmp_path / "sender"
        first = run_once(
            sender,
            secret=SECRET,
            source_instance=SOURCE,
            exporter=export,
            transport=transport,
            now=T1,
        )
        assert first["status"] == "pending"
        assert not (sender / "cursors.json").exists()
        path = next(inbox.glob("*.json.gz"))
        import_file(
            path,
            session_factory=destination,
            secret=SECRET,
            expected_source_instance=SOURCE,
            receipts_dir=receipts,
            archive_dir=inbox.parent / "processed",
        )
        second = run_once(
            sender,
            secret=SECRET,
            source_instance=SOURCE,
            exporter=export,
            transport=transport,
            now=T2,
        )
        assert second["status"] == "imported"
        assert len(exports) == 1
        state = json.loads((sender / "cursors.json").read_text())
        assert state["document_until"] == T1.isoformat()
        assert state["digest_until"] == T1.isoformat()
        assert list(inbox.glob("*.json.gz")) == []  # receipt handles retries after archival
        assert list((sender / "outbox").glob("*.json.gz")) == []
        run_once(
            sender,
            secret=SECRET,
            source_instance=SOURCE,
            exporter=export,
            transport=transport,
            now=T2,
        )
        assert exports[1]["since"] == T1 - timedelta(minutes=5)
        assert exports[1]["digest_since"] == T1 - timedelta(minutes=5)


def test_import_commit_failure_produces_failed_receipt_and_retains_file(
    session, destination, tmp_path
):
    add_graph(session)
    batch = build_batch(session, secret=SECRET, until=T1)
    path = write_batch(batch, tmp_path / "inbox" / "batch.json.gz")

    @contextmanager
    def fail_commit():
        with destination() as target:
            yield target
            raise RuntimeError("simulated commit failure")

    with pytest.raises(RuntimeError):
        import_file(
            path,
            session_factory=fail_commit,
            secret=SECRET,
            expected_source_instance=SOURCE,
            receipts_dir=tmp_path / "receipts",
        )
    receipt = json.loads(
        receipt_path(tmp_path / "receipts", batch["payload"]["batch_id"]).read_text()
    )
    assert receipt["payload"]["status"] == "failed"
    assert path.exists()
    with destination() as target:
        assert target.query(SourceDocument).count() == 0
    import_file(
        path,
        session_factory=destination,
        secret=SECRET,
        expected_source_instance=SOURCE,
        receipts_dir=tmp_path / "receipts",
    )
    receipt = json.loads(
        receipt_path(tmp_path / "receipts", batch["payload"]["batch_id"]).read_text()
    )
    assert receipt["payload"]["status"] == "imported"


@pytest.mark.parametrize("failure", ["network", "tampered", "wrong-batch", "failed"])
def test_failed_or_untrusted_receipt_never_advances_cursor(session, tmp_path, failure):
    batch = build_batch(session, secret=SECRET, until=T1, digest_until=T1)

    def transport(method, batch_id, path=None):
        if method == "POST":
            return {"status": "accepted", "batch_id": batch_id}
        if failure == "network":
            raise SyncError("network down")
        receipt = make_receipt(
            batch, secret=SECRET, status="failed" if failure == "failed" else "imported"
        )
        if failure == "tampered":
            receipt["payload"]["counts"] = {"documents_added": 999}
        if failure == "wrong-batch":
            receipt["payload"]["batch_signature"] = "different-batch"
            receipt["signature"] = _sign(receipt["payload"], SECRET)
        return receipt

    with pytest.raises(SyncError):
        run_once(
            tmp_path,
            secret=SECRET,
            source_instance=SOURCE,
            exporter=lambda **_: batch,
            transport=transport,
            now=T1,
        )
    assert not (tmp_path / "cursors.json").exists()
    assert len(list((tmp_path / "outbox").glob("*.json.gz"))) == 1


def test_receiver_rejects_batch_id_collision_and_protects_receipts(session, tmp_path, monkeypatch):
    monkeypatch.setenv("WORLDNET_SYNC_SECRET", SECRET)
    monkeypatch.setenv("WORLDNET_SYNC_INBOX_DIRECTORY", str(tmp_path / "inbox"))
    batch = build_batch(session, secret=SECRET)
    headers = {"Authorization": f"Bearer {SECRET}", "X-WorldNet-Source-Instance": SOURCE}
    with TestClient(app) as client:
        body = gzip.compress(json.dumps(batch).encode())
        assert client.post("/upload", content=body, headers=headers).status_code == 201
        batch["payload"]["window_start"] = T0.isoformat()
        batch["signature"] = _sign(batch["payload"], SECRET)
        assert (
            client.post(
                "/upload", content=gzip.compress(json.dumps(batch).encode()), headers=headers
            ).status_code
            == 409
        )
        assert client.get(f"/batches/{batch['payload']['batch_id']}").status_code == 401
    assert not list((tmp_path / "inbox").glob("*.part"))


def test_decompressed_batch_limit(tmp_path):
    path = tmp_path / "bomb.gz"
    path.write_bytes(gzip.compress(b" " * 20000))
    with pytest.raises(SyncError, match="too large"):
        read_batch(path, max_bytes=1000)


def test_legacy_cursor_backfills_digest_history(session, tmp_path):
    (tmp_path / "last_successful_export").write_text(T1.isoformat())
    windows = []

    def export(**kwargs):
        windows.append(kwargs)
        return build_batch(session, secret=SECRET, **kwargs)

    def transport(method, batch_id, path=None):
        return {"status": "accepted" if method == "POST" else "pending", "batch_id": batch_id}

    run_once(
        tmp_path,
        secret=SECRET,
        source_instance=SOURCE,
        exporter=export,
        transport=transport,
        now=T2,
    )
    assert windows[0]["since"] == T1 - timedelta(minutes=5)
    assert windows[0]["digest_since"] is None


def test_curl_pin_and_header_file_keep_secret_out_of_process_arguments(tmp_path, monkeypatch):
    from pathlib import Path
    from types import SimpleNamespace

    observed = []

    def fake_run(args, **kwargs):
        observed.extend(args)
        header = Path(args[args.index("--header") + 1][1:])
        assert SECRET in header.read_text()
        assert header.stat().st_mode & 0o777 == 0o600
        return SimpleNamespace(returncode=0, stdout=b'{"status":"pending"}')

    monkeypatch.setattr("app.sync.client.subprocess.run", fake_run)
    transport = CurlTransport(
        url="https://example.com/upload",
        pin="sha256//" + "A" * 43 + "=",
        secret=SECRET,
        source_instance=SOURCE,
    )
    transport("GET", "batch-test")
    assert SECRET not in " ".join(observed)
    assert "--pinnedpubkey" in observed
    assert observed[-1] == "https://example.com/batches/batch-test"


def test_receipt_write_crash_after_commit_can_be_recovered(
    session, destination, tmp_path, monkeypatch
):
    add_graph(session)
    batch = build_batch(session, secret=SECRET, until=T1)
    path = write_batch(batch, tmp_path / "inbox" / "batch.json.gz")
    from app.sync.receipts import atomic_json

    def crash(*_):
        raise OSError("simulated receipt disk failure")

    monkeypatch.setattr("app.sync.importer.atomic_json", crash)
    with pytest.raises(OSError):
        import_file(
            path,
            session_factory=destination,
            secret=SECRET,
            expected_source_instance=SOURCE,
            receipts_dir=tmp_path / "receipts",
        )
    with destination() as target:
        assert target.query(SourceDocument).count() == 1
    assert path.exists()
    assert not receipt_path(tmp_path / "receipts", batch["payload"]["batch_id"]).exists()
    monkeypatch.setattr("app.sync.importer.atomic_json", atomic_json)
    counts = import_file(
        path,
        session_factory=destination,
        secret=SECRET,
        expected_source_instance=SOURCE,
        receipts_dir=tmp_path / "receipts",
    )
    assert counts["documents_existing"] == 1
    assert counts["documents_added"] == 0
    assert receipt_path(tmp_path / "receipts", batch["payload"]["batch_id"]).exists()


def test_archive_crash_after_cursor_write_retries_same_batch(session, tmp_path, monkeypatch):
    from pathlib import Path

    batch = build_batch(session, secret=SECRET, until=T1, digest_until=T1)

    def transport(method, batch_id, path=None):
        if method == "POST":
            return {"status": "imported", "batch_id": batch_id}
        return make_receipt(batch, secret=SECRET, status="imported")

    original = Path.replace

    def crash_archive(path, target):
        if path.parent.name == "outbox" and Path(target).parent.name == "sent":
            raise OSError("simulated archive failure")
        return original(path, target)

    monkeypatch.setattr(Path, "replace", crash_archive)
    with pytest.raises(OSError):
        run_once(
            tmp_path,
            secret=SECRET,
            source_instance=SOURCE,
            exporter=lambda **_: batch,
            transport=transport,
            now=T1,
        )
    assert (tmp_path / "cursors.json").exists()
    assert len(list((tmp_path / "outbox").glob("*.json.gz"))) == 1
    monkeypatch.setattr(Path, "replace", original)

    def unexpected_export(**_):
        pytest.fail("must retry the existing batch")

    result = run_once(
        tmp_path,
        secret=SECRET,
        source_instance=SOURCE,
        exporter=unexpected_export,
        transport=transport,
        now=T2,
    )
    assert result["status"] == "imported"


def test_digest_window_is_half_open(session):
    add_digest(session)
    before = build_batch(session, secret=SECRET, until=T1, digest_until=T1)
    after = build_batch(
        session, secret=SECRET, since=T1, until=T2, digest_since=T1, digest_until=T2
    )
    assert before["payload"]["digests"] == []
    assert len(after["payload"]["digests"]) == 1


def test_missing_digest_dependency_rolls_back_import(session, destination):
    _, event = add_graph(session)
    add_digest(session, event)
    batch = build_batch(session, secret=SECRET, until=T2)
    batch["payload"]["events"] = []
    batch["signature"] = _sign(batch["payload"], SECRET)
    with pytest.raises(SyncError, match="dependency"):
        with destination() as target:
            import_batch(target, batch, secret=SECRET)
    with destination() as target:
        assert target.query(SourceDocument).count() == 0
        assert target.query(DigestLog).count() == 0


def test_manual_repair_never_skips_unsynced_windows(session, tmp_path):
    from app.sync.receipts import atomic_json

    original = {"document_until": T0.isoformat(), "digest_until": T0.isoformat()}
    atomic_json(tmp_path / "cursors.json", original)
    batch = build_batch(session, secret=SECRET, since=T1, until=T2, digest_since=T1)
    write_batch(batch, tmp_path / "outbox" / "repair.json.gz")

    def transport(method, batch_id, path=None):
        if method == "POST":
            return {"status": "imported", "batch_id": batch_id}
        return make_receipt(batch, secret=SECRET, status="imported")

    result = run_once(
        tmp_path,
        secret=SECRET,
        source_instance=SOURCE,
        exporter=lambda **_: None,
        transport=transport,
        now=T2,
    )
    assert result["status"] == "imported"
    assert json.loads((tmp_path / "cursors.json").read_text()) == original


def test_legacy_import_tagging_preserves_remote_update_clock(session, destination):
    from copy import deepcopy

    add_digest(session)
    first = build_batch(session, secret=SECRET, until=T2)
    with destination() as target:
        import_batch(target, first, secret=SECRET)
        legacy = target.query(DigestLog).one()
        legacy.source_instance = None
        legacy.outlet_id = first["payload"]["digests"][0]["outlet_id"]
        legacy.updated_at = T1.replace(tzinfo=None)
        from sqlalchemy.orm import attributes

        attributes.flag_modified(legacy, "updated_at")
    with destination() as target:
        import_batch(target, first, secret=SECRET)
    with destination() as target:
        assert target.query(DigestLog).one().updated_at == T1.replace(tzinfo=None)
    second = deepcopy(first)
    second["payload"]["digests"][0]["updated_at"] = T2.isoformat()
    second["payload"]["digests"][0]["body"] = "Updated remotely"
    second["signature"] = _sign(second["payload"], SECRET)
    with destination() as target:
        assert import_batch(target, second, secret=SECRET)["digests_updated"] == 1


def test_updated_digest_item_snapshot_removes_items_without_replay_resurrection(
    session, destination
):
    _, event = add_graph(session)
    digest = add_digest(session, event)
    first = build_batch(session, secret=SECRET, until=T2)
    with destination() as target:
        import_batch(target, first, secret=SECRET)
        assert target.query(DigestItem).count() == 1
    session.query(DigestItem).delete()
    digest.body, digest.updated_at = "No relevant news after correction", T2
    session.flush()
    second = build_batch(
        session, secret=SECRET, since=T2, until=T2 + timedelta(hours=1), digest_since=T2
    )
    with destination() as target:
        import_batch(target, second, secret=SECRET)
        assert target.query(DigestItem).count() == 0
    with destination() as target:
        import_batch(target, first, secret=SECRET)
        assert target.query(DigestItem).count() == 0
        assert target.query(DigestLog).one().body == "No relevant news after correction"


def test_full_snapshot_repairs_equal_version_partial_legacy_batch(session, destination):
    from copy import deepcopy

    _, event = add_graph(session)
    add_digest(session, event)
    complete = build_batch(session, secret=SECRET, until=T2)
    legacy = deepcopy(complete)
    legacy["payload"].pop("digest_items_complete")
    legacy["payload"]["digest_items"] = []
    legacy["signature"] = _sign(legacy["payload"], SECRET)
    with destination() as target:
        import_batch(target, legacy, secret=SECRET)
        assert target.query(DigestItem).count() == 0
    with destination() as target:
        import_batch(target, complete, secret=SECRET)
        assert target.query(DigestItem).count() == 1
    with destination() as target:
        import_batch(target, legacy, secret=SECRET)
        assert target.query(DigestItem).count() == 1
