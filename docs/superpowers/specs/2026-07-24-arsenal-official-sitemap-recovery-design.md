# arsenal_official 커버리지 복구 — sitemap 발견 · GetArticle 확장 전환

- 날짜: 2026-07-24
- 선행 spec: `docs/superpowers/specs/2026-07-19-arsenal-official-api-recovery-design.md`
  — taxonomy 판별 · 재계약 Men 한정 · rule_stage official 확정은 그대로 승계한다.
- 진단: `docs/troubleshooting/2026-07-24-arsenal-official-filter-starvation.md`
  + 2026-07-24 전 소스 커버리지 감사 라이브 실측 (이 문서 §2).
- 브레인스토밍 확정 (사용자, 2026-07-24): 접근안 A (sitemap + GetArticle)
  · 백필 6/1 전체 재검증 · 감시 = 정밀 조건 알림 + 관측 로그 · precision 5행 흡수.

## 1. 배경 · 목표

공홈 어댑터의 발견 경로였던 GraphQL 리스트 (`GetArticlesByTaxonomy`) 가 새 기사를 내주지 않아
tier 0 소스가 Tzolis 영입 오피셜 (07-23 12:10 UTC 발행) 을 통째로 놓쳤다.
필터 (`_accept`) 는 정상이었고, 결함은 발견 계층에 있다.

목표:

- **발견 경로 교체** — 동결된 리스트 쿼리를 버리고 sitemap 기반 발견으로 전환한다.
- **소급 백필** — 2026-06-01 이후 공홈 뉴스 전체를 sitemap 기준으로 재검증해 놓친 오피셜을 복원한다.
- **precision 라벨** — 신규 수집에 `published_precision='time'` 을 부여하고 기존 5행을 백필한다.
- **재발 감시** — "조용한 0건" 을 사람이 즉시 인지할 수 있게 정밀 조건 알림 2축 + 관측 로그를 넣는다.

## 2. 감사 실측 (2026-07-24) — 설계의 근거

- **리스트 피드 동결**: 최신 항목이 07-22 14:01 UTC 에서 멈춤 (31시간+ 지속 재확인).
  `sortField` 변경 무효 · `total` 은 46,895 → 46,896 증가 (인덱스는 새 기사를 인지).
  400건 창 (page 1~8) 어디에도 Tzolis 미출현
  → 기존 진단 (50건 창 도배) 에 더해 피드 자체가 새 기사를 안 내주는 결함이 확인됐다.
- **공홈 프론트엔드도 같은 쿼리 사용**: `/news` 페이지 번들 (chunk 8632) 에서
  `GetArticlesByTaxonomy` 확인, SSR props 에 기사 목록 없음
  → 공홈 뉴스 페이지도 같은 동결을 겪고 있고, 수리 시점을 우리가 예측 · 감지할 수 없다.
- **sitemap 은 신선**: `/sitemaps/articles/{1..16}/sitemap.xml` 약 3만 건 · lastmod 분 단위 갱신.
  최신 기사가 1번 파일 맨 앞에 붙는다 (07-23 기사 29건이 index 0~28 — 실측).
- **확장 GetArticle 성립**: `title · publicationDate · taxonomies · articleType · articleBody`
  를 한 콜에 반환 (Tzolis glideId 로 실증). 리스트가 동결된 시각에도 GetArticle 은 정상이었다.
- **07-19 이후 `_accept` 대상은 Tzolis 오피셜 1건뿐** (공홈 신규 뉴스 49건 전수 taxonomy 검사)
  — 그 1건이 누락이다.

## 3. 접근안 결정

- **A안 (채택) — sitemap 발견 + 확장 GetArticle**: 발견은 SEO 필수 표면 (sitemap) 이라
  공홈이 깨뜨릴 유인이 최저이고 장애가 fetch 에러로 드러난다.
  메타 · 본문은 검증된 GetArticle 확장 1콜. 기존 코드 (`_accept` · `_body_payload`) 재사용 최대.
