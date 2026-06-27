"""
新光影城爬蟲
API: POST /api/VistaDataV2/GetSessionByCinemasIDForApp
     Body: {"CinemasID":"1001","CustomerID":"","Mobile":""}

回應結構:
  data.Session[]    → 場次資料 (ShowDate / ShowTime / ScreenName / FilmNameID / FilmType)
  data.SessionFilm[] → 電影資料 (FilmNameID / FilmName / FilmType)
  join on FilmNameID 取得電影名稱

策略:
  1. Playwright 載入 /films，點擊第一個電影卡片 (div.skc-movie-item)
     → 觸發 CinemasID=1001 的 API
  2. 透過頁面 Dropdown 切換影城 (div.Dropdown-control) 觸發其他 4 個影城的 API
"""
import asyncio
import json
from datetime import datetime
from playwright.async_api import async_playwright, Page

BASE_URL = "https://www.skcinemas.com"
CHAIN = "新光"

CINEMAS = {
    "1001": "台北獅子林新光影城",
    "1005": "台北天母新光影城",
    "1004": "桃園青埔新光影城",
    "1003": "台中中港新光影城",
    "1002": "台南西門新光影城",
}

# 每個影城的專屬關鍵字（用於從 Dropdown 選項文字比對 CinemasID）
_CINEMA_KEYWORD = {
    "獅子林": "1001",
    "天母": "1005",
    "青埔": "1004",
    "中港": "1003",
    "西門": "1002",
}

SPECIAL_HALL_KEYWORDS = {
    "dolby": "Dolby",
    "mx4d": "MX4D",
    "luxe": "LUXE",
    "osim": "OSIM",
    "sealy": "B.O.X.Sealy",
    "b.o.x": "B.O.X.",
    "acg": "ACG",
    "imax": "IMAX",
    "4dx": "4DX",
    "gold": "GOLD CLASS",
}


def _extract_sessions(data: dict) -> list[dict]:
    """
    從 GetSessionByCinemasIDForApp 回應中解析場次

    data 結構:
      result: bool
      data:
        SessionFilm: [{FilmNameID, FilmName, FilmType}]
        SessionDate: [{FilmNameID, SessionBusinessDate}]
        Session: [{SessionID, FilmNameID, FilmType, CinemasID, ScreenName, ShowDate, ShowTime, ...}]
    """
    inner = data.get("data") or {}
    if not inner:
        return []

    # 建立 FilmNameID → FilmName 映射
    film_map = {}
    for film in inner.get("SessionFilm", []):
        fid = film.get("FilmNameID", "")
        fname = film.get("FilmName", "")
        if fid and fname:
            film_map[fid] = fname

    sessions = inner.get("Session", [])
    results = []

    for s in sessions:
        fid = s.get("FilmNameID", "")
        film_name = film_map.get(fid, fid)

        show_time_raw = s.get("ShowTime", "")          # "19:15:00"
        show_time = show_time_raw[:5] if show_time_raw else ""  # → "19:15"

        results.append({
            "session_id": s.get("SessionID", ""),
            "film_name_id": fid,
            "film_name": film_name,
            "film_type": s.get("FilmType", ""),        # "英語版" / "數位" / "特別場"
            "cinema_id": s.get("CinemasID", ""),
            "screen_name": s.get("ScreenName", ""),    # "1廳" / "Dolby 廳" / "LUXE 廳"
            "show_date": s.get("ShowDate", ""),        # "YYYY/MM/DD"
            "show_time": show_time,                    # "HH:MM"
        })

    return results


def _detect_hall_type(screen_name: str, film_type: str) -> str:
    combined = f"{screen_name} {film_type}".lower()
    for kw, ht in SPECIAL_HALL_KEYWORDS.items():
        if kw in combined:
            return ht
    return "standard"


