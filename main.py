"""
ETL 主程式
執行順序: Extract (三個影城) → Transform (正規化) → Load (BigQuery / 本地 JSON)

用法:
  python main.py                  # 全部執行，結果存 output.json
  python main.py --load           # 全部執行，存 output.json + 上傳 BigQuery
  python main.py --source miramar # 僅跑美麗華
  python main.py --dry-run        # 只印結果，不寫檔
"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from scrapers import miramar, skcinemas, vscinemas
from transform import normalize

OUTPUT_FILE = Path(__file__).parent / "output.json"

SCRAPERS = {
    "miramar": miramar.extract,
    "skcinemas": skcinemas.extract,
    "vscinemas": vscinemas.extract,
}


def run(sources: list[str], dry_run: bool = False, load: bool = False):
    all_raw = []
    start = datetime.utcnow()

    for name in sources:
        print(f"\n=== Extract: {name} ===")
        try:
            records = SCRAPERS[name]()
            print(f"  → {len(records)} 筆原始資料")
            all_raw.extend(records)
        except Exception as e:
            print(f"  [ERROR] {name} 爬蟲失敗: {e}", file=sys.stderr)

    print(f"\n=== Transform ===")
    normalized = normalize(all_raw)
    print(f"  → {len(normalized)} 筆有效場次 (過濾無效日期/時間後)")

    # 依影城/日期摘要
    from collections import Counter
    summary = Counter(
        (r["chain"], r["show_date"]) for r in normalized
    )
    for (chain, d), cnt in sorted(summary.items()):
        print(f"  {chain} {d}: {cnt} 場")

    elapsed = (datetime.utcnow() - start).total_seconds()
    print(f"\n耗時: {elapsed:.1f} 秒")

    if dry_run:
        print("[dry-run] 未寫入檔案")
        return normalized

    # 輸出 JSON（不含 _source_raw 以免過大）
    clean = [{k: v for k, v in r.items() if k != "_source_raw"} for r in normalized]
    OUTPUT_FILE.write_text(json.dumps(clean, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n結果已寫入: {OUTPUT_FILE} ({OUTPUT_FILE.stat().st_size // 1024} KB)")

    if load:
        print("\n=== Load: BigQuery ===")
        from load import load_to_bigquery
        count = load_to_bigquery(clean)
        print(f"  → BigQuery 寫入完成：{count} 筆")

    return normalized


def main():
    parser = argparse.ArgumentParser(description="Cinema showtime ETL")
    parser.add_argument(
        "--source",
        choices=list(SCRAPERS.keys()),
        help="只執行指定影城爬蟲 (預設: 全部)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只列印結果，不寫檔",
    )
    parser.add_argument(
        "--load",
        action="store_true",
        help="寫入 BigQuery（需設定 BQ_PROJECT_ID / BQ_DATASET_ID）",
    )
    args = parser.parse_args()

    sources = [args.source] if args.source else list(SCRAPERS.keys())
    run(sources, dry_run=args.dry_run, load=args.load)


if __name__ == "__main__":
    main()
