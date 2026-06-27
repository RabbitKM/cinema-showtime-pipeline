"""
威秀影城爬蟲
用 Playwright 攔截頁面載入時的 GetLstDicCinema API response，
再對每個影城呼叫 GetShowTimes 並解析 HTML 片段
"""
import asyncio
import re
from datetime import datetime
from playwright.async_api import async_playwright, Page

BASE_URL = "https://www.vscinemas.com.tw"
CHAIN = "威秀"


_LANG_TOKENS = {"英", "中", "日", "國"}

# (比對字串, 正規化廳型)；GC 是 Gold Class 縮寫，需放在 GOLD CLASS 之前
_HALL_MAP = (
    ("IMAX",        "IMAX"),
    ("4DX",         "4DX"),
    ("MX4D",        "MX4D"),
    ("GOLD CLASS",  "GOLD CLASS"),
    ("GC",          "GOLD CLASS"),
    ("TITAN",       "TITAN"),
    ("MUCROWN",     "MUCROWN"),
    ("DOLBY ATMOS", "Dolby"),
    ("ATMOS",       "Dolby"),
    ("LUXE",        "LUXE"),
    ("OSIM",        "OSIM"),
)


def _parse_version(raw: str) -> tuple[str, str, str, str]:
    """
    (4DX 3D 英)海洋奇緣 → (movie_name, hall_type, hall_name, language)

    hall_type  正規化廳型: IMAX / 4DX / GOLD CLASS / standard ...
    hall_name  版本字串去掉語言碼 token: "IMAX 3D" / "GC 數位" / "A+" / "數位"
    language   英文 / 中文 / 日文 / ""
               "國" (國語) 對應 "中文"
    """
    raw = raw.strip()
    match = re.match(r"^\(([^)]+)\)\s*(.+)$", raw)
    if not match:
        return raw, "standard", "", ""

    version_str = match.group(1).strip()
    movie_name = match.group(2).strip()
    movie_name = re.sub(r"\s*\([^)]+\)\s*$", "", movie_name).strip()

    version_upper = version_str.upper()
    hall_type = "standard"
    for keyword, normalized in _HALL_MAP:
        if keyword in version_upper:
            hall_type = normalized
            break

    # "國" = 國語 = 中文
    language = ""
    for code, name in (("英", "英文"), ("中", "中文"), ("日", "日文"), ("國", "中文")):
        if code in version_str:
            language = name
            break

    # hall_name = 版本字串去掉語言碼 (以空格分隔 token 過濾)
    hall_name = " ".join(t for t in version_str.split() if t not in _LANG_TOKENS)

    return movie_name, hall_type, hall_name, language


def _parse_showtimes_html(html: str, theater_id: str, theater_name: str) -> list[dict]:
    """
    解析 GetShowTimes HTML
    結構:
      strong.LangTW.MovieName  → 電影中文名（含廳型前綴）
      div.col-xs-12 (inner)
        strong.LangTW.RealShowDate → "07月08日 星期三"
        div.SessionTimeInfo
          div.col-xs-0: HH:MM
    """
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "lxml")
    results = []
    scraped_at = datetime.utcnow().isoformat()

    for movie_el in soup.find_all(
        "strong",
        class_=lambda c: c and "MovieName" in c and "LangTW" in c,
    ):
        raw_name = movie_el.get_text(strip=True)
        movie_name, hall_type, hall_name, language = _parse_version(raw_name)

        outer_div = movie_el.parent
        if not outer_div:
            continue

        inner_div = None
        for child in outer_div.children:
            if getattr(child, "name", None) == "div":
                inner_div = child
                break
        if not inner_div:
            continue

        current_date_raw = ""
        for child in inner_div.children:
            # NavigableString 的 name 是 None，需跳過
            if not getattr(child, "name", None):
                continue
            classes = child.get("class", [])
            if child.name == "strong" and "LangTW" in classes and "RealShowDate" in classes:
                current_date_raw = child.get_text(strip=True)
            elif child.name == "div" and "SessionTimeInfo" in classes:
                for time_div in child.find_all("div", class_="col-xs-0"):
                    t = time_div.get_text(strip=True)
                    tm = re.match(r"^(\d{2}:\d{2})(\(隔日\))?$", t)
                    if tm:
                        results.append({
                            "source": "vscinemas",
                            "chain": CHAIN,
                            "theater_id": theater_id,
                            "theater_name": theater_name,
                            "movie_name": movie_name,
                            "movie_name_raw": raw_name,
                            "hall_type": hall_type,
                            "hall_name": hall_name,
                            "language": language,
                            "show_date_raw": current_date_raw,
                            "show_time": tm.group(1),
                            "is_next_day": bool(tm.group(2)),
                            "scraped_at": scraped_at,
                        })

    return results


