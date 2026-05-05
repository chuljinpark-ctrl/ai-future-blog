"""
core_scraper.py
LGE AX Benchmark — Article fetcher
Reads sources.json, fetches new articles, returns list of raw article dicts
"""

import json
import time
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
SOURCES_FILE = Path(__file__).parent / "sources.json"
DATA_FILE = ROOT / "data" / "cases.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LGE-AX-Benchmark/1.0)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
}
REQUEST_TIMEOUT = 15
DELAY_BETWEEN_REQUESTS = 2  # seconds


def load_sources() -> list[dict]:
    with open(SOURCES_FILE) as f:
        data = json.load(f)
    return [s for s in data["sources"] if s.get("active", True)]


def load_existing_urls() -> set[str]:
    """Return set of URLs already in cases.json to avoid duplicates."""
    try:
        with open(DATA_FILE) as f:
            db = json.load(f)
        return {c["url"] for c in db.get("cases", [])}
    except FileNotFoundError:
        return set()


def fetch_rss(url: str) -> list[dict]:
    """Fetch and parse an RSS/Atom feed. Returns list of {title, url, summary, published}."""
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        # RSS 2.0
        ns = {}
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link = item.findtext("link", "").strip()
            desc = item.findtext("description", "").strip()
            pub = item.findtext("pubDate", "")
            if title and link:
                articles.append({
                    "title": title,
                    "url": link,
                    "summary": BeautifulSoup(desc, "html.parser").get_text()[:500],
                    "published": pub,
                })

        # Atom
        atom_ns = "http://www.w3.org/2005/Atom"
        for entry in root.iter(f"{{{atom_ns}}}entry"):
            title = entry.findtext(f"{{{atom_ns}}}title", "").strip()
            link_el = entry.find(f"{{{atom_ns}}}link")
            link = link_el.get("href", "") if link_el is not None else ""
            summary = entry.findtext(f"{{{atom_ns}}}summary", "").strip()
            pub = entry.findtext(f"{{{atom_ns}}}published", "")
            if title and link:
                articles.append({
                    "title": title,
                    "url": link,
                    "summary": BeautifulSoup(summary, "html.parser").get_text()[:500],
                    "published": pub,
                })

    except Exception as e:
        log.warning(f"RSS fetch failed for {url}: {e}")
    return articles


def fetch_html_links(url: str, keywords: list[str]) -> list[dict]:
    """
    Scrape an HTML page and extract article links containing relevant keywords.
    Returns list of {title, url, summary}.
    """
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            href = a["href"]

            # Normalise relative URLs
            if href.startswith("/"):
                from urllib.parse import urlparse
                base = urlparse(url)
                href = f"{base.scheme}://{base.netloc}{href}"

            if not href.startswith("http"):
                continue

            # Only include links whose title mentions a keyword
            title_lower = title.lower()
            if any(kw.lower() in title_lower for kw in keywords):
                articles.append({
                    "title": title,
                    "url": href,
                    "summary": "",
                    "published": datetime.now(timezone.utc).isoformat(),
                })

    except Exception as e:
        log.warning(f"HTML scrape failed for {url}: {e}")
    return articles


def fetch_article_body(url: str) -> str:
    """Fetch the main text body of an article page (first ~3000 chars)."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Remove nav, header, footer, ads
        for tag in soup(["nav", "header", "footer", "aside", "script", "style"]):
            tag.decompose()

        # Try common article containers
        for selector in ["article", "main", ".article-body", ".post-content", ".entry-content"]:
            el = soup.select_one(selector)
            if el:
                return el.get_text(separator=" ", strip=True)[:3000]

        return soup.get_text(separator=" ", strip=True)[:3000]
    except Exception as e:
        log.warning(f"Body fetch failed for {url}: {e}")
        return ""


def is_relevant(title: str, body: str, keywords: list[str]) -> bool:
    """Check if an article is relevant to our benchmark categories."""
    ai_terms = ["ai", "artificial intelligence", "machine learning", "generative", "gpt", "llm", "copilot", "automation"]
    combined = (title + " " + body).lower()
    has_ai = any(term in combined for term in ai_terms)
    has_keyword = any(kw.lower() in combined for kw in keywords)
    return has_ai and has_keyword


def scrape_all_sources() -> list[dict]:
    """
    Main entry point. Scrapes all active sources and returns
    a list of new (not-yet-in-DB) articles with body text.
    """
    existing_urls = load_existing_urls()
    sources = load_sources()

    # Collect all keywords across categories
    with open(SOURCES_FILE) as f:
        src_data = json.load(f)
    all_keywords = []
    for kws in src_data.get("category_keywords", {}).values():
        all_keywords.extend(kws)

    new_articles = []

    for source in sources:
        log.info(f"Processing source: {source['name']}")
        raw_articles = []

        if source.get("rss"):
            raw_articles = fetch_rss(source["rss"])
        elif source.get("scrape_method") == "html":
            raw_articles = fetch_html_links(source["url"], all_keywords)

        time.sleep(DELAY_BETWEEN_REQUESTS)

        for article in raw_articles:
            url = article["url"]
            if url in existing_urls:
                continue

            if not is_relevant(article["title"], article.get("summary", ""), all_keywords):
                continue

            # Fetch full body
            log.info(f"  Fetching body: {article['title'][:60]}")
            body = fetch_article_body(url)
            time.sleep(DELAY_BETWEEN_REQUESTS)

            if not is_relevant(article["title"], body, all_keywords):
                continue

            article["body_text"] = body
            article["source_id"] = source["id"]
            article["source_name"] = source["name"]
            article["fetched_at"] = datetime.now(timezone.utc).isoformat()
            new_articles.append(article)
            existing_urls.add(url)  # prevent double-adding same session

    log.info(f"Scraping complete. New relevant articles: {len(new_articles)}")
    return new_articles


if __name__ == "__main__":
    articles = scrape_all_sources()
    print(json.dumps(articles[:2], indent=2, ensure_ascii=False))
