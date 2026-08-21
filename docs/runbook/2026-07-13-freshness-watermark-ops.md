# 신선도 워터마크 알림 운영 (2026-07-13)

## 목적

소스가 조용히 죽어도 파이프라인은 "0건 성공" 으로 넘어가는 사각을 메우는 SLO-5 신선도 감시의 해석 · 대응 · 임계 조정 · 롤백을 정리.

- 감시 신호 — 소스별 `MAX(fetched_at)` 워터마크의 경과 시간이 임계 ( 전역 48h · 소스별 override ) 를 초과하면 Discord 알림.
- **그 워터마크는 Mongo `raw_items` 의 원본 수집 시각이다** ( 2026-08-20 개정 ) .
  기사 표 (`articles`) 를 보던 종전 신호는 다른 행으로 흡수되는 소스를 매일 수집돼도 stale 로 찍었다 ( `x_ornstein` 이 18일 넘게 그랬다 ) .
  설계 근거는 `docs/superpowers/specs/2026-08-20-absorbed-source-freshness-signal-design.md`.
- SLO-6 과의 분담 — SLO-6 은 회차 단위 수집량 급변 ( 건수 ), SLO-5 는 누적 무소식 ( 시간 ) 을 본다.
  저빈도라 min_baseline 에 걸러지는 소스도 SLO-5 는 잡는다.
- **신선도가 안 잡는 자리** — 수집은 되는데 뒤 단계 ( 여자팀 · 기자 allowlist · 중복 · 본문 등급 ) 가 전부 걷어내는 경우다.
  그 자리는 SLO-6 과 후보 절벽 알림이 맡는다.
- 이력 — 매 회차 소스별 한 행을 `source_freshness` 에 남긴다 ( SLO-7 모니터링 뷰 기반 ).
  `last_fetched_at` 이 판정에 쓰는 원본 수집 시각이고, `stored_fetched_at` 은 기사 표 워터마크를 기록만 해 둔 값이다.
  둘이 벌어지는 소스가 곧 흡수당하는 소스다.

## 알림 해석

- **🕰️ 신선도 경고 (주황)** — stale 소스가 하나라도 있으면 한 embed 로 묶여 온다.
  제목이 stale 건수를, description 이 전체 조망 ( `감시 5소스: stale 1 · 정상 3 · 워터마크 없음 1` ) 을 보여준다.
- **소스당 필드** — 경과 시간 · 적용 임계, 마지막 수집 시각 (Discord 상대시간 · 절대시간), 이번 회차 후보 건수, 어댑터 기반 원인 후보 한 줄 (힌트 매핑이 있는 어댑터만), 다음 재알림 안내.
  `기본 임계` 필드 ( `전역 48h` ) 와 필드의 임계가 다르면 그 소스는 override 적용 상태다.
- **마지막 저장 줄** — 기사 표가 원본보다 뒤처진 소스에만 붙는다 ( `마지막 저장: … (그 뒤로는 다른 행으로 흡수)` ) .
  받기는 받았는데 그 뒤로는 자기 행이 안 남았다는 뜻이고, 신선도 고장이 아니라 흡수 관측이다.
- **후보 건수는 진단 재료다** — 후보가 있으면 "전부 이미 받은 글입니다" 로 적고, 어댑터 힌트는 후보 0건일 때만 붙는다.
  판정이 원본 수집으로 옮겨간 2026-08-20 부터 이 문구가 참이 됐다.
  종전 문구 ( "경로는 응답하나 새 글이 없습니다" ) 는 저장 결과를 보던 신호에서 나온 것이라 흡수당하는 소스에서 거짓이었다 ( `docs/troubleshooting/2026-08-20-live-source-marked-stale-by-watermark.md` ) .
  2026-08-14 개정 전에는 이 계수가 발송 조건이었다 ( 후보가 있으면 알림 자체를 막았다 ).
  그래서 `x_ornstein` 이 13일째 새 글을 못 가져오는데도 알림이 한 번도 안 나갔다 — 경위는 `docs/troubleshooting/2026-08-15-alert-suppression-becomes-silence.md`.
