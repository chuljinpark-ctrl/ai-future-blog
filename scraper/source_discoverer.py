"""
source_discoverer.py
LGE AX Benchmark — Source discoverer

Uses GitHub Models (gpt-4o-mini) to suggest candidate sources for each gap.
No external web_search tool needed — the model uses its training knowledge
of publishing platforms, then source_validator.py confirms they're still active.

GITHUB_TOKEN is automatically available in GitHub Actions (no extra secret).
"""

import json
import os
import re
import time
import logging
from pathlib import Path
from typing import Optional

from openai import OpenAI

log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
SOURCES_FILE = Path(__file__).parent / "sources.json"

GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"
MODEL = "gpt-4o-mini"

DISCOVERY_PROMPT = """\
You are a research analyst for LG Electronics' AI Transformation strategy team.
We maintain a database of global AI sales & marketing case studies.

COVERAGE GAP
Topic tag: {tag}
LGE strategy categories affected: {categories}
Existing cases with this tag: {example_cases}

ALREADY TRACKED SOURCES (do NOT suggest these):
{existing_domains}

TASK
Suggest 2–3 specific websites that:
1. Regularly publish NEW AI case studies in sales/marketing/CX (at least monthly)
2. Include SPECIFIC outcome metrics — percentages, dollar amounts, time savings
3. Are NOT in our existing source list above
4. Are publicly accessible (not paywalled)

Respond ONLY with this JSON (no markdown, no explanation):
{{
  "candidates": [
    {{
      "domain": "example.com",
      "name": "Publication Name — Section",
      "section_url": "https://example.com/ai-section/",
      "rss_url": "https://example.com/feed/ or null",
      "rationale": "One sentence explaining why this source has quantified AI sales/marketing cases",
      "expected_tags": ["tag1", "tag2"],
      "priority": "high or mid"
    }}
  ]
}}

Rules:
- section_url must be the SECTION page, not the homepage
- rss_url: provide if you know it, else null (validator will auto-detect)
- Only suggest sources you are confident exist and publish regularly
- Avoid: academic journals, vendor whitepapers, paywalled reports
"""


def load_existing_domains() -> set[str]:
    with open(SOURCES_FILE) as f:
        d = json.load(f)
    domains: set[str] = set()
    for s in d["sources"]:
        url = s.get("section_url", s.get("base_url", ""))
        if "://" in url:
            domains.add(url.split("://", 1)[1].split("/")[0])
    for exc in d.get("excluded_sources", {}).get("domains", []):
        domains.add(exc.get("domain", ""))
    return domains


def _get_client() -> OpenAI:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    return OpenAI(base_url=GITHUB_MODELS_ENDPOINT, api_key=token)


def discover_sources_for_gap(gap: dict, existing_domains: set[str]) -> list[dict]:
    """Call GitHub Models to suggest candidate sources for one gap topic."""
    cat_names = {
        "1-1": "customer acquisition", "1-2": "sales conversion",
        "1-3": "upsell / average order value", "1-4": "retention / churn / LTV",
        "1-5": "new revenue model", "2-1": "marketing cost reduction",
        "2-2": "sales productivity", "2-3": "customer service automation",
        "2-4": "demand forecasting / operations", "2-5": "brand risk / VOC",
    }
    cats = ", ".join(
        cat_names.get(c, c)
        for c in sorted(set(gap["category_ids"]))
    )

    prompt = DISCOVERY_PROMPT.format(
        tag=gap["tag"],
        categories=cats,
        example_cases=", ".join(gap.get("case_ids", [])[:3]) or "none yet",
        existing_domains="\n".join(sorted(existing_domains)[:25]),
    )

    log.info(f"Discovering sources for gap: {gap['tag']}")
    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.3,
        )
        raw = response.choices[0].message.content.strip()
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        parsed = json.loads(raw)
        candidates = parsed.get("candidates", [])

        for c in candidates:
            c["gap_tag"]          = gap["tag"]
            c["gap_severity"]     = gap["severity"]
            c["gap_category_ids"] = gap["category_ids"]

        log.info(f"  → {len(candidates)} candidates")
        return candidates

    except json.JSONDecodeError as e:
        log.warning(f"  JSON parse error for '{gap['tag']}': {e}")
        return []
    except Exception as e:
        log.error(f"  API error: {e}")
        return []


def discover_all(gaps: list[dict], max_gaps: int = 10,
                 delay_seconds: float = 1.0) -> list[dict]:
    """Run discovery for top N priority gaps. Returns deduplicated candidates."""
    existing_domains = load_existing_domains()

    priority_gaps = [
        g for g in gaps
        if g["source_count"] == 0 and g["case_count"] >= 2
    ][:max_gaps]

    if not priority_gaps:
        log.info("No significant gaps — skipping discovery.")
        return []

    log.info(f"Discovering for {len(priority_gaps)} gaps: "
             f"{[g['tag'] for g in priority_gaps]}")

    all_candidates: list[dict] = []
    seen_domains = set(existing_domains)

    for gap in priority_gaps:
        candidates = discover_sources_for_gap(gap, seen_domains)
        for c in candidates:
            domain = c.get("domain", "")
            if domain and domain not in seen_domains:
                all_candidates.append(c)
                seen_domains.add(domain)
        time.sleep(delay_seconds)

    log.info(f"Discovery done. Unique candidates: {len(all_candidates)}")
    return all_candidates


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    from source_analyzer import analyze_gaps
    gaps = analyze_gaps()
    candidates = discover_all(gaps, max_gaps=3)
    print(json.dumps(candidates, indent=2, ensure_ascii=False))