def _normalize(collected: dict[str, list[dict]]) -> list[dict]:
    scraped_at = datetime.utcnow().isoformat()
    results = []

    for cinema_id, sessions in collected.items():
        theater_name = CINEMAS.get(cinema_id, cinema_id)
        theater_id = f"skcinemas_{cinema_id}"

        for s in sessions:
            hall_type = _detect_hall_type(s["screen_name"], s["film_type"])

            # 語言判斷（國語版 = 國語 = 中文）
            ft = s["film_type"]
            if "英" in ft or "ENG" in ft.upper():
                language = "英文"
            elif "日" in ft or "JPN" in ft.upper():
                language = "日文"
            elif "中" in ft or "國" in ft or "CHI" in ft.upper():
                language = "中文"
            else:
                language = ""

            results.append({
                "source": "skcinemas",
                "chain": CHAIN,
                "theater_id": theater_id,
                "theater_name": theater_name,
                "movie_name": s["film_name"],
                "hall_type": hall_type,
                "hall_name": s["film_type"],   # FilmType 含廳型/3D/特別場等細節
                "language": language,
                "show_date_raw": s["show_date"],   # "YYYY/MM/DD"
                "show_time": s["show_time"],       # "HH:MM"
                "session_id": s["session_id"],
                "scraped_at": scraped_at,
            })

    return results


async def _collect_sessions(page: Page) -> dict[str, list[dict]]:
    collected: dict[str, list[dict]] = {}

    async def on_response(response):
        if "GetSessionByCinemasIDForApp" not in response.url:
            return
        try:
            data = await response.json()
            req = response.request
            body = json.loads(req.post_data or "{}")
            cid = body.get("CinemasID", "")
            if cid:
                sessions = _extract_sessions(data)
                collected[cid] = sessions
                print(f"  [skcinemas] CinemasID={cid}: {len(sessions)} 場次")
        except Exception as e:
            print(f"  [skcinemas] response 解析失敗: {e}")

    page.on("response", on_response)

    # 載入電影列表，點第一個卡片進入詳細頁（觸發 CinemasID=1001 API）
    await page.goto(f"{BASE_URL}/films", wait_until="load", timeout=60_000)
    await page.wait_for_timeout(2_000)

    cards = await page.query_selector_all(".skc-movie-item")
    if cards:
        await cards[0].click()
        try:
            await page.wait_for_load_state("networkidle", timeout=20_000)
        except Exception:
            await page.wait_for_load_state("load", timeout=20_000)
    else:
        await page.goto(
            f"{BASE_URL}/films/FP202605220015",
            wait_until="load",
            timeout=60_000,
        )

    await page.wait_for_timeout(2_000)

    # 點擊影城切換 Dropdown 取得其他 4 個影城
    remaining = [cid for cid in CINEMAS if cid not in collected]
    if remaining:
        await _switch_cinemas(page, remaining, collected)

    return collected


async def _switch_cinemas(page: Page, remaining: list[str], collected: dict):
    """點擊 Dropdown 依序切換至所有影城，每次觸發 GetSessionByCinemasIDForApp"""
    dropdown_ctrl = await page.query_selector(".Dropdown-control")
    if not dropdown_ctrl:
        print(f"  [skcinemas] 找不到影城切換 Dropdown")
        return

    pending = list(remaining)  # 尚未取得的影城清單

    for _pass in range(6):
        if not pending:
            return

        # 開啟 dropdown
        await dropdown_ctrl.click()
        await page.wait_for_timeout(800)

        options = await page.query_selector_all(".Dropdown-option")
        if not options:
            print("  [skcinemas] Dropdown 選項未出現")
            return

        target_opt = None
        target_cid = None

        for opt in options:
            text = (await opt.inner_text()).strip()
            # 從關鍵字找出此選項對應的 CinemasID
            cid_for_opt = next(
                (cid for kw, cid in _CINEMA_KEYWORD.items() if kw in text),
                None,
            )
            # 只點擊尚未收集、且在 pending 清單中的選項
            if cid_for_opt and cid_for_opt in pending and cid_for_opt not in collected:
                target_opt = opt
                target_cid = cid_for_opt
                break

        if target_opt is None:
            print(f"  [skcinemas] 找不到對應 pending={pending} 的 Dropdown 選項")
            return

        print(f"  [skcinemas] 切換至影城 {target_cid} ({CINEMAS.get(target_cid, '')})")
        await target_opt.click()
        await page.wait_for_timeout(3_000)

        # 更新 pending（以 collected 為準）
        pending = [c for c in pending if c not in collected]

    if pending:
        print(f"  [skcinemas] 以下影城未取得資料: {pending}")


async def _extract_async() -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        )
        page = await context.new_page()

        try:
            collected = await _collect_sessions(page)
        finally:
            await browser.close()

        return _normalize(collected)


def extract() -> list[dict]:
    return asyncio.run(_extract_async())
