"""
scraper/quality_filter.py

'Life After AI' 블로그의 자동 수집 파이프라인용 품질 필터.
아티클이 Trinity Eye 토론(정/반/합) 재료로 적합한지 평가하여
accept / hold / reject 중 하나로 분류한다.

평가 흐름:
  1. 하드 필터 (regex)  - 명백한 노이즈는 LLM 호출 전에 제거 → 비용 절감
  2. 중복 감지            - 기존 cases와 제목·회사·카테고리 비교
  3. LLM 점수             - life_change, debate_potential, topic_match
  4. 최종 판정            - 합계 점수로 accept / hold / reject

통합 위치:
  scraper/llm_summarizer.py가 case dict를 만든 직후, updater.py가
  cases.json에 병합하기 전에 evaluate_article()을 호출하면 된다.
"""

import re
import json
import difflib
from typing import Dict, List, Optional, Callable
from urllib.parse import urlparse


# ============================================================
# 1. 하드 필터 - 정규식 기반 사전 차단
# ============================================================

# 제목에 매칭되면 즉시 reject (한·영 모두 커버)
HARD_REJECT_TITLE_PATTERNS = [
    # 제품 할인·세일·딜
    r"\d+\s*%\s*(할인|off|discount)",
    r"\b(deal|sale|할인|특가|세일|프로모션)\b",
    r"\$\d+(\.\d+)?\s*(off|할인)",

    # 단순 국가 출시 뉴스 ("X 나라에 출시")
    r"(독일|이탈리아|스페인|프랑스|일본|영국|호주|멕시코|브라질|인도|싱가포르|대만)\s*(출시|런칭|진출|상륙)",
    r"\b(germany|italy|spain|france|japan|uk|australia|mexico|brazil|india)\b.{0,30}\b(launch|debut|rollout)\b",

    # 모델/SW 버전 업그레이드 뉴스
    r"\bv?\d+\.\d+\b.{0,20}(업그레이드|upgrade|출시|release)",
    r"(early\s*access|베타|beta\s*release|preview)",

    # 카테고리 인덱스성 제목 (한 단어/매우 짧음)
    r"^(스마트\s*홈|smart\s*home|AI\s*at\s*work|product\s*reviews?)\s*$",
]

# URL이 카테고리·태그·검색·제품상세 페이지면 reject
HARD_REJECT_URL_PATTERNS = [
    r"/category/", r"/tag/", r"/topics?/?$",
    r"/search\?", r"/home/?$",  # 매체의 카테고리 허브
]

# 신뢰 불가 도메인 (광고성·타블로이드·헬프문서)
BLOCKED_DOMAINS = {
    "support.google.com",     # Google 헬프 문서
    "the-sun.com",            # 타블로이드
    "amazon.com",             # 제품 상세 페이지
}


def matches_hard_reject(title: str, url: str) -> Optional[str]:
    """매칭되면 reject 이유 문자열 반환, 아니면 None."""
    for pattern in HARD_REJECT_TITLE_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            return f"title:{pattern[:40]}"

    for pattern in HARD_REJECT_URL_PATTERNS:
        if re.search(pattern, url, re.IGNORECASE):
            return f"url:{pattern}"

    domain = urlparse(url).netloc.replace("www.", "")
    if domain in BLOCKED_DOMAINS:
        return f"domain:{domain}"

    return None


# ============================================================
# 2. 중복 감지
# ============================================================

def is_duplicate(
    new_article: Dict,
    existing_cases: List[Dict],
    base_threshold: float = 0.7,
) -> Optional[str]:
    """
    같은 회사·같은 카테고리면 threshold를 낮춰서 엄격히 검사.
    중복 발견 시 기존 케이스의 id 반환.
    """
    new_title = (new_article.get("title") or "").lower()
    new_body_head = (new_article.get("body") or "")[:200].lower()
    new_company = (new_article.get("company") or "").lower()
    new_category = new_article.get("category")

    for existing in existing_cases:
        ex_title = (existing.get("title") or "").lower()
        ex_body_head = (existing.get("body") or "")[:200].lower()
        ex_company = (existing.get("company") or "").lower()

        # 같은 회사 + 같은 카테고리 → 매우 엄격 (한·영 표기 차이 흡수)
        same_co_cat = (
            new_company == ex_company
            and new_category == existing.get("category")
        )
        threshold = 0.45 if same_co_cat else base_threshold

        title_sim = difflib.SequenceMatcher(None, new_title, ex_title).ratio()
        body_sim = difflib.SequenceMatcher(None, new_body_head, ex_body_head).ratio()

        # 제목 또는 본문 도입부 둘 중 하나라도 threshold 넘으면 중복
        if title_sim >= threshold or body_sim >= threshold:
            return existing.get("id")

    return None


