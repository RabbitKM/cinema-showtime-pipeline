import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from google.cloud import bigquery
from google.oauth2 import service_account

_here = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(os.path.dirname(_here), ".env"))

PROJECT_ID = os.getenv("BQ_PROJECT_ID", "cinema-showtime-pipeline")
DATASET_ID = os.getenv("BQ_DATASET_ID", "cinema_check")

bq_client: bigquery.Client = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global bq_client

    sa_rel = os.getenv("GCP_SERVICE_ACCOUNT_PATH", "service_account.json")
    sa_path = os.path.join(_here, sa_rel)
    if not os.path.exists(sa_path):
        sa_path = os.path.join(os.path.dirname(_here), sa_rel)

    if os.path.exists(sa_path):
        creds = service_account.Credentials.from_service_account_file(
            sa_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        bq_client = bigquery.Client(project=PROJECT_ID, credentials=creds)
    else:
        bq_client = bigquery.Client(project=PROJECT_ID)

    print("BigQuery 連線完成")
    yield


app = FastAPI(title="台灣影城場次瀏覽", lifespan=lifespan)


def _serialize(value):
    import datetime, decimal
    if isinstance(value, (datetime.date, datetime.datetime)):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


@app.get("/")
async def root():
    return FileResponse(os.path.join(_here, "index.html"))


@app.get("/api/data")
async def get_data():
    sql = f"""
        SELECT
            show_date,
            movie_name,
            theater_name,
            chain,
            hall_type,
            hall_name,
            show_time,
            language,
            is_special_hall,
            FORMAT_TIMESTAMP('%Y-%m-%d %H:%M', MAX(scraped_at) OVER(), 'Asia/Taipei') AS last_updated
        FROM `{PROJECT_ID}.{DATASET_ID}.fact_showtimes`
        ORDER BY show_date, chain, show_time
    """
    result = bq_client.query(sql).result()
    columns = [f.name for f in result.schema]
    rows = [[_serialize(v) for v in row.values()] for row in result]
    return JSONResponse({"columns": columns, "rows": rows})


@app.get("/health")
async def health():
    return {"status": "ok"}
