"""
llm_summarizer.py
Life After AI — LLM-based article extractor
Uses GitHub Models API (OpenAI-compatible). GITHUB_TOKEN auto-injected by Actions.
"""

import hashlib
import json
import os
import logging
import re
from datetime import date
from typing import Optional
from pathlib import Path

from openai import OpenAI

log = logging.getLogger(__name__)

ROOT        = Path(__file__).parent.parent
SOURCES_FILE = Path(__file__).parent / "sources.json"

GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"
MODEL = "gpt-4o-mini"

# ── Category taxonomy ──────────────────────────────────────────────────────────
CATEGORIES = {
    "1-1": "AI Home — 집이 스스로 운영되는 공간 (스마트홈 AI, 홈 자동화, Gemini for Home, Alexa+, Matter)",
    "1-2": "Wellness Home — 집이 건강·회복·예방 공간 (수면, 공기질, 시니어 모니터링, ambient assisted living)",
    "1-3": "Energy Optimization — 에너지 자동 최적화 (HEMS, 전기요금, 태양광, EV충전, home battery)",
    "2-1": "Agentic Commerce — AI가 탐색·비교·구매를 대행 (agentic AI, zero-click, autonomous purchase, GEO)",
    "2-2": "AI Shopping — 대화형·개인화 쇼핑 (AI stylist, conversational commerce, guided shopping, AI sales assistant)",
    "2-3": "Subscription AI — AI 기반 구독·사용 관리 (subscription economy, usage-based, predictive maintenance, consumable)",
    "3-1": "AI Assistant — 개인·가족 생활 AI 비서 (personal AI agent, Gemini, ChatGPT for daily life, family AI)",
    "3-2": "Productivity Life — AI와 업무·생산성 변화 (AI at work, Work Trend Index, hybrid work, frontier firms)",
    "3-3": "Capability Divide — AI 활용 역량 격차 (digital divide, AI literacy, senior onboarding, grey digital divide)",
    "4-1": "Emotional AI — AI와 정서 대화·외로움 (loneliness, mental health chatbot, emotional support AI)",
    "4-2": "Companion — AI 동반자 디바이스·서비스 (companion robot, social robot, AI pet, senior companion)",
    "4-3": "Aging Society — 시니어·고령화 AI 돌봄 (elder care, home-based care, fall detection, medication reminder)",
}

VALID_CATEGORIES = set(CATEGORIES.keys())

# ── Extraction prompt ──────────────────────────────────────────────────────────
EXTRACTION_PROMPT = """당신은 'Life After AI' 리서치 블로그의 아티클 분석가입니다.
이 블로그는 AI가 고객의 집·소비·개인 생활·인간 관계를 어떻게 바꾸는지 추적합니다.

## 12개 분석 카테고리:
{categories}

## 분석할 아티클:
제목: {title}
출처: {source_name}
URL: {url}
힌트 카테고리: {hint_cats}
본문:
{body}

## 지시사항:
1. 위 12개 카테고리 중 가장 적합한 하나에 해당하면 JSON으로 추출하세요.
2. company = 아티클의 핵심 기업·기관명 (연구기관·미디어·스타트업·대기업 모두 가능)
3. short = 2~4자 영문 약어 (예: GOO, AMA, MCK, DEL)
4. kpi_value = 가장 핵심적인 수치 또는 키워드 (수치 없으면 "N/A")
5. metrics = 기사에서 언급된 실제 수치·사실 1~4개 (없으면 1개, 최대 4개)
6. trend: "pos"(긍정·성장), "neg"(부정·감소·위험), "neu"(중립·정보)
7. 모든 텍스트 필드(title, description, body)는 반드시 한국어로 작성
8. 위 12개 카테고리와 무관한 아티클은 has_case: false 반환

JSON 형식 (마크다운 코드블록 없이 순수 JSON만):
{{
  "has_case": true,
  "company": "기업/기관명 (영문 또는 한글)",
  "short": "약어",
  "category": "1-1 ~ 4-3 중 하나",
  "kpi_value": "핵심 수치 또는 키워드",
  "kpi_label": "수치 설명 (10자 이내)",
  "title": "아티클 제목 (한국어, 30자 이내)",
  "description": "한 줄 설명 (한국어, 60자 이내, 사례의 핵심 의미)",
  "body": "상세 요약 (한국어, 150~200자, 배경·내용·시사점)",
  "metrics": [
    {{"value": "수치 또는 사실", "label": "설명", "trend": "pos|neg|neu"}}
  ],
  "tags": ["태그1", "태그2"],
  "source": "출처명, 연도",
  "url": "{url}"
}}

무관하면: {{"has_case": false}}
JSON 외 텍스트 절대 포함 금지.
"""


