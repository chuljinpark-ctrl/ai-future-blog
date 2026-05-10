"""
run_pipeline.py
Life After AI — Daily batch pipeline entry point
Usage: python scraper/run_pipeline.py [--dry-run]
"""

import sys
import json
import logging
import argparse
from datetime import datetime
from pathlib import Path

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
    log.info(f"Life After AI Pipeline — {datetime.now().strftime('%Y-%m-%d %H:%M UTC')}")
    log.info(f"Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    log.info("=" * 60)

    # Step 1: Scrape sources
    log.info("\n[Step 1] Scraping sources...")
    from core_scraper import scrape_all_sources
    articles = scrape_all_sources()
    log.info(f"  → {len(articles)} new articles fetched")

    if not articles:
        log.info("No new articles found. Pipeline complete.")
        return

    # Step 2: LLM extraction
    log.info(f"\n[Step 2] Extracting cases from {len(articles)} articles via GitHub Models...")
    from llm_summarizer import extract_cases_from_articles
    new_cases = extract_cases_from_articles(articles)
    log.info(f"  → {len(new_cases)} cases extracted")

    if not new_cases:
        log.info("No relevant cases extracted. Pipeline complete.")
        return

    # Step 3: Merge into DB
    if dry_run:
        log.info(f"\n[Step 3] DRY RUN — would add {len(new_cases)} cases:")
        for c in new_cases:
            log.info(f"  [{c['category']}] {c['company']}: {c['title']}")
    else:
        log.info(f"\n[Step 3] Updating cases.json...")
        from updater import merge_new_cases
        summary = merge_new_cases(new_cases)
        log.info(f"  → Added: {summary['added']}, Skipped: {summary['skipped']}, "
                 f"Total: {summary['total']}")

    log.info("\nPipeline complete.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Life After AI daily pipeline")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and extract but don't write to DB")
    args = parser.parse_args()

    import os
    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    main(dry_run=args.dry_run)
