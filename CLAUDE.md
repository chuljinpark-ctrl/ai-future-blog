# LGE AX Benchmark System — Claude Code Context

## 프로젝트 목적
LG전자 AX(AI Transformation) 전략을 위한 글로벌 AI 영업·마케팅 벤치마크 DB 자동 수집·업데이트 시스템.
- **매일 KST 10:00**: 소스 스크래핑 → GitHub Models(gpt-4o-mini)로 케이스 추출 → cases.json 업데이트 → GitHub Pages 자동 배포
- **매월 1일 KST 09:00**: 커버리지 갭 분석 → 신규 소스 후보 발굴 → 검증 → PR 생성

## 디렉토리 구조
```
lge-benchmark/
├── CLAUDE.md                           ← 이 파일
├── README.md
├── requirements.txt                    ← openai, requests, bs4, lxml
│
├── docs/                               ← GitHub Pages 서빙 루트 (소스 + 배포 일원화)
│   ├── index.html                      ← Hero 페이지 (랜딩)
│   ├── dashboard.html                  ← 벤치마크 대시보드
│   ├── archive.html                    ← 케이스 피드 (블로그형)
│   ├── admin.html                      ← 소스 관리 어드민
│   ├── hero.css                        ← 공통 디자인 시스템 CSS
│   └── data/
│       ├── cases.json                  ← DB 사본 (Actions가 동기화)
│       └── sources.json                ← 소스 목록 사본 (Actions가 동기화)
│
├── data/
│   ├── cases.json                      ← 메인 DB (소스 오브 트루스)
│   └── source_candidates.json          ← 월별 소스 발굴 결과
│
├── scraper/
│   ├── sources.json                    ← 모니터링 소스 7개 (활성)
│   ├── core_scraper.py                 ← RSS/HTML 스크래퍼
│   ├── llm_summarizer.py               ← GitHub Models로 케이스 추출
│   ├── updater.py                      ← cases.json 병합
│   ├── run_pipeline.py                 ← 일별 배치 엔트리
│   ├── source_analyzer.py              ← 커버리지 갭 분석
│   ├── source_discoverer.py            ← GitHub Models로 소스 후보 발굴
│   ├── source_validator.py             ← RSS확인·빈도·키워드 스코어링
│   └── run_source_update.py            ← 월별 소스 업데이트 엔트리
│
└── .github/workflows/
    ├── daily_update.yml                ← 매일 배치 (UTC 01:00)
    └── monthly_source_update.yml       ← 매월 소스 업데이트 (UTC 00:00, 1일)
```

## LLM — GitHub Models (별도 Secret 불필요)
모든 LLM 호출은 GitHub Models API 사용.
- Endpoint: `https://models.inference.ai.azure.com`
- Model: `gpt-4o-mini` (비용 효율, 정밀도 필요 시 `gpt-4o`로 교체)
- Auth: `GITHUB_TOKEN` — GitHub Actions에서 자동 주입, 별도 등록 불필요
- SDK: `openai` Python 패키지 (OpenAI 호환 API)

```python
from openai import OpenAI
client = OpenAI(
    base_url="https://models.inference.ai.azure.com",
    api_key=os.environ["GITHUB_TOKEN"],   # 자동 주입
)
```

## 배포 — GitHub Pages
- 소스: `docs/` 폴더 (main 브랜치)
- URL: `https://{username}.github.io/lge-benchmark/`
- 동작: Actions가 `data/cases.json` → `docs/data/cases.json` 동기화 후 push → Pages 자동 재배포

### GitHub Pages 활성화 방법 (최초 1회)
1. Repository → Settings → Pages
2. Source: `Deploy from a branch`
3. Branch: `main` / Folder: `/docs`
4. Save

## 데이터 스키마 (cases.json)
```json
{
  "id": "SEP-20260505-a3f9c1",  // SHORT-YYYYMMDD-urlhash6 형식
  "category": "1-1",       // 1-1 ~ 2-5
  "company": "Sephora",
  "short": "SEP",
  "color_bg": "#FBEAF0",
  "color_text": "#72243E",
  "kpi_value": "+11%",
  "kpi_label": "신규 고객 유입",
  "title": "AI 버추얼 아티스트",
  "description": "한 줄 설명 (50자)",
  "body": "상세 내용 (한국어, 150~200자)",
  "metrics": [{"value":"...", "label":"...", "trend":"pos|neg|neu"}],  // 4개
  "tags": ["retail","AR"],
  "source": "출처명, 연도",
  "url": "https://...",
  "added_date": "2026-05-05",
  "verified": true          // 자동 수집 = false, 수동 검토 후 true
}
```