- **재알림은 48시간 고정 간격** — 임계를 넘은 회차에 한 번 알리고, 그 뒤 경과가 48h 씩 늘 때마다 다시 알린다.
  간격이 안 찬 stale 소스는 필드에서 빠지고 조망 줄의 `재알림 대기 N` 으로만 남는다.
  간격은 임계와 독립이다 — 임계의 배수로 두면 임계가 큰 저빈도 소스에서 재알림이 영영 안 온다.
- **임계를 고친 회차는 한 번 몰린다** — 직전 회차 판정을 새 임계로 다시 쓸 수 없어, 그 시점에 stale 인 소스가 전부 한 번씩 알린다.
  `config/sources.yaml` 의 임계를 손댄 배포에서는 이것이 정상이다.
- **그 배포 직후에만 재알림이 48시간보다 빨리 올 수 있다** — 간격을 마지막 알림이 아니라 임계를 넘은 시점부터 세기 때문이다.
  임계를 고쳐 끼어든 첫 알림은 그 눈금에 안 맞으므로, 다음 알림까지가 최소 0시간에서 최대 48시간 사이로 짧아진다.
  2026-08-20 배포 실측 — `x_ornstein` 경과 438h · 임계 120h 라 다음 눈금이 456h 였고 두 번째 알림이 18시간 뒤에 왔다 (그 하루만 소스당 2건 · 이후로는 48시간 간격).
  **도배로 읽지 말 것** — 임계를 손댄 배포에서 한 번만 나오는 모양이다.
- **메타** — `회차` 필드의 run_id 앞 8자로 `pipeline_runs` · `source_freshness` 회차를 특정하고, embed 하단 시각은 검사 시각 (UTC) 이다.
- **제목 클릭** — 이 런북으로 연결된다.
- **무알림** — 모든 소스가 임계 안이거나, 재알림 간격이 아직 안 찼거나, 워터마크 자체가 없는 소스뿐인 경우.
  어느 쪽인지는 매 회차 남는 저널 한 줄로 답한다 ( 발송이 0건이어도 남는다 ) .
  `journalctl -u bullet-in.service --since '-1 day' | grep '신선도 판정'` 으로 `감시 N소스 · stale N · 발송 N · 재알림 대기 N` 과, 대기 중인 소스별 다음 알림까지 남은 시간을 본다.
  워터마크 없음 ( 기사 0건 ) 은 "신규 추가" 와 "처음부터 죽음" 을 구분할 수 없어 알림에서 제외한다 — 이 케이스는 SLO-6 · 에러 로그가 담당.
- **감시 제외 소스 ( `freshness_hours: 0` )** — 판정 루프 자체에서 빠진다.
  stale 이든 아니든 필드에 나타나지 않고, `source_freshness` 이력에도 안 남는다 ( 무알림과 달리 완전히 대상 밖 ) .
  이벤트 구동이라 정상 공백에 상한이 없는 소스에 쓴다 — 유한한 임계는 어떤 값을 골라도 비수기 정상 공백에서 오탐이 재발한다 ( 스펙 `docs/superpowers/specs/2026-08-07-alert-f2-unit-attribution-and-observability-design.md` §1.2 · §3.2 ) .
- **필드 문구는 관측 사실만** — "이번 회차 후보 0건" 처럼 경과만 적고, 원인은 추정하지 않는다.
  2026-08-07 이전에는 "수집 끊김 의심" 을 붙였으나, arsenal_official 이 정상 공백에도 매 회차 발화해 원인 문구를 뺐다.
- **실물 캡처** — 개편 embed: `docs/assets/discord-alert-embed-after.png` · 개편 전: `docs/assets/discord-alert-embed-before.png`.

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

- **「수집은 되는데 다른 행으로 흡수됨」 은 2026-08-20 부터 원인 목록에서 빠졌다.**
  판정이 Mongo `raw_items` 를 보므로 흡수는 더 이상 알림을 만들지 않는다.
  그때까지의 경위는 `docs/troubleshooting/2026-08-20-live-source-marked-stale-by-watermark.md` 에 있다.
