"""
台灣影城特殊廳場次 AI 查詢 API

架構同 03_BQ_Gemini：
  SentenceTransformer 語意搜尋 → 找最相近的 SQL 模板
  Gemini 生成最終 SQL（參考模板 + 即時 schema）
  BigQuery 執行查詢並回傳結果

認證：本機用 GCP_SERVICE_ACCOUNT_PATH，Cloud Run 用 ADC
"""
import os
import re
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from google import genai as google_genai
from google.cloud import bigquery
from google.oauth2 import service_account
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer

from templates import SQL_TEMPLATES

_api_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(os.path.dirname(_api_dir), ".env"))  # cinema_check/.env

embed_model: SentenceTransformer = None
template_embeddings: np.ndarray = None
gemini_clients: list = []   # 支援多 key 輪替，遇到 429 自動換下一把
bq_client = None
bq_schema_info: str = ""

PROJECT_ID = os.getenv("BQ_PROJECT_ID", "cinema-showtime-pipeline")
DATASET_ID = os.getenv("BQ_DATASET_ID", "cinema_check")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global embed_model, template_embeddings, gemini_clients, bq_client, bq_schema_info

    print("載入嵌入模型中...")
    embed_model = SentenceTransformer("all-MiniLM-L6-v2")
    descriptions = [t["description"] for t in SQL_TEMPLATES]
    template_embeddings = embed_model.encode(descriptions, normalize_embeddings=True)
    print(f"已載入 {len(SQL_TEMPLATES)} 個 SQL 模板")

    # 讀取所有 Gemini key（GEMINI_API_KEY, GEMINI_API_KEY_2, GEMINI_API_KEY_3...）
    raw_keys = [os.getenv("GEMINI_API_KEY")]
    for i in range(2, 6):
        k = os.getenv(f"GEMINI_API_KEY_{i}")
        if k:
            raw_keys.append(k)
    valid_keys = [k for k in raw_keys if k]
    if not valid_keys:
        raise RuntimeError("GEMINI_API_KEY 未設定")
    gemini_clients = [
        google_genai.Client(api_key=k, http_options={"api_version": "v1alpha"})
        for k in valid_keys
    ]
    print(f"Gemini clients 初始化完成：{len(gemini_clients)} 把 key")

    sa_rel = os.getenv("GCP_SERVICE_ACCOUNT_PATH", "service_account.json")
    # 先找 api/ 同層，再往上找 cinema_check/
    api_dir = os.path.dirname(os.path.abspath(__file__))
    sa_path = os.path.join(api_dir, sa_rel)
    if not os.path.exists(sa_path):
        sa_path = os.path.join(os.path.dirname(api_dir), sa_rel)
    if os.path.exists(sa_path):
        credentials = service_account.Credentials.from_service_account_file(
            sa_path, scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        bq_client = bigquery.Client(project=PROJECT_ID, credentials=credentials)
    else:
        bq_client = bigquery.Client(project=PROJECT_ID)

    try:
        table_ref = bq_client.get_table(f"{PROJECT_ID}.{DATASET_ID}.fact_showtimes")
        cols = ", ".join(f"{f.name} ({f.field_type})" for f in table_ref.schema)
        bq_schema_info = f"fact_showtimes：{cols}"
        print(f"BigQuery schema 載入完成")
    except Exception as e:
        bq_schema_info = ""
        print(f"警告：無法取得 schema：{e}")

    print("伺服器準備完成！")
    yield


app = FastAPI(title="台灣影城特殊廳場次查詢", lifespan=lifespan)


class QueryRequest(BaseModel):
    question: str


def _find_best_template(question: str) -> dict:
    q_emb = embed_model.encode([question], normalize_embeddings=True)
    scores = np.dot(template_embeddings, q_emb.T).flatten()
    return SQL_TEMPLATES[int(np.argmax(scores))]


def _build_prompt(question: str, template: dict) -> str:
    return f"""你是台灣電影場次資料分析助理。請根據使用者問題，產生一個能在 BigQuery 執行的 SQL 查詢。

【資料庫資訊】
專案: {PROJECT_ID}
資料集: {DATASET_ID}
資料表欄位: {bq_schema_info}

欄位說明：
- show_date: 場次日期（DATE，台灣時間）
- movie_name: 電影中文名稱
- theater_name: 影城名稱（搜尋時**一律使用 LIKE '%關鍵字%' 模糊比對，嚴禁用精確 = 符號**）
  威秀影城：台北信義威秀影城、台北西門威秀影城、台北京站威秀影城、台北南港 LaLaport威秀影城、MUVIE CINEMAS 台北松仁、中和環球威秀影城、新店裕隆城威秀影城、新竹巨城威秀影城、新竹大遠百威秀影城、板橋大遠百威秀影城、林口MITSUI OUTLET PARK威秀影城、桃園統領威秀影城、桃園桃知道威秀影城、台中大遠百威秀影城、台中iFG 遠雄廣場威秀影城、台南FOCUS威秀影城、台南大遠百威秀影城、高雄大遠百威秀影城
  新光影城：台北獅子林新光影城、台北天母新光影城、桃園青埔新光影城、台中中港新光影城、台南西門新光影城
  美麗華：美麗華影城
- chain: 院線（威秀 / 新光 / 美麗華）
- hall_type: 正規化廳型（IMAX / 4DX / MX4D / Dolby / GOLD CLASS / TITAN / MUCROWN / LUXE / OSIM / SEALY / standard）
- hall_name: 原始廳型細節（例如 IMAX 3D、4DX 3D、GC 數位）
- show_time: 場次時間（STRING，格式 HH:MM）
- language: 語言（英文 / 中文 / 日文 / 空字串）
- is_special_hall: 是否為特殊廳（BOOL）
- scraped_at: 資料抓取時間（TIMESTAMP UTC）

日期函式請使用 CURRENT_DATE('Asia/Taipei') 或 CURRENT_TIMESTAMP()。

【參考 SQL 模板】（可以此為起點修改，不必完全照抄）
{template['sql_template'].format(project=PROJECT_ID, dataset=DATASET_ID, movie_name='', hall_type='', theater_name='')}

【使用者問題】
{question}

請直接輸出 SQL，不要加任何說明文字或 markdown 格式。"""


def _clean_sql(raw: str) -> str:
    raw = re.sub(r"```(?:sql)?", "", raw, flags=re.IGNORECASE)
    return raw.replace("```", "").strip()


def _serialize(value: Any) -> Any:
    import datetime, decimal
    if isinstance(value, (datetime.date, datetime.datetime)):
        return str(value)
    if isinstance(value, decimal.Decimal):
        return float(value)
    return value


@app.get("/")
async def root():
    index = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(index):
        return FileResponse(index)
    return JSONResponse({"status": "Cinema Showtime API running"})


@app.post("/query")
async def query(req: QueryRequest):
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="問題不能為空")

    template = _find_best_template(req.question)
    prompt = _build_prompt(req.question, template)

    sql = None
    last_err = None
    for client in gemini_clients:
        try:
            response = client.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
            )
            sql = _clean_sql(response.text)
            break
        except Exception as e:
            last_err = e
            err_str = str(e).lower()
            if any(kw in err_str for kw in ("429", "quota", "rate", "resource exhausted")):
                continue   # 換下一把 key
            raise HTTPException(status_code=500, detail=f"Gemini 生成失敗：{e}")
    if sql is None:
        raise HTTPException(status_code=429, detail=f"所有 Gemini API key 均達速率限制，請稍後再試。({last_err})")

    try:
        result = bq_client.query(sql).result()
        columns = [f.name for f in result.schema]
        rows = [[_serialize(v) for v in row.values()] for row in result]
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"BigQuery 查詢失敗：{e}\nSQL: {sql}")

    return {"sql": sql, "columns": columns, "rows": rows, "template_used": template["id"]}


@app.get("/health")
async def health():
    return {"status": "ok"}
