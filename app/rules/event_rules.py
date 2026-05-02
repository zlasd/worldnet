"""Additional event classification rules."""
from app.core.enums import EventType

# Event types that require official source to be actionable
REQUIRES_OFFICIAL_SOURCE = {
    EventType.EARNINGS_RELEASE,
    EventType.BUYBACK,
    EventType.DIVIDEND,
    EventType.EQUITY_OFFERING,
    EventType.MNA,
    EventType.INSIDER_TRADE,
    EventType.MAJOR_HOLDER_CHANGE,
    EventType.TRADING_HALT,
}

# Event types that are always high-impact regardless of source
ALWAYS_HIGH_IMPACT = {
    EventType.TRADING_HALT,
    EventType.DELISTING_RISK,
    EventType.INVESTIGATION,
}