## 카테고리 구조
### Top-line 향상
- 1-1: 신규 고객 획득 | 1-2: 전환율 상승 | 1-3: 객단가·Mix 개선
- 1-4: 재구매·LTV 확대 | 1-5: 신규 수익모델

### Bottom-line 개선
- 2-1: 마케팅 운영비 절감 | 2-2: 영업 운영비 절감 | 2-3: CS·케어 비용 절감
- 2-4: 운영 판단력·실행력 | 2-5: 리스크·품질 비용 절감

## 파이프라인 흐름

### 일별 (daily_update.yml)
```
UTC 01:00 (KST 10:00)
  ↓
core_scraper.py    — sources.json의 7개 소스 RSS/HTML 스크래핑
  ↓
llm_summarizer.py  — GitHub Models gpt-4o-mini로 케이스 추출
  ↓
updater.py         — cases.json에 신규 케이스 병합
  ↓
docs/data/cases.json 동기화 → git push → GitHub Pages 자동 갱신
```

### 월별 (monthly_source_update.yml)
```
UTC 00:00 (KST 09:00), 매월 1일
  ↓
source_analyzer.py    — cases.json 태그 vs sources.json 커버리지 갭 분석
  ↓
source_discoverer.py  — GitHub Models로 갭별 신규 소스 후보 2-3개 제안
  ↓
source_validator.py   — RSS 확인 + 발행빈도 + 키워드 점수 (100점 만점)
  ↓
score ≥ 75 → sources.json 자동 추가 + PR 생성
score 50~74 → PR에 수동 검토 안내
score < 50  → 기각
```

## 소스 목록 (scraper/sources.json)
현재 7개 소스 | RSS 5개 + HTML 2개

| 우선순위 | 소스 | 방식 | 주요 커버 |
|---------|------|------|---------|
| high | salesforce-blog | RSS | B2B 영업 AI, CRM |
| high | microsoft-blog | RSS | Copilot, 생산성 |
| high | think-with-google | HTML | 미디어, ROAS |
| medium | marketing-dive | RSS | 마케팅 자동화 |
| medium | supply-chain-dive | RSS | 수요예측·재고 |
| medium | klarna-newsroom | HTML | 핀테크, CS 자동화 |
| low | cognigy-blog | RSS | CS 자동화, AHT |

excluded_sources (bot 차단으로 비활성): mckinsey, bcg, hbr, marketingweek, bain, gartner

## GitHub 설정 체크리스트 (최초 1회)
- [ ] GitHub Pages 활성화 (Settings → Pages → main/docs)
- [ ] 별도 Secret 불필요 — GITHUB_TOKEN 자동 사용
- [ ] Workflow permissions: Read and write (Settings → Actions → General)

## 로컬 실행
```bash
pip install -r requirements.txt

# 갭 분석만 (API 불필요)
python scraper/run_source_update.py --analyze-only

# 일별 배치 dry-run (GITHUB_TOKEN 필요)
export GITHUB_TOKEN=your_personal_access_token
python scraper/run_pipeline.py --dry-run

# 월별 소스 업데이트 dry-run
python scraper/run_source_update.py --no-auto-approve --max-gaps 3
```

## 로컬 확인
```bash
# docs/가 소스이자 서빙 폴더이므로 바로 실행
cp data/cases.json docs/data/cases.json
cp scraper/sources.json docs/data/sources.json
cd docs && python -m http.server 8080
# → http://localhost:8080/dashboard.html
```

## TODO
- [ ] GitHub repo 생성 및 push
- [ ] GitHub Pages 활성화
- [ ] Workflow permissions → Read and write 확인
- [ ] 첫 Actions 수동 실행 (daily_update → workflow_dispatch)
- [ ] 대시보드 URL 확인
