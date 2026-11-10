from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy import event as sa_event
from sqlalchemy.orm import Session

from app.api.deps import get_db
from app.api.main import app
from app.core.config import settings
from app.db.base import Base
from app.digests.config import parse_digest_task_config
from app.digests.dispatcher import DigestDispatcher
from app.digests.runner import collect_digest_candidates
from app.macro_data.service import observations, run_data_digest, snapshots, store_releases
from app.macro_data.sources import (
    BEA_RSS,
    BLS_SERIES,
    LPR_API,
    PBC_REPRINT,
    OfficialDataClient,
    parse_bea,
    parse_bls,
    parse_fed,
    parse_lpr,
    parse_nbs,
    parse_pbc,
)
from app.macro_data.types import Reading, Release
from app.models.digest import DigestItem, DigestLog
from app.models.normalized_event import NormalizedEvent
from app.models.source_document import SourceDocument
from app.notifications.base import NotificationResult
from app.sync.transfer import build_batch, import_batch
from app.tasks.task_config import load_task_definitions

NOW = datetime(2026, 11, 10, 14, tzinfo=timezone.utc)


def release(value="3.1", period="2026-10", **kw):
    return Release(provider="bls", country="US", group="cpi", period=period,
                   title="美国 CPI", source_url="https://api.bls.gov/publicAPI/v2/timeseries/data/",
                   readings=[Reading(series_id="US.test_cpi", name="美国 CPI 同比", period=period, value=value, unit="%")], **kw)


class Client:
    warnings = []

    def __init__(self, data=None, fails=False):
        self.data, self.fails = data if data is not None else [release()], fails

    def fetch(self, provider, now):
        if self.fails:
            raise OSError("temporary failure")
        return self.data


class Notifier:
    channel = "webhook"

    def __init__(self, name="test", ok=True):
        self.outlet_id, self.ok, self.sent = name, ok, []

    def send(self, payload):
        self.sent.append(payload)
        return NotificationResult(ok=self.ok, error=None if self.ok else "temporary failure")


def run(session, data=None, now=NOW, outlets=None, client=None, providers=None):
    return run_data_digest(session, {"providers": ["bls"] if providers is None else providers},
                           now=now, client=client or Client(data), dispatcher=DigestDispatcher(outlets or []))


def test_initial_history_is_queryable_but_only_latest_period_notifies(session):
    notifier = Notifier()
    result = run(session, [release("3.0", "2026-09"), release()], outlets=[notifier])
    assert result["snapshots_created"] == 2 and result["events_created"] == 1
    assert len(observations(session)) == 2
    assert "首次采集快照" in notifier.sent[0].message_body
    assert "2026-09：3.0 %" in notifier.sent[0].message_body
    assert session.query(SourceDocument).filter(SourceDocument.published_at.is_not(None)).count() == 0
    session.commit()
    assert run(session, [release("3.0", "2026-09"), release()], now=NOW + timedelta(hours=3), outlets=[notifier])["items"] == 0
    assert len(notifier.sent) == 1


def test_new_period_revision_and_value_reversion_preserve_all_vintages(session):
    run(session)
    run(session, [release("3.2")], now=NOW + timedelta(hours=3))
    run(session, [release("3.1")], now=NOW + timedelta(hours=6))
    current = observations(session, series_id="US.test_cpi", period="2026-10")
    assert len(current) == 1 and current[0]["value"] == "3.1"
    assert current[0]["notice_kind"] == "revision"
    assert len(observations(session, history=True)) == 3
    assert len({d.document_id for d, _, _ in snapshots(session, history=True)}) == 3
    run(session, [release("3.4", "2026-11")], now=NOW + timedelta(days=30))
    latest = observations(session)[0]
    assert latest["notice_kind"] == "update"
    assert latest["previous_period"]["period"] == "2026-10"
    assert latest["previous_period"]["value"] == "3.1"


def test_partial_notification_failure_retries_only_failed_outlet(session):
    ok, bad = Notifier("ok"), Notifier("bad", False)
    run(session, outlets=[ok, bad])
    bad.ok = True
    run(session, now=NOW + timedelta(hours=3), outlets=[ok, bad])
    assert len(ok.sent) == 1 and len(bad.sent) == 2
    assert session.query(DigestLog).filter_by(status="sent").count() == 2


