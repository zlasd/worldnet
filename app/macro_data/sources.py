"""Read published values from official APIs and explicitly labelled release tables."""

import calendar
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fractions import Fraction
from urllib.parse import urljoin, urlsplit
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from app.macro_data.types import Reading, Release

NBS_URL = "https://www.stats.gov.cn/sj/zxfb/"
PBC_STATS = "https://www.pbc.gov.cn/diaochatongjisi/116219/index.html"
PBC_NEWS = "https://www.pbc.gov.cn/goutongjiaoliu/113456/113469/index.html"
BLS_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"
BEA_RSS = "https://apps.bea.gov/rss/rss.xml"
FED_RSS = "https://www.federalreserve.gov/feeds/press_monetary.xml"
LPR_API = "https://www.chinamoney.com.cn/ags/ms/cm-u-bk-currency/LprHis"
LPR_PAGE = "https://www.chinamoney.com.cn/chinese/bklpr/"

# Units/adjustments follow the agencies' series definitions, not inferred titles.
BLS_SERIES = {
    "CUUR0000SA0": ("cpi", "美国 CPI 指数", "指数（1982–84=100）", "NSA"),
    "CUSR0000SA0": ("cpi", "美国 CPI 指数", "指数（1982–84=100）", "SA"),
    "CUUR0000SA0L1E": ("cpi", "美国核心 CPI 指数", "指数（1982–84=100）", "NSA"),
    "CUSR0000SA0L1E": ("cpi", "美国核心 CPI 指数", "指数（1982–84=100）", "SA"),
    "CES0000000001": ("employment", "美国非农就业总人数", "千人", "SA"),
    "LNS14000000": ("employment", "美国失业率", "%", "SA"),
    "CES0500000003": ("employment", "美国私营部门平均时薪", "美元/小时", "SA"),
    "WPSFD4": ("ppi", "美国最终需求 PPI 指数", "指数（2009-11=100）", "SA"),
    "JTS000000000000000JOL": ("jolts", "美国职位空缺数", "千人", "SA"),
}


def compact(value: str) -> str:
    return re.sub(r"\s+", "", value).replace("−", "-")


def number(value: str) -> Decimal:
    cleaned = compact(value).replace(",", "").rstrip("%")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", cleaned):
        raise ValueError("Unrecognized numeric cell")
    return Decimal(cleaned)


def rows(node) -> list[list[str]]:
    return [[compact(c.get_text("", strip=True)) for c in r.find_all(["td", "th"], recursive=False)]
            for r in node.select("tr")]


def meta(soup, name: str) -> str:
    node = soup.find("meta", attrs={"name": name})
    return node.get("content", "") if node else ""


def month_period(title: str) -> str:
    match = re.search(r"(20\d{2})年(?:1[—－–-])?(\d{1,2})月", compact(title))
    if not match or not 1 <= int(match[2]) <= 12:
        raise ValueError("Reference month missing")
    return f"{match[1]}-{int(match[2]):02d}"


def reading(series_id, name, period, value, unit="%", adjustment="unspecified", **kw):
    return Reading(series_id=series_id, name=name, period=period, value=None if value is None else number(str(value)),
                   unit=unit, adjustment=adjustment, **kw)


def nbs_group(title: str) -> str | None:
    for word, group in [("居民消费价格", "cpi"), ("工业生产者出厂价格", "ppi"),
                        ("采购经理指数运行", "pmi"), ("国内生产总值", "gdp"),
                        ("规模以上工业增加值", "industrial"), ("社会消费品零售总额", "retail"),
                        ("全国固定资产投资", "investment")]:
        if word in title:
            return group
    return None


