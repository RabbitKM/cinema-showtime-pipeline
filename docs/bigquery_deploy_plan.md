# Plan: BigQuery Load + AI Query API + Cloud Scheduling

## Context
ETL pipeline (Extract/Transform) 已完成並產出 output.json（約 13,500 筆）。
本計畫新增 Load 層（BigQuery）、AI 自然語言查詢介面（同 03_BQ_Gemini 模式）、以及每日 2 次的 Cloud Run 排程。
Project ID: `cinema-showtime-pipeline`，Dataset: `cinema_check`。

---

## 架構總覽

```
Cloud Scheduler (2x/day)
    ↓ HTTP trigger
Cloud Run Job: cinema-etl          Cloud Run Service: cinema-api
    ↓ python main.py --load              ↓ FastAPI + Gemini
    ↓                                    ↓
    BigQuery: fact_showtimes  ←──────── NL → SQL 查詢
```

---

## Phase 1：ETL Load 層 ✅

### 檔案清單
- `load.py` — BigQuery 寫入邏輯
- `main.py` — 新增 `--load` flag
- `.env.example` — 環境變數範本
- `requirements.txt` — 補 `google-auth`
- `Dockerfile` — ETL Job 容器（含 Chrome）

### BigQuery Schema（fact_showtimes）

| 欄位 | 型別 | mode |
|------|------|------|
| show_date | DATE | REQUIRED |
| movie_name | STRING | REQUIRED |
| theater_id | STRING | REQUIRED |
| theater_name | STRING | REQUIRED |
| chain | STRING | REQUIRED |
| hall_type | STRING | REQUIRED |
| hall_name | STRING | NULLABLE |
| show_time | STRING | REQUIRED |
| language | STRING | NULLABLE |
| is_special_hall | BOOL | REQUIRED |
| scraped_at | TIMESTAMP | REQUIRED |

- 分區：`TimePartitioning(field="show_date")`
- Cluster：`["chain", "hall_type"]`
- Load 策略：`WRITE_TRUNCATE`（每次全量覆蓋）

---

## Phase 2：排程（Cloud Run Job + Cloud Scheduler）

### 1. Service Account 設定

```bash
# 建立 ETL 用 SA
gcloud iam service-accounts create cinema-etl-sa \
  --display-name="Cinema ETL Service Account" \
  --project=cinema-showtime-pipeline

# 給予 BigQuery 寫入權限
gcloud projects add-iam-policy-binding cinema-showtime-pipeline \
  --member="serviceAccount:cinema-etl-sa@cinema-showtime-pipeline.iam.gserviceaccount.com" \
  --role="roles/bigquery.dataEditor"

gcloud projects add-iam-policy-binding cinema-showtime-pipeline \
  --member="serviceAccount:cinema-etl-sa@cinema-showtime-pipeline.iam.gserviceaccount.com" \
  --role="roles/bigquery.jobUser"

# 本機開發：下載金鑰
gcloud iam service-accounts keys create service_account.json \
  --iam-account=cinema-etl-sa@cinema-showtime-pipeline.iam.gserviceaccount.com
```

### 2. Build & Deploy Cloud Run Job

```bash
# 在 cinema_check/ 目錄下執行
gcloud builds submit --tag gcr.io/cinema-showtime-pipeline/cinema-etl .

gcloud run jobs create cinema-etl \
  --image gcr.io/cinema-showtime-pipeline/cinema-etl \
  --region asia-east1 \
  --service-account cinema-etl-sa@cinema-showtime-pipeline.iam.gserviceaccount.com \
  --set-env-vars BQ_PROJECT_ID=cinema-showtime-pipeline,BQ_DATASET_ID=cinema_check \
  --memory 2Gi \
  --task-timeout 1800
```

### 3. Cloud Scheduler（台灣時間 10:00 / 22:00 = UTC 02:00 / 14:00）

```bash
# 建立 Scheduler 用 SA
gcloud iam service-accounts create cinema-scheduler-sa \
  --display-name="Cinema Scheduler SA" \
  --project=cinema-showtime-pipeline

gcloud projects add-iam-policy-binding cinema-showtime-pipeline \
  --member="serviceAccount:cinema-scheduler-sa@cinema-showtime-pipeline.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# 早上場（台灣時間 10:00）
gcloud scheduler jobs create http cinema-etl-morning \
  --schedule="0 2 * * *" \
  --time-zone="UTC" \
  --uri="https://asia-east1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/cinema-showtime-pipeline/jobs/cinema-etl:run" \
  --message-body='{}' \
  --oauth-service-account-email=cinema-scheduler-sa@cinema-showtime-pipeline.iam.gserviceaccount.com \
  --location=asia-east1

# 晚上場（台灣時間 22:00）
gcloud scheduler jobs create http cinema-etl-evening \
  --schedule="0 14 * * *" \
  --time-zone="UTC" \
  --uri="https://asia-east1-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/cinema-showtime-pipeline/jobs/cinema-etl:run" \
  --message-body='{}' \
  --oauth-service-account-email=cinema-scheduler-sa@cinema-showtime-pipeline.iam.gserviceaccount.com \
  --location=asia-east1
```

---

## Phase 3：AI 查詢 API（同 03_BQ_Gemini）

> 待 Load 層驗證完成後實作。

```
api/
├── main.py        # FastAPI + Gemini（NL → SQL → BigQuery 執行）
├── templates.py   # 場次分析 SQL templates
├── Dockerfile     # python:3.12-slim（無需 Chrome）
└── requirements.txt
```

Cloud Run Service: `cinema-api`（持久運行，提供查詢 API）

---

## 驗證步驟

1. 本機：`cp .env.example .env` → 填入 SA 金鑰路徑 → `python main.py --load`
2. BigQuery Console 確認 `cinema_check.fact_showtimes` 分區正確
3. Docker 本機測試：`docker build -t cinema-etl . && docker run --env-file .env cinema-etl`
4. Cloud Run Job 手動觸發：`gcloud run jobs execute cinema-etl --region asia-east1`
5. Cloud Scheduler 觸發後確認 BigQuery 資料更新時間戳
