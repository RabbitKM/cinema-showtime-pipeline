"""
Load 層：將正規化場次資料寫入 BigQuery fact_showtimes 表

認證策略（同 03_BQ_Gemini 模式）：
  本機開發：讀 GCP_SERVICE_ACCOUNT_PATH 指向的服務帳號 JSON
  Cloud Run：使用內建 Application Default Credentials（ADC），無需金鑰檔案

環境變數：
  BQ_PROJECT_ID              GCP 專案 ID
  BQ_DATASET_ID              BigQuery Dataset 名稱
  GCP_SERVICE_ACCOUNT_PATH   本機服務帳號金鑰路徑（Cloud Run 省略）
"""
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from google.cloud import bigquery
from google.oauth2 import service_account

load_dotenv()

TABLE_ID = "fact_showtimes"

SCHEMA = [
    bigquery.SchemaField("show_date",       "DATE",      mode="REQUIRED"),
    bigquery.SchemaField("movie_name",      "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("theater_id",      "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("theater_name",    "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("chain",           "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("hall_type",       "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("hall_name",       "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("show_time",       "STRING",    mode="REQUIRED"),
    bigquery.SchemaField("language",        "STRING",    mode="NULLABLE"),
    bigquery.SchemaField("is_special_hall", "BOOL",      mode="REQUIRED"),
    bigquery.SchemaField("scraped_at",      "TIMESTAMP", mode="REQUIRED"),
]


def _get_client(project_id: str) -> bigquery.Client:
    sa_path = os.path.join(
        os.path.dirname(__file__),
        os.getenv("GCP_SERVICE_ACCOUNT_PATH", "service_account.json"),
    )
    if os.path.exists(sa_path):
        credentials = service_account.Credentials.from_service_account_file(
            sa_path,
            scopes=["https://www.googleapis.com/auth/cloud-platform"],
        )
        return bigquery.Client(project=project_id, credentials=credentials)
    return bigquery.Client(project=project_id)


def _prepare_row(rec: dict) -> dict:
    """將 normalize() 輸出的 dict 轉為 BigQuery 相容格式"""
    scraped_raw = rec.get("scraped_at", "")
    if scraped_raw and not scraped_raw.endswith("+00:00") and not scraped_raw.endswith("Z"):
        scraped_raw += "+00:00"

    return {
        "show_date":       rec["show_date"],
        "movie_name":      rec.get("movie_name") or "",
        "theater_id":      rec.get("theater_id") or "",
        "theater_name":    rec.get("theater_name") or "",
        "chain":           rec.get("chain") or "",
        "hall_type":       rec.get("hall_type") or "standard",
        "hall_name":       rec.get("hall_name") or None,
        "show_time":       rec.get("show_time") or "",
        "language":        rec.get("language") or None,
        "is_special_hall": bool(rec.get("is_special_hall", False)),
        "scraped_at":      scraped_raw or None,
    }


def load_to_bigquery(records: list[dict]) -> int:
    """
    將 normalize() 輸出寫入 BigQuery fact_showtimes（WRITE_TRUNCATE）。
    回傳寫入筆數。
    """
    project_id = os.getenv("BQ_PROJECT_ID")
    dataset_id = os.getenv("BQ_DATASET_ID")
    if not project_id or not dataset_id:
        raise RuntimeError("BQ_PROJECT_ID 或 BQ_DATASET_ID 未設定，請確認 .env 檔案")

    client = _get_client(project_id)

    # 確保 Dataset 存在
    dataset_ref = bigquery.Dataset(f"{project_id}.{dataset_id}")
    dataset_ref.location = "asia-east1"
    client.create_dataset(dataset_ref, exists_ok=True)

    table_ref = f"{project_id}.{dataset_id}.{TABLE_ID}"

    job_config = bigquery.LoadJobConfig(
        schema=SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        time_partitioning=bigquery.TimePartitioning(
            type_=bigquery.TimePartitioningType.DAY,
            field="show_date",
        ),
        clustering_fields=["chain", "hall_type"],
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
    )

    rows = [_prepare_row(r) for r in records]

    load_job = client.load_table_from_json(rows, table_ref, job_config=job_config)
    load_job.result()  # 等待完成

    table = client.get_table(table_ref)
    return table.num_rows