def parse_nbs(html: str, url: str) -> Release:
    soup = BeautifulSoup(html, "lxml")
    title = meta(soup, "ArticleTitle")
    group = nbs_group(title)
    body = soup.select_one(".trs_editor_view, .TRS_Editor")
    if not group or body is None:
        raise ValueError("NBS article structure not recognized")
    text = compact(body.get_text("", strip=True))
    published = parse_date(meta(soup, "PubDate")).replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    values = []
    if group == "gdp":
        m = re.search(r"(20\d{2})年([一二三四1234])季度", title)
        if not m:
            raise ValueError("NBS GDP quarter missing")
        quarter = "一二三四".index(m[2]) + 1 if m[2] in "一二三四" else int(m[2])
        period = f"{m[1]}-Q{quarter}"
        table_list = body.select("table")
        r = next(r for r in rows(table_list[0]) if r and r[0] == "GDP")
        if (len(r) != 5 and not (quarter == 1 and len(r) == 3)) or "绝对额（亿元）" not in text or "比上年同期增长" not in text:
            raise ValueError("NBS GDP columns changed")
        values = [reading("CN.GDP.nominal", "中国当季名义 GDP", period, r[1], "亿元"),
                  reading("CN.GDP.yoy", "中国当季实际 GDP 同比", period, r[3] if len(r) == 5 else r[2])]
        if len(table_list) >= 3 and "GDP环比增长速度" in text:
            row = next(r for r in rows(table_list[2]) if r and r[0] == m[1])
            values.append(reading("CN.GDP.qoq", "中国实际 GDP 环比", period, row[quarter], adjustment="SA"))
    else:
        period = month_period(title)
        table_rows = rows(body)
        if group in {"cpi", "ppi"}:
            if "环比涨跌幅" not in text or "同比涨跌幅" not in text:
                raise ValueError("Price table headers changed")
            labels = [("居民消费价格", "CPI", "中国 CPI")] if group == "cpi" else [
                ("一、工业生产者出厂价格", "PPI", "中国工业生产者出厂价格")]
            if group == "cpi":
                labels.append(("其中：不包括食品和能源", "CORE_CPI", "中国核心 CPI"))
            for label, code, name in labels:
                r = next(r for r in table_rows if r and r[0] == label)
                if len(r) != 4:
                    raise ValueError("Price table column count changed")
                for column, suffix, label in [(1, "mom", "环比"), (2, "yoy", "同比")]:
                    values.append(reading(f"CN.{code}.{suffix}", name + label, period, r[column], adjustment="NSA"))
        elif group == "pmi":
            for code, name, pattern in [
                ("manufacturing", "中国制造业 PMI", r"(?<!非)制造业采购经理指数[（(]PMI[）)]为([\d.]+)%"),
                ("nonmanufacturing", "中国非制造业商务活动指数", r"非制造业商务活动指数为([\d.]+)%"),
                ("composite", "中国综合 PMI 产出指数", r"综合PMI产出指数为([\d.]+)%"),
            ]:
                m = re.search(pattern, text)
                if not m:
                    raise ValueError(f"Missing PMI measure {code}")
                values.append(reading(f"CN.PMI.{code}", name, period, m[1], adjustment="SA"))
        elif group in {"industrial", "retail"}:
            label = "规模以上工业增加值" if group == "industrial" else "社会消费品零售总额"
            r = next(r for r in table_rows if r and r[0] == label)
            if len(r) == 5:
                values.append(reading(f"CN.{group}.yoy", label + "当月同比", period, r[2]))
                values.append(reading(f"CN.{group}.ytd_yoy", label + "年初至今同比", period, r[4]))
                if group == "retail":
                    values.append(reading("CN.retail.level", label + "当月金额", period, r[1], "亿元"))
            elif len(r) == 3 and "1—2月" in text:
                values.append(reading(f"CN.{group}.ytd_yoy", label + "1—2月累计同比", period, r[2]))
            else:
                raise ValueError("Industrial/retail table columns changed")
        elif group == "investment":
            r = next(r for r in table_rows if r and r[0] == "固定资产投资（不含农户）")
            if len(r) != 2:
                raise ValueError("Investment table columns changed")
            values.append(reading("CN.investment.ytd_yoy", "中国固定资产投资（不含农户）年初至今同比", period, r[1]))
    return Release(provider="nbs", country="CN", group=group, period=period, title=title,
                   source_url=url, published_at=published, readings=values, text=text[:20000],
                   vintage="初步核算" if "初步核算" in title else "")


