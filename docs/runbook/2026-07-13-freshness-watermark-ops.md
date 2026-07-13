# 신선도 워터마크 알림 운영 (2026-07-13)

## 목적

소스가 조용히 죽어도 파이프라인은 "0건 성공" 으로 넘어가는 사각을 메우는 SLO-5 신선도 감시의 해석 · 대응 · 임계 조정 · 롤백을 정리.

- 감시 신호 — 소스별 `MAX(fetched_at)` 워터마크의 경과 시간이 임계 ( 전역 48h · 소스별 override ) 를 초과하면 Discord 알림.
- SLO-6 과의 분담 — SLO-6 은 회차 단위 수집량 급변 ( 건수 ), SLO-5 는 누적 무소식 ( 시간 ) 을 본다.
  저빈도라 min_baseline 에 걸러지는 소스도 SLO-5 는 잡는다.
- 이력 — 매 회차 소스별 한 행을 `source_freshness` 에 남긴다 ( SLO-7 모니터링 뷰 기반 ).

## 알림 해석

- **🕰️ 신선도 경고 (주황)** — stale 소스가 하나라도 있으면 한 embed 로 묶여 온다.
  제목이 stale 건수를, description 이 전체 조망 ( `감시 5소스: stale 1 · 정상 3 · 워터마크 없음 1` ) 을 보여준다.
- **소스당 필드** — 경과 시간 · 적용 임계, 마지막 수집 시각 (Discord 상대시간 · 절대시간), 어댑터 기반 원인 후보 한 줄 (힌트 매핑이 있는 어댑터만).
  `기본 임계` 필드 ( `전역 48h` ) 와 필드의 임계가 다르면 그 소스는 override 적용 상태다.
- **메타** — `회차` 필드의 run_id 앞 8자로 `pipeline_runs` · `source_freshness` 회차를 특정하고, embed 하단 시각은 검사 시각 (UTC) 이다.
- **제목 클릭** — 이 런북으로 연결된다.
- **무알림** — 모든 소스가 임계 안이거나, 워터마크 자체가 없는 소스뿐인 경우.
  워터마크 없음 ( 기사 0건 ) 은 "신규 추가" 와 "처음부터 죽음" 을 구분할 수 없어 알림에서 제외한다 — 이 케이스는 SLO-6 · 에러 로그가 담당.

## 대응 — 원인 → 처방 진단표

알림은 "무엇이 오래됐는지" 만 말한다.
원인은 아래 순서로 좁힌다.

| 원인 | 확인 방법 | 처방 |
|---|---|---|
| 셀렉터 드리프트 ( 사이트 개편 ) | 어댑터 단독 `fetch()` 라이브 실행 → 0건이면 `list_url` 을 브라우저로 열어 구조 대조 | `config/sources.yaml` 셀렉터 수정 · `docs/troubleshooting/2026-06-12-live-source-selector-drift.md` |
| 피드 · 검색 URL 변경 | `list_url` · `search_url` 직접 접속 → 404 · 리다이렉트 확인 | `feed_url` · `list_url` 갱신 |
| X 쿠키 만료 | 파이프라인 로그의 x_playwright 로그인 오류 · `x_cookies.json` 수정 시각 | 쿠키 재주입 — `docs/runbook/2026-07-03-afcstuff-playwright-adapter-ops.md` |
| 기자 계정 이전 · 핸들 변경 | X 에서 해당 핸들 직접 확인 | `config/sources.yaml` 의 `handle` · 팔로우 대상 갱신 |
| 소스가 진짜 조용 ( 오프시즌 ) | 원문 사이트에 실제로 새 글이 없음 | 조치 없음 — 정상. 반복되면 임계 상향 검토 ( 아래 ) |

- 라이브 검증이 우선이다.
  단위 테스트는 모킹이라 드리프트를 못 잡는다 ( CLAUDE.md "자주 밟는 함정" ).

## 임계 조정 가이드

임계는 `config/sources.yaml` 에서만 조정한다 ( 코드 무수정 ).

- **전역 `freshness_default_hours: 48`** — 파이프라인이 6 시간 간격 4 회/일 돌므로 48h = 8 회차 연속 무신규.
  일반 언론 소스의 주말 · 뉴스 공백을 견디는 보수적 기본값이다.
- **소스별 `freshness_hours` override** — 소스 항목에 키를 추가하면 그 소스만 좁아진다.
  현재 `x_afcstuff: 24` ( X aggregator 는 매일 다건 포스팅 → 24h 무소식이면 이상 ).
- **오탐이 잦으면** — 해당 소스의 실제 발행 간격을 `source_freshness` 이력으로 확인하고 override 를 늘린다.
  `SELECT source_id, MAX(age_hours) FROM source_freshness GROUP BY source_id` 로 평시 최대 경과를 본다.
- **오프시즌** — 이적 뉴스 소스는 시즌 중 대비 확연히 뜸해진다.
  반복 오탐 시 전역을 올리기보다 뜸한 소스만 override ( 예: 72–96h ) 를 준다.

## 검증

webhook · DB 없이도 판정 · 포맷 로직을 확인할 수 있다.

```bash
uv run pytest tests/test_quality.py -v                       # evaluate_freshness 경계 · override · NULL
uv run pytest tests/test_notify.py -v                        # build_freshness_alert 포맷
uv run pytest tests/integration/test_source_freshness.py -v  # 테이블 적재 (MariaDB 필요 · 없으면 skip)
```

## 실패 모드

- **알림 실패 무해** — `send_alert` 가 모든 예외를 삼켜 파이프라인을 죽이지 않는다 ( `docs/troubleshooting/2026-07-13-alert-exception-swallow-gap.md` ).
- **워터마크 없음 무알림** — 기사 0건 소스는 행만 남고 조용하다.
  신규 소스를 붙였는데 며칠째 `last_fetched_at` 이 NULL 이면 어댑터 자체가 죽은 것 — SLO-6 드롭 알림 · 에러 로그를 본다.
- **UTC 시계 기준** — 워터마크 (`fetched_at`) 는 어댑터가 UTC 로 저장하고, `now` 도 DB `UTC_TIMESTAMP()` 로 받는다.
  양쪽 시계가 UTC 로 고정되어 앱 · DB 컨테이너의 TZ 설정과 무관하게 판정이 흔들리지 않는다.

## 롤백

- 기능 제거는 `git revert` 로 충분하다.
  `source_freshness` 는 append 전용 이력이라 남아 있어도 무해하고, 테이블 자체도 `CREATE TABLE IF NOT EXISTS` 라 재적용 충돌이 없다.
- 알림만 임시로 끄려면 `DISCORD_WEBHOOK_URL` 을 해제한다 ( WARNING 로깅 폴백 ).
  감시 · 이력 적재는 계속 돈다.

## 참고

- spec · plan: `docs/superpowers/{specs,plans}/2026-07-13-slo5-freshness-watermark*`.
- SLO-6 알림 운영: `docs/runbook/2026-07-13-collection-alerts-ops.md`.
- 로드맵: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` ( Tier 3 · SLO-5 ).