- B안 (기각) — 리스트 유지 + 페이징 확대: 동결은 창 크기 문제가 아니라 실측으로 반증됨.
- C안 (기각) — sitemap + SSR HTML 파싱: 에러로 드러나는 GraphQL 의존을
  조용히 깨지는 파싱 의존으로 교환하는 셈 — 이번 사고 유형 (조용한 실패) 재도입 + 본문 파싱 신규 코드.

## 4. 어댑터 설계 (`adapters/arsenal_api.py` 개편)

### 4.1 발견 — sitemap 48h 창

- `GET https://www.arsenal.com/sitemaps/articles/1/sitemap.xml` 직접 1회 (상수 URL).
  최신 기사가 이 파일 맨 앞에 붙는다 (실측) — 인덱스 체인을 매 회차 걷지 않는다.
  구조 개편으로 경로가 바뀌면 404 = fetch 에러로 드러나고, 그때 인덱스에서 재발견한다.
- 후보 = `/news/` 경로이면서 `lastmod ≥ now − WINDOW_HOURS` 인 항목.
- `WINDOW_HOURS = 48` 상수 기본값. 생성자 인자 `window_hours` 로만 조정 (config 미노출
  — 07-19 spec 의 "요청 밖 설정성 배제" 유지). 백필 스크립트만 큰 값을 쓴다.
- 창 48h 근거: 회차 간격 6h 의 8배 여유
  → 타이머 18.5h 정지 (07-23 실측) 같은 결손도 캐치업 1회로 흡수.
  창 중첩 재수집은 dedup (URL UNIQUE · content_hash) 이 무비용 처리.
- sitemap 요청 실패는 fetch 에러로 전파한다 (조용한 폴백 없음).

### 4.2 메타 · 본문 — 확장 GetArticle 1콜

- glideId = 후보 URL 끝 토큰, 정규식 `-([A-Za-z0-9]{10,})$` (Tzolis 로 URL 접미 = glideId 실증).
- `ARTICLE_QUERY` 를 확장해 `title · publicationDate · taxonomies · articleType · articleBody`
  를 요청한다. 명시 필드 요청이므로 스키마 드리프트는 validation 에러로 드러난다.
- `_accept` (기존 로직 그대로 — `News + Men + (Transfer news | Contract news)`) 를
  GetArticle 응답에 적용해 통과분만 RawItem 으로 만든다.
- payload: `title` · `published` (publicationDate) · **`published_precision: "time"`**
  · `_body_payload` 재사용 (body · image_url · authors).
