"""
美麗華影城爬蟲
頁面: https://www.miramarcinemas.tw/Timetable/Index?cinema=standard (一般廳)
      https://www.miramarcinemas.tw/Timetable/Index?cinema=group  (特別廳)

頁面為 SSR，所有日期場次資料以 CSS toggle 方式預載於 HTML 中
用 Playwright 直接在瀏覽器 context 執行 JS 取出全部 booking link 及其上下文
"""
import asyncio
import re
from datetime import datetime
from playwright.async_api import async_playwright

BASE_URL = "https://www.miramarcinemas.tw"
THEATER_ID = "miramar_001"
THEATER_NAME = "美麗華影城"
CHAIN = "美麗華"

_HALL_PATTERNS = [
    "Dolby Cinema 3D", "Dolby Cinema",
    "IMAX3D", "IMAX2D", "IMAX",
    "4DX", "MX4D", "LUXE",
    "標準廳",
]
_LANG_PATTERNS = [
    "英文(ENG)", "中文(CHI)", "日文(JPN)",
    "英文", "中文", "日文",
]

# JavaScript 注入至 Playwright 瀏覽器，一次抓完整頁所有 booking links 的上下文
_EXTRACT_JS = """
() => {
    const HALL_PATTERNS = %s;
    const LANG_PATTERNS = %s;

    function cleanIcon(s) {
        return s.replace(/watch_later/g, '').trim();
    }

    function detectHall(text) {
        text = cleanIcon(text);
        for (const h of HALL_PATTERNS) {
            if (text === h || text.startsWith(h)) return h;
        }
        for (const l of LANG_PATTERNS) {
            if (text === l || text.startsWith(l)) return l;
        }
        return null;
    }

    const results = [];

    document.querySelectorAll('a[href*="/Booking/TicketType"]').forEach(link => {
        const href = link.getAttribute('href') || '';
        const sessionMatch = href.match(/session=(\\d+)/);
        const idMatch = href.match(/id=([^&]+)/);
        if (!sessionMatch || !idMatch) return;

        const showTime = link.textContent.trim();
        if (!/^\\d{2}:\\d{2}$/.test(showTime)) return;

        const movieId = idMatch[1];
        const sessionId = sessionMatch[1];

        // DOM 結構: a.booking_time → div.time_area → div.block.{UUID}.{DATE}
        // blockEl 提前宣告，供廳型和日期兩個區塊共用
        const blockEl = link.closest('.block');

        // --- 找廳型: 從 .block 的直接子元素找廳型文字 ---
        let hallType = '';
        let el = link.parentElement;
        if (blockEl) {
            for (const child of blockEl.children) {
                if (child.classList.contains('time_area')) continue;
                const detected = detectHall(child.textContent);
                if (detected) { hallType = detected; break; }
            }
        }
        // fallback: 向上搜尋前兄弟節點
        if (!hallType) {
            for (let d = 0; d < 8 && !hallType; d++) {
                if (!el) break;
                let prev = el.previousElementSibling;
                while (prev && !hallType) {
                    const detected = detectHall(prev.textContent);
                    if (detected) hallType = detected;
                    prev = prev.previousElementSibling;
                }
                el = el.parentElement;
            }
        }

        // --- 找日期: 從 .block 的 CSS class 取出 "6月27日" ---
        let showDate = '';
        if (blockEl) {
            const m = blockEl.className.match(/(\\d{1,2})月(\\d{1,2})日/);
            if (m) showDate = m[1] + '月' + m[2] + '日';
        }
        // fallback: 找直接文字節點
        if (!showDate) {
            el = link.parentElement;
            for (let d = 0; d < 8 && !showDate; d++) {
                if (!el) break;
                for (const child of el.childNodes) {
                    if (child.nodeType !== 3) continue;
                    const t = child.textContent.trim();
                    let m = t.match(/(\\d{1,2}\\/\\d{1,2})/);
                    if (m) { showDate = m[1]; break; }
                    m = t.match(/(\\d{1,2}月\\d{1,2}日)/);
                    if (m) { showDate = m[1]; break; }
                }
                if (!showDate) el = el.parentElement;
            }
        }

        // --- 找電影名稱: 透過同 movieId 的「電影介紹」連結找到相鄰中文文字 ---
        let movieName = '';
        const introLink = document.querySelector(
            'a[href*="/Movie/Detail"][href*="' + movieId + '"]'
        );
        if (introLink) {
            let mel = introLink.parentElement;
            for (let d = 0; d < 5 && !movieName; d++) {
                if (!mel) break;
                const tw = document.createTreeWalker(mel, NodeFilter.SHOW_TEXT);
                while (tw.nextNode()) {
                    const t = tw.currentNode.textContent.trim();
                    if (
                        t.length >= 2 && t.length <= 40 &&
                        /[\\u4e00-\\u9fa5]/.test(t) &&
                        !/電影介紹|片長|分鐘|保護|普遍|輔導|限制|請選擇|美麗華/.test(t)
                    ) {
                        movieName = t;
                        break;
                    }
                }
                mel = mel.parentElement;
            }
        }

        results.push({
            sessionId, movieId, showTime,
            hallType: hallType || 'standard',
            showDate: showDate || '',
            movieName: movieName || '',
        });
    });

    return results;
}
"""


async def _extract_async() -> list[dict]:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        all_records = []
        scraped_at = datetime.utcnow().isoformat()

        js = _EXTRACT_JS % (
            str(_HALL_PATTERNS).replace("'", '"'),
            str(_LANG_PATTERNS).replace("'", '"'),
        )

        for cinema_type in ("standard", "group"):
            url = f"{BASE_URL}/Timetable/Index?cinema={cinema_type}"
            await page.goto(url, wait_until="networkidle", timeout=30_000)

            raw_items = await page.evaluate(js)

            for item in raw_items:
                # 將 JS camelCase 鍵轉為 transform 期望的 snake_case 鍵
                normalized = {
                    "source": "miramar",
                    "chain": CHAIN,
                    "theater_id": THEATER_ID,
                    "theater_name": THEATER_NAME,
                    "cinema_type": cinema_type,
                    "scraped_at": scraped_at,
                    "movie_name": item.get("movieName", ""),
                    "movie_id": item.get("movieId", ""),
                    "session_id": item.get("sessionId", ""),
                    "show_time": item.get("showTime", ""),
                    "hall_type": item.get("hallType", "standard"),
                    "show_date_raw": item.get("showDate", ""),
                }
                all_records.append(normalized)
            print(f"  [miramar] cinema_type={cinema_type}: {len(raw_items)} 筆場次")

        await browser.close()
        return all_records


def extract() -> list[dict]:
    return asyncio.run(_extract_async())