# ============================================================
# 3. LLM 점수 평가
# ============================================================

SCORING_PROMPT_TEMPLATE = """다음 아티클을 'Life After AI' 블로그의 Trinity Eye 토론(정/반/합) 재료로 적합한지 평가하세요.

블로그의 12개 주제:
  1-1 AI Home (집이 스스로 운영)
  1-2 Wellness Home (건강·예방·회복 공간)
  1-3 Energy Optimization (에너지·생활비 자동 최적화)
  2-1 Agentic Commerce (AI가 탐색·비교·구매 대행)
  2-2 AI Shopping (대화형 상담 쇼핑)
  2-3 Subscription AI (소유보다 사용·관리 위임)
  3-1 AI Assistant (개인·가족 생활 운영 비서)
  3-2 Productivity Life (개인 생산성 확장)
  3-3 Capability Divide (AI 활용 격차)
  4-1 Emotional AI (정서적 대화·감정 관리)
  4-2 Companion (생활 속 AI 동반자)
  4-3 Aging Society (재택 돌봄)

평가 아티클:
  제목: {title}
  출처: {source}
  요약: {body}

다음 JSON으로만 응답하세요. 다른 설명·코드블록 금지.
{{
  "life_change_score": <0-5: 사람들 삶/사회 변화를 다루는 정도. 단순 제품·기능 스펙은 0-1>,
  "debate_potential": <0-5: 정/반 양쪽에서 논쟁할 만한가. 합의된 사실 보도는 0-1>,
  "topic_match": "<12개 주제 ID 중 하나, 매핑 불가면 'none'>",
  "topic_match_strength": <0-5: 매핑된 주제와 얼마나 명확히 연결되는가>,
  "korea_relevance": <0-5: 한국에 일반화 가능한가>,
  "perspective": "<낙관 | 비판 | 중립 | 데이터>",
  "rejection_signal": "<reject 추천 시 한 줄 이유, 없으면 빈 문자열>"
}}"""


def score_with_llm(article: Dict, llm_call_fn: Callable[[str], str]) -> Dict:
    """LLM에게 점수 받기. llm_call_fn은 프로젝트의 LLM 호출 함수."""
    prompt = SCORING_PROMPT_TEMPLATE.format(
        title=article.get("title", ""),
        source=article.get("source", ""),
        body=(article.get("body") or "")[:1500],
    )

    response = llm_call_fn(prompt).strip()

    # 코드블록 제거
    if response.startswith("```"):
        response = re.sub(r"^```(?:json)?\s*", "", response)
        response = re.sub(r"\s*```$", "", response)

    try:
        parsed = json.loads(response)
        # 점수 범위 클램핑
        for key in ["life_change_score", "debate_potential",
                    "topic_match_strength", "korea_relevance"]:
            parsed[key] = max(0, min(5, int(parsed.get(key, 0))))
        return parsed
    except (json.JSONDecodeError, ValueError, TypeError):
        return {
            "life_change_score": 0, "debate_potential": 0,
            "topic_match": "none", "topic_match_strength": 0,
            "korea_relevance": 0, "perspective": "중립",
            "rejection_signal": "llm_parse_error",
        }


# ============================================================
# 4. 최종 판정
# ============================================================

# 임계값 (튜닝 가능)
# - 합계 점수 = life_change + debate + topic_match_strength (각 0-5, 최대 15)
ACCEPT_THRESHOLD = 11  # 11~15: 즉시 게시 (verified=True)
HOLD_THRESHOLD = 7     # 7~10:  사람 검토 대기 (verified=False)
                       # 0~6:   자동 폐기


