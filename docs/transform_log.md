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

1. **跨日場次（隔日）遺失**
   - 問題：威秀部分影廳有凌晨跨日場次，時間格式為 `00:45(隔日)`，transform 的 `^\d{2}:\d{2}$` regex 完全過濾這些場次
   - 修正：
     - `_parse_showtimes_html()` 改用 `^(\d{2}:\d{2})(\(隔日\))?$` 比對，提取時間部分並記錄 `is_next_day: True`
     - `transform.py` `normalize()` 中，若 `is_next_day=True` 則 `show_date + timedelta(days=1)`
   - 影響：各影城跨日場次（00:xx、01:xx 隔日）得以正確記錄，日期對應到隔天

2. **韓語場次 language 為空**（已知缺口，待補）
   - 查驗：威秀電影介紹頁（`/film/detail.aspx`）「放映版本」欄位有標示 `韓`（e.g. `數位 / 韓`、`GC 數位 / 韓`），但場次 API（`/ShowTimes/GetShowTimes`）回傳的版本字串 **不含語言 token**
   - 例：介紹頁顯示 `數位 / 韓`，API 回傳 `(數位)屍速禁區`
   - 現狀：韓語片 `language=""` — 為 API 與介紹頁資料不同步的缺口
   - TODO：額外爬 `/film/detail.aspx?id={movie_id}` 取語言標記，以 movie_id join 回場次資料，補上 `韓文` 對應

3. **GC → GOLD CLASS**
   - 問題：威秀 Gold Class 廳版本字串為 `GC 數位`，程式只比對 `"GOLD CLASS"` 全名，導致匹配失敗 → 歸類為 `standard`（is_special_hall=False）
   - 修正：在 `_HALL_MAP` 加入 `("GC", "GOLD CLASS")` 別名，置於 `GOLD CLASS` 之後（避免 `GC` 誤觸 `GOLD CLASS` 字串）
   - 影響：253 筆 GOLD CLASS 場次從 `standard` 正確改為 `GOLD CLASS`

2. **「國」語對應中文**
   - 問題：威秀版本字串用 `國`（國語）表示中文場，語言對照表只有 `英/中/日`，`國` 未對應 → `language = ""`
   - 修正：加入 `("國", "中文")` 對應
   - 影響：約 1,900+ 筆威秀中文場次 language 從空白正確填入 `"中文"`

3. **`hall_name` 保留版本字串**
   - 問題：`hall_name` 未填，前端看不出 `IMAX` vs `IMAX 3D`、`GC 數位` vs 一般 `數位`
   - 修正：`_parse_version()` 新增第 4 個回傳值；`hall_name` = 版本字串去掉語言 token（按空格分割後過濾 `{英,中,日,國}`）
   - 範例：`"4DX 3D 英"` → hall_type=`4DX`、hall_name=`4DX 3D`

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

---

## 過濾規則

Transform 過濾掉以下記錄：

- `show_date` 無法解析（日期格式不符任何規則）
- `show_time` 不符 `HH:MM` 格式

---

## 實際數量（2026-06-27 執行）

| 院線 | 原始筆數 | 有效場次 | 特殊廳 |
|------|---------|---------|--------|
| 威秀 | ~11,967 | ~11,967 | 1,628 |
| 新光 | ~1,037 | ~1,037 | 316 |
| 美麗華 | ~505 | ~505 | 29 |
| **合計** | **~13,509** | **~13,509** | **1,973** |

特殊廳分布：IMAX 616、4DX 427、Dolby 342、GOLD CLASS 253、TITAN 130、LUXE 67、MX4D 67、MUCROWN 46、OSIM 25