- 라이브 검증이 우선이다.
  단위 테스트는 모킹이라 드리프트를 못 잡는다 ( CLAUDE.md "자주 밟는 함정" ).

## 임계 조정 가이드

임계는 `config/sources.yaml` 에서만 조정한다 ( 코드 무수정 ).

- **전역 `freshness_default_hours: 48`** — 새로 붙는 소스가 처음부터 override 를 갖지는 않으므로 기본값으로 유지한다.
  지금은 감시 중인 소스 전부가 아래 override 를 갖고 있어 실제 판정에 쓰이지는 않는다.
- **소스별 `freshness_hours` override** — 소스 항목에 키를 추가하면 그 소스만 임계가 달라진다.
  2026-08-14 실측 ( 21일 · 166회차 ) 의 소스별 공백 95 백분위를 24h 배수로 올려 정했다.

| 소스 | 임계 | 원래 값 | 공백 95% |
|---|---|---|---|
| fmkorea · x_afcstuff · bbc_gossip | 24h | — | 15h · 15h · 21h |
| **bbc_sport** | **72h** | 96h | 75h |
| **skysports** | **96h** | 120h | 99h |
| **guardian** | **120h** | 192h | 168h |
| x_ornstein | 120h | — | 111h |

  `x_ornstein` 이 120h 인 것은 그 계정이 저빈도라서다.
  같은 X 소스라도 `x_afcstuff` 는 집계 계정이라 하루에 여러 건이 올라오고, `x_ornstein` 은 본인 계정에 `#AFC` 필터가 걸려 21일에 5건이었다.
  종전에는 둘 다 "X 는 고빈도" 라는 이유로 24h 였고, 그래서 `x_ornstein` 은 정상 동작 중에도 112회 중 103회가 stale 이었다.
- **굵은 세 줄은 이적 시장 마감 전 임시값이다** ( 2026-08-20 · 원본 수집 기준 재측정 ) .
  **2026-09-02 마감 뒤 「원래 값」 열로 되돌린다** — 안건 ι · 임계계절성이고, 절차는 `docs/runbook/2026-08-20-freshness-threshold-recalibration.md` 가 정본이다.
  되돌릴 자리는 셋이다 — `config/sources.yaml` 세 줄 · `tests/test_freshness_config.py` 의 계약 표 · 이 표.
  마감이 다가올수록 기사가 늘어 공백이 짧아지므로, 이 값들을 마감 뒤에 그대로 두면 정상 침묵에서 울린다.
- 고른 기준은 **「최근 14일 알림이 소스당 1건 이하가 되는 가장 작은 임계」** 다.
  마감 전 임시값에서 실제로 `bbc_sport` 1건 · `skysports` 1건 · `guardian` 0건이 나왔다.
- **`x_ornstein` 은 이번에 안 건드렸다** — 원본 기준 공백 p95 가 186h 로 현행 120h 보다 크다 ( 데이터는 좁히지 말고 넓히라고 한다 ) .
  신호 교체 효과와 섞이므로 안건 ι 에서 함께 본다.
- **`freshness_hours: 0` = 감시 제외** — 좁히는 override 와 달리 판정 자체를 끈다.
  적용 사례: `arsenal_official` — 1군 이적 · 계약 공식 발표에만 반응하는 이벤트 구동 소스라, 채택 0 이 며칠이고 이어져도 정상일 수 있다.
  대신 채택 필터가 실제 발표를 놓쳤는지는 `docs/runbook/2026-07-13-collection-alerts-ops.md` 의 채택 누락 관측 알림이 담당한다.
- **재측정 절차** — 아래 쿼리로 소스별 stale 비율을 보고, 한 소스라도 20% 를 넘으면 그 소스의 임계를 다시 잰다.
  정상 소스가 회차의 5분의 1에서 경고를 켜면 그것은 경고가 아니라 소음이고, 결국 알림 전체를 못 믿게 만든다.

