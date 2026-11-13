from app.core.enums import EventSubtype, EventType, Sentiment
from app.rules.text_rules import contains_term, management_change_kind
from app.utils.text import clean_text

EVENT_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    (
        EventType.EARNINGS_RELEASE,
        ["quarterly results", "annual results", "earnings per share", "EPS", "revenue", "net income",
         "financial results", "季报", "年报", "业绩"],
    ),
    (
        EventType.EARNINGS_PREANNOUNCEMENT,
        ["profit warning", "earnings warning", "pre-announcement", "盈利预警", "业绩预告"],
    ),
    (
        EventType.GUIDANCE_CHANGE,
        ["raises guidance", "lowers guidance", "updates outlook", "调高指引", "调低指引", "业绩指引"],
    ),
    (EventType.EARNINGS_CALL, ["earnings call", "conference call", "analyst call", "业绩电话会"]),
    (EventType.BUYBACK, ["share repurchase", "buyback", "stock repurchase", "回购", "购回"]),
    (EventType.DIVIDEND, ["dividend", "special dividend", "派息", "股息", "分红"]),
    (
        EventType.EQUITY_OFFERING,
        ["secondary offering", "share placement", "rights issue", "配股", "增发", "募股"],
    ),
    (
        EventType.CONVERTIBLE_OFFERING,
        ["convertible bond", "CB offering", "可转债", "可换股债券"],
    ),
    (EventType.MNA, ["merger", "acquisition", "takeover", "acquire", "合并", "收购", "并购"]),
    (EventType.ASSET_SALE, ["asset sale", "divest", "disposal", "出售资产", "处置"]),
    (EventType.PRIVATIZATION, ["privatization", "go private", "私有化"]),
    (
        EventType.INSIDER_TRADE,
        ["insider", "director dealing", "insider buy", "insider sell", "内幕", "董事买卖"],
    ),
    (
        EventType.MAJOR_HOLDER_CHANGE,
        ["major shareholder", "substantial shareholder", "reduces stake", "减持", "增持", "大股东"],
    ),
    (
        EventType.BOARD_CHANGE,
        ["board of directors", "director appointment", "director resignation", "董事会", "董事辞任"],
    ),
    (
        EventType.EQUITY_INCENTIVE,
        ["stock option", "restricted stock", "equity award", "股权激励", "股票期权"],
    ),
    (EventType.REGULATORY_ACTION, ["regulatory", "regulator", "SEC", "SFC", "CSRC", "监管", "证监"]),
    (EventType.INVESTIGATION, ["investigation", "probe", "inquiry", "调查"]),
    (EventType.LITIGATION, ["lawsuit", "litigation", "legal action", "sue", "诉讼", "法律行动"]),
    (EventType.AUDIT_ISSUE, ["audit", "auditor", "restatement", "审计", "核数师"]),
    (
        EventType.COMPLIANCE_ISSUE,
        ["compliance", "violation", "penalty", "fine", "合规", "违规", "罚款"],
    ),
    (EventType.TRADING_HALT, ["trading halt", "trading suspended", "trading suspension", "suspends trading", "halt trading", "停牌", "暂停买卖"]),
    (EventType.DELISTING_RISK, ["delisting", "delist", "退市"]),
    (EventType.MAJOR_CONTRACT, ["contract", "deal", "order", "合同", "合约", "订单"]),
    (EventType.PRODUCT_LAUNCH, ["launches", "new product", "released", "发布", "推出", "新品"]),
    (EventType.CAPACITY_EXPANSION, ["expansion", "new factory", "capacity", "扩产", "扩建"]),
    (
        EventType.SUPPLY_CHAIN_EVENT,
        ["supply chain", "supplier", "shortage", "供应链", "供应商"],
    ),
    (EventType.PARTNERSHIP, ["partnership", "joint venture", "collaborate", "合作", "联合", "合资"]),
    (EventType.POLICY_CHANGE, ["policy", "regulation change", "政策", "法规"]),
]

SUBTYPE_KEYWORD_RULES: list[tuple[str, list[str]]] = [
    (EventSubtype.EARNINGS_BEAT, ["beat", "exceeded", "surpassed", "超预期", "超越"]),
    (EventSubtype.EARNINGS_MISS, ["miss", "below expectations", "disappointed", "未达预期", "低于预期"]),
    (EventSubtype.GUIDANCE_RAISE, ["raises guidance", "raised outlook", "上调指引", "上调预期"]),
    (
        EventSubtype.GUIDANCE_CUT,
        ["cuts guidance", "lowered outlook", "profit warning", "下调指引", "下调预期", "盈利预警"],
    ),
    (EventSubtype.PROFIT_WARNING, ["profit warning", "盈利预警", "业绩预警"]),
]

NEGATIVE_KEYWORDS = [
    "warning", "investigation", "probe", "lawsuit", "delisting", "halt", "resign",
    "resigns", "resigned", "resignation", "fine", "penalty", "miss", "cut", "lower",
    "调查", "诉讼", "减持", "预警", "停牌", "辞职", "辞任", "辞去",
]
POSITIVE_KEYWORDS = [
    "beat", "beats", "record", "growth", "raises", "buyback", "dividend", "acquisition", "partnership",
    "超预期", "回购", "增长", "创纪录",
]


def detect_event_type(title: str, raw_text: str = "", source_type: str = "") -> tuple[str, str | None]:
    title, raw_text = clean_text(title), clean_text(raw_text)
    combined = f"{title} {raw_text}"

    best_type = EventType.UNKNOWN
    best_subtype = None
    best_score = 0

    # A concrete headline event wins over incidental mentions in the body.
    # Critical trading status in a headline must not lose to an M&A keyword.
    for is_headline, text in ((True, title), (False, raw_text)):
        for event_type, keywords in EVENT_KEYWORD_RULES:
            score = sum(1 for kw in keywords if contains_term(text, kw))
            if score > best_score:
                best_score = score
                best_type = event_type
        if is_headline:
            for event_type, keywords in EVENT_KEYWORD_RULES:
                if event_type in {EventType.TRADING_HALT, EventType.DELISTING_RISK}:
                    if any(contains_term(title, kw) for kw in keywords):
                        best_type = event_type
                        break
            if best_type in {EventType.TRADING_HALT, EventType.DELISTING_RISK}:
                break
            if management_change_kind(title, raw_text):
                best_type = EventType.MANAGEMENT_CHANGE
                break
        if best_type != EventType.UNKNOWN:
            break

    if best_type != EventType.UNKNOWN:
        for subtype, keywords in SUBTYPE_KEYWORD_RULES:
            if any(contains_term(combined, kw) for kw in keywords):
                best_subtype = subtype
                break

    return best_type, best_subtype


def detect_sentiment(title: str, raw_text: str = "") -> str:
    combined = clean_text(f"{title} {raw_text}")
    neg_count = sum(1 for kw in NEGATIVE_KEYWORDS if contains_term(combined, kw))
    pos_count = sum(1 for kw in POSITIVE_KEYWORDS if contains_term(combined, kw))

    if pos_count > 0 and neg_count > 0:
        return Sentiment.MIXED
    elif pos_count > neg_count:
        return Sentiment.POSITIVE
    elif neg_count > pos_count:
        return Sentiment.NEGATIVE
    else:
        return Sentiment.NEUTRAL
