"""
add_article.py
Life After AI — Single URL article extractor
Usage: python scraper/add_article.py --url URL [--category-hint CAT]
"""

import argparse
import logging
import os
import sys
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("add_article.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LifeAfterAI-Bot/1.0)",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_page_title(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        og = soup.find("meta", {"property": "og:title"})
        if og and og.get("content"):
            return og["content"].strip()
        t = soup.find("title")
        return t.get_text(strip=True) if t else url
    except Exception as e:
        log.warning(f"Could not fetch title: {e}")
        return url


def main():
    parser = argparse.ArgumentParser(description="Add a single article to the Life After AI DB")
    parser.add_argument("--url", required=True, help="Article URL")
    parser.add_argument("--category-hint", default="",
                        help="Optional category hint (e.g. 1-1, 2-1)")
    args = parser.parse_args()

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    from core_scraper import fetch_article_body, load_existing_urls

    # Deduplicate check
    existing = load_existing_urls()
    if args.url in existing:
        log.info("이미 DB에 있는 URL입니다 — 건너뜁니다")
        sys.exit(0)

    log.info(f"URL: {args.url}")
    title  = get_page_title(args.url)
    body   = fetch_article_body(args.url)

    if not body:
        log.error("아티클 본문을 가져오지 못했습니다")
        sys.exit(1)

    domain = urlparse(args.url).netloc.replace("www.", "")
    article = {
        "title":       title,
        "url":         args.url,
        "body_text":   body,
        "source_name": domain,
        "source_cats": [args.category_hint] if args.category_hint else [],
        "summary":     "",
    }
    log.info(f"제목: {title[:80]}")

    from llm_summarizer import extract_case
    log.info("GitHub Models로 케이스 추출 중...")
    case = extract_case(article)

    if not case:
        log.warning("관련 케이스를 찾지 못했습니다 (Life After AI 카테고리와 무관한 아티클)")
        sys.exit(0)

    log.info(f"추출 완료: [{case['category']}] {case['company']} — {case['title']}")

    from updater import merge_new_cases
    summary = merge_new_cases([case])
    log.info(f"DB 업데이트: {summary}")


if __name__ == "__main__":
    main()