def parse_bls(payload: dict) -> list[Release]:
    if payload.get("status") != "REQUEST_SUCCEEDED":
        raise ValueError("BLS API request failed or quota exhausted")
    releases = defaultdict(list)
    seen = set()
    for series in payload.get("Results", {}).get("series", []):
        sid = series["seriesID"]
        if sid not in BLS_SERIES:
            continue
        seen.add(sid)
        group, name, unit, adjustment = BLS_SERIES[sid]
        history = {}
        for item in series["data"]:
            if not re.fullmatch(r"M(0[1-9]|1[0-2])", item["period"]):
                continue  # M13 is an annual average, never a monthly observation.
            period = f"{item['year']}-{item['period'][1:]}"
            if period in history:
                raise ValueError("Duplicate BLS observation")
            history[period] = item
        if not history:
            raise ValueError(f"Empty BLS series {sid}")
        for period, item in history.items():
            notes = [f["text"] for f in item.get("footnotes", []) if f.get("text")]
            missing = item["value"].strip() == "-"
            releases[group, period].append(reading(f"US.{sid}", name, period, None if missing else item["value"], unit, adjustment,
                                                   notes=notes, status="unavailable" if missing else "available"))
            if missing:
                continue
            year, month = map(int, period.split("-"))
            previous = f"{year - (month == 1)}-{12 if month == 1 else month - 1:02d}"
            year_ago = f"{year - 1}-{month:02d}"
            available = {p for p, v in history.items() if v["value"].strip() != "-"}
            change = None
            if sid == "CES0000000001" and previous in available:
                change = ("change", "美国新增非农就业（按同一批次修订后总量计算）", number(item["value"]) - number(history[previous]["value"]), "千人")
            elif sid.startswith("CUUR") and year_ago in available:
                change = ("yoy", name.replace("指数", "同比"), (number(item["value"]) / number(history[year_ago]["value"]) - 1) * 100, "%")
            elif (sid.startswith("CUSR") or sid == "WPSFD4") and previous in available:
                change = ("mom", name.replace("指数", "环比"), (number(item["value"]) / number(history[previous]["value"]) - 1) * 100, "%")
            if change:
                suffix, label, value, derived_unit = change
                releases[group, period].append(reading(
                    f"US.{sid}.{suffix}", label, period, value.quantize(Decimal("0.001")),
                    derived_unit, adjustment, basis="依据同一次官方 API 响应计算；非机构直接公布的增速", notes=notes,
                ))
    if seen != set(BLS_SERIES):
        raise ValueError("BLS response omitted requested series")
    names = {"cpi": "美国 CPI", "employment": "美国就业与工资", "ppi": "美国 PPI", "jolts": "美国职位空缺"}
    return [Release(provider="bls", country="US", group=group, period=period,
                    title=f"{names[group]}：{period}", source_url=BLS_URL,
                    readings=values, text="BLS API 未提供本批观测的原始发布时间；以抓取时间记录可得性。")
            for (group, period), values in sorted(releases.items())]


