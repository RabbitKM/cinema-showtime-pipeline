# 台灣影城特殊廳場次 ETL 分析平台

> 面試用專案說明文件。涵蓋架構設計、技術選型、挑戰與解法、live demo URL。

---

## 專案概要

**目標**：自動爬取台灣三大院線（威秀、新光、美麗華）的電影場次，清洗正規化後存入 BigQuery，並提供兩個面向使用者的分析介面。

**動機**：展示完整的資料工程能力——從爬蟲、ETL pipeline、雲端部署，到 AI 驅動的查詢介面，以及資料品質問題的系統性處理。

**成果**：
- 每日自動抓取 12,000+ 筆場次資料（三家院線 × 每日兩次）
- 兩個雲端 UI：自然語言 AI 查詢平台、試算表風格篩選平台
- 全程免費或極低成本（GCP 免費額度 + Gemini API free tier）

---

## Live Demo URL

| 服務 | URL |
|------|-----|
| AI 自然語言查詢平台 | https://cinema-api-798473841655.asia-east1.run.app |
| 試算表篩選瀏覽平台 | https://cinema-browse-798473841655.asia-east1.run.app |

---

## 技術架構

```
┌─────────────────────────────────────────────────────┐
│                   ETL Pipeline                       │
│                                                      │
│  Extract (scrapers/)  →  Transform  →  Load          │
│  ├── vscinemas.py         transform.py  load.py      │
│  ├── skcinemas.py         正規化廳型    BigQuery      │
│  └── miramar.py           正規化語言    WRITE_TRUNCATE│
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                  部署架構（混合）                     │
│                                                      │
│  Cloud Run Job (cinema-etl)                          │
│    威秀 + 美麗華，每日 10:00 / 22:00 CST             │
│                                                      │
│  Windows 工作排程器（本機）                           │
│    三家全跑（含新光），每日 10:30 / 22:30 CST         │
│    → 30 分鐘後覆蓋，確保資料完整                     │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│               兩個 Cloud Run Services                │
│                                                      │
│  cinema-api (FastAPI)          cinema-browse (FastAPI)│
│  ├── GET /      → index.html   ├── GET /  → index.html│
│  ├── POST /query → NL→SQL→BQ   └── GET /api/data→BQ  │
│  └── GET /health               (全量載入 client-side 篩選)│
└─────────────────────────────────────────────────────┘
```

**BigQuery Table**: `cinema-showtime-pipeline.cinema_check.fact_showtimes`

---

## 技術選型與理由

| 技術 | 選擇理由 |
|------|---------|
| **Playwright** | vscinemas 網站使用 Akamai bot detection，`requests` 直接被擋；必須使用真實 Chrome（`channel="chrome"`）才能通過 |
| **BigQuery** | Schema 彈性（支援 NULLABLE 欄位）、SQL 標準查詢、免費額度充裕、與 GCP 其他服務整合 |
| **Sentence Transformers** | 輕量語意搜尋，本地推論（不耗 API 額度），用於 NL 問題→SQL 模板匹配 |
| **Gemini 2.5 Flash** | 免費 API 額度、支援 SQL 生成、速度快；配合 3 key 輪替避免 rate limit |
| **Cloud Run** | Serverless、無需管理 VM、自動 scale-to-zero（節省費用）、Docker 容器部署 |
| **FastAPI** | async 支援、自動 OpenAPI 文件、Pydantic 驗證 |

---

## AI 查詢平台架構（cinema-api）

```
使用者輸入自然語言問題
        │
        ▼
SentenceTransformer (all-MiniLM-L6-v2)
  → 語意相似度搜尋 11 個 SQL 模板
  → 找出最相近的模板（cosine similarity）
        │
        ▼
Gemini 2.5 Flash
  → 輸入：問題 + 最相近模板 + BigQuery schema + 真實影城名稱清單
  → 輸出：完整可執行的 BigQuery SQL
        │
        ▼
BigQuery 執行 SQL → 回傳結果
        │
        ▼
前端渲染（廳型彩色 badge、院線顏色、院線官網連結）
```

**關鍵 prompt 設計**：
- 注入 31 間真實影城名稱（vscinemas 25 間 + 新光 5 間 + 美麗華 1 間）
- 明確指示「影城名稱一律用 LIKE '%關鍵字%' 模糊比對」
- 避免 Gemini 自行猜測影城名稱格式（曾出現 `威秀影城(信義店)` 等幻覺）

---

## 關鍵技術挑戰與解法

### 1. skcinemas（新光）Cloudflare IP 封鎖

**問題**：GCP Cloud Run 的出口 IP 被 Cloudflare 封鎖，`Page.goto: Timeout 60000ms exceeded`，即使加長 timeout 也無解。

**驗證過程**：
- 確認是 IP 封鎖（非程式碼問題）
- 嘗試直接呼叫 API (`POST /api/VistaDataV2/GetSessionByCinemasIDForApp`)，但需要瀏覽器 JS session，`requests` 回傳 `result: False`

**解法**：混合架構
- Cloud Run Job 只跑 vscinemas + miramar（`--source vscinemas miramar`）
- 本機 Windows 工作排程器跑全部三家（含新光），30 分鐘後以 `WRITE_TRUNCATE` 覆蓋，確保 BigQuery 有完整資料
- Cloud Run 資料作為本機未執行時的備份

### 2. 三院線異質資料正規化

每家院線的資料格式完全不同：

| | 威秀 | 新光 | 美麗華 |
|--|------|------|--------|
| 日期格式 | `07月08日 星期三` | `2026/06/26` | CSS class `6月27日` |
| 廳型來源 | 版本字串 `(4DX 3D 英)電影名` | `FilmType` 欄位 | HTML 元素文字 |
| 語言標記 | `英/中/日/國` token | `英文版/國語版/日文版` | 嵌在廳型字串內 |

