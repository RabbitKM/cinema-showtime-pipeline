# ETL Transform 層紀錄

## 架構概覽

```
Extract (scrapers/)  →  Transform (transform.py)  →  Load (output.json / BigQuery)
```

Transform 層負責將三個爬蟲的異質原始資料，統一正規化為單一 schema，並過濾無效資料。

---

## 輸出 Schema（fact_showtimes）

| 欄位 | 型別 | 說明 |
|------|------|------|
| `show_date` | STRING (YYYY-MM-DD) | 場次日期，由各來源日期格式統一轉換 |
| `movie_name` | STRING | 電影中文名稱（已去掉版本前綴） |
| `theater_id` | STRING | 影城唯一 ID，e.g. `vscinemas_TP`、`skcinemas_1001`、`miramar_001` |
| `theater_name` | STRING | 影城中文名稱 |
| `chain` | STRING | 院線：`威秀` / `新光` / `美麗華` |
| `hall_type` | STRING | 正規化廳型（見下表） |
| `hall_name` | STRING | 原始廳型字串（保留 3D、GC 數位等細節） |
| `show_time` | STRING (HH:MM) | 場次時間 |
| `language` | STRING | `英文` / `中文` / `日文` / `""` |
| `is_special_hall` | BOOL | hall_type 屬於特殊廳則為 True |
| `scraped_at` | STRING (ISO 8601 UTC) | 爬取時間戳 |

---

## 正規化廳型對應表

| 原始值（含別名） | hall_type | is_special_hall |
|---|---|---|
| IMAX、IMAX 3D | `IMAX` | True |
| 4DX、4DX 3D | `4DX` | True |
| MX4D | `MX4D` | True |
| GOLD CLASS、**GC**（威秀縮寫） | `GOLD CLASS` | True |
| TITAN | `TITAN` | True |
| MUCROWN | `MUCROWN` | True |
| Dolby Atmos | `Dolby` | True |
| LUXE | `LUXE` | True |
| OSIM | `OSIM` | True |
| **SEALY**（新光 B.O.X. Sealy） | `SEALY` | True |
| 其他（數位、3D 數位、A+、標準廳…） | `standard` | False |

---

## 日期解析規則（`_parse_date`）

各來源日期格式不同，統一轉為 `YYYY-MM-DD`：

| 原始格式 | 來源 | 範例 |
|---|---|---|
| `M/D` | 美麗華 JS | `6/27` |
| `M/D 五`（含星期） | 美麗華 JS | `6/27 五` |
| `XX月XX日 星期三` | 威秀 HTML | `07月08日 星期三` |
| `XX月XX日`（CSS class） | 美麗華 DOM | `6月27日`（從 `.block` class 提取） |
| `YYYY/MM/DD` | 新光 JSON | `2026/06/26` |
| `YYYY-MM-DD` | 通用 | `2026-07-08` |

跨年判斷：月份比當前月份早 2 個月以上 → 推測為明年。

---

## 語言正規化規則（`_normalize_language`）

| 原始字碼 | 對應語言 | 備註 |
|---|---|---|
| `英`、`ENG` | `英文` | |
| `中`、`CHI` | `中文` | |
| `日`、`JPN` | `日文` | |
| **`國`** | **`中文`** | 威秀「國語」場修正（原未對應） |

**Fallback 邏輯**：若 raw record 無 `language` 欄位，額外檢查 `hall_type` 欄位（美麗華 hall_type 可能是 `"英文(ENG)"` 等語言標記）。

---

## 各爬蟲 Transform 相關修正紀錄

### 威秀（vscinemas）— `scrapers/vscinemas.py` `_parse_showtimes_html()` / `_parse_version()`

版本字串格式：`(HALL_TYPE [3D] LANG)電影名`，e.g. `(4DX 3D 英)海洋奇緣`

**修正項目：**

1. **GC → GOLD CLASS**
   - 問題：威秀 Gold Class 廳版本字串為 `GC 數位`，程式只比對 `"GOLD CLASS"` 全名，導致匹配失敗 → 歸類為 `standard`（is_special_hall=False）
   - 修正：在 `_HALL_MAP` 加入 `("GC", "GOLD CLASS")` 別名，置於 `GOLD CLASS` 之後（避免 `GC` 誤觸 `GOLD CLASS` 字串）
   - 影響：253 筆 GOLD CLASS 場次從 `standard` 正確改為 `GOLD CLASS`

