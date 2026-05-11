"""
delete_articles.py
Life After AI — Delete articles from DB by ID
Usage: python scraper/delete_articles.py --ids "ID1,ID2,..."
"""

import argparse
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

ROOT      = Path(__file__).parent.parent
DATA_FILE = ROOT / "data" / "cases.json"


def main():
    parser = argparse.ArgumentParser(description="Delete articles by ID")
    parser.add_argument("--ids", required=True,
                        help="Comma-separated article IDs to delete")
    args = parser.parse_args()

    ids_to_delete = {i.strip() for i in args.ids.split(",") if i.strip()}
    log.info(f"삭제 대상 ID: {ids_to_delete}")

    with open(DATA_FILE, encoding="utf-8") as f:
        db = json.load(f)

    before = len(db["cases"])
    removed = [c for c in db["cases"] if c["id"] in ids_to_delete]
    db["cases"] = [c for c in db["cases"] if c["id"] not in ids_to_delete]
    deleted = before - len(db["cases"])

    if deleted == 0:
        log.warning("해당 ID를 찾지 못했습니다.")
        return

    db["meta"]["total_cases"]  = len(db["cases"])
    db["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)

    for c in removed:
        log.info(f"  삭제: [{c['category']}] {c['company']} — {c['title']}")
    log.info(f"완료: {deleted}개 삭제, 잔여 {len(db['cases'])}개")


if __name__ == "__main__":
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    main()
