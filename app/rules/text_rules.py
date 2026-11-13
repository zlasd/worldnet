"""Text matching for news rules; HTML attributes are not news evidence."""

import re

from app.utils.text import clean_text


def contains_term(text: str, term: str) -> bool:
    if term.isascii():
        # ASCII boundaries also allow Chinese headlines such as “宣布CEO辞职”.
        return re.search(
            r"(?<![a-z0-9_])" + re.escape(term) + r"(?![a-z0-9_])",
            text,
            re.IGNORECASE,
        ) is not None
    return term in text


EXECUTIVE_ROLE = re.compile(
    r"(?<![a-z])(?:ceo|cfo|cto|coo)(?![a-z])|"
    r"chief (?:executive|financial|technology|operating)(?: officer)?|"
    r"首席(?:执行|财务|技术|运营)官|行政总裁|总裁|总经理|董事长",
    re.IGNORECASE,
)
DEPARTURE = re.compile(
    r"\b(?:resign(?:s|ed|ing|ation)?|quit(?:s)?|"
    r"(?:step(?:s|ped)?|stepping) down|oust(?:s|ed|ing)?|"
    r"dismiss(?:es|ed|al)?|fired)\b|辞职|辞任|辞去|离任|卸任|免职|解职|解聘",
    re.IGNORECASE,
)
APPOINTMENT = re.compile(
    r"\b(?:appoint(?:s|ed|ing|ment)?|nam(?:e|es|ed|ing)|"
    r"replac(?:e|es|ed|ing|ement)|succeed(?:s|ed|ing)?)\b|委任|任命|出任|接任|换帅",
    re.IGNORECASE,
)
DENIAL = re.compile(
    r"\b(?:den(?:y|ies|ied)|refut(?:e|es|ed)|not|never|won't|no plans)\b|"
    r"否认|辟谣|不会|并未|没有|无意",
    re.IGNORECASE,
)
UNCERTAIN = re.compile(
    r"\b(?:may|might|could|reportedly|rumou?rs?|consider(?:s|ed|ing)?|"
    r"preparing|plans? to|expected to)\b|据悉|传闻|或将|考虑|可能|拟",
    re.IGNORECASE,
)


def management_change_kind(title: str, raw_text: str = "") -> str | None:
    """Require a headline action and a role in the headline/lead.

    A headline denial overrides the body. Speculation remains a change to
    monitor, but is not treated as an announced executive departure.
    """
    title = clean_text(title)
    if DENIAL.search(title):
        return None
    # Background paragraphs frequently repeat an earlier resignation. They
    # must not turn a different CEO's interview or a daily podcast into P1.
    lead = re.split(r"[。！？!?;；\n]|(?<=[a-z])\.\s", clean_text(raw_text)[:400])[0]
    roles = list(EXECUTIVE_ROLE.finditer(title))
    for pattern, kind in ((DEPARTURE, "departure"), (APPOINTMENT, "appointment")):
        for action in pattern.finditer(title):
            if any(abs(role.start() - action.start()) <= 100 for role in roles) or (
                not roles and EXECUTIVE_ROLE.search(lead) and not DENIAL.search(lead)
            ):
                if UNCERTAIN.search(title):
                    return "proposed"
                return kind
    return None
