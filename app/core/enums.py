from enum import Enum


class Market(str, Enum):
    US = "US"
    HK = "HK"
    CN = "CN"


class SourceType(str, Enum):
    FILING = "filing"
    EXCHANGE_ANNOUNCEMENT = "exchange_announcement"
    COMPANY_IR = "company_ir"
    NEWS = "news"
    TRANSCRIPT = "transcript"
    REGULATOR = "regulator"
    BLOG = "blog"


class SourceTier(str, Enum):
    OFFICIAL = "official"
    PRIMARY_MEDIA = "primary_media"
    SECONDARY_MEDIA = "secondary_media"
    AGGREGATOR = "aggregator"


class MatchType(str, Enum):
    EXPLICIT_TICKER = "explicit_ticker"
    COMPANY_NAME = "company_name"
    ALIAS = "alias"
    INFERRED_SECTOR = "inferred_sector"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class Sentiment(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    MIXED = "mixed"
    NEUTRAL = "neutral"


class Actionability(str, Enum):
    IMMEDIATE = "immediate"
    MONITOR = "monitor"
    DIGEST_ONLY = "digest_only"


class NotificationChannel(str, Enum):
    TELEGRAM = "telegram"
    EMAIL = "email"
    WEBHOOK = "webhook"


class NotificationPriority(str, Enum):
    P1 = "p1"
    P2 = "p2"
    P3 = "p3"


class NotificationStatus(str, Enum):
    SENT = "sent"
    FAILED = "failed"
    SKIPPED = "skipped"


class WatchlistItemPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class IngestionStatus(str, Enum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"
    DUPLICATE = "duplicate"


class EventType(str, Enum):
    # Earnings
    EARNINGS_RELEASE = "earnings_release"
    EARNINGS_PREANNOUNCEMENT = "earnings_preannouncement"
    GUIDANCE_CHANGE = "guidance_change"
    EARNINGS_CALL = "earnings_call"
    # Capital Operations
    BUYBACK = "buyback"
    DIVIDEND = "dividend"
    EQUITY_OFFERING = "equity_offering"
    CONVERTIBLE_OFFERING = "convertible_offering"
    MNA = "mna"
    ASSET_SALE = "asset_sale"
    PRIVATIZATION = "privatization"
    # Shareholders & Management
    INSIDER_TRADE = "insider_trade"
    MAJOR_HOLDER_CHANGE = "major_holder_change"
    MANAGEMENT_CHANGE = "management_change"
    BOARD_CHANGE = "board_change"
    EQUITY_INCENTIVE = "equity_incentive"
    # Regulatory & Legal
    REGULATORY_ACTION = "regulatory_action"
    INVESTIGATION = "investigation"
    LITIGATION = "litigation"
    AUDIT_ISSUE = "audit_issue"
    COMPLIANCE_ISSUE = "compliance_issue"
    TRADING_HALT = "trading_halt"
    DELISTING_RISK = "delisting_risk"
    # Operations & Industry
    MAJOR_CONTRACT = "major_contract"
    PRODUCT_LAUNCH = "product_launch"
    CAPACITY_EXPANSION = "capacity_expansion"
    SUPPLY_CHAIN_EVENT = "supply_chain_event"
    PARTNERSHIP = "partnership"
    POLICY_CHANGE = "policy_change"
    # Unknown
    UNKNOWN = "unknown"


class EventSubtype(str, Enum):
    EARNINGS_BEAT = "earnings_beat"
    EARNINGS_MISS = "earnings_miss"
    GUIDANCE_RAISE = "guidance_raise"
    GUIDANCE_CUT = "guidance_cut"
    PROFIT_WARNING = "profit_warning"
    UNKNOWN = "unknown"