def test_refresh_failure_keeps_values_and_does_not_invent_data(session):
    run(session)
    outcome = run(session, client=Client(fails=True), now=NOW + timedelta(hours=3))
    assert outcome["warnings"] and outcome["snapshots_created"] == 0
    assert observations(session)[0]["value"] == "3.1"


def test_partial_source_warnings_reach_html_and_image_notification_summary(session):
    client = Client()
    client.warnings = ["金融统计本轮未更新", "金融统计本轮未更新"]
    notifier = Notifier()
    outcome = run(session, client=client, outlets=[notifier])
    payload = notifier.sent[0]
    assert outcome["warnings"] == ["金融统计本轮未更新"]
    assert "金融统计本轮未更新" in payload.summary
    assert "金融统计本轮未更新" in payload.html_body
    assert "金融统计本轮未更新" in payload.weixin_body


def test_numeric_format_changes_do_not_create_false_revisions(session):
    run(session, [release("3.10")])
    assert run(session, [release("3.1")], now=NOW + timedelta(hours=1))["snapshots_created"] == 0


def test_values_and_events_rollback_together(session):
    store_releases(session, [release()], NOW)
    session.rollback()
    assert session.query(SourceDocument).count() == session.query(NormalizedEvent).count() == 0


def test_regular_digest_excludes_superseded_values(session):
    run(session)
    run(session, [release("3.4")], now=NOW + timedelta(hours=1))
    candidates = collect_digest_candidates(
        session, window_start=(NOW - timedelta(hours=1)).replace(tzinfo=None),
        window_end=(NOW + timedelta(hours=2)).replace(tzinfo=None),
        config=parse_digest_task_config({"llm": {"enabled": False}}),
    )
    assert len(candidates) == 1 and candidates[0].priority == "p1"
    assert "数据修订" in candidates[0].title and "3.4 %" in candidates[0].summary


def test_sync_carries_actual_values_history_and_notifies_mainland_once(session, tmp_path):
    run(session, [release("2.9", "2026-09"), release()])
    run(session, [release("3.2")], now=NOW + timedelta(hours=1))
    batch = build_batch(session, secret="test", source_instance="oci-overseas", until=NOW + timedelta(days=1))
    engine = create_engine(f"sqlite:///{tmp_path / 'target.db'}")

    @sa_event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    notifier = Notifier()
    with Session(engine) as target:
        import_batch(target, batch, secret="test")
        import_batch(target, batch, secret="test")
        assert len(observations(target, history=True)) == 3
        assert observations(target)[0]["value"] == "3.2"
        run(target, providers=[], outlets=[notifier], now=NOW + timedelta(hours=2))
        run(target, providers=[], outlets=[notifier], now=NOW + timedelta(hours=3))
        assert len(notifier.sent) == 1 and "3.2 %" in notifier.sent[0].message_body
        assert target.query(DigestItem).count() >= 3
    engine.dispose()


def test_observation_api_auth_filter_and_missing_values(session, monkeypatch):
    run(session)
    monkeypatch.setattr(settings, "api_access_key", "test-key")
    app.dependency_overrides[get_db] = lambda: session
    try:
        client = TestClient(app)
        assert client.get("/macro-data/observations").status_code == 401
        response = client.get("/macro-data/observations?country=US&series_id=US.test_cpi", headers={"X-API-Key": "test-key"})
        assert response.status_code == 200 and response.json()[0]["value"] == "3.1"
        assert response.json()[0]["published_at"] is None
        assert client.get("/macro-data/releases", headers={"X-API-Key": "test-key"}).json()[0]["readings"]
    finally:
        app.dependency_overrides.clear()


def test_profiles_route_values_to_correct_collectors():
    for directory, providers, cron in [("/nonexistent", ["nbs", "pbc"], "20 */3 * * *"),
                                       ("config/tasks/overseas", ["bls", "bea", "fed"], "0 */3 * * *")]:
        task = next(t for t in load_task_definitions(custom_dir=directory) if t.task_id == "macro-data-releases")
        assert task.source_config["providers"] == providers and task.cron == cron


def test_missing_and_nonfinite_numbers_are_not_zero():
    r = Reading(series_id="missing", name="missing", period="2026-10", value=None, status="unavailable", unit="%")
    assert r.model_dump(mode="json")["value"] is None
    for value in ["NaN", "Infinity", None]:
        with pytest.raises(ValueError):
            Reading(series_id="bad", name="bad", period="2026-10", value=value, unit="%")


