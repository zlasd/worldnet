import json
from datetime import datetime

from app.digests.config import parse_digest_task_config
from app.digests.llm import build_digest_messages, select_digest_items, validate_digest_output
from app.digests.types import DigestCandidate


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
                    "why_it_matters": "It changes market expectations.",
                    "suggested_action": "Review affected holdings.",
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

    assert "Return JSON only" in messages[0]["content"]
    assert "Return at most 3 items" in messages[0]["content"]
    assert "Prefer regulatory and earnings events." in messages[1]["content"]
    assert "event-1" in messages[1]["content"]


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
                "why_it_matters": "A",
                "suggested_action": "B",
            },
            {
                "event_id": "event-2",
                "rank": 2,
                "priority": "p2",
                "title": "Two",
                "why_it_matters": "A",
                "suggested_action": "B",
            },
        ],
    }
    config = parse_digest_task_config({"selection": {"max_items": 1}, "llm": {"max_retries": 0}})
    client = FakeDigestClient([json.dumps(payload)])

    result = select_digest_items([_candidate("event-1"), _candidate("event-2")], config, client=client)

    assert result.used_llm is False
    assert result.error == "digest_llm_too_many_items"
    assert len(result.items) == 1
