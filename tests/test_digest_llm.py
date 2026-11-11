import json
from datetime import datetime

import httpx
import pytest

from app.digests.config import parse_digest_task_config
from app.digests.llm import (
    OpenAICompatibleDigestClient,
    build_digest_messages,
    select_digest_items,
    validate_digest_output,
)
from app.digests.types import DigestCandidate


def test_ninfer_text_fallback_preserves_schema_validation_and_connection_deadline(monkeypatch):
    calls = []
    content = json.dumps({"summary": "摘要", "items": [{"event_id": "event-1", "rank": 1, "priority": "p2", "title": "事件", "summary": "事实"}]})

    def post(url, **kwargs):
        calls.append(kwargs)
        if len(calls) == 1:
            return httpx.Response(400, json={"error": {"code": "response_format_not_supported", "param": "response_format"}})
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    monkeypatch.setattr("app.digests.llm.httpx.post", post)
    client = OpenAICompatibleDigestClient(base_url="http://test/v1", api_key="test", model="bonsai-27b", timeout_seconds=120)
    result = select_digest_items([_candidate("event-1")], parse_digest_task_config({"llm": {"max_retries": 0}}), client)
    assert result.used_llm and result.items[0].event_id == "event-1"
    client.complete([{"role": "user", "content": "Return JSON"}])
    assert [r["json"]["response_format"]["type"] for r in calls] == ["json_object", "text", "text"]
    assert calls[0]["timeout"].connect == 10 and calls[0]["timeout"].read == 120


@pytest.mark.parametrize("status,error", [
    (400, {"code": "model_not_found", "param": "model"}),
    (400, {"code": "response_format_not_supported", "param": "other"}),
    (401, {"code": "response_format_not_supported", "param": "response_format"}),
    (429, {"code": "rate_limit"}),
])
def test_unrelated_llm_errors_do_not_downgrade_or_repeat_requests(monkeypatch, status, error):
    calls = []

    def post(*args, **kwargs):
        calls.append(kwargs)
        return httpx.Response(status, json={"error": error})

    monkeypatch.setattr("app.digests.llm.httpx.post", post)
    client = OpenAICompatibleDigestClient(base_url="http://test/v1", api_key="test", model="test")
    with pytest.raises(RuntimeError, match=f"llm_http_{status}"):
        client.complete([])
    assert len(calls) == 1


def test_text_mode_still_rejects_invalid_json(monkeypatch):
    responses = iter([
        httpx.Response(400, json={"error": {"code": "response_format_not_supported", "param": "response_format"}}),
        httpx.Response(200, json={"choices": [{"message": {"content": "not JSON"}}]}),
    ])
    monkeypatch.setattr("app.digests.llm.httpx.post", lambda *a, **kw: next(responses))
    client = OpenAICompatibleDigestClient(base_url="http://test/v1", api_key="test", model="test")
    result = select_digest_items([_candidate("event-1")], parse_digest_task_config({"llm": {"max_retries": 0}}), client)
    assert not result.used_llm and result.error == "digest_llm_invalid_json"


class FakeDigestClient:
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)
        response = self.responses.pop(0)
        if response == "__raise__":
            raise RuntimeError("llm_down")
        return response


def _candidate(event_id: str = "event-1") -> DigestCandidate:
    return DigestCandidate(
        event_id=event_id,
        title=f"Event {event_id}",
        summary="Important event summary.",
        priority="p2",
        event_type="policy_change",
        severity="medium",
        actionability="monitor",
        source_name="rsshub_cls_telegraph",
        source_tier="official",
        detected_at=datetime(2026, 7, 4, 10, 0),
        event_time=None,
        instrument_id=None,
    )


def _valid_output(event_id: str = "event-1") -> str:
    return json.dumps(
        {
            "summary": "Important daily summary.",
            "items": [
                {
                    "event_id": event_id,
                    "rank": 1,
                    "priority": "p2",
                    "title": "Policy update",
                    "summary": "政策更新摘要。",
                }
            ],
        }
    )


def test_build_digest_messages_injects_user_prompt_without_replacing_schema():
    config = parse_digest_task_config(
        {
            "llm": {
                "user_prompt": "Prefer regulatory and earnings events.",
            },
            "selection": {"max_items": 3},
        }
    )

    messages = build_digest_messages([_candidate()], config)

    assert "只返回 JSON" in messages[0]["content"]
    assert "最多返回 3 条 items" in messages[0]["content"]
    assert "Prefer regulatory and earnings events." in messages[1]["content"]
    assert "event-1" in messages[1]["content"]
    assert "rsshub_cls_telegraph" in messages[1]["content"]


def test_validate_digest_output_accepts_valid_json():
    result = validate_digest_output(_valid_output(), [_candidate()], max_items=10)

    assert result.used_llm is True
    assert result.items[0].event_id == "event-1"
    assert result.items[0].rank == 1


def test_select_digest_items_retries_after_invalid_json():
    config = parse_digest_task_config({"llm": {"max_retries": 1}})
    client = FakeDigestClient(["not-json", _valid_output()])

    result = select_digest_items([_candidate()], config, client=client)

    assert result.used_llm is True
    assert len(client.messages) == 2
    assert result.items[0].event_id == "event-1"


def test_select_digest_items_falls_back_after_unknown_event_id():
    config = parse_digest_task_config({"llm": {"max_retries": 0}})
    client = FakeDigestClient([_valid_output("unknown-event")])

    result = select_digest_items([_candidate()], config, client=client)

    assert result.used_llm is False
    assert result.error == "digest_llm_unknown_event_id"
    assert result.items[0].event_id == "event-1"


def test_select_digest_items_falls_back_when_llm_returns_too_many_items():
    payload = {
        "summary": "Too many.",
        "items": [
            {
                "event_id": "event-1",
                "rank": 1,
                "priority": "p2",
                "title": "One",
                "summary": "A",
            },
            {
                "event_id": "event-2",
                "rank": 2,
                "priority": "p2",
                "title": "Two",
                "summary": "B",
            },
        ],
    }
    config = parse_digest_task_config({"selection": {"max_items": 1}, "llm": {"max_retries": 0}})
    client = FakeDigestClient([json.dumps(payload)])

    result = select_digest_items([_candidate("event-1"), _candidate("event-2")], config, client=client)

    assert result.used_llm is False
    assert result.error == "digest_llm_too_many_items"
    assert len(result.items) == 1
