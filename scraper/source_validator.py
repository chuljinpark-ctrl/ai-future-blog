"""
source_validator.py
LGE AX Benchmark — Source validator

For each candidate source dict (from source_discoverer.py), attempts to:
  1. Confirm the section_url is reachable (HTTP 200)
  2. Find a working RSS feed (tries candidate rss_url + common patterns)
  3. Count articles in the last 30 days (publishing frequency)
  4. Score keyword relevance against our category keywords
  5. Assign an overall quality score 0–100

Score breakdown
---------------
RSS confirmed        : +30 pts
Frequency ≥ 8/month  : +25 pts (linear scale from 0)
Keyword relevance    : up to +30 pts
Section URL reachable: +15 pts
                       -------
Max                  : 100 pts

Auto-approve threshold : ≥ 75
Flag for review       : 50–74
Reject                : < 50
"""

import json
import re
import time
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
from email.utils import parsedate_to_datetime
import xml.etree.ElementTree as ET

import requests

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
SOURCES_FILE = Path(__file__).parent / "sources.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LGE-AX-Benchmark/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
TIMEOUT = 12
DELAY   = 1.5  # seconds between requests


# ── RSS detection ──────────────────────────────────────────────────────────────

COMMON_RSS_SUFFIXES = [
    "/feed/", "/feed", "/rss/", "/rss", "/atom.xml",
    "/rss.xml", "/feed.xml", "/blog/feed/", "/news/feed/",
    "/feeds/news/", "/feeds/",
]


def find_rss_url(base_url: str, candidate_rss: Optional[str]) -> Optional[str]:
    """
    Try candidate_rss first, then common patterns derived from base_url.
    Returns the first working RSS URL, or None.
    """
    # Normalise base
    base = base_url.rstrip("/")
    if not base.startswith("http"):
        base = "https://" + base

    urls_to_try: list[str] = []
    if candidate_rss:
        urls_to_try.append(candidate_rss)
    for suffix in COMMON_RSS_SUFFIXES:
        urls_to_try.append(base + suffix)

    for url in urls_to_try:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
            ct = resp.headers.get("Content-Type", "")
            if resp.status_code == 200 and (
                "xml" in ct or "rss" in ct or "atom" in ct
                or resp.text.strip().startswith("<?xml")
                or "<rss" in resp.text[:500]
                or "<feed" in resp.text[:500]
            ):
                log.info(f"  RSS found: {url}")
                return url
        except Exception:
            pass
        time.sleep(0.3)

    return None


# ── RSS article count ──────────────────────────────────────────────────────────