def parse_bea(html: str, url: str, title: str, published: datetime) -> Release:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one(".field--name-body")
    if body is None:
        raise ValueError("BEA release body missing")
    text = " ".join(body.stripped_strings)
    values = []
    if title.startswith(("GDP (", "Gross Domestic Product (")):
        match = re.search(r"([1-4])(?:st|nd|rd|th) Quarter(?: and Year)? (20\d{2})", title)
        if not match:
            raise ValueError("BEA GDP quarter missing")
        period, group = f"{match[2]}-Q{match[1]}", "gdp"
        table = body.select_one("table")
        if table is None or "SAAR" not in table.get_text():
            raise ValueError("BEA GDP table basis missing")
        row = next(r for r in rows(table) if r and r[0] == "RealGDP")
        values.append(reading("US.GDP.qoq_annualized", "美国实际 GDP 环比折年率", period, row[-1], adjustment="SA"))
        vintage = title.split(")")[0].split("(")[-1]
    else:
        match = re.search(r"Personal Income and Outlays, ([A-Za-z]+) (20\d{2})", title)
        if not match:
            raise ValueError("BEA PCE reference period missing")
        month = list(calendar.month_name).index(match[1])
        period, group, vintage = f"{match[2]}-{month:02d}", "pce", ""
        table = body.select_one("table")
        if table is None or "preceding month" not in table.get_text():
            raise ValueError("BEA PCE table basis missing")
        labels = {"PCEpriceindex": ("PCE", "美国 PCE 物价指数"),
                  "PCEpriceindexexcludingfoodandenergy": ("CORE_PCE", "美国核心 PCE 物价指数"),
                  "Current-dollarpersonalincome": ("income", "美国个人收入"),
                  "Current-dollarPCE": ("consumption", "美国个人消费支出")}
        for row in rows(table):
            if row and row[0] in labels:
                code, label = labels[row[0]]
                values.append(reading(f"US.{code}.mom", label + "环比", period, row[-1], adjustment="SA"))
        annual = re.search(r"From the same month one year ago,.*?(?=Personal Income and Related|For definitions|$)", text, re.S)
        if not annual:
            raise ValueError("BEA PCE annual comparison missing")
        matches = re.findall(r"(?:increased|decreased) ([\d.]+) percent", annual[0])
        directions = re.findall(r"(increased|decreased) [\d.]+ percent", annual[0])
        if len(matches) < 2:
            raise ValueError("BEA PCE annual values missing")
        for code, label, value, direction in zip(["PCE", "CORE_PCE"], ["美国 PCE 同比", "美国核心 PCE 同比"], matches, directions):
            values.append(reading(f"US.{code}.yoy", label, period, ("-" if direction == "decreased" else "") + value, adjustment="SA"))
        if len(values) != 6:
            raise ValueError("BEA PCE table omitted required metrics")
    return Release(provider="bea", country="US", group=group, period=period, title=title,
                   source_url=url, published_at=published, readings=values, text=text[:20000], vintage=vintage)


def fractional_rate(value: str) -> Decimal:
    if "-" in value:
        whole, fraction = value.split("-", 1)
        return Decimal(whole) + fractional_rate(fraction)
    f = Fraction(value)
    return Decimal(f.numerator) / Decimal(f.denominator)


def parse_fed(html: str, url: str, published: datetime) -> Release:
    soup = BeautifulSoup(html, "lxml")
    body = soup.select_one("#article")
    if body is None:
        raise ValueError("FOMC statement body missing")
    text = " ".join(body.stripped_strings).replace("–", "-").replace("‑", "-")
    match = re.search(r"target range for the federal funds rate (?:by [\d./-]+ percentage points? )?(?:at|to) ([\d./-]+) to ([\d./-]+) percent", text)
    if not match:
        raise ValueError("FOMC target range missing")
    period = published.astimezone(ZoneInfo("America/New_York")).date().isoformat()
    values = [reading("US.fed_funds." + suffix, "联邦基金目标利率" + label, period, fractional_rate(value))
              for suffix, label, value in [("lower", "下限", match[1]), ("upper", "上限", match[2])]]
    if values[0].value > values[1].value:
        raise ValueError("Invalid FOMC target range")
    return Release(provider="fed", country="US", group="fomc", period=period,
                   title=f"FOMC 政策声明：{period}", source_url=url, published_at=published,
                   readings=values, kind="policy", text=text[:20000])