async def _extract_async() -> list[dict]:
    async with async_playwright() as p:
        # channel="chrome" 使用系統安裝的 Chrome，可繞過 Akamai Bot Manager
        # Cloud Run 部署時需在 Dockerfile 安裝 google-chrome-stable
        try:
            browser = await p.chromium.launch(headless=True, channel="chrome")
        except Exception:
            browser = await p.chromium.launch(headless=True)

        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1920, "height": 1080},
        )
        page = await context.new_page()

        # 先訪問主頁，建立 session / cookie
        await page.goto(f"{BASE_URL}/film/index.aspx", wait_until="networkidle", timeout=30_000)
        # 再載入 ShowTimes 頁面，等 select 元素被 JS 填充
        await page.goto(f"{BASE_URL}/ShowTimes/", wait_until="networkidle", timeout=30_000)
        await page.wait_for_timeout(2_000)

        # 透過 fetch 取得影城清單
        cinemas_data: list[dict] = await page.evaluate("""
            async () => {
                const r = await fetch('/api/GetLstDicCinema', {
                    headers: {'X-Requested-With': 'XMLHttpRequest'}
                });
                return await r.json();
            }
        """)

        if not cinemas_data:
            # fallback: 從 select 元素取影城清單
            cinemas_data = await page.evaluate("""
                () => {
                    const sel = document.getElementById('CinemaNameTWInfoF');
                    if (!sel) return [];
                    return Array.from(sel.options)
                        .filter(o => o.value)
                        .map(o => ({strText: o.text.trim(), strValue: o.value.trim()}));
                }
            """)

        print(f"  [vscinemas] 取得 {len(cinemas_data)} 個影城")

        all_results = []

        for cinema in cinemas_data:
            cinema_name = cinema.get("strText", "")
            cinema_value = cinema.get("strValue", "")
            parts = cinema_value.split("|")
            if len(parts) != 2:
                continue
            _cinema_id, cinema_code = parts
            theater_id = f"vscinemas_{cinema_code}"

            try:
                # 用 page.evaluate 內的 fetch 呼叫（繼承瀏覽器 session/cookie）
                # URL 是相對路徑 (ASP.NET app 掛載於 /ShowTimes/)
                # 從 /ShowTimes/ 頁面發出 → 解析為 /ShowTimes/ShowTimes/GetShowTimes
                html = await page.evaluate(
                    """async (code) => {
                        const resp = await fetch('ShowTimes/GetShowTimes', {
                            method: 'POST',
                            headers: {
                                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                                'X-Requested-With': 'XMLHttpRequest',
                            },
                            body: 'CinemaCode=' + encodeURIComponent(code),
                        });
                        return await resp.text();
                    }""",
                    cinema_code,
                )

                records = _parse_showtimes_html(html, theater_id, cinema_name)
                all_results.extend(records)
                print(f"  [vscinemas] {cinema_name}({cinema_code}): {len(records)} 筆")

            except Exception as e:
                print(f"  [vscinemas] {cinema_name}({cinema_code}) 失敗: {e}")

        await browser.close()
        return all_results


def extract() -> list[dict]:
    return asyncio.run(_extract_async())