def test_bls_missing_month_annual_average_flags_and_derived_values():
    data = {"status": "REQUEST_SUCCEEDED", "Results": {"series": [
        {"seriesID": sid, "data": [
            {"year": "2026", "period": "M10", "value": "105", "footnotes": [{"text": "preliminary"}]},
            {"year": "2026", "period": "M09", "value": "100", "footnotes": []},
            {"year": "2025", "period": "M10", "value": "-", "footnotes": [{"text": "Data unavailable"}]},
            {"year": "2025", "period": "M13", "value": "999", "footnotes": []},
        ]} for sid in BLS_SERIES]}}
    parsed = parse_bls(data)
    readings = [r for release in parsed for r in release.readings]
    assert not any(r.period.endswith("13") for r in readings)
    assert any(r.value is None and r.status == "unavailable" for r in readings)
    derived = next(r for r in readings if r.series_id == "US.CES0000000001.change" and r.period == "2026-10")
    assert derived.value == 5 and "计算" in derived.basis and derived.notes == ["preliminary"]
    assert not any(r.series_id == "US.CUUR0000SA0.yoy" for r in readings)
    data["Results"]["series"].pop()
    with pytest.raises(ValueError, match="omitted"):
        parse_bls(data)


def nbs_html(title, content):
    return f'<meta name="ArticleTitle" content="{title}"><meta name="PubDate" content="2026/11/09 09:30"><div class="trs_editor_view">{content}</div>'


def test_nbs_price_table_negative_flat_and_core_values():
    html = nbs_html("2026年10月份居民消费价格", '<table><tr><td>环比涨跌幅</td><td>同比涨跌幅</td></tr><tr><td>居民消费价格</td><td>0.0</td><td>-0.2</td><td>0.5</td></tr><tr><td>其中：不包括食品和能源</td><td>0.1</td><td>0.8</td><td>1.1</td></tr></table>')
    release = parse_nbs(html, "https://www.stats.gov.cn/test")
    assert release.period == "2026-10" and release.published_at.hour == 9
    values = {r.series_id: r.value for r in release.readings}
    assert values["CN.CPI.mom"] == 0 and str(values["CN.CPI.yoy"]) == "-0.2"
    with pytest.raises((ValueError, StopIteration)):
        parse_nbs(html.replace("居民消费价格</td>", "未知指标</td>"), release.source_url)


def test_nbs_cumulative_investment_not_monthly():
    html = nbs_html("2026年1—9月份全国固定资产投资基本情况", '<table><tr><td>固定资产投资（不含农户）</td><td>-7.2</td></tr></table>')
    release = parse_nbs(html, "https://www.stats.gov.cn/test")
    assert release.period == "2026-09" and release.readings[0].series_id.endswith("ytd_yoy")


def test_lpr_and_pbc_date_only_does_not_invent_publication_time():
    release = parse_lpr({"head": {"rep_code": "200"}, "records": [{"showDateCN": "2026-10-20", "1Y": "3.00", "5Y": "3.50"}]})[0]
    assert release.published_at is None and str(release.published_date) == "2026-10-20"
    html = '<meta name="ArticleTitle" content="调整存款准备金率"><meta name="PubDate" content="2026-11-03"><meta name="createDate" content="2026-11-02 10:00:00"><div id="zoom">自11月15日起调整。</div>'
    release = parse_pbc(html, "https://www.pbc.gov.cn/test")
    assert release.kind == "policy" and release.published_at is None
    assert str(release.published_date) == "2026-11-03"


def test_fed_fractional_target_range_and_policy_text():
    html = '<div id="article">The Committee decided to maintain the target range for the federal funds rate at 3-3/4 to 4 percent. Policy explanation.</div>'
    release = parse_fed(html, "https://www.federalreserve.gov/test", NOW)
    assert [r.value for r in release.readings] == [pytest.approx(3.75), 4]
    assert release.kind == "policy" and "Policy explanation" in release.text
    changed = parse_fed(html.replace("at 3-3/4", "by 1/4 percentage point to 3-3/4"), release.source_url, NOW)
    assert changed.readings == release.readings
    with pytest.raises(ValueError):
        parse_fed(html.replace("3-3/4", "5"), release.source_url, NOW)


