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
            "source_name": candidate.source_name,
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
        "你是 WorldNet 的金融与重大资讯日报筛选器。"
        "只返回 JSON，不要使用 Markdown 代码块，不要输出额外解释。"
        "JSON 对象必须包含：summary 字符串、items 数组。"
        "summary 是整份日报的中文总摘要。"
        "items 中每一项必须包含 event_id、rank、priority、title、summary。"
        "每个 item.summary 是该事件的中文事实摘要，不要写成推荐动作、投资建议或“为什么重要”。"
        "只能使用候选集中出现的 event_id。"
        "priority 只能是 p1、p2、p3。"
        f"最多返回 {config.selection.max_items} 条 items。"
        "优先选择对持仓、监管、财报、宏观市场、重大风险或产业趋势有直接影响的信息。"
    )
    user_prompt = (
        "请从以下候选事件中筛选重要事项，生成中文日报。\n\n"
        f"用户补充偏好：\n{config.llm.user_prompt or '无'}\n\n"
        "候选事件 JSON：\n"
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
        item_summary = item.get("summary")
        if event_id not in candidate_ids:
            raise ValueError("digest_llm_unknown_event_id")
        if not isinstance(rank, int) or rank <= 0:
            raise ValueError("digest_llm_invalid_rank")
        if priority not in VALID_PRIORITIES:
            raise ValueError("digest_llm_invalid_priority")
        if not isinstance(title, str) or not title.strip():
            raise ValueError("digest_llm_title_empty")
        if not isinstance(item_summary, str) or not item_summary.strip():
            raise ValueError("digest_llm_item_summary_empty")

        ranks.append(rank)
        selected_items.append(
            DigestSelectedItem(
                event_id=event_id,
                rank=rank,
                priority=priority,
                title=title.strip(),
                summary=item_summary.strip(),
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
            summary=candidate.summary or candidate.title,
        )
        for index, candidate in enumerate(candidates[:max_items])
    ]
    return DigestSelectionResult(
        summary="LLM 不可用，已使用规则降级生成日报。" if error else "规则生成的重要事项日报。",
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
        return DigestSelectionResult(summary="本期未发现重要新闻事项。", items=[], used_llm=False)
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
