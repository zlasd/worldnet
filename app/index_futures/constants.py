from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProductSpec:
    product: str
    name: str
    index_code: str
    index_name: str
    multiplier: int


PRODUCT_SPECS = {
    "IF": ProductSpec("IF", "沪深300股指期货", "000300", "沪深300", 300),
    "IH": ProductSpec("IH", "上证50股指期货", "000016", "上证50", 300),
    "IC": ProductSpec("IC", "中证500股指期货", "000905", "中证500", 200),
    "IM": ProductSpec("IM", "中证1000股指期货", "000852", "中证1000", 200),
}

RESEARCH_DISCLAIMER = "模拟研究，不连接真实账户，不构成交易指令。"
