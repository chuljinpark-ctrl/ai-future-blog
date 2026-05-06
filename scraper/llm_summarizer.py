"""
llm_summarizer.py
LGE AX Benchmark — LLM-based case extractor
Uses GitHub Models API (OpenAI-compatible) — no extra secrets needed,
GITHUB_TOKEN is automatically injected by GitHub Actions.
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

ROOT = Path(__file__).parent.parent
SOURCES_FILE = Path(__file__).parent / "sources.json"

# GitHub Models endpoint & model
GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"
MODEL = "gpt-4o-mini"          # cost-efficient; upgrade to gpt-4o for higher precision

with open(SOURCES_FILE) as f:
    _src_data = json.load(f)
CATEGORY_KEYWORDS = _src_data.get("category_keywords", {})

CATEGORIES = {
    "1-1": "신규 고객 획득 (신규 고객, 매장 내방, 미디어 Mix, 타겟팅, SNS 유입)",
    "1-2": "전환율 상승 (구매 상담, 견적 제안, 개인화 추천, 프로모션 반응률)",
    "1-3": "객단가·Mix 개선 (Upsell, Cross-sell, 번들 판매, 가격 최적화)",
    "1-4": "재구매·LTV 확대 (이탈 방지, 재구독, Care 연계, 구독 Lock-in)",
    "1-5": "신규 수익모델 (신사업 영업, Total Solution, 서비스·플랫폼형)",
    "2-1": "마케팅 운영비 절감 (개발·운영 인건비, 콘텐츠 에이전시, 미디어 효율화, 판촉비)",
    "2-2": "영업 운영비 절감 (매장 학습, TM 상담, 제안서 효율화, 영업 커버리지)",
    "2-3": "CS·케어 비용 절감 (CS 처리비, 셀프 해결률, 케어 효율화, 예측 케어)",
    "2-4": "운영 판단력·실행력 강화 (수요예측, 가격·판촉 최적화, 재고, 의사결정)",
    "2-5": "리스크·품질 비용 절감 (VOC 탐지, 구독 리스크, 브랜드 리스크)",
}

EXTRACTION_PROMPT = """당신은 LG전자 AX(AI Transformation) 전략팀의 글로벌 벤치마킹 분석가입니다.
아래 기사를 읽고, AI를 영업/마케팅에 적용한 구체적인 기업 사례가 있다면 추출하세요.

## 분류 기준 (카테고리):
{categories}

## 기사 내용:
제목: {title}
출처: {source_name}
URL: {url}
본문:
{body}

## 출력 형식:
사례가 있다면 아래 JSON으로만 응답하세요 (마크다운 없이 순수 JSON):
{{
  "has_case": true,
  "company": "기업명 (영문 또는 한글)",
  "short": "3자 이내 약어 (예: SAM, P&G, LOR)",
  "category": "카테고리 코드 (1-1 ~ 2-5 중 하나)",
  "kpi_value": "핵심 수치 (예: +40%, -70%, $500M, 2배)",
  "kpi_label": "수치 설명 (예: 전환율, 비용 절감, 처리량)",
  "title": "사례 제목 (한국어, 20자 이내)",
  "description": "한 줄 설명 (한국어, 50자 이내)",
  "body": "상세 내용 (한국어, 150~200자)",
  "metrics": [
    {{"value": "수치1", "label": "설명1", "trend": "pos"}},
    {{"value": "수치2", "label": "설명2", "trend": "pos"}},
    {{"value": "수치3", "label": "설명3", "trend": "neu"}},
    {{"value": "수치4", "label": "설명4", "trend": "pos"}}
  ],
  "tags": ["태그1", "태그2", "태그3"],
  "source": "출처명, 연도",
  "url": "{url}"
}}

사례가 없거나 AI 영업/마케팅과 무관하면:
{{"has_case": false}}

