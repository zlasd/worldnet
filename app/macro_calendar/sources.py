"""Parse explicit dates from official calendars; never infer release dates from cadence."""

import calendar
import re
from datetime import date, datetime, time
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from app.macro_calendar.types import CalendarRelease

NBS_INDEX = "https://www.stats.gov.cn/xxgk/sjfb/fbrcb/"
BEA_URL = "https://www.bea.gov/news/schedule"
FED_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
BLS_TITLES = (
    "Consumer Price Index", "Producer Price Index", "Employment Situation",
    "Job Openings and Labor Turnover", "Employment Cost Index", "Productivity and Costs",
    "U.S. Import and Export Price Indexes",
)
NBS_TITLES = (
    "国民经济运行", "主要行业增加值", "采购经理指数", "居民消费价格", "工业生产者价格",
    "工业生产月度", "固定资产投资", "房地产", "社会消费品零售", "居民收支",
    "产能利用率", "住宅销售价格", "工业经济效益",
)


def _text(node) -> str:
    return " ".join(node.stripped_strings)


def _clock(value: str) -> time | None:
    match = re.search(r"\b(\d{1,2}):(\d{2})(?:\s*(AM|PM))?", value, re.I)
    if not match:
        return None
    hour, minute = int(match[1]), int(match[2])
    if match[3]:
        hour = hour % 12 + (12 if match[3].upper() == "PM" else 0)
    return time(hour, minute)


def _grid(table) -> list[list[str]]:
    """Expand HTML rowspan/colspan so date and time rows retain their month columns."""
    cells: dict[tuple[int, int], str] = {}
    rows = table.find_all("tr")
    for row_index, row in enumerate(rows):
        column = 0
        for cell in row.find_all(["td", "th"], recursive=False):
            while (row_index, column) in cells:
                column += 1
            rowspan = int(cell.get("rowspan", 1))
            colspan = int(cell.get("colspan", 1))
            if not 1 <= rowspan <= 50 or not 1 <= colspan <= 50:
                raise ValueError("Unexpected calendar table span")
            for r in range(row_index, row_index + rowspan):
                for c in range(column, column + colspan):
                    cells[r, c] = _text(cell)
            column += colspan
    return [
        [cells.get((r, c), "") for c in range(14)]
        for r in range(len(rows))
    ]


def parse_nbs(html: str, year: int, url: str) -> list[CalendarRelease]:
    soup = BeautifulSoup(html, "lxml")
    table = next((t for t in soup.find_all("table") if "1月" in _text(t) and "12月" in _text(t)), None)
    if table is None:
        raise ValueError("NBS release calendar table not found")
    rows = _grid(table)
    releases = []
    for index, row in enumerate(rows):
        title = row[1]
        if not any(word in title for word in NBS_TITLES):
            continue
        ordinal = 0
        for month, value in enumerate(row[2:14], 1):
            days = re.findall(r"(?<!\d)(\d{1,2})\s*[/／]\s*[一二三四五六日天]", value)
            if not days:
                if any(word in value for word in ("待定", "延期", "取消")):
                    ordinal += 1
                    releases.append(CalendarRelease(
                        provider="nbs", key=f"{year}:{title}:{ordinal}", title=title,
                        country="CN", release_date=None, timezone="Asia/Shanghai",
                        source_url=url, status="cancelled" if "取消" in value else "postponed",
                    ))
                continue
            time_cell = value
            if index + 1 < len(rows) and rows[index + 1][1] == title:
                time_cell += " " + rows[index + 1][month + 1]
            clocks = re.findall(r"\d{1,2}[:：]\d{2}", time_cell)
            for i, day in enumerate(days):
                ordinal += 1
                releases.append(CalendarRelease(
                    provider="nbs", key=f"{year}:{title}:{ordinal}", title=title,
                    country="CN", release_date=date(year, month, int(day)),
                    release_time=_clock(clocks[min(i, len(clocks) - 1)].replace("：", ":")) if clocks else None,
                    timezone="Asia/Shanghai", source_url=url,
                ))
    return releases


def parse_bls(html: str, url: str) -> list[CalendarRelease]:
    releases = []
    for row in BeautifulSoup(html, "lxml").select("tr"):
        cells = row.find_all("td", recursive=False)
        if len(cells) != 3:
            continue
        date_text, time_text, title = map(_text, cells)
        if not title.startswith(BLS_TITLES) or " for " not in title:
            continue
        status = "scheduled"
        if "cancel" in date_text.lower():
            status = "cancelled"
        elif any(word in date_text.lower() for word in ("tbd", "postpon", "to be")):
            status = "postponed"
        elif not re.search(r"\b20\d{2}\b", date_text):
            raise ValueError("BLS calendar date has no year")
        releases.append(CalendarRelease(
            provider="bls", key=title, title=title, country="US",
            release_date=parse_date(date_text, fuzzy=True).date() if status == "scheduled" else None,
            release_time=_clock(time_text) if status == "scheduled" else None,
            timezone="America/New_York", source_url=url, status=status,
        ))
    return releases