def parse_pbc(html: str, url: str) -> Release:
    soup = BeautifulSoup(html, "lxml")
    title, date_text = meta(soup, "ArticleTitle"), meta(soup, "PubDate")
    body = soup.select_one("#zoom")
    if not title or body is None or not date_text:
        raise ValueError("PBC release structure missing")
    text = compact(body.get_text("", strip=True))
    # A date-only page is kept as a date, not a fabricated release timestamp.
    date = parse_date(date_text).date()
    published = parse_date(date_text).replace(tzinfo=ZoneInfo("Asia/Shanghai")) if re.search(r"\d{1,2}:\d{2}", date_text) else None
    values, kind, group, period = [], "data", "financial", date.isoformat()
    if "金融统计数据报告" in title:
        m = re.search(r"(20\d{2})年(\d{1,2})月末", text)
        if not m:
            year = re.search(r"20\d{2}", title)
            month = re.search(r"(\d{1,2})月末", text)
            if not year or not month:
                raise ValueError("PBC financial reference month missing")
            period = f"{year[0]}-{int(month[1]):02d}"
        else:
            period = f"{m[1]}-{int(m[2]):02d}"
        for code, label, pattern in [
            ("M2", "中国 M2", r"广义货币[（(]M2[）)]余额([\d.]+)(万亿元|亿元)，同比(增长|下降)([\d.]+)%"),
            ("M1", "中国 M1", r"狭义货币[（(]M1[）)]余额([\d.]+)(万亿元|亿元)，同比(增长|下降)([\d.]+)%"),
            ("TSF", "中国社会融资规模存量", r"社会融资规模存量为([\d.]+)(万亿元|亿元)，同比(增长|下降)([\d.]+)%"),
            ("loans", "中国人民币贷款余额", r"月末人民币贷款余额([\d.]+)(万亿元|亿元)，同比(增长|下降)([\d.]+)%"),
        ]:
            m = re.search(pattern, text)
            if not m:
                raise ValueError(f"PBC financial metric missing: {code}")
            amount = number(m[1]) * (10000 if m[2] == "万亿元" else 1)
            values.extend([reading(f"CN.{code}.level", label + "余额" if code in {"M1", "M2"} else label, period, amount, "亿元"),
                           reading(f"CN.{code}.yoy", label + "同比", period, ("-" if m[3] == "下降" else "") + m[4])])
        # Cumulative flows are explicitly distinct from monthly new credit/TSF.
        m = re.search(r"社会融资规模增量累计为([\d.]+)(万亿元|亿元)", text)
        if m:
            values.append(reading("CN.TSF.ytd_flow", "中国社融年初至今累计增量", period, number(m[1]) * (10000 if m[2] == "万亿元" else 1), "亿元"))
    elif "贷款市场报价利率" in title:
        group, kind = "lpr", "policy"
        for code, label, pattern in [("1y", "1年期", r"1年期LPR为([\d.]+)%"), ("5y_plus", "5年期以上", r"5年期以上LPR为([\d.]+)%")]:
            m = re.search(pattern, text, re.I)
            if not m:
                raise ValueError("LPR rate missing")
            values.append(reading(f"CN.LPR.{code}", label + " LPR", period, m[1]))
    else:
        group, kind = "policy:" + urlsplit(url).path, "policy"
        if "外汇存款准备金率" in title:
            m = re.search(r"外汇存款准备金率由现行的[\d.]+%提高到([\d.]+)%", text)
            if m:
                values.append(reading("CN.FX_RRR.announced", "已公告的外汇存款准备金率（生效日期见正文）", period, m[1]))
    return Release(provider="pbc", country="CN", group=group, period=period, title=title,
                   source_url=url, published_at=published, published_date=date, readings=values, kind=kind, text=text[:20000])


def parse_lpr(payload: dict) -> list[Release]:
    if str(payload.get("head", {}).get("rep_code")) != "200" or not payload.get("records"):
        raise ValueError("LPR response has no observations")
    releases = []
    for record in payload["records"]:
        period = date.fromisoformat(record["showDateCN"]).isoformat()
        values = [reading("CN.LPR." + suffix, label + " LPR", period, record[key])
                  for suffix, label, key in [("1y", "1年期", "1Y"), ("5y_plus", "5年期以上", "5Y")]]
        releases.append(Release(provider="pbc", country="CN", group="lpr", period=period,
                                title=f"贷款市场报价利率（LPR）：{period}", source_url=LPR_PAGE,
                                published_date=date.fromisoformat(period), readings=values, kind="policy",
                                text="全国银行间同业拆借中心受权公布；原始数据接口：" + LPR_API))
    return releases


