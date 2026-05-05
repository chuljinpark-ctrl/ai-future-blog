"""
run_pipeline.py
LGE AX Benchmark — Daily batch pipeline entry point
Usage: python scraper/run_pipeline.py [--dry-run]
"""

import sys
import json
import logging
import argparse
from datetime import datetime

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("pipeline.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


def main(dry_run: bool = False):
    log.info("=" * 60)
    log.info(f"LGE AX Benchmark Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M KST')}")
    log.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    log.info("=" * 60)

    # Step 1: Scrape sources
    log.info("\n[Step 1] Scraping sources...")
    from core_scraper import scrape_all_sources
    articles = scrape_all_sources()
    log.info(f"  → {len(articles)} new articles fetched")

    if not articles:
        log.info("No new articles. Pipeline complete.")
        return

    # Step 2: Extract cases via LLM
    log.info(f"\n[Step 2] Extracting cases from {len(articles)} articles...")
    from llm_summarizer import extract_cases_from_articles
    new_cases = extract_cases_from_articles(articles)
    log.info(f"  → {len(new_cases)} cases extracted")

    if not new_cases:
        log.info("No new cases extracted. Pipeline complete.")
        return

    # Step 3: Update DB
    if dry_run:
        log.info(f"\n[Step 3] DRY RUN — would add {len(new_cases)} cases:")
        for c in new_cases:
            log.info(f"  [{c['category']}] {c['company']}: {c['title']}")
    else:
        log.info(f"\n[Step 3] Updating cases.json...")
        from updater import merge_new_cases
        summary = merge_new_cases(new_cases)
        log.info(f"  → Added: {summary['added']}, Skipped: {summary['skipped']}, Total: {summary['total']}")

    log.info("\nPipeline complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="LGE AX Benchmark daily pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and extract but don't write to DB")
    args = parser.parse_args()

    # Change to scraper directory for relative imports
    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    main(dry_run=args.dry_run)