def evaluate_article(
    article: Dict,
    existing_cases: List[Dict],
    llm_call_fn: Callable[[str], str],
) -> Dict:
    """
    Returns:
        {
          "decision": "accept" | "hold" | "reject",
          "reason":   str,
          "scores":   dict | None,
          "duplicate_of": str | None,
        }
    """
    title = article.get("title", "")
    url = article.get("url", "")

    # 1차: 하드 필터
    hard_reason = matches_hard_reject(title, url)
    if hard_reason:
        return {"decision": "reject", "reason": f"hard_filter:{hard_reason}",
                "scores": None, "duplicate_of": None}

    # 2차: 중복
    dup_id = is_duplicate(article, existing_cases)
    if dup_id:
        return {"decision": "reject", "reason": "duplicate",
                "scores": None, "duplicate_of": dup_id}

    # 3차: LLM 점수
    scores = score_with_llm(article, llm_call_fn)

    if scores.get("rejection_signal"):
        return {"decision": "reject",
                "reason": f"llm:{scores['rejection_signal']}",
                "scores": scores, "duplicate_of": None}

    if scores.get("topic_match") == "none":
        return {"decision": "reject", "reason": "no_topic_match",
                "scores": scores, "duplicate_of": None}

    total = (
        scores.get("life_change_score", 0)
        + scores.get("debate_potential", 0)
        + scores.get("topic_match_strength", 0)
    )

    if total >= ACCEPT_THRESHOLD:
        decision = "accept"
    elif total >= HOLD_THRESHOLD:
        decision = "hold"
    else:
        decision = "reject"

    return {"decision": decision, "reason": f"score_total:{total}",
            "scores": scores, "duplicate_of": None}


# ============================================================
# 5. 소급 적용 - 기존 cases.json 정리
# ============================================================

def audit_existing_cases(
    cases_json_path: str,
    llm_call_fn: Callable[[str], str],
    dry_run: bool = True,
) -> Dict:
    """
    이미 쌓인 cases.json을 다시 평가.
    verified=False인 케이스를 검토 대상으로 삼고,
    verified=True 케이스를 '기준 풀'로 사용해 중복 비교.

    dry_run=True: 리포트만 출력 (수정 없음)
    dry_run=False: 실제로 cases.json에서 reject된 항목 제거
    """
    with open(cases_json_path, encoding="utf-8") as f:
        data = json.load(f)

    cases = data["cases"]
    verified_pool = [c for c in cases if c.get("verified")]
    unverified = [c for c in cases if not c.get("verified")]

    results = {"accept": [], "hold": [], "reject": []}

    for article in unverified:
        result = evaluate_article(article, verified_pool, llm_call_fn)
        result["id"] = article["id"]
        result["title"] = article["title"]
        results[result["decision"]].append(result)

    if not dry_run:
        reject_ids = {r["id"] for r in results["reject"]}
        new_cases = [c for c in cases if c["id"] not in reject_ids]
        # accept된 unverified는 verified=True로 승격
        accept_ids = {r["id"] for r in results["accept"]}
        for c in new_cases:
            if c["id"] in accept_ids:
                c["verified"] = True

        data["cases"] = new_cases
        data["meta"]["total_cases"] = len(new_cases)

        with open(cases_json_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    return results


# ============================================================
# CLI 진입점
# ============================================================

if __name__ == "__main__":
    import sys

    def github_models_call(prompt: str) -> str:
        """GitHub Models gpt-4o-mini 호출 예시 (실제 구현은 프로젝트 기존 함수 사용)."""
        from openai import OpenAI
        import os
        client = OpenAI(
            base_url="https://models.inference.ai.azure.com",
            api_key=os.environ["GITHUB_TOKEN"],
        )
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            response_format={"type": "json_object"},
        )
        return resp.choices[0].message.content

    if len(sys.argv) < 2:
        print("usage: python quality_filter.py <cases.json> [--apply]")
        sys.exit(1)

    cases_path = sys.argv[1]
    dry = "--apply" not in sys.argv

    report = audit_existing_cases(cases_path, github_models_call, dry_run=dry)

    print(f"\n{'=' * 60}")
    print(f"Quality audit report ({'DRY RUN' if dry else 'APPLIED'})")
    print(f"{'=' * 60}")
    for decision in ["accept", "hold", "reject"]:
        items = report[decision]
        print(f"\n[{decision.upper()}] {len(items)}개")
        for item in items:
            print(f"  - {item['id']}: {item['title'][:50]}")
            print(f"    이유: {item['reason']}")