class OfficialDataClient:
    def __init__(self, get=None, post=None):
        self.get, self.post = get or httpx.get, post or httpx.post
        self.warnings: list[str] = []

    def fetch_text(self, url: str) -> str:
        if urlsplit(url).hostname not in {"www.stats.gov.cn", "www.pbc.gov.cn", "www.bea.gov", "bea.gov", "apps.bea.gov", "www.federalreserve.gov"}:
            raise ValueError("Unexpected official source host")
        response = self.get(url, timeout=25, follow_redirects=True,
                            headers={"User-Agent": "WorldNet/0.1 (official macroeconomic data reader)"})
        response.raise_for_status()
        return response.text

    def fetch(self, provider: str, now: datetime) -> list[Release]:
        self.warnings = []
        if provider == "bls":
            response = self.post(BLS_URL, json={"seriesid": list(BLS_SERIES),
                                 "startyear": str(now.year - 1), "endyear": str(now.year)}, timeout=30)
            response.raise_for_status()
            return parse_bls(response.json())
        releases = []
        targets = {}
        if provider == "nbs":
            for page in [NBS_URL, NBS_URL + "index_1.html", NBS_URL + "index_2.html"]:
                soup = BeautifulSoup(self.fetch_text(page), "lxml")
                for a in soup.select("a[href]"):
                    title, url = a.get_text("", strip=True), urljoin(page, a["href"])
                    if nbs_group(title) and "/sj/zxfb/20" in url:
                        targets[url] = (title, None)
        elif provider == "pbc":
            try:
                response = self.post(LPR_API, params={"lang": "CN",
                                     "strStartDate": (now.date() - timedelta(days=180)).isoformat(),
                                     "strEndDate": now.date().isoformat()},
                                     headers={"Referer": LPR_PAGE}, timeout=25)
                response.raise_for_status()
                releases.extend(parse_lpr(response.json()))
            except Exception as exc:
                self.warnings.append(f"pbc: LPR 获取失败（{type(exc).__name__}）")
            for page in [PBC_STATS, PBC_NEWS]:
                try:
                    soup = BeautifulSoup(self.fetch_text(page), "lxml")
                except Exception as exc:
                    reason = f"HTTP {exc.response.status_code}" if isinstance(exc, httpx.HTTPStatusError) else type(exc).__name__
                    self.warnings.append(f"pbc: 人民银行目录获取失败（{reason}）；金融统计及央行公告本轮未更新")
                    continue
                for a in soup.select("a[href]"):
                    title, url = a.get_text("", strip=True), urljoin(page, a["href"])
                    # LPR has one canonical API above; alternating HTML/API bodies
                    # must not create artificial policy revisions for the same date.
                    if any(word in title for word in ["金融统计数据报告", "准备金率", "下调政策利率", "上调政策利率"]):
                        targets[url] = (title, None)
        elif provider in {"bea", "fed"}:
            soup = BeautifulSoup(self.fetch_text(BEA_RSS if provider == "bea" else FED_RSS), "xml")
            for item in soup.select("item"):
                title = item.title.get_text()
                if provider == "bea" and not title.startswith(("GDP (", "Gross Domestic Product (", "Personal Income and Outlays,")):
                    continue
                if provider == "fed" and title != "Federal Reserve issues FOMC statement":
                    continue
                published = parse_date(item.pubDate.get_text(), tzinfos={"EST": -18000, "EDT": -14400, "GMT": 0, "UTC": 0})
                if published.tzinfo is None:
                    raise ValueError("Official RSS publication timezone missing")
                if published < now - timedelta(days=180):
                    continue
                targets[item.link.get_text().strip()] = (title, published)
        else:
            raise ValueError("Unknown macro data provider")
        for url, (title, published) in list(targets.items())[:30]:
            try:
                html = self.fetch_text(url)
                if provider == "nbs":
                    result = parse_nbs(html, url)
                elif provider == "pbc":
                    result = parse_pbc(html, url)
                elif provider == "bea":
                    result = parse_bea(html, url, title, published)
                else:
                    result = parse_fed(html, url, published)
                releases.append(result)
            except Exception as exc:
                self.warnings.append(f"{provider}: {title} 解析/获取失败（{type(exc).__name__}）")
        if not releases:
            raise ValueError(f"No published observations found for {provider}")
        # The newest published vintage wins when RSS contains multiple estimates.
        unique = {}
        for release in sorted(releases, key=lambda r: r.published_at or datetime.min.replace(tzinfo=timezone.utc)):
            unique[release.key] = release
        return list(unique.values())