def parse_bea(html: str, url: str = BEA_URL) -> list[CalendarRelease]:
    soup = BeautifulSoup(html, "lxml")
    releases = []
    for table in soup.select("#release-schedule-table"):
        header = table.find("thead")
        match = re.search(r"\b(20\d{2})\b", _text(header) if header else "")
        if not match:
            raise ValueError("BEA calendar year missing")
        year = int(match[1])
        for row in table.select("tbody tr"):
            title_node, date_node = row.select_one(".release-title"), row.select_one(".scheduled-date")
            if not title_node or not date_node:
                continue
            title = _text(title_node)
            if not (title.startswith(("GDP (", "Gross Domestic Product (", "Personal Income and Outlays", "U.S. International Trade"))):
                continue
            date_text = _text(date_node)
            date_part = date_node.select_one(".release-date")
            status = "scheduled"
            if "cancel" in date_text.lower():
                status = "cancelled"
            elif any(word in date_text.lower() for word in ("tbd", "postpon", "to be")):
                status = "postponed"
            elif date_part is None:
                raise ValueError("BEA release date missing")
            releases.append(CalendarRelease(
                provider="bea", key=title, title=title, country="US",
                release_date=parse_date(f"{_text(date_part)} {year}").date() if status == "scheduled" else None,
                release_time=_clock(date_text) if status == "scheduled" else None,
                timezone="America/New_York", source_url=url, status=status,
            ))
    return releases


def parse_fed(html: str, url: str = FED_URL) -> list[CalendarRelease]:
    soup = BeautifulSoup(html, "lxml")
    releases = []
    months = {name: i for names in (calendar.month_name, calendar.month_abbr)
              for i, name in enumerate(names) if name}
    for panel in soup.select(".panel"):
        heading = panel.find("h4")
        year_match = re.search(r"(20\d{2}) FOMC Meetings", _text(heading) if heading else "")
        if not year_match:
            continue
        year = int(year_match[1])
        for meeting in panel.select(".fomc-meeting"):
            month_node, day_node = meeting.select_one(".fomc-meeting__month"), meeting.select_one(".fomc-meeting__date")
            if not month_node or not day_node:
                raise ValueError("FOMC meeting date missing")
            month_text, day_text = _text(month_node), _text(day_node)
            # Unscheduled/notation votes are not a future regular decision calendar.
            if "notation" in day_text.lower() or "unscheduled" in day_text.lower():
                continue
            month = months.get(month_text.split("/")[-1].strip())
            days = re.findall(r"\d{1,2}", day_text)
            if not month or not days:
                raise ValueError("Unrecognized FOMC meeting date")
            release_date = date(year, month, int(days[-1]))
            title = "FOMC 例会结束／政策决定日" + ("（含经济预测 SEP）" if "*" in day_text else "")
            releases.append(CalendarRelease(
                provider="fed", key=f"{year}:{month}:decision", title=title,
                country="US", release_date=release_date,
                timezone="America/New_York", source_url=url,
            ))
            minutes = meeting.select_one(".fomc-meeting__minutes")
            match = re.search(r"Released\s+([A-Za-z]+\s+\d{1,2},\s*20\d{2})", _text(minutes) if minutes else "")
            if match:
                releases.append(CalendarRelease(
                    provider="fed", key=f"{year}:{month}:minutes", title="FOMC 会议纪要",
                    country="US", release_date=parse_date(match[1]).date(),
                    timezone="America/New_York", source_url=url,
                ))
    return releases


class OfficialCalendarClient:
    def __init__(self, get=None):
        self.get = get or httpx.get

    def _fetch(self, url: str) -> str:
        response = self.get(url, timeout=20, follow_redirects=True, headers={
            "User-Agent": "WorldNet/0.1 (official release calendar reader)",
        })
        response.raise_for_status()
        return response.text

    def fetch(self, provider: str, now: datetime) -> list[CalendarRelease]:
        if provider == "nbs":
            index = BeautifulSoup(self._fetch(NBS_INDEX), "lxml")
            releases = []
            found = set()
            for link in index.find_all("a", href=True):
                match = re.search(r"(20\d{2})年国家统计局主要统计信息发布日程表", _text(link))
                if not match or int(match[1]) not in (now.year, now.year + 1) or match[1] in found:
                    continue
                url = urljoin(NBS_INDEX, link["href"])
                if urlsplit(url).hostname != "www.stats.gov.cn":
                    raise ValueError("Unexpected NBS calendar host")
                found.add(match[1])
                releases.extend(parse_nbs(self._fetch(url), int(match[1]), url))
        elif provider == "bls":
            url = f"https://www.bls.gov/schedule/{now.year}/home.htm"
            html = self._fetch(url)
            releases = parse_bls(html, url)
            next_url = f"https://www.bls.gov/schedule/{now.year + 1}/home.htm"
            if any(urljoin(url, a["href"]) == next_url for a in BeautifulSoup(html, "lxml").find_all("a", href=True)):
                releases.extend(parse_bls(self._fetch(next_url), next_url))
        elif provider == "bea":
            releases = parse_bea(self._fetch(BEA_URL))
        elif provider == "fed":
            releases = parse_fed(self._fetch(FED_URL))
        else:
            raise ValueError(f"Unknown calendar provider: {provider}")
        if not releases:
            raise ValueError(f"No recognized releases in {provider} calendar")
        identities = [(r.provider, r.key) for r in releases]
        if len(identities) != len(set(identities)):
            raise ValueError(f"Duplicate release identities in {provider} calendar")
        return releases
