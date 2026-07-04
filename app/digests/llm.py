from __future__ import annotations

import json
from typing import Protocol

import httpx

from app.core.config import settings
from app.digests.config import DigestTaskConfig
from app.digests.types import DigestCandidate, DigestSelectedItem, DigestSelectionResult

VALID_PRIORITIES = {"p1", "p2", "p3"}


class DigestLlmClient(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str:
        ...


class OpenAICompatibleDigestClient:
    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        model: str | None = None,
        timeout_seconds: float | None = None,
    ) -> None:
        self.base_url = (base_url or settings.llm_base_url or "").rstrip("/")
        self.api_key = api_key or settings.llm_api_key
        self.model = model or settings.llm_model
        self.timeout_seconds = timeout_seconds or settings.llm_timeout_seconds

    @property
    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def complete(self, messages: list[dict[str, str]]) -> str:
        if not self.is_configured:
            raise RuntimeError("llm_not_configured")

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "messages": messages,
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
            },
            timeout=self.timeout_seconds,
        )
        if response.status_code >= 400:
            raise RuntimeError(f"llm_http_{response.status_code}")
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError("llm_invalid_response") from exc
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("llm_empty_response")
        return content


def _candidate_payload(candidates: list[DigestCandidate]) -> list[dict[str, str | None]]:
    return [
        {
            "event_id": candidate.event_id,
            "title": candidate.title,
            "summary": candidate.summary,
            "priority": candidate.priority,
            "event_type": candidate.event_type,
            "severity": candidate.severity,
            "actionability": candidate.actionability,
            "source_tier": candidate.source_tier,
            "instrument_id": candidate.instrument_id,
        }
        for candidate in candidates
    ]


def build_digest_messages(
    candidates: list[DigestCandidate],
    config: DigestTaskConfig,
) -> list[dict[str, str]]:
    system_prompt = (
        "You are WorldNet's financial event digest selector. "
        "Return JSON only. Do not include markdown fences or commentary. "
        "The JSON object must have: summary string, items array. "
        "Each item must have event_id, rank, priority, title, why_it_matters, suggested_action. "
        "Only use event_id values from the provided candidates. "
        "priority must be one of p1, p2, p3. "
        f"Return at most {config.selection.max_items} items."
    )
    user_prompt = (
        "Select the most important events for a daily digest.\n\n"
        f"Additional user guidance:\n{config.llm.user_prompt or '(none)'}\n\n"
        "Candidates JSON:\n"
        f"{json.dumps(_candidate_payload(candidates), ensure_ascii=False)}"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def validate_digest_output(
    content: str,
    candidates: list[DigestCandidate],
    max_items: int,
) -> DigestSelectionResult:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise ValueError("digest_llm_invalid_json") from exc
    if not isinstance(payload, dict):
        raise ValueError("digest_llm_output_not_object")

    summary = payload.get("summary")
    items = payload.get("items")
    if not isinstance(summary, str) or not summary.strip():
        raise ValueError("digest_llm_summary_empty")
    if not isinstance(items, list):
        raise ValueError("digest_llm_items_not_list")
    if len(items) > max_items:
        raise ValueError("digest_llm_too_many_items")

    candidate_ids = {candidate.event_id for candidate in candidates}
    ranks: list[int] = []
    selected_items: list[DigestSelectedItem] = []
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("digest_llm_item_not_object")

        event_id = item.get("event_id")
        rank = item.get("rank")
        priority = item.get("priority")
        title = item.get("title")
        why_it_matters = item.get("why_it_matters")
        suggested_action = item.get("suggested_action")
        if event_id not in candidate_ids:
            raise ValueError("digest_llm_unknown_event_id")
        if not isinstance(rank, int) or rank <= 0:
            raise ValueError("digest_llm_invalid_rank")
        if priority not in VALID_PRIORITIES:
            raise ValueError("digest_llm_invalid_priority")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("digest_llm_title_empty")
        if not isinstance(why_it_matters, str) or not why_it_matters.strip():
            raise ValueError("digest_llm_why_it_matters_empty")
        if not isinstance(suggested_action, str) or not suggested_action.strip():
            raise ValueError("digest_llm_suggested_action_empty")

        ranks.append(rank)
        selected_items.append(
            DigestSelectedItem(
                event_id=event_id,
                rank=rank,
                priority=priority,
                title=title.strip(),
                why_it_matters=why_it_matters.strip(),
                suggested_action=suggested_action.strip(),
            )
        )

    if len(set(ranks)) != len(ranks):
        raise ValueError("digest_llm_duplicate_rank")
    if ranks != sorted(ranks):
        raise ValueError("digest_llm_ranks_not_sorted")

    return DigestSelectionResult(
        summary=summary.strip(),
        items=selected_items,
        used_llm=True,
    )


def rule_based_selection(
    candidates: list[DigestCandidate],
    max_items: int,
    error: str | None = None,
) -> DigestSelectionResult:
    selected_items = [
        DigestSelectedItem(
            event_id=candidate.event_id,
            rank=index + 1,
            priority=candidate.priority,
            title=candidate.title,
            why_it_matters=candidate.summary or "重大事件，需关注后续影响。",
            suggested_action="检查相关公告、持仓和后续进展。",
        )
        for index, candidate in enumerate(candidates[:max_items])
    ]
    return DigestSelectionResult(
        summary="LLM unavailable; rule-based digest" if error else "Rule-based digest",
        items=selected_items,
        used_llm=False,
        error=error,
    )


def select_digest_items(
    candidates: list[DigestCandidate],
    config: DigestTaskConfig,
    client: DigestLlmClient | None = None,
) -> DigestSelectionResult:
    if not candidates:
        return DigestSelectionResult(summary="No digest candidates.", items=[], used_llm=False)
    if not config.llm.enabled:
        return rule_based_selection(candidates, config.selection.max_items)

    llm_client = client or OpenAICompatibleDigestClient()
    last_error: str | None = None
    for _ in range(config.llm.max_retries + 1):
        try:
            content = llm_client.complete(build_digest_messages(candidates, config))
            return validate_digest_output(content, candidates, config.selection.max_items)
        except Exception as exc:
            last_error = str(exc) or exc.__class__.__name__

    return rule_based_selection(candidates, config.selection.max_items, error=last_error)
