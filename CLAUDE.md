# LGE AX Benchmark System — Claude Code Context

## 프로젝트 목적
LG전자 AX(AI Transformation) 전략을 위한 글로벌 AI 영업·마케팅 벤치마크 DB 구축 및 자동 업데이트.
매일 KST 10:00에 글로벌 주요 소스를 스크래핑하고, Gemini Flash로 사례를 추출·구조화해 cases.json을 업데이트한다.

## 디렉토리 구조
```
lge-benchmark/
├── CLAUDE.md                      ← 이 파일 (컨텍스트 핸드오프)
├── README.md
├── requirements.txt
├── data/
│   └── cases.json                 ← 메인 DB (40개 사례, 10개 카테고리)
├── dashboard/
│   └── index.html                 ← 대시보드 (fetch 기반, cases.json 읽음)
├── scraper/
│   ├── sources.json               ← 모니터링 소스 목록 (13개)
│   ├── core_scraper.py            ← RSS/HTML 스크래퍼
│   ├── llm_summarizer.py          ← Gemini Flash 사례 추출
│   ├── updater.py                 ← cases.json 병합
│   └── run_pipeline.py            ← 배치 엔트리 포인트
└── .github/
    └── workflows/
        └── daily_update.yml       ← GitHub Actions (UTC 01:00 = KST 10:00)
```

## 데이터 스키마 (cases.json)
```json
{
  "id": "SEP-001",           // SHORT-NNN 형식
  "category": "1-1",         // 1-1 ~ 2-5
  "company": "Sephora",
  "short": "SEP",            // 3자 약어
  "color_bg": "#FBEAF0",
  "color_text": "#72243E",
  "kpi_value": "+11%",
  "kpi_label": "신규 고객 유입",
  "title": "AI 버추얼 아티스트",
  "description": "한 줄 설명",
  "body": "상세 내용 (한국어)",
  "metrics": [{"value":"...", "label":"...", "trend":"pos|neg|neu"}],  // 4개
  "tags": ["retail", "AR"],
  "source": "출처명, 연도",
  "url": "https://...",
  "added_date": "2026-05-05",
  "verified": true            // 자동 수집은 false, 수동 검토 후 true
}
```

## 카테고리 구조
### Top-line 향상
- 1-1: 신규 고객 획득 (매장 내방, 미디어 Mix, 타겟팅, SNS)
- 1-2: 전환율 상승 (상담 품질, 견적, 개인화 추천, 프로모션)
- 1-3: 객단가·Mix (Upsell, 번들, 프리미엄, 가격 최적화)
- 1-4: 재구매·LTV (이탈 방지, 재구독, Care, Lock-in)
- 1-5: 신규 수익모델 (신사업, Total Solution, 서비스·플랫폼)

### Bottom-line 개선
- 2-1: 마케팅 운영비 절감 (인건비, 에이전시, 미디어, 판촉비)
- 2-2: 영업 운영비 절감 (매장 학습, TM, 제안서, 커버리지)
- 2-3: CS·케어 비용 절감 (CS 처리비, 셀프해결, 케어, 예측케어)
- 2-4: 운영 판단력·실행력 (수요예측, 가격, 재고, 의사결정)
- 2-5: 리스크·품질 비용 (VOC, 구독 리스크, 브랜드 리스크)

## 환경 변수 (GitHub Secrets)
- GEMINI_API_KEY: Google Gemini API key (Gemini 2.0 Flash 사용)

## 배포
- GitHub Pages: /dashboard/index.html → https://{user}.github.io/lge-benchmark/dashboard/
- Vercel: vercel.json 설정으로 data/ 폴더도 서빙
- 대시보드는 ../data/cases.json을 fetch로 읽음

## 다음 작업 TODO
- [ ] vercel.json 작성
- [ ] README.md 작성
- [ ] 로컬 테스트: python scraper/run_pipeline.py --dry-run
- [ ] GEMINI_API_KEY를 GitHub Secrets에 등록
- [ ] GitHub repo 생성 및 push
- [ ] GitHub Actions 첫 실행 확인

## 주의사항
- cases.json의 verified=false 케이스는 자동 수집된 것 (대시보드에 NEW 뱃지)
- 수동으로 verified=true 로 변경한 뒤 commit하면 공식 검증 사례가 됨
- 스크래퍼는 robots.txt를 준수, delay=2초 설정됨