- **에러 처리**: glideId 추출 실패 · getArticle null · HTTP 에러는 항목별 예외 격리
  + WARNING 로그로 집계한다 (PR #29 선례). 조용한 스킵 금지.

### 4.3 삭제

- `GetArticlesByTaxonomy` 리스트 쿼리 · `pages` 생성자 인자 · config `pages` 제거
  (이 개편이 만든 고아만 제거).

## 5. 관측 · 알림

- 어댑터가 fetch 중 퍼널을 집계해 `self.coverage = {candidates, men_tagged, accepted}` 로
  노출하고 로그 한 줄을 남긴다: `arsenal: 창 후보 N · Men K · accept M`.
- run.py 가 collect 후 어댑터 목록에서 coverage 를 읽어 (run.py 는 adapters 를 보유)
  두 불변식 위반 시 `notify.send_alert(**notify.build_coverage_alert(...))` 를 보낸다:
  - **후보 0** — 48h 창에 공홈 뉴스가 하나도 없음 = 발견 경로 장애.
    공홈은 평시에도 일 10~15건을 발행 (실측) → 오탐 사실상 없음.
  - **Men 태그 출현 0** — 경기 리포트 등 일상 기사가 늘 `Men` 을 달아 비수기에도
    소멸하지 않음 → 소멸 = taxonomy 어휘 드리프트.
- 창 자체가 48h 라 "지속" 판정이 내장 — 이력 테이블 불필요.
  고장이 지속되면 회차마다 재발송된다 (기존 SLO 알림과 같은 성질 — 의도된 동작).
- accept 0 은 알림 대상이 아니다 — 이적창 비수기에 몇 달간 정상이라 어떤 임계도
  오탐 아니면 미탐이 된다. 로그의 후보 · accept 짝이 SLO-5 알림 수신 시의 진단 수단이다.
- SLO-5 와의 관계: SLO-5 는 "DB 에 새 행이 오래 없다" (결과 축) 만 본다.
  이번 사고에서 9회 stale 을 기록하고도 평시와 구분되지 않았다.
  이 알림 2축은 "소스가 낸 후보 대비 산출" (원인 축) 을 봐 즉시 해석 가능한 신호를 준다.

## 6. precision 라벨 백필 (기존 5행)

- 대상: arsenal_official 5행 (`published_precision IS NULL` · raw 에 `published` 존재 확인됨).
- 방법: dry-run 으로 대상 확정 → 스냅샷 → `published_precision='time'` UPDATE.
- VM 절차는 `docs/runbook/2026-07-24-vm-live-reprocess-deploy.md` (타이머 창 · 스냅샷 선행).

## 7. 소급 백필 — 6/1 전체 재검증 (1회성)

- 근거: 07-19 백필 (5건) 은 지금 동결 · 정렬 이상이 확인된 리스트 피드로 수행됐다
  → 당시 누락 가능성을 배제할 수 없어 sitemap 기준으로 이적창 전체를 재검증한다.
- 방법: 07-19 선례 (§4.4) 와 동일하게 전용 모듈 없이 **단독 스크립트**
  — 어댑터를 `window_hours` 6/1 커버 (약 1,300h) 로 인스턴스화해
  표준 적재 경로 (RawStore → to_articles → upsert → rule_stage) 를 1회 통과.
- 비용: 대상 351건 (lastmod ≥ 06-01 인 `/news/`, 실측) → GetArticle 351콜 · 무료 · 약 2~3분.
  dedup 이 기존 5행 중복을 처리하고, 채택분 번역은 정규 회차가 멱등 흡수한다.
- run.py 종단 실행이 아니므로 fmkorea 무접촉.

## 8. config · factory

- `sources.yaml`: arsenal 항목 `pages: 2` 제거 · 주석을 sitemap 발견 경로로 갱신.
- `factory.py`: `ArsenalApiAdapter(sid, pages=…)` → `ArsenalApiAdapter(sid)`.

## 9. 테스트 · 검증

- 단위 (sitemap XML · GetArticle 응답 모킹):
  - 창 컷오프 (48h 경계) · `/news/` 경로 필터 · glideId 추출 (성공 · 실패).
  - `_accept` 승계 케이스: 방출 오피셜 통과 · 여자팀 차단 · 아카데미 차단 · Video 차단.
  - `published_precision='time'` 부여 · payload 매핑.
  - coverage 집계 (candidates · men_tagged · accepted) · getArticle null 이 WARNING 집계되는지.
  - run.py 알림 배선: 후보 0 · Men 0 각각에서 notify 호출, 정상 창에서 미호출.
- **라이브 단독 fetch (머지 전 필수 — 셀렉터 드리프트 관례)**: Tzolis 오피셜 실수집 확인.
- 종단: 백필 실행 후 rule_stage=official 태깅 · 카드 노출 · precision 시각 병기 확인.

## 10. 범위 밖

- 퍼널 관측 (후보 대비 accept) 의 전 소스 일반화 — 이번 PR 에서 패턴 실증 후
  별도 트랙 후보로만 기록한다.
- fmkorea 복구 (별도 트랙) · B4 잔여 (afcstuff · guardian precision) · 레거시 EN 149행 백필 (별도 PR).
- GetArticlesByTaxonomy 동결 자체의 원인 규명 — 공홈 내부 문제로 우리 통제 밖.