2. **`hall_name` 保留版本字串**
   - 問題：`hall_name` 未填，前端看不出 `IMAX` vs `IMAX 3D`、`GC 數位` vs 一般 `數位`
   - 修正：`_parse_version()` 新增第 4 個回傳值；`hall_name` = 版本字串去掉語言 token（按空格分割後過濾 `{英,中,日,國}`）
   - 範例：`"4DX 3D 英"` → hall_type=`4DX`、hall_name=`4DX 3D`

3. **「國」語對應中文**
   - 問題：威秀版本字串用 `國`（國語）表示中文場，語言對照表只有 `英/中/日`，`國` 未對應 → `language = ""`
   - 修正：加入 `("國", "中文")` 對應
   - 影響：約 1,900+ 筆威秀中文場次 language 從空白正確填入 `"中文"`

4. **韓語場次 language 為空**（已知缺口，待補）
   - 查驗：威秀電影介紹頁（`/film/detail.aspx`）「放映版本」欄位有標示 `韓`（e.g. `數位 / 韓`、`GC 數位 / 韓`），但場次 API（`/ShowTimes/GetShowTimes`）回傳的版本字串 **不含語言 token**
   - 例：介紹頁顯示 `數位 / 韓`，API 回傳 `(數位)屍速禁區`
   - 現狀：韓語片 `language=""` — 為 API 與介紹頁資料不同步的缺口
   - TODO：額外爬 `/film/detail.aspx?id={movie_id}` 取語言標記，以 movie_id join 回場次資料，補上 `韓文` 對應

5. **跨日場次（隔日）遺失**
   - 問題：威秀部分影廳有凌晨跨日場次，時間格式為 `00:45(隔日)`，transform 的 `^\d{2}:\d{2}$` regex 完全過濾這些場次
   - 修正：
     - `_parse_showtimes_html()` 改用 `^(\d{2}:\d{2})(\(隔日\))?$` 比對，提取時間部分並記錄 `is_next_day: True`
     - `transform.py` `normalize()` 中，若 `is_next_day=True` 則 `show_date + timedelta(days=1)`
   - 影響：各影城跨日場次（00:xx、01:xx 隔日）得以正確記錄，日期對應到隔天

6. **ATMOS 未對應 Dolby**
   - 問題：威秀部分場次版本字串為 `ATMOS`（無 "DOLBY" 前綴），`_HALL_MAP` 只有 `"DOLBY ATMOS"` 條件，導致匹配失敗 → `standard`
   - 修正：`_HALL_MAP` 加入 `("ATMOS", "Dolby")`，置於 `DOLBY ATMOS` 之後；`transform._normalize_hall_type` 亦補充 `"ATMOS" in r` 條件
   - 影響：69 筆 ATMOS 場次從 `standard` 正確改為 `Dolby`（is_special_hall=True）

---

### 美麗華（miramar）— `scrapers/miramar.py` JS 注入

**修正項目：**

1. **日期偵測錯誤（所有場次日期變成同一天）**
   - 問題：原用 `TreeWalker` 從 booking link 向上爬 DOM 找日期文字，爬到高層容器後，TreeWalker 掃描容器內所有子節點文字，找到的是第一個出現的日期（今天），導致所有日期都錯誤標為同一天
   - 修正：日期直接編碼在 `.block` div 的 CSS class 中（格式：`block {UUID} 6月27日`），改用 `link.closest('.block').className.match(/(\d{1,2})月(\d{1,2})日/)` 精準提取
   - 影響：美麗華資料從「1 個日期 525 筆」正確展開為「19 個日期 505 筆」

2. **廳型偵測改善**
   - 問題：原用前兄弟節點掃描，有邊界情境失誤
   - 修正：從 `.block` 的直接子元素（非 `.time_area` 的 child）讀廳型文字，原方法作為 fallback

---

### 新光（skcinemas）— `scrapers/skcinemas.py`

**主要修正（API 回應格式解析）：**

- 問題：程式預期 `{Films: [...]}` 格式，實際 API 回傳 `{data: {SessionFilm: [...], Session: [...]}}`
- 修正：`_extract_sessions()` 改為：
  1. 從 `data.data.SessionFilm[]` 建立 `FilmNameID → FilmName` 映射
  2. 從 `data.data.Session[]` 提取場次，join FilmName
  3. `ShowTime: "19:15:00"` → 截取前 5 碼 `"19:15"`

**影城切換：**

- 新光有 5 間影城，電影詳情頁有 Dropdown（`.Dropdown-control`）切換
- 爬蟲點擊 Dropdown 依序切換至 5 間影城，每次觸發 `GetSessionByCinemasIDForApp` API
- 關鍵：以 `_CINEMA_KEYWORD`（獅子林/天母/青埔/中港/西門）比對 Dropdown 選項文字，避免點錯已收集的影城

