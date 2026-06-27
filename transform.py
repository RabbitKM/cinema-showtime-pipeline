"""
Transform 層: 將三個影城的原始 dict 正規化為統一的 fact_showtimes schema

fact_showtimes 欄位:
  show_date       DATE        "YYYY-MM-DD"
  movie_name      STRING      已清理的電影中文名稱
  theater_id      STRING      e.g. "vscinemas_TP"
  theater_name    STRING      e.g. "台北信義威秀影城"
  chain           STRING      "美麗華" / "新光" / "威秀"
  hall_type       STRING      正規化廳型: IMAX / 4DX / Dolby / standard ...
  hall_name       STRING      原始廳名 (未正規化)
  show_time       STRING      "HH:MM"
  language        STRING      中文 / 英文 / 日文 / ""
  is_special_hall BOOL
  scraped_at      STRING      ISO 8601 UTC
"""
import re
from datetime import date, datetime, timedelta

SPECIAL_HALL_TYPES = {"IMAX", "4DX", "MX4D", "Dolby", "GOLD CLASS", "TITAN", "MUCROWN", "LUXE", "OSIM"}


def _parse_date(raw: str, year_hint: int | None = None) -> str | None:
    """
    嘗試將各種日期字串轉為 "YYYY-MM-DD"
    支援:
      "6/26"    → 依 year_hint 或今年
      "6/26 五"
      "07月08日 星期三"
      "2026/07/08"
      "2026-07-08"
    """
    if not raw:
        return None

    raw = raw.strip()
    y = year_hint or datetime.utcnow().year

    # YYYY/MM/DD or YYYY-MM-DD
    m = re.match(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})", raw)
    if m:
        return f"{m.group(1)}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"

    # XX月XX日
    m = re.match(r"(\d{1,2})月(\d{1,2})日", raw)
    if m:
        mon, day = int(m.group(1)), int(m.group(2))
        # 跨年判斷: 若月份小於現在月份 2 個月以上，推測是明年
        now = datetime.utcnow()
        if mon < now.month - 1:
            y += 1
        return f"{y}-{mon:02d}-{day:02d}"

    # M/D or MM/DD
    m = re.match(r"(\d{1,2})/(\d{1,2})", raw)
    if m:
        mon, day = int(m.group(1)), int(m.group(2))
        now = datetime.utcnow()
        if mon < now.month - 1:
            y += 1
        return f"{y}-{mon:02d}-{day:02d}"

    return None


def _normalize_hall_type(raw: str) -> str:
    """正規化廳型字串"""
    if not raw:
        return "standard"
    r = raw.upper()
    if "DOLBY" in r:
        return "Dolby"
    if "IMAX" in r:
        return "IMAX"
    if "4DX" in r:
        return "4DX"
    if "MX4D" in r:
        return "MX4D"
    if "GOLD" in r:
        return "GOLD CLASS"
    if "TITAN" in r:
        return "TITAN"
    if "MUCROWN" in r:
        return "MUCROWN"
    if "LUXE" in r:
        return "LUXE"
    if "OSIM" in r:
        return "OSIM"
    if "ACG" in r:
        return "ACG"
    return "standard"


def _normalize_language(raw: str) -> str:
    if not raw:
        return ""
    r = raw
    if "英" in r or "ENG" in r.upper():
        return "英文"
    if "日" in r or "JPN" in r.upper():
        return "日文"
    if "中" in r or "CHI" in r.upper():
        return "中文"
    return ""


def normalize(records: list[dict]) -> list[dict]:
    """
    將所有爬蟲的 raw dict 統一轉為 fact_showtimes 格式
    過濾掉無效資料（無法解析日期 / 場次時間）
    """
    out = []
    year_hint = datetime.utcnow().year

    for rec in records:
        show_date = _parse_date(rec.get("show_date_raw", ""), year_hint)
        if not show_date:
            continue  # 跳過無效日期

        show_time = rec.get("show_time", "").strip()
        if not re.match(r"^\d{2}:\d{2}$", show_time):
            continue  # 跳過無效時間

        if rec.get("is_next_day"):
            show_date = (date.fromisoformat(show_date) + timedelta(days=1)).isoformat()

        raw_hall = rec.get("hall_type", "") or rec.get("hall_name", "")
        hall_type = _normalize_hall_type(raw_hall)

        # 優先用 language 欄位；若無則從 hall_type 嘗試提取
        # （美麗華 hallType 可能是 "英文(ENG)"、"日文(JPN)" 等語言標記）
        raw_lang = rec.get("language") or rec.get("hall_type", "")
        language = _normalize_language(raw_lang)

        out.append(
            {
                "show_date": show_date,
                "movie_name": (rec.get("movie_name") or "").strip(),
                "theater_id": rec.get("theater_id", ""),
                "theater_name": rec.get("theater_name", ""),
                "chain": rec.get("chain", ""),
                "hall_type": hall_type,
                "hall_name": rec.get("hall_name") or rec.get("hall_type") or "",
                "show_time": show_time,
                "language": language,
                "is_special_hall": hall_type in SPECIAL_HALL_TYPES,
                "scraped_at": rec.get("scraped_at", ""),
                # 保留原始欄位供 raw_showtimes
                "_source_raw": rec,
            }
        )

    return out