**解法**：`transform.py` 統一正規化層，處理日期、廳型（`_HALL_MAP` 對應表）、語言（Fallback 邏輯）。

**邊界情況修正**（各自發現並修復）：
- 威秀 GC → GOLD CLASS（縮寫未在對應表）
- 威秀 ATMOS 未對應 Dolby
- 威秀「國」語 → 中文
- 威秀跨日場次 `00:45(隔日)` → `show_date + 1`
- 新光 B.O.X. Sealy 未在特殊廳清單
- 美麗華日期從 DOM CSS class 提取（TreeWalker 法有 bug）

### 3. vscinemas Akamai Bot Detection

**問題**：`playwright install` 下載的 Chromium 被識別為爬蟲並封鎖。

**解法**：
- 安裝真實 Google Chrome Stable（`apt-get install google-chrome-stable`）
- 使用 `browser_type.launch(channel="chrome")` 指定真實 Chrome
- Dockerfile 加入 Google Chrome APT source

### 4. Gemini Rate Limit（面試現場保護）

**問題**：多次快速查詢觸發 Gemini API 429 Rate Limit。

**解法**：3 key 輪替機制
- 讀取 `GEMINI_API_KEY`、`GEMINI_API_KEY_2`、`GEMINI_API_KEY_3`
- 查詢失敗且為 429/quota/rate 類錯誤 → 自動切換下一把 key
- 全部失敗才回傳 429 錯誤給使用者
- Keys 存在 Cloud Run 環境變數，不需重新 build 即可新增

---

## 資料 Schema（fact_showtimes）

| 欄位 | 型別 | 說明 |
|------|------|------|
| `show_date` | STRING (YYYY-MM-DD) | 場次日期 |
| `movie_name` | STRING | 電影中文名稱 |
| `theater_id` | STRING | 影城唯一 ID |
| `theater_name` | STRING | 影城中文名稱 |
| `chain` | STRING | 院線（威秀/新光/美麗華） |
| `hall_type` | STRING | 正規化廳型（IMAX/4DX/Dolby 等 10 種） |
| `hall_name` | STRING | 原始廳型細節（IMAX 3D、GC 數位等） |
| `show_time` | STRING (HH:MM) | 場次時間 |
| `language` | STRING | 英文/中文/日文/空字串 |
| `is_special_hall` | BOOL | 是否為特殊廳 |
| `scraped_at` | TIMESTAMP (UTC) | 爬取時間戳 |

**資料規模**：每次爬取約 12,000–13,500 筆，WRITE_TRUNCATE 每日兩次覆蓋。

---

## 試算表瀏覽平台（cinema-browse）

**設計**：一次載入全量資料（~400KB JSON），所有篩選在 client-side JS 執行，無需再打 API。

**篩選功能**：
- 下拉多選：日期、院線、影城、廳型、語言、是否特殊廳
- 時段下拉：早上(06-12)、下午(12-17)、晚上(17-21)、深夜(21-)
- 文字搜尋：電影名稱、廳名

**修正的 UX 問題**：
- 原設計「預設全勾/勾選=排除」→ 改為「預設全不勾/勾選=包含」
- 修正後「新光 + IMAX → 正確顯示空表格」

---

## 專案目錄結構

```
cinema_check/
├── main.py                 # ETL 主程式（--source 多選、--load、--dry-run）
├── transform.py            # 正規化層
├── load.py                 # BigQuery WRITE_TRUNCATE 寫入
├── run_etl_local.ps1       # 本機 Windows 排程腳本
├── Dockerfile              # Cloud Run Job（ETL）
├── scrapers/
│   ├── vscinemas.py        # 威秀（真實 Chrome + HTML 解析）
│   ├── skcinemas.py        # 新光（Playwright + API 攔截）
│   └── miramar.py          # 美麗華（JS 注入提取資料）
├── api/
│   ├── main.py             # FastAPI（NL→SQL→BQ）
│   ├── templates.py        # 11 個 SQL 模板
│   ├── index.html          # AI 查詢前端
│   ├── Dockerfile
│   └── requirements.txt
├── browse/
│   ├── main.py             # FastAPI（全量資料 API）
│   ├── index.html          # 試算表篩選前端
│   ├── Dockerfile
│   └── requirements.txt
└── docs/
    ├── transform_log.md    # ETL 修正紀錄（含邊界情況）
    └── PROJECT_BRIEF.md    # 本文件
```

---

## 面試可能被問的問題

**架構類**
- 為什麼選 BigQuery 而不是 PostgreSQL？
- Cloud Run Job vs Cloud Run Service 的差異？
- WRITE_TRUNCATE 的取捨是什麼？（當下只需要最新資料，不需歷史累積）

**技術深度**
- Akamai bot detection 怎麼繞過？
- SentenceTransformer 在這裡扮演什麼角色？
- 三個院線資料格式完全不同，你怎麼統一正規化？
- `(隔日)` 跨日場次問題怎麼發現的？

**挑戰與決策**
- 新光被 Cloudflare 封鎖，你怎麼決策的？（混合架構 vs 付費 proxy）
- Gemini 幻覺問題（影城名稱猜錯）怎麼發現、怎麼修？
- Rate limit 問題在面試現場最嚴重，怎麼設計的保護機制？

**擴展性**
- 如果要加第四家院線，流程是什麼？
- 如果要保留歷史資料，需要改哪裡？（load.py WRITE_APPEND + show_date 分區）
- booking_url 要怎麼加？（miramar 已有，威秀/新光需研究 URL 格式）