```sql
SELECT source_id,
       COUNT(*) AS checks,
       ROUND(MAX(age_hours), 1) AS max_age,
       SUM(stale) AS stale_n
FROM source_freshness
WHERE checked_at >= NOW() - INTERVAL 30 DAY
GROUP BY source_id ORDER BY stale_n DESC;
```

- **오프시즌** — 이적 뉴스 소스는 시즌 중 대비 확연히 뜸해진다.
  위 임계는 이적 시장이 열린 21일치로 잰 값이라, 시장이 닫히면 좁게 느껴질 수 있다.
  그때는 전역을 올리기보다 뜸해진 소스만 다시 재서 override 를 늘린다.

## 검증

webhook · DB 없이도 판정 · 포맷 로직을 확인할 수 있다.

```bash
uv run pytest tests/test_quality.py -v                       # evaluate_freshness 경계 · override · NULL
uv run pytest tests/test_notify.py -v                        # build_freshness_alert 포맷
uv run pytest tests/integration/test_source_freshness.py -v  # 테이블 적재 (MariaDB 필요 · 없으면 skip)
```

- **실발송 스모크** — Discord 수락 · 렌더링 확인 절차는 `docs/runbook/2026-07-13-collection-alerts-ops.md` 의 "실발송 스모크" 절 참조 (신선도 샘플 포함).

## 실패 모드

- **알림 실패 무해** — `send_alert` 가 모든 예외를 삼켜 파이프라인을 죽이지 않는다 ( `docs/troubleshooting/2026-07-13-alert-exception-swallow-gap.md` ).
- **워터마크 없음 무알림** — 기사 0건 소스는 행만 남고 조용하다.
  신규 소스를 붙였는데 며칠째 `last_fetched_at` 이 NULL 이면 어댑터 자체가 죽은 것 — SLO-6 드롭 알림 · 에러 로그를 본다.
- **UTC 시계 기준** — 워터마크 (`fetched_at`) 는 어댑터가 UTC 로 저장하고, `now` 도 DB `UTC_TIMESTAMP()` 로 받는다.
  양쪽 시계가 UTC 로 고정되어 앱 · DB 컨테이너의 TZ 설정과 무관하게 판정이 흔들리지 않는다.

## 롤백

- 임계만 되돌리려면 `config/sources.yaml` 의 `freshness_hours` 를 원래 값으로 되돌린다 ( 코드 무수정 ) .
- 재알림 간격을 되돌리려면 `quality.py` 의 `FRESHNESS_REALERT_HOURS` 를 늘린다.
  값을 키우면 첫 알림만 남고 반복이 사실상 멎는다.
- 기능 제거는 `git revert` 로 충분하다.
  `source_freshness` 는 append 전용 이력이라 남아 있어도 무해하고, 테이블 자체도 `CREATE TABLE IF NOT EXISTS` 라 재적용 충돌이 없다.
- 알림만 임시로 끄려면 `DISCORD_WEBHOOK_URL` 을 해제한다 ( WARNING 로깅 폴백 ).
  감시 · 이력 적재는 계속 돈다.

## 참고

- spec · plan: `docs/superpowers/{specs,plans}/2026-07-13-slo5-freshness-watermark*`.
- 감시 제외 규약 · 문구 정비: `docs/superpowers/specs/2026-08-07-alert-f2-unit-attribution-and-observability-design.md` §3.2.
- 살아 있는 소스가 stale 로 찍히는 경위 · 원본 대조 절차: `docs/troubleshooting/2026-08-20-live-source-marked-stale-by-watermark.md`.
- 임계 재조정 · 억제 제거 · 재알림 간격의 설계 근거: `docs/superpowers/specs/2026-08-14-slo5-freshness-alert-blind-spot-design.md`.
- 함정: `docs/troubleshooting/2026-07-13-freshness-clock-mixing-gap.md` (시계 혼합 · UTC 고정 경위) ·
  `docs/troubleshooting/2026-08-07-arsenal-official-transfer-tag-omission.md` (arsenal_official 감시 제외 경위) .
- SLO-6 알림 운영: `docs/runbook/2026-07-13-collection-alerts-ops.md`.
- 로드맵: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` ( Tier 3 · SLO-5 ).
