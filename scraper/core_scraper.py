"""
core_scraper.py
Life After AI — Article fetcher
Reads sources.json, fetches new articles, returns list of raw article dicts.
"""

import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent
SOURCES_FILE = Path(__file__).parent / "sources.json"
DATA_FILE = ROOT / "data" / "cases.json"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; LifeAfterAI-Bot/1.0; research aggregator)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ko;q=0.8",
}
REQUEST_TIMEOUT = 15
DELAY = 2  # seconds between requests


def load_sources() -> list[dict]:
    with open(SOURCES_FILE) as f:
        data = json.load(f)
    return [s for s in data["sources"] if s.get("active", True)]


def load_existing_urls() -> set[str]:
    try:
        with open(DATA_FILE) as f:
            db = json.load(f)
        return {c["url"] for c in db.get("cases", [])}
    except FileNotFoundError:
        return set()


def load_all_keywords() -> list[str]:
    with open(SOURCES_FILE) as f:
        src = json.load(f)
    kws = []
    for lst in src.get("category_keywords", {}).values():
        kws.extend(lst)
    return list(set(kw.lower() for kw in kws))


def fetch_rss(url: str) -> list[dict]:
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        # RSS 2.0
        for item in root.iter("item"):
            title = item.findtext("title", "").strip()
            link  = item.findtext("link",  "").strip()
            desc  = item.findtext("description", "").strip()
            pub   = item.findtext("pubDate", "")
            if title and link:
                articles.append({
                    "title":     title,
                    "url":       link,
                    "summary":   BeautifulSoup(desc, "html.parser").get_text()[:600],
                    "published": pub,
                })

        # Atom
        atom_ns = "http://www.w3.org/2005/Atom"
        for entry in root.iter(f"{{{atom_ns}}}entry"):
            title   = entry.findtext(f"{{{atom_ns}}}title", "").strip()
            link_el = entry.find(f"{{{atom_ns}}}link")
            link    = link_el.get("href", "") if link_el is not None else ""
            summary = entry.findtext(f"{{{atom_ns}}}summary", "").strip()
            pub     = entry.findtext(f"{{{atom_ns}}}published", "")
            if title and link:
                articles.append({
                    "title":     title,
                    "url":       link,
                    "summary":   BeautifulSoup(summary, "html.parser").get_text()[:600],
                    "published": pub,
                })

    except Exception as e:
        log.warning(f"RSS fetch failed ({url}): {e}")
    return articles


def fetch_html_links(url: str, keywords: list[str]) -> list[dict]:
    articles = []
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        from urllib.parse import urlparse
        base = urlparse(url)

        for a in soup.find_all("a", href=True):
            title = a.get_text(strip=True)
            href  = a["href"]

            if href.startswith("/"):
                href = f"{base.scheme}://{base.netloc}{href}"
            if not href.startswith("http"):
                continue
            if len(title) < 10:
                continue

            title_lower = title.lower()
            if any(kw in title_lower for kw in keywords):
                articles.append({
                    "title":     title,
                    "url":       href,
                    "summary":   "",
                    "published": datetime.now(timezone.utc).isoformat(),
                })
    except Exception as e:
        log.warning(f"HTML scrape failed ({url}): {e}")
    return articles


def fetch_article_body(url: str) -> str:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        for tag in soup(["nav", "header", "footer", "aside", "script", "style", "noscript"]):
            tag.decompose()

        for selector in ["article", "main", ".article-body", ".post-content",
                         ".entry-content", ".content-body", "[role='main']"]:
            el = soup.select_one(selector)
            if el:
                return el.get_text(separator=" ", strip=True)[:4000]

        return soup.get_text(separator=" ", strip=True)[:4000]
    except Exception as e:
        log.warning(f"Body fetch failed ({url}): {e}")
        return ""


# Life After AI relevance terms
AI_TERMS = [
    "ai", "artificial intelligence", "machine learning", "generative ai",
    "gpt", "llm", "large language model", "chatbot", "autonomous",
    "smart home", "automation", "agentic", "companion robot",
    "digital health", "welltech", "voice assistant",
]


def is_relevant(title: str, body: str, keywords: list[str]) -> bool:
    combined = (title + " " + body).lower()
    has_ai  = any(term in combined for term in AI_TERMS)
    has_kw  = any(kw in combined for kw in keywords)
    return has_ai and has_kw


def scrape_all_sources() -> list[dict]:
    existing_urls = load_existing_urls()
    sources       = load_sources()
    all_keywords  = load_all_keywords()
    new_articles  = []

    for source in sources:
        log.info(f"Source: {source['name']}")
        src_keywords = [kw.lower() for kw in source.get("expected_tags", [])] or all_keywords
        raw = []

        if source.get("rss"):
            raw = fetch_rss(source["rss"])
        elif source.get("scrape_method") in ("html", "html_search"):
            raw = fetch_html_links(source["url"], src_keywords + all_keywords)

        time.sleep(DELAY)

        for article in raw:
            url = article["url"]
            if url in existing_urls:
                continue
            if not is_relevant(article["title"], article.get("summary", ""), all_keywords):
                continue

            log.info(f"  Fetching: {article['title'][:70]}")
            body = fetch_article_body(url)
            time.sleep(DELAY)

            if not is_relevant(article["title"], body, all_keywords):
                continue

            article["body_text"]      = body
            article["source_id"]      = source["id"]
            article["source_name"]    = source["name"]
            article["source_cats"]    = source.get("categories", [])
            article["fetched_at"]     = datetime.now(timezone.utc).isoformat()
            # RSS published 날짜를 LLM에 힌트로 전달
            raw_pub = article.get("published", "")
            if raw_pub:
                try:
                    from email.utils import parsedate_to_datetime
                    article["published_hint"] = parsedate_to_datetime(raw_pub).strftime("%Y-%m-%d")
                except Exception:
                    import re as _re
                    m = _re.search(r"(20\d\d-\d\d-\d\d)", raw_pub)
                    article["published_hint"] = m.group(1) if m else None
            else:
                article["published_hint"] = None
            new_articles.append(article)
            existing_urls.add(url)

    log.info(f"Scraping done. New articles: {len(new_articles)}")
    return new_articles


if __name__ == "__main__":
    articles = scrape_all_sources()
    print(json.dumps(articles[:2], indent=2, ensure_ascii=False))
