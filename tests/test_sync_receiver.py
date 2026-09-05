import gzip
import json

from fastapi.testclient import TestClient

from app.sync.receiver import app
from app.sync.transfer import _sign


def _body(*, secret: str = "sync-secret", batch_id: str = "batch-test-1") -> bytes:
    payload = {
        "schema_version": 1,
        "batch_id": batch_id,
        "source_instance": "oci-overseas",
        "documents": [],
        "matches": [],
        "events": [],
        "digests": [],
        "digest_items": [],
    }
    batch = {
        "payload": payload,
        "signature_algorithm": "hmac-sha256",
        "signature": _sign(payload, secret),
    }
    return gzip.compress(json.dumps(batch).encode("utf-8"))


def test_sync_receiver_accepts_signed_batch(monkeypatch, tmp_path):
    monkeypatch.setenv("WORLDNET_SYNC_SECRET", "sync-secret")
    monkeypatch.setenv("WORLDNET_SYNC_INBOX_DIRECTORY", str(tmp_path))

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            content=_body(),
            headers={
                "Authorization": "Bearer sync-secret",
                "X-WorldNet-Source-Instance": "oci-overseas",
                "X-WorldNet-Batch-Id": "batch-test-1",
                "Content-Type": "application/gzip",
            },
        )

    assert response.status_code == 201
    assert response.json() == {"status": "accepted", "batch_id": "batch-test-1"}
    assert (tmp_path / "batch-batch-test-1.json.gz").is_file()
    assert not list(tmp_path.glob("*.part"))


def test_sync_receiver_rejects_bad_credentials_without_writing(monkeypatch, tmp_path):
    monkeypatch.setenv("WORLDNET_SYNC_SECRET", "sync-secret")
    monkeypatch.setenv("WORLDNET_SYNC_INBOX_DIRECTORY", str(tmp_path))

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            content=_body(),
            headers={"Authorization": "Bearer wrong", "X-WorldNet-Source-Instance": "oci-overseas"},
        )

    assert response.status_code == 401
    assert list(tmp_path.iterdir()) == []


def test_sync_receiver_rejects_tampered_batch_and_cleans_temp(monkeypatch, tmp_path):
    monkeypatch.setenv("WORLDNET_SYNC_SECRET", "sync-secret")
    monkeypatch.setenv("WORLDNET_SYNC_INBOX_DIRECTORY", str(tmp_path))
    raw = bytearray(_body())
    raw[-1] ^= 1

    with TestClient(app) as client:
        response = client.post(
            "/upload",
            content=bytes(raw),
            headers={
                "Authorization": "Bearer sync-secret",
                "X-WorldNet-Source-Instance": "oci-overseas",
                "Content-Type": "application/gzip",
            },
        )

    assert response.status_code == 400
    assert list(tmp_path.iterdir()) == []
