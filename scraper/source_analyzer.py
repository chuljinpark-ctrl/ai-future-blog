"""
source_analyzer.py
LGE AX Benchmark — Gap analyzer

Compares tags in cases.json against expected_tags in sources.json.
Returns a ranked list of underrepresented topics to guide source discovery.
"""

import json
import logging
from pathlib import Path
from collections import Counter

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
CASES_FILE  = ROOT / "data" / "cases.json"
SOURCES_FILE = Path(__file__).parent / "sources.json"


def load_cases() -> list[dict]:
    with open(CASES_FILE) as f:
        return json.load(f)["cases"]


def load_sources() -> list[dict]:
    with open(SOURCES_FILE) as f:
        return json.load(f)["sources"]


def tags_covered_by_sources(sources: list[dict]) -> dict[str, list[str]]:
    """
    Returns {tag: [source_id, ...]} mapping for all tags declared
    in any source's expected_tags list.
    """
    coverage: dict[str, list[str]] = {}
    for s in sources:
        for tag in (s.get("expected_tags") or s.get("tags", [])):
            coverage.setdefault(tag, []).append(s["id"])
    return coverage


def analyze_gaps() -> list[dict]:
    """
    Main entry point.

    Returns a list of gap dicts, ordered by severity (highest first):
        {
          "tag":          str,          # e.g. "e-commerce"
          "case_count":   int,          # how many cases use this tag
          "source_count": int,          # how many sources cover it (0 = full gap)
          "case_ids":     list[str],    # which cases have this tag
          "category_ids": list[str],    # which LGE categories are affected
          "severity":     float,        # case_count / max(1, source_count)
          "search_query": str,          # suggested web-search query
        }
    """
    cases   = load_cases()
    sources = load_sources()
    coverage = tags_covered_by_sources(sources)

    # Count tag usage across all cases
    tag_counter: Counter = Counter()
    tag_to_cases: dict[str, list[str]] = {}
    tag_to_cats:  dict[str, list[str]] = {}

    for c in cases:
        for tag in c.get("tags", []):
            tag_counter[tag] += 1
            tag_to_cases.setdefault(tag, []).append(c["id"])
            tag_to_cats.setdefault(tag, []).append(c["category"])

    # Build gap list
    gaps = []
    for tag, count in tag_counter.items():
        src_count = len(coverage.get(tag, []))
        severity  = count / max(1, src_count)   # higher = bigger gap
        gaps.append({
            "tag":          tag,
            "case_count":   count,
            "source_count": src_count,
            "case_ids":     list(dict.fromkeys(tag_to_cases[tag])),   # deduplicated
            "category_ids": list(dict.fromkeys(tag_to_cats[tag])),
            "severity":     round(severity, 2),
            "search_query": _make_search_query(tag, tag_to_cats[tag]),
        })

    # Sort: full gaps first (source_count==0), then by severity
    gaps.sort(key=lambda g: (-int(g["source_count"] == 0), -g["severity"]))
    return gaps


def _make_search_query(tag: str, categories: list[str]) -> str:
    """Build a targeted web-search query for finding sources on this topic."""
    cat_names = {
        "1-1": "customer acquisition",
        "1-2": "sales conversion",
        "1-3": "upsell average order value",
        "1-4": "customer retention churn LTV",
        "1-5": "new revenue model",
        "2-1": "marketing cost reduction",
        "2-2": "sales productivity",
        "2-3": "customer service automation",
        "2-4": "demand forecasting operations",
        "2-5": "brand risk VOC",
    }
    primary_cat = max(set(categories), key=categories.count)
    ctx = cat_names.get(primary_cat, "AI business case study")
    readable_tag = tag.replace("_", " ")
    return f"AI {readable_tag} {ctx} case study results 2024 2025 site metrics"


def print_gap_report(n: int = 15) -> None:
    gaps = analyze_gaps()
    full_gaps  = [g for g in gaps if g["source_count"] == 0]
    part_gaps  = [g for g in gaps if g["source_count"] > 0]

    print(f"\n{'='*60}")
    print("SOURCE GAP ANALYSIS")
    print(f"{'='*60}")
    print(f"\n● Full gaps (0 sources): {len(full_gaps)} topics")
    for g in full_gaps[:n]:
        cats = ", ".join(sorted(set(g["category_ids"])))
        print(f"  [{g['case_count']:2}x cases] {g['tag']:30}  cats: {cats}")

    print(f"\n● Partial gaps (1-2 sources): {len(part_gaps)} topics")
    for g in part_gaps[:n]:
        if g["source_count"] <= 2:
            cats = ", ".join(sorted(set(g["category_ids"])))
            print(f"  [{g['case_count']:2}x cases, {g['source_count']}src] {g['tag']:26}  cats: {cats}")
    print()


if __name__ == "__main__":
    print_gap_report()
