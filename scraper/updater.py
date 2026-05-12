"""
updater.py
Life After AI — DB updater
Merges new extracted cases into cases.json, deduplicates, updates meta.
Routes new cases through quality_filter before merge: accept/hold/reject.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

log = logging.getLogger(__name__)
ROOT = Path(__file__).parent.parent
DATA_FILE = ROOT / "docs" / "data" / "cases.json"
REJECTED_LOG = Path(__file__).parent / "rejected_log.jsonl"

# Abort the batch when LLM keeps failing — prevents a broken model from
# silently flooding cases.json with llm_error holds for human review.
ERROR_THRESHOLD = 5


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


def _quality_filter_enabled() -> bool:
    return os.environ.get("QUALITY_FILTER_ENABLED", "true").lower() in ("1", "true", "yes")


def _append_rejected_log(case: dict, reason: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "id":        case.get("id"),
        "title":     case.get("title"),
        "reason":    reason,
        "url":       case.get("url"),
    }
    with open(REJECTED_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def log_quality_decision(case: dict, result: dict, dry_run: bool = False) -> None:
    decision = result["decision"]
    reason = result["reason"]
    title_snip = (case.get("title") or "")[:50]
    tag = {"accept": "[QF accept]", "hold": "[QF hold]  ", "reject": "[QF reject]"}[decision]
    log.info(f"  {tag} {case.get('company')} — {title_snip} ({reason})")
    if decision == "reject" and not dry_run:
        _append_rejected_log(case, reason)


def _run_quality_filter(new_cases: list[dict], db_cases: list[dict],
                        dry_run: bool) -> tuple[list[dict], dict]:
    """
    Route each case through quality_filter.evaluate_article.
    Returns (kept_cases, qf_summary). 'kept_cases' excludes rejects;
    accepts get verified=True, holds get verified=False.
    """
    from quality_filter import evaluate_article
    from llm_summarizer import call_llm_json

    kept: list[dict] = []
    summary = {"accept": 0, "hold": 0, "reject": 0, "llm_errors": 0}

    for case in new_cases:
        try:
            result = evaluate_article(case, db_cases, call_llm_json)
        except Exception as e:
            summary["llm_errors"] += 1
            err_type = type(e).__name__
            log.warning(
                f"  [QF llm_error] id={case.get('id')} "
                f"err={err_type}: {e} → fallback to hold"
            )
            if summary["llm_errors"] >= ERROR_THRESHOLD:
                raise RuntimeError(
                    f"Quality filter aborted: {summary['llm_errors']} LLM errors "
                    f"in this batch (threshold={ERROR_THRESHOLD}). "
                    "Check API key, quota, and GitHub Models service status."
                )
            result = {
                "decision":     "hold",
                "reason":       f"llm_error:{err_type}",
                "scores":       None,
                "duplicate_of": None,
            }

        log_quality_decision(case, result, dry_run=dry_run)

        if result["decision"] == "reject":
            summary["reject"] += 1
            continue

        case["verified"] = (result["decision"] == "accept")
        if result.get("scores"):
            case["quality_scores"] = result["scores"]
        kept.append(case)
        summary[result["decision"]] += 1

    return kept, summary


def merge_new_cases(new_cases: list[dict], dry_run: bool = False) -> dict:
    """
    Merge new cases into the DB.
    Returns a summary dict: {added, skipped, total, quality_filter}.
    With dry_run=True the quality filter still runs (to surface decisions),
    but no DB save and no rejected_log writes happen.
    """
    db = load_db()
    existing_urls = {c["url"] for c in db["cases"]}

    if _quality_filter_enabled():
        kept_cases, qf_summary = _run_quality_filter(
            new_cases, db["cases"], dry_run=dry_run,
        )
        log.info(
            f"Quality filter: accept={qf_summary['accept']}, "
            f"hold={qf_summary['hold']}, reject={qf_summary['reject']}, "
            f"llm_errors={qf_summary['llm_errors']}"
        )
    else:
        log.info("Quality filter disabled (QUALITY_FILTER_ENABLED)")
        kept_cases = list(new_cases)
        qf_summary = None

    added = 0
    skipped = 0

    for case in kept_cases:
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

        if dry_run:
            log.info(f"  [DRY] would add [{case['category']}] {case['company']} — {case['title']}")
        else:
            db["cases"].append(case)
            log.info(f"Added: [{case['category']}] {case['company']} — {case['title']}")
        existing_urls.add(url)
        added += 1

    if not dry_run:
        db["meta"]["last_updated"] = datetime.now(timezone.utc).isoformat()
        db["meta"]["total_cases"] = len(db["cases"])
        if added > 0:
            save_db(db)

    summary = {"added": added, "skipped": skipped, "total": len(db["cases"]),
               "quality_filter": qf_summary}
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
