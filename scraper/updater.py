"""
updater.py
Life After AI — DB updater
Merges new extracted cases into cases.json, deduplicates, updates meta
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)
ROOT = Path(__file__).parent.parent
DATA_FILE = ROOT / "data" / "cases.json"


def load_db() -> dict:
    with open(DATA_FILE) as f:
        return json.load(f)


def save_db(db: dict) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    log.info(f"Saved {len(db['cases'])} cases to {DATA_FILE}")


def deduplicate(cases: list[dict]) -> list[dict]:
    """Remove cases with duplicate URLs."""
    seen_urls = set()
    unique = []
    for c in cases:
        url = c.get("url", "")
        if url and url not in seen_urls:
            seen_urls.add(url)
            unique.append(c)
    return unique


def merge_new_cases(new_cases: list[dict]) -> dict:
    """
    Merge new cases into the DB.
    Returns a summary dict: {added, skipped, total}
    """
    db = load_db()
    existing_urls = {c["url"] for c in db["cases"]}

    added = 0
    skipped = 0

    for case in new_cases:
        url = case.get("url", "")
        if url in existing_urls:
            log.info(f"Skip (duplicate): {case.get('company')} — {url[:60]}")
            skipped += 1
            continue

        # Validate required fields
        required = ["id", "category", "company", "title", "url"]
        if not all(case.get(f) for f in required):
            log.warning(f"Skip (missing fields): {case}")
            skipped += 1
            continue

        db["cases"].append(case)
        existing_urls.add(url)
        added += 1
        log.info(f"Added: [{case['category']}] {case['company']} — {case['title']}")

    # Update meta
    db["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
    db["meta"]["total_cases"] = len(db["cases"])

    if added > 0:
        save_db(db)

    summary = {"added": added, "skipped": skipped, "total": len(db["cases"])}
    log.info(f"Update summary: {summary}")
    return summary


def get_stats() -> dict:
    """Return stats about the current DB."""
    db = load_db()
    cats = {}
    for c in db["cases"]:
        cat = c.get("category", "unknown")
        cats[cat] = cats.get(cat, 0) + 1

    verified = sum(1 for c in db["cases"] if c.get("verified"))
    return {
        "total": len(db["cases"]),
        "verified": verified,
        "unverified": len(db["cases"]) - verified,
        "by_category": cats,
        "last_updated": db["meta"].get("last_updated"),
    }


if __name__ == "__main__":
    print(json.dumps(get_stats(), indent=2, ensure_ascii=False))