중요:
- trend는 "pos"(긍정), "neg"(부정), "neu"(중립) 중 하나
- metrics는 정확히 4개
- 수치는 구체적인 숫자/퍼센트가 있을 때만 포함
- JSON 외 다른 텍스트 절대 포함 금지
"""


def _get_client() -> OpenAI:
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        raise RuntimeError("GITHUB_TOKEN not set — required for GitHub Models API")
    return OpenAI(base_url=GITHUB_MODELS_ENDPOINT, api_key=token)


def get_color_for_company(company: str) -> tuple[str, str]:
    colors = [
        ("#E1F5EE", "#085041"),
        ("#FAEEDA", "#633806"),
        ("#E6F1FB", "#0C447C"),
        ("#EEEDFE", "#3C3489"),
        ("#FBEAF0", "#72243E"),
        ("#FEF3E2", "#6B3A00"),
    ]
    idx = hash(company.lower()) % len(colors)
    return colors[idx]


def extract_case_github_models(article: dict) -> Optional[dict]:
    """
    Call GitHub Models (gpt-4o-mini) to extract a structured benchmark case.
    Returns a case dict ready for cases.json, or None.
    """
    categories_text = "\n".join(f"- {k}: {v}" for k, v in CATEGORIES.items())
    prompt = EXTRACTION_PROMPT.format(
        categories=categories_text,
        title=article.get("title", ""),
        source_name=article.get("source_name", ""),
        url=article.get("url", ""),
        body=article.get("body_text", "")[:2500],
    )

    try:
        client = _get_client()
        response = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=1000,
            temperature=0.2,
        )
        raw = response.choices[0].message.content.strip()

        # Strip markdown fences
        raw = re.sub(r"^```json\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

        data = json.loads(raw)
        if not data.get("has_case"):
            return None

        short = data.get("short", "UNK").upper().replace(" ", "")[:4]
        url_hash = hashlib.md5(article.get("url", "").encode()).hexdigest()[:6]
        case_id = f"{short}-{date.today().strftime('%Y%m%d')}-{url_hash}"
        bg, tc = get_color_for_company(data.get("company", ""))

        return {
            "id":          case_id,
            "category":    data["category"],
            "company":     data["company"],
            "short":       short,
            "color_bg":    bg,
            "color_text":  tc,
            "kpi_value":   data.get("kpi_value", ""),
            "kpi_label":   data.get("kpi_label", ""),
            "title":       data.get("title", ""),
            "description": data.get("description", ""),
            "body":        data.get("body", ""),
            "metrics":     data.get("metrics", []),
            "tags":        data.get("tags", []),
            "source":      data.get("source", article.get("source_name", "")),
            "url":         data.get("url", article.get("url", "")),
            "added_date":  date.today().isoformat(),
            "verified":    False,
        }

    except json.JSONDecodeError as e:
        log.warning(f"JSON parse error for {article.get('url', '')}: {e}")
        return None
    except Exception as e:
        log.error(f"GitHub Models API error: {e}")
        return None


def extract_cases_from_articles(articles: list[dict]) -> list[dict]:
    cases = []
    for i, article in enumerate(articles):
        log.info(f"[{i+1}/{len(articles)}] Extracting: {article.get('title', '')[:60]}")
        case = extract_case_github_models(article)
        if case:
            log.info(f"  → Case: {case['company']} / {case['category']} / {case['kpi_value']}")
            cases.append(case)
        else:
            log.info("  → No relevant case")
    return cases


if __name__ == "__main__":
    mock = {
        "title": "Walmart cuts inventory costs by $4.9B using AI demand forecasting",
        "url": "https://example.com/walmart-ai",
        "source_name": "Supply Chain Dive",
        "body_text": """
        Walmart deployed AI-powered demand forecasting across its supply chain,
        achieving 90% inventory accuracy and reducing excess inventory by $4.9 billion.
        The system analyzes over 100 data points updating every 4 hours.
        """,
    }
    case = extract_case_github_models(mock)
    print(json.dumps(case, indent=2, ensure_ascii=False))