**資料品質修正：**

1. **國語版 → 中文**
   - 問題：新光 `FilmType` 用 `國語版` 表示中文場，語言判斷只有 `英/日/中`，`國語版` 無「中」字 → `language=""`
   - 修正：加入 `"國" in ft` 條件 → `"中文"`
   - 影響：國語場次正確填入 `language="中文"`

2. **hall_name 改存 FilmType（原為 ScreenName）**
   - 問題：`hall_name` 原存 ScreenName（`1廳`、`2廳` 等廳號），遺失 FilmType 中的 `特別場`、`3D`、`B.O.X.` 等場次版本細節
   - 修正：`hall_name = s["film_type"]`（如 `B.O.X. Osim`、`MX4D-3D`、`特別場DolbyCinema`）
   - 影響：hall_name 語義與威秀一致，保留完整版本資訊

3. **SEALY 廳型新增**
   - 問題：新光 B.O.X. Sealy 廳（FilmType=`B.O.X. Sealy`）經 `transform._normalize_hall_type` 落回 `standard`，`is_special_hall=False`
   - 修正：`transform._normalize_hall_type` 加入 `"SEALY" → "SEALY"`；`SPECIAL_HALL_TYPES` 加入 `"SEALY"`
   - 影響：17 筆 Sealy 場次 `is_special_hall` 從 False → True

**已知缺口（不加欄位，記錄設計決策）：**

- **廳號（ScreenName）未保留**：新光 API 有 `ScreenName`（`1廳`、`2廳`…）代表實體廳編號。修正後 `hall_name` 改存 FilmType，ScreenName 未另存欄位。
  - 原因：威秀、美麗華皆無廳號概念，加欄位會造成跨院線空值；廳號對廳型/語言分析幫助有限
  - 若未來有需求，可在爬蟲加回 `screen_name` raw 欄位（API 直接提供，不需額外爬取）

---

---

## 待辦與設計決策

### TODO：電影訂票連結（booking_url）

**背景：** AI 查詢介面（`cinema-api`）目前回傳的場次資料無法直接點擊到訂票頁面或電影詳細資訊，使用者需自行前往各院線網站搜尋。

**可行性評估：**

| 院線 | 狀態 | 說明 |
|------|------|------|
| 美麗華 | ✅ 資料已存在 | `scrapers/miramar.py` 已從 DOM 提取 `movieId`、`sessionId`、booking `href`（格式：`/Booking/TicketType?id={movieId}&session={sessionId}`），目前僅用於輔助提取，未存入 schema |
| 威秀 | 🔍 待研究 | 電影詳細頁為 `/film/detail.aspx?Cid=XXX`，需研究場次 API 是否含電影 ID |
| 新光 | ✅ API 有資料 | `GetSessionByCinemasIDForApp` 回傳 `SessionID`、`FilmNameID`，需研究官網訂票 URL 格式 |

**實作方向：**
1. `schema` 新增 `booking_url STRING NULLABLE` 欄位
2. 美麗華：scraper 直接回傳 `https://www.miramarcinemas.tw{href}`
3. 威秀/新光：研究 URL 格式後補上
4. BigQuery 重新 load（WRITE_TRUNCATE，schema 向後相容）
5. `cinema-api` `/query` endpoint 的結果加入可點擊連結
6. `browse.html` 表格加入「訂票」連結欄

---

## 過濾規則

Transform 過濾掉以下記錄：

- `show_date` 無法解析（日期格式不符任何規則）
- `show_time` 不符 `HH:MM` 格式（`HH:MM(隔日)` 為例外：接受並自動 +1 天，見威秀跨日修正）

**跨日場次日期設計說明：**
威秀使用 `00:45(隔日)` 標記跨日場。`24:30` 此類超過 24 小時制不符合 SQL/BigQuery TIME 規格，直接存原時間（00:45）並將 `show_date` +1 天，才能正確反映播映的實際日曆時間。

---

## 實際數量（2026-06-27 執行）

| 院線 | 原始筆數 | 有效場次 | 特殊廳 |
|------|---------|---------|--------|
| 威秀 | ~11,967 | ~11,967 | 1,628 |
| 新光 | ~1,037 | ~1,037 | 316 |
| 美麗華 | ~505 | ~505 | 29 |
| **合計** | **~13,509** | **~13,509** | **1,973** |

特殊廳分布：IMAX 616、4DX 427、Dolby 342、GOLD CLASS 253、TITAN 130、LUXE 67、MX4D 67、MUCROWN 46、OSIM 25