def test_bea_annualized_gdp_and_pce_yoy_mom_stay_distinct():
    html = '<div class="field--name-body"><table><tr><th>Percent change (SAAR)</th></tr><tr><td>Real GDP</td><td>-0.5</td></tr></table></div>'
    release = parse_bea(html, "https://www.bea.gov/test", "GDP (Second Estimate), 3rd Quarter 2026", NOW)
    assert release.period == "2026-Q3" and release.readings[0].series_id.endswith("qoq_annualized")
    assert release.vintage == "Second Estimate"
    labels = ["PCE price index", "PCE price index excluding food and energy", "Current-dollar personal income", "Current-dollar PCE"]
    html = '<div class="field--name-body"><table><tr><th>Percent change from preceding month</th></tr>'
    html += ''.join(f'<tr><td>{s}</td><td>0.2</td><td>0.3</td></tr>' for s in labels)
    html += '</table>From the same month one year ago, the PCE price index increased 3.6 percent. Excluding food and energy, the PCE price index increased 3.1 percent. For definitions</div>'
    release = parse_bea(html, "https://www.bea.gov/test", "Personal Income and Outlays, September 2026", NOW)
    assert len(release.readings) == 6
    assert {r.series_id: str(r.value) for r in release.readings}["US.PCE.yoy"] == "3.6"


def test_rss_est_edt_timezone_is_explicit():
    rss = '<rss><channel><item><title>GDP (Advance Estimate), 3rd Quarter 2026</title><link>https://www.bea.gov/news/example</link><pubDate>Thu, 29 Oct 2026 08:30:00 EDT</pubDate></item></channel></rss>'
    html = '<div class="field--name-body"><table><tr><td>SAAR</td></tr><tr><td>Real GDP</td><td>3.4</td></tr></table></div>'

    class Response:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    client = OfficialDataClient(get=lambda url, **kw: Response(rss if url == BEA_RSS else html))
    result = client.fetch("bea", NOW)
    assert result[0].published_at.utcoffset() == timedelta(hours=-4)


def test_pbc_partial_failure_retains_successful_lpr_source():
    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"head": {"rep_code": "200"}, "records": [{"showDateCN": "2026-10-20", "1Y": "3", "5Y": "3.5"}]}

    def failed_get(*args, **kwargs):
        raise OSError("source offline")

    client = OfficialDataClient(get=failed_get, post=lambda *args, **kwargs: Response())
    releases = client.fetch("pbc", NOW)
    assert releases[0].group == "lpr" and client.warnings


def test_pbc_official_reprint_fallback_checks_issuer_scope_and_publication_time():
    title = "央行发布2026年前三季度金融统计数据报告"
    html = f'''<meta name="ArticleTitle" content="{title}">
    <meta name="ContentSource" content="中国人民银行"><meta name="PubDate" content="2026-10-14 17:51:02">
    <publishtime>2026-10-14 17:39:35</publishtime><div id="zoomcon"><ucapcontent>
    初步统计，2026年9月末社会融资规模存量为468.17万亿元，同比增长7.1%。
    广义货币(M2)余额359.63万亿元，同比增长7.2%。狭义货币(M1)余额116.76万亿元，同比增长3.2%。
    月末人民币贷款余额283.44万亿元，同比增长4.8%。社会融资规模增量累计为27.46万亿元。
    </ucapcontent></div>'''
    url = PBC_REPRINT + "202610/report.shtml"
    parsed = parse_pbc(html, url)
    assert parsed.published_at.minute == 39 and "转载" in parsed.publication_note
    assert parsed.period == "2026-09" and len(parsed.readings) == 9
    assert next(r for r in parsed.readings if r.series_id == "CN.M2.level").value == 3596300
    for bad in [html.replace('content="中国人民银行"', 'content="媒体评论"'), html.replace(title, "2026年前三季度苏州市金融统计数据报告")]:
        with pytest.raises(ValueError, match="national PBC"):
            parse_pbc(bad, url)

    class Response:
        def __init__(self, text=""):
            self.text = text

        def raise_for_status(self):
            pass

        def json(self):
            return {"head": {"rep_code": "200"}, "records": [{"showDateCN": "2026-10-20", "1Y": "3", "5Y": "3.5"}]}

    def get(url_, **kwargs):
        if url_ == url:
            return Response(html)
        if url_.startswith(PBC_REPRINT):
            return Response(f'<a href="{url}">{title}</a>')
        raise OSError("primary unavailable")

    def post(url_, **kwargs):
        assert url_ == LPR_API
        return Response()

    client = OfficialDataClient(get=get, post=post)
    result = client.fetch("pbc", NOW)
    assert {r.group for r in result} == {"lpr", "financial"}
    assert any("官方转载" in warning for warning in client.warnings)
