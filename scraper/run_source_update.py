"""
run_source_update.py
LGE AX Benchmark — Monthly source update pipeline

Workflow
--------
1. Analyze coverage gaps (source_analyzer)
2. Discover candidate sources via Claude + web_search (source_discoverer)
3. Validate each candidate: RSS, frequency, keyword score (source_validator)
4. Write results to data/source_candidates.json
5. Optionally auto-approve high-score candidates into sources.json

Usage
-----
  python scraper/run_source_update.py                     # full run
  python scraper/run_source_update.py --analyze-only      # gap report only
  python scraper/run_source_update.py --no-auto-approve   # generate candidates only
  python scraper/run_source_update.py --max-gaps 5        # limit discovery
"""

import sys
import json
import logging
import argparse
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("source_update.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

ROOT        = Path(__file__).parent.parent
SOURCES_FILE     = Path(__file__).parent / "sources.json"
CANDIDATES_FILE  = ROOT / "data" / "source_candidates.json"

AUTO_APPROVE_THRESHOLD = 75   # score >= this → auto-add to sources.json
REVIEW_THRESHOLD       = 50   # score >= this → flag for human review


# ── Helper ────────────────────────────────────────────────────────────────────

def build_source_entry(candidate: dict) -> dict:
    """Convert a validated candidate into a sources.json entry."""
    section_url = candidate.get("section_url", "https://" + candidate["domain"])
    return {
        "id":           _make_id(candidate["domain"]),
        "name":         candidate.get("name", candidate["domain"]),
        "url":          section_url,
        "base_url":     "https://" + candidate["domain"],
        "section_url":  section_url,
        "rss":          candidate["validation"].get("rss_url_confirmed"),
        "scrape_method": "rss" if candidate["validation"].get("rss_confirmed") else "html",
        "priority":     candidate.get("priority", "mid"),
        "active":       True,
        "expected_tags": candidate.get("expected_tags", []),
        "added_by":     "auto",
        "added_date":   datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "validation_score": candidate["validation"].get("score", 0),
    }


def _make_id(domain: str) -> str:
    """Turn e.g. 'www.retaildive.com' → 'retaildive'."""
    clean = domain.replace("www.", "").split(".")[0]
    return clean.lower()


def load_sources() -> dict:
    with open(SOURCES_FILE) as f:
        return json.load(f)


def save_sources(d: dict) -> None:
    with open(SOURCES_FILE, "w", encoding="utf-8") as f:
        json.dump(d, f, ensure_ascii=False, indent=2)


def auto_approve(validated: list[dict]) -> dict:
    """
    Add approved candidates to sources.json.
    Returns summary {added, skipped}.
    """
    sources_data = load_sources()
    existing_ids = {s["id"] for s in sources_data["sources"]}
    added = 0

    for c in validated:
        if c.get("status") != "approved":
            continue
        entry = build_source_entry(c)
        if entry["id"] in existing_ids:
            log.info(f"  Skip (duplicate id): {entry['id']}")
            continue
        sources_data["sources"].append(entry)
        existing_ids.add(entry["id"])
        added += 1
        log.info(f"  Auto-approved: {entry['id']} (score={entry['validation_score']})")

    if added:
        sources_data["meta"]["last_updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S+00:00")
        save_sources(sources_data)

    return {"added": added, "skipped": len(validated) - added}


# ── Main ──────────────────────────────────────────────────────────────────────

def apply_reviewed() -> None:
    """Apply manually-approved candidates from source_candidates.json to sources.json."""
    if not CANDIDATES_FILE.exists():
        log.error(f"No candidates file at {CANDIDATES_FILE}. Run full discovery first.")
        return
    data = json.loads(CANDIDATES_FILE.read_text(encoding="utf-8"))
    candidates = data.get("candidates", [])
    to_apply = [c for c in candidates if c.get("status") == "approved"]
    if not to_apply:
        log.info("No approved candidates found in source_candidates.json.")
        return
    log.info(f"Applying {len(to_apply)} approved candidates from source_candidates.json...")
    summary = auto_approve(to_apply)
    log.info(f"  → Added {summary['added']} sources to sources.json")


def main(analyze_only: bool = False,
         no_auto_approve: bool = False,
         max_gaps: int = 10) -> None:

    log.info("=" * 60)
    log.info(f"LGE AX Source Update — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    log.info("=" * 60)

    # ── Step 1: Gap analysis ──────────────────────────────────────────────────
    log.info("\n[Step 1] Analyzing coverage gaps...")
    from source_analyzer import analyze_gaps
    gaps = analyze_gaps()

    full_gaps = [g for g in gaps if g["source_count"] == 0 and g["case_count"] >= 2]
    log.info(f"  → {len(gaps)} total tag gaps found")
    log.info(f"  → {len(full_gaps)} significant full gaps (0 sources, ≥2 cases)")
    for g in full_gaps[:8]:
        log.info(f"     [{g['case_count']:2}x] {g['tag']}")

    if analyze_only:
        log.info("\nAnalyze-only mode — stopping here.")
        return

    if not full_gaps:
        log.info("\nNo significant gaps found — no discovery needed.")
        # Write empty candidates file to mark run
        CANDIDATES_FILE.write_text(json.dumps({
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "gaps_analyzed": len(gaps),
            "candidates": [],
            "summary": "No significant gaps found."
        }, indent=2, ensure_ascii=False))
        return

    # ── Step 2: Source discovery ──────────────────────────────────────────────
    log.info(f"\n[Step 2] Discovering sources for top {min(max_gaps, len(full_gaps))} gaps...")
    from source_discoverer import discover_all
    raw_candidates = discover_all(full_gaps, max_gaps=max_gaps)
    log.info(f"  → {len(raw_candidates)} raw candidates found")

    if not raw_candidates:
        log.info("No candidates discovered.")
        return

    # ── Step 3: Validation ────────────────────────────────────────────────────
    log.info(f"\n[Step 3] Validating {len(raw_candidates)} candidates...")
    from source_validator import validate_all
    validated = validate_all(raw_candidates)

    approved = [c for c in validated if c.get("status") == "approved"]
    review   = [c for c in validated if c.get("status") == "review"]
    rejected = [c for c in validated if c.get("status") == "rejected"]

    log.info(f"\n  Validation results:")
    log.info(f"    ✅ Approved  (≥{AUTO_APPROVE_THRESHOLD}): {len(approved)}")
    log.info(f"    👀 Review    ({REVIEW_THRESHOLD}–{AUTO_APPROVE_THRESHOLD-1}): {len(review)}")
    log.info(f"    ❌ Rejected  (<{REVIEW_THRESHOLD}): {len(rejected)}")

    for c in approved + review:
        score = c["validation"].get("score", 0)
        rss   = "RSS✓" if c["validation"].get("rss_confirmed") else "HTML"
        freq  = c["validation"].get("articles_last_30d", 0)
        log.info(f"    [{c['status']:8}] {c['domain']:35} score={score:3} {rss} freq={freq}/mo")

    # ── Step 4: Write candidates file ─────────────────────────────────────────
    log.info(f"\n[Step 4] Writing candidates to {CANDIDATES_FILE.name}...")
    output = {
        "generated_at":     datetime.now(timezone.utc).isoformat(),
        "gaps_analyzed":    len(full_gaps),
        "summary": {
            "total":    len(validated),
            "approved": len(approved),
            "review":   len(review),
            "rejected": len(rejected),
        },
        "candidates": validated,
        "review_instructions": (
            "Candidates with status='approved' will be auto-added if --no-auto-approve "
            "is not set. Review 'review' candidates manually and change status to "
            "'approved' then re-run with --apply-reviewed, or add them to sources.json "
            "directly."
        ),
    }
    CANDIDATES_FILE.write_text(json.dumps(output, indent=2, ensure_ascii=False))
    log.info(f"  → Saved to {CANDIDATES_FILE}")

    # ── Step 5: Auto-approve ──────────────────────────────────────────────────
    if not no_auto_approve and approved:
        log.info(f"\n[Step 5] Auto-approving {len(approved)} high-score candidates...")
        summary = auto_approve(validated)
        log.info(f"  → Added {summary['added']} sources to sources.json")
    elif no_auto_approve:
        log.info("\n[Step 5] Skipped (--no-auto-approve). Review candidates manually.")
    else:
        log.info("\n[Step 5] No auto-approved candidates.")

    log.info("\n✅ Source update complete.")


if __name__ == "__main__":
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    parser = argparse.ArgumentParser(description="LGE AX monthly source updater")
    parser.add_argument("--analyze-only",    action="store_true",
                        help="Only run gap analysis, skip discovery")
    parser.add_argument("--no-auto-approve", action="store_true",
                        help="Generate candidates but don't write to sources.json")
    parser.add_argument("--max-gaps",        type=int, default=10,
                        help="Max number of gaps to run discovery for (default: 10)")
    parser.add_argument("--apply-reviewed",  action="store_true",
                        help="Apply manually-approved candidates from source_candidates.json")
    args = parser.parse_args()

    if args.apply_reviewed:
        apply_reviewed()
    else:
        main(
            analyze_only    = args.analyze_only,
            no_auto_approve = args.no_auto_approve,
            max_gaps        = args.max_gaps,
        )