# ── Color palette for company badges ──────────────────────────────────────────
COLORS = [
    ("#eaf5f3", "#3a8f7d"),  # teal
    ("#fdf3e7", "#b5711b"),  # amber
    ("#eaf7ec", "#2e7d4f"),  # green
    ("#fdf0eb", "#a9583e"),  # coral
    ("#e8f0fb", "#2a5fc8"),  # blue
    ("#f3e8fb", "#7b3ab5"),  # purple
]


def get_color(company: str) -> tuple[str, str]:
    idx = hash(company.lower()) % len(COLORS)
    return COLORS[idx]


def _client() -> OpenAI:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set")
    return OpenAI(base_url=GITHUB_MODELS_ENDPOINT, api_key=token)


def extract_case(article: dict) -> Optional[dict]:
    categories_text = "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items())
    hint_cats = ", ".join(article.get("source_cats", [])) or "없음"

    prompt = EXTRACTION_PROMPT.format(
        categories=categories_text,
        title=article.get("title", ""),
        source_name=article.get("source_name", ""),
        url=article.get("url", ""),
        hint_cats=hint_cats,
        body=article.get("body_text", "")[:3000],
    )

    try:
        resp = _client().chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1200,
            temperature=0.2,
        )
        raw = resp.choices[0].message.content.strip()
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)
        if not data.get("has_case"):
            return None

        # Validate category
        cat = data.get("category", "")
        if cat not in VALID_CATEGORIES:
            log.warning(f"Invalid category '{cat}' — skipping")
            return None

        short    = re.sub(r"[^A-Z0-9]", "", data.get("short", "UNK").upper())[:4] or "UNK"
        url_hash = hashlib.md5(article.get("url", "").encode()).hexdigest()[:6]
        case_id  = f"{short}-{date.today().strftime('%Y%m%d')}-{url_hash}"
        bg, tc   = get_color(data.get("company", ""))

        # Clamp metrics to 1–4
        metrics = data.get("metrics", [])[:4]
        if not metrics:
            metrics = [{"value": data.get("kpi_value", "N/A"),
                        "label": data.get("kpi_label", ""),
                        "trend": "neu"}]

        return {
            "id":          case_id,
            "category":    cat,
            "company":     data.get("company", ""),
            "short":       short,
            "color_bg":    bg,
            "color_text":  tc,
            "kpi_value":   data.get("kpi_value", "N/A"),
            "kpi_label":   data.get("kpi_label", ""),
            "title":       data.get("title", ""),
            "description": data.get("description", ""),
            "body":        data.get("body", ""),
            "metrics":     metrics,
            "tags":        data.get("tags", [])[:4],
            "source":      data.get("source", article.get("source_name", "")),
            "url":         data.get("url", article.get("url", "")),
            "added_date":  date.today().isoformat(),
            "verified":    False,
        }

    except json.JSONDecodeError as e:
        log.warning(f"JSON parse error ({article.get('url','')}): {e}")
        return None
    except Exception as e:
        log.error(f"API error: {e}")
        return None


def extract_cases_from_articles(articles: list[dict]) -> list[dict]:
    cases = []
    for i, article in enumerate(articles):
        log.info(f"[{i+1}/{len(articles)}] {article.get('title','')[:70]}")
        case = extract_case(article)
        if case:
            log.info(f"  → [{case['category']}] {case['company']} / {case['kpi_value']}")
            cases.append(case)
        else:
            log.info("  → 해당 없음")
    return cases


if __name__ == "__main__":
    mock = {
        "title": "Gemini for Home brings conversational AI to smart devices",
        "url": "https://blog.google/products/google-nest/gemini-home/",
        "source_name": "Google Home Blog",
        "source_cats": ["1-1", "3-1"],
        "body_text": """
        Google announced Gemini for Home, bringing conversational AI to Nest and smart home devices.
        Users can ask Gemini to control lights, thermostats, and routines using natural language.
        Early access begins October 2025 in the US. The system integrates with 50,000+ smart home devices
        via Matter and Google Home platform. Unlike previous voice assistants, Gemini understands context
        and can execute multi-step home automation tasks.
        """,
    }
    case = extract_case(mock)
    print(json.dumps(case, indent=2, ensure_ascii=False))
