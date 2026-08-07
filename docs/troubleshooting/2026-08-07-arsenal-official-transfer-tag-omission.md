# arsenal_official 이적 발표가 태그 누락으로 채택 필터에서 빠졌다 (2026-08-07)

채택 필터 (Men + 이적 태그) 가 실제 1군 이적 발표 기사를 놓쳤다.
「Christian Norgaard joins Everton」 (08-05 21:09 UTC 발행) 이 정기 회차에서 수집되지 않았다.
**08-04 문서의 "채택 0 은 산술적으로 맞다" 는 결론이 이 사례로 깨졌다** — 태그 판별 자체가 실제 발표를 놓칠 수 있다.

## 1. 증상

- 뇌르고르의 에버턴 이적 발표 기사가 arsenal.com 에 올라왔는데 수집되지 않았다.
- 공홈 커버리지 알림 (창 후보 0 · Men 소멸 감시) 은 조용했다 — 발견 경로는 정상이었다는 뜻이다.
- 신선도 알림은 매 회차 "이번 회차 후보 0건" 을 알렸지만, 이 사례가 진짜 미수집인지 정상 공백인지는 문구만으로 구분할 수 없었다.

## 2. 확인한 것

96시간 창 후보 47건 전수 조회 + 과거 채택 6건 재조회로 원인을 확정했다.

- **발견 경로 정상** — 뇌르고르 기사는 sitemap 창 후보에 들어왔고, GetArticle 조회도 됐다 (Men 계수에도 포함됐다).
- **탈락 지점은 태그 판별** — 기사에는 `Men` · `News` 는 있는데 `Transfer news` · `Contract news` 가 없었다.
- **어휘 소멸이 아니다** — 과거 채택 6건을 지금 재조회해도 전부 `Transfer news` 를 달고 있다.
- **방출이라서 빠진 것도 아니다** — 트로사르 방출 (07-15) 은 이적 태그가 정상적으로 붙어 있었다.
- 편집 측 태깅 누락인지, 방침 변화인지는 표본 1건이라 단정하지 않는다.

## 3. 기존 감시로는 못 잡는 이유

- 커버리지 알림 (`quality.evaluate_coverage`) 은 창 후보 0 또는 Men 소멸만 본다.
태그 판별 결과까지는 보지 않는다.
- 신선도 알림은 정상 공백과 실수집을 같은 문구로 알려 변별력이 없다.
- 채택 필터는 이벤트 구동 소스다 (1군 발표에만 반응한다).
유한한 신선도 임계로는 오탐 없이 이 소스를 감시할 수 없다 — 어떤 값을 골라도 비수기 정상 공백에서 오발화가 재발한다 (하루 8회 도배).

## 4. 대응

수집 범위 판단 (필터 수정 · Club 태그 수용) 은 건드리지 않고, 놓쳤을 가능성만 알리는 쪽으로 좁혔다.

### 4.1 채택 누락 관측 알림

- `quality.filter_miss_suspects` — Men + News 이지만 비채택인 기사 중,
제목이 이적성 패턴 (`joins` · `signs` · `transfer` · `loan`) 에 매치하고 발행이 6시간 이내인 것만 추린다.
- 6시간 창은 3시간 회차 기준 기사당 최대 2회 발화로 도배를 막는 무상태 설계다.
sitemap lastmod 갱신으로 되살아나는 옛 기사 (2019년 글 등) 도 발행 시각 조건이 걸러 준다.
- `notify.build_filter_miss_alert` — 제목 "🔍 공홈 이적 관련 기사 미수집 — N건" 으로,
기사별 태그 · 발행 시각 · 링크만 관측 사실로 싣는다 (원인 추정 없음).
- 96시간 창 실측 대조 — Men + News 비채택 기사 중 이적성 패턴 매치는 뇌르고르 1건뿐이었다 (오탐 0).
- 배선은 `run.py` 정기 회차 안에서, 어댑터가 남긴 `men_news_rejects` 를 판정에 넘기는 방식이다.

### 4.2 신선도 감시 제외

- arsenal_official 을 신선도 감시 대상에서 뺐다 — `config/sources.yaml` 에 `freshness_hours: 0` 을 추가했다.
- `quality.evaluate_freshness` 는 임계가 0 이하인 소스를 판정 루프에서 건너뛴다 (감시 자체를 안 한다).
- `notify.build_freshness_alert` 의 문구도 "이번 회차 후보 0건 — 수집 끊김 의심" 에서 "이번 회차 후보 0건" 으로 바꿔, 원인 추정을 뺐다.
남은 소스에는 여전히 적용된다.

## 5. 남은 제품 판단

- **필터 범위** — `Club` 태그가 붙은 이적 정리 기사를 받을지는 여전히 제품 결정이다 (08-04 문서와 동일한 미결).
- **뇌르고르 기사 회수** — `backfill_arsenal.py` 로 놓친 기사를 소급 수집할지는 이 문서에서 정하지 않는다.
- 관측 알림은 놓쳤을 가능성만 알릴 뿐, 수집 여부는 매번 사람이 판단한다.

## 6. 참고

- 스펙: `docs/superpowers/specs/2026-08-07-alert-f2-unit-attribution-and-observability-design.md` §1.4 · §3.2 · §3.3.
- 코드: `src/bullet_in/quality.py` 의 `filter_miss_suspects` · `evaluate_freshness`,
`src/bullet_in/notify.py` 의 `build_filter_miss_alert` · `build_freshness_alert`.
- 앞선 문서: `docs/troubleshooting/2026-08-04-arsenal-official-accept-zero-not-a-fault.md` — "채택 0 은 산술적으로 맞다" 는 결론이 이 문서로 정정됐다.