def count_recent_articles(rss_url: str, days: int = 30) -> int:
    """Return number of articles published in the last `days` days."""
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    count  = 0
    try:
        resp = requests.get(rss_url, headers=HEADERS, timeout=TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        for item in root.iter("item"):
            pub_str = item.findtext("pubDate", "")
            try:
                pub = parsedate_to_datetime(pub_str)
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                if pub >= cutoff:
                    count += 1
            except Exception:
                count += 1  # count if unparseable (assume recent)

        atom_ns = "http://www.w3.org/2005/Atom"
        for entry in root.iter(f"{{{atom_ns}}}entry"):
            pub_str = entry.findtext(f"{{{atom_ns}}}published", "")
            try:
                pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                if pub >= cutoff:
                    count += 1
            except Exception:
                count += 1

    except Exception as e:
        log.warning(f"  Could not count articles from {rss_url}: {e}")

    return count


# ── Section URL reachability ───────────────────────────────────────────────────

def check_url_reachable(url: str) -> bool:
    try:
        resp = requests.head(url, headers=HEADERS, timeout=TIMEOUT,
                             allow_redirects=True)
        return resp.status_code < 400
    except Exception:
        return False


# ── Keyword relevance ──────────────────────────────────────────────────────────

def load_category_keywords() -> list[str]:
    with open(SOURCES_FILE) as f:
        d = json.load(f)
    kws = []
    for kw_list in d.get("category_keywords", {}).values():
        kws.extend(kw_list)
    return [k.lower() for k in kws]


def keyword_score(candidate: dict, all_keywords: list[str]) -> int:
    """Score 0–30 based on keyword overlap between candidate metadata and our keywords."""
    text = " ".join([
        candidate.get("name", ""),
        candidate.get("rationale", ""),
        " ".join(candidate.get("expected_tags", [])),
        candidate.get("section_url", ""),
    ]).lower()

    matches = sum(1 for kw in all_keywords if kw in text)
    # Scale: 10+ matches → 30 pts, proportional below
    return min(30, int((matches / 10) * 30))


# ── Main validation ────────────────────────────────────────────────────────────

def validate_candidate(candidate: dict, all_keywords: list[str]) -> dict:
    """
    Validate a single candidate and return an enriched dict with scores.
    """
    result = dict(candidate)  # copy
    result["validation"] = {}
    score = 0

    section_url = candidate.get("section_url", "")
    base_url    = "https://" + candidate.get("domain", "")
    candidate_rss = candidate.get("rss_url")

    log.info(f"Validating: {candidate.get('domain')} — {candidate.get('name')}")

    # 1. Section URL reachable (+15)
    reachable = check_url_reachable(section_url)
    result["validation"]["section_reachable"] = reachable
    if reachable:
        score += 15
        log.info("  Section URL: reachable ✓")
    else:
        log.info("  Section URL: unreachable ✗")
    time.sleep(DELAY)

    # 2. RSS feed (+30)
    rss_url = find_rss_url(base_url, candidate_rss)
    result["validation"]["rss_confirmed"] = rss_url is not None
    result["validation"]["rss_url_confirmed"] = rss_url
    if rss_url:
        score += 30
        # Update the candidate's rss_url if it was unknown
        if not candidate_rss:
            result["rss_url"] = rss_url
    time.sleep(DELAY)

    # 3. Publishing frequency (+25 max)
    articles_30d = 0
    if rss_url:
        articles_30d = count_recent_articles(rss_url)
        freq_score   = min(25, int((articles_30d / 8) * 25))  # 8/month = full score
        score += freq_score
        log.info(f"  Articles last 30d: {articles_30d} → +{freq_score}pts")
    result["validation"]["articles_last_30d"] = articles_30d
    time.sleep(DELAY)

    # 4. Keyword relevance (+30 max)
    kw_pts = keyword_score(candidate, all_keywords)
    score += kw_pts
    log.info(f"  Keyword score: {kw_pts}")

    result["validation"]["score"] = score

    # Disposition
    if score >= 75:
        result["status"] = "approved"
    elif score >= 50:
        result["status"] = "review"
    else:
        result["status"] = "rejected"

    log.info(f"  Total score: {score}/100 → {result['status']}")
    return result


def validate_all(candidates: list[dict]) -> list[dict]:
    """Validate a list of candidates. Returns enriched list sorted by score."""
    all_keywords = load_category_keywords()
    validated = []
    for c in candidates:
        v = validate_candidate(c, all_keywords)
        validated.append(v)
        time.sleep(DELAY)

    validated.sort(key=lambda x: x["validation"].get("score", 0), reverse=True)
    return validated


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    # Quick smoke test
    test = {
        "domain": "www.retaildive.com",
        "name": "Retail Dive — AI",
        "section_url": "https://www.retaildive.com/topic/artificial-intelligence/",
        "rss_url": "https://www.retaildive.com/feeds/news/",
        "rationale": "Covers retail AI with metrics",
        "expected_tags": ["retail", "e-commerce", "inventory"],
        "priority": "high",
    }
    kws = load_category_keywords()
    result = validate_candidate(test, kws)
    print(json.dumps(result, indent=2, ensure_ascii=False))
