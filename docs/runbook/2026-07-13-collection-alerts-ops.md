# 수집 이상 알림 운영 (2026-07-13)

## 목적

파이프라인이 깨졌을 때 Discord 로 통지하는 SLO-6 알림 (PR #34) 의 설정 · 해석 · 튜닝 · 롤백을 정리.

- 두 알림 경로 — 하드 실패 (파이프라인 예외 crash → Airflow `on_failure_callback`) · 소프트 드리프트 (실행은 성공했으나 한 소스가 조용히 0건 = 셀렉터 드리프트 → 소스별 수집량 이상탐지) .
- 공유 배관 — `src/bullet_in/notify.py` 의 `send_alert` 가 Discord embed 를 발송.

## Discord webhook 설정

알림은 급한 정도에 따라 세 채널로 갈라져 나간다 ( 스펙 `docs/superpowers/specs/2026-08-14-slo5-freshness-alert-blind-spot-design.md` §7 ).
채널별 변수가 없으면 종전처럼 `DISCORD_WEBHOOK_URL` 하나로 모인다.

| 채널 | 환경변수 | 실리는 알림 | 받는 사람이 할 일 |
| --- | --- | --- | --- |
| 장애 | `DISCORD_WEBHOOK_INCIDENT` | 파이프라인 실패 · 수집 0건 ( 절벽 ) · 선수 검색 배치 전멸 | 원인을 좁히고 고친다 |
| 관측 | `DISCORD_WEBHOOK_REVIEW` | 링크 선수 후보 등재 · 명단 이적 상태 낡음 · 공홈 채택 누락 | 확정 CLI · 명단 런북으로 결정한다 |
| 경향 | `DISCORD_WEBHOOK_TREND` | 수집량 이상 · 신선도 · 공홈 커버리지 | 당장 할 일이 없을 때가 많다 |

- **webhook URL 발급** — Discord 서버 → 서버 설정 → 연동 (Integrations) → 웹후크 → 새 웹후크 → 채널 선택 → 웹후크 URL 복사.
  채널을 셋으로 쓰려면 채널마다 한 번씩 발급한다.
- **셋 중 없는 것은 기존 웹훅으로 떨어진다** — 세 변수를 하나도 안 넣고 배포해도 알림이 사라지지 않는다.
  그래서 코드 배포와 웹훅 설정은 순서를 가리지 않는다.
  변수를 나중에 채우면 그 채널부터 갈라져 나간다 ( 재배포 불요 · 프로세스 재시작만 필요 ).
- **주입** — 이 프로젝트는 dotenv 미사용이므로 셸 export 로 넣는다.
  `.env` 에 `DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...` 를 추가하고 `set -a; source .env; set +a` 후 실행.
  채널 변수도 같은 자리에 같은 형식으로 넣는다.
- **갈렸는지 판정하는 법** — 「알림이 왔다」 가 아니라 「어느 채널로 왔다」 로 본다.
  변수를 잘못 넣으면 발송은 성공하고 채널만 기존 하나로 모이므로 로그로는 구분이 안 된다.
- **Airflow 환경** — DAG 워커 프로세스에도 같은 변수가 보여야 한다 (컨테이너 env · Airflow Variable → env 매핑 등 배포 방식에 맞춤) .
- **미설정 동작** — 변수가 없으면 발송하지 않고 `WARNING` 으로 제목 · 설명을 로깅한다 (폴백) .
  dev · CI 는 이 폴백으로 도므로 webhook 없이도 테스트가 깨지지 않는다.
- **저널에서는 주소가 가려진다** — httpx 요청 로그에 `api/webhooks/[REDACTED]` 로 남는다 (#220) .
  웹훅 주소는 그 자체가 인증 수단이라 저널 읽기 권한이 곧 발송 권한이 되는 것을 막는다.
  `httpx` 로거 전체를 올리지 않고 필터로 주소만 치환하므로 나머지 요청 로그 (수집 진단 근거) 는 그대로 남는다.

## 알림 해석

두 종류의 embed 가 온다.

- **⚠️ 수집량 이상 (주황)** — 소프트 드리프트.
  실행은 성공했으나 소스별 수집량이 지난 이력 대비 2σ 밖.
  `▼` 는 드롭 ( 평소보다 급감 ) · `▲` 는 스파이크 ( 급증 ) 다.
  한 소스만 걸리면 제목이 그 소스 이름과 숫자를 싣는다 ( `⚠️ 수집량 드롭 — fmkorea 축구 소식통 0건 (평소 ~14)` ) .
  여럿이면 첫 소스 이름과 나머지 계수를 싣는다.
  제목 클릭은 이 런북으로 연결된다.
- **「수집량」 이 무엇을 센 값인지 description 에 적혀 있다** — 중복 · 필터를 지나 이번 회차에 새로 담은 글 수다.
  검색 · 목록에서 찾은 글 수 ( 후보 ) 가 아니다.
- **소스당 필드** — `▼ 0건 (평소 ~14)` · 최근 5회 → (오늘) 시퀀스 · 후보 대비 적재 한 줄 ( `이번 회차 후보 33건 중 새로 담은 글 30건` ) .
  `회차` 필드의 run_id 앞 8자로 회차를 특정한다.
- **어댑터 힌트는 드롭이면서 후보가 0건일 때만 붙는다** — 후보가 있는데 적재만 줄었다면 발견은 도는 것이므로 셀렉터 드리프트 힌트에 근거가 없다.
  스파이크에는 원인 후보를 아예 안 붙인다.
  종전의 「중복 유입 · 파싱 회귀 의심」 은 관측이 아니라 추측이었다 — 같은 함정으로 SLO-5 를 두 번 고쳤다 ( #169 · #174 ) .
- **❌ 파이프라인 실패 (빨강)** — 하드 실패.
  `run_pipeline` 태스크가 예외로 중단.
  fields 의 `로그` 링크 · `Try` · `Host` 로 Airflow 태스크를 특정하고, description 의 예외 요약 (최대 400자) 으로 원인을 좁힌다.
- **🚨 수집 0건 (빨강)** — 직전 회차까지 글을 가져오던 소스가 이번 회차에 한 건도 못 가져옴.
  회차 자체는 성공으로 끝나므로 실패 알림이 따로 오지 않는다.
  제목에 소스 이름이 오고, 어댑터가 실패 계수를 내놓으면 `— 검색 4건이 전부 실패했습니다` 가 붙는다.
- **소스당 필드가 네 구획으로 나뉜다** — 무슨 일이 있었나 · 평소와 비교 · 지금 어떤 상태인가 · 무엇을 하나.
  앞 둘은 관측이고 뒤 둘은 판단 재료다.
- **「무슨 일이 있었나」** — 설정에 적힌 검색 키워드를 알림이 직접 싣는다 ( 실패 계수와 키워드 수가 같으면 「전부 실패」 로 적는다 ) .
  서버 응답 코드가 뒤따르고 430 이면 `(자동 수집 차단 응답)` 이 붙는다.
  키워드도 응답 코드도 없는 어댑터는 이 구획이 통째로 빠진다.
- **「평소와 비교」 의 숫자는 「찾은 글」 이다** — 중복을 포함한 발견 결과 수이고 저장된 글 수가 아니다.
  이 정의가 알림 안에 한 줄로 들어 있다.
- **「지금 어떤 상태인가」** — `회차는 실패로 끝나지 않았습니다 (success_rate 1) — 어댑터가 예외를 던지지 않아 실패 알림이 따로 가지 않았습니다`.
  「정상 종료」 라고 안 쓰는 이유는 아래 대응 절에 있다.
- **원인은 여전히 적지 않는다** — 후보 0 이 차단인지 셀렉터 드리프트인지는 알림 시점에 알 수 없다.
  응답 코드는 서버가 준 사실이라 적고 어댑터 힌트는 안 붙인다.
- **🚨 fmkorea 선수 검색 실패 (빨강)** — 이적설 선수 명단을 이름으로 검색하는 배치에서 그 차례 전원이 실패.
  새로 가져온 글이 0건이고 검색 순서가 전진하지 않아 다음 차례에 같은 선수들을 다시 시도한다.
  사람이 되돌릴 것은 없다.
- **🔍 공홈 이적 관련 기사 미수집 (주황)** — 관측 전용 알림 (스펙 2026-08-07 §3.3).
  arsenal_official 창 후보 중 `Men` · `News` 는 있는데 이적 태그 (`Transfer news` · `Contract news`) 가 없어 비채택된 기사 가운데,
  제목이 이적성 표현 (`joins` · `signs` · `transfer` · `loan`) 이고 발행이 6시간 이내인 것만 추려서 온다.
  기사별 필드에 태그 · 발행 시각 · 링크만 실리고, 채택 여부 판단은 담지 않는다.
  제목 클릭은 이 런북으로 연결된다.
- **실물 캡처** — 개편 수집량 embed: `docs/assets/discord-alert-embed-after.png` · 개편 전: `docs/assets/discord-alert-embed-before.png`.

## 대응

- **▼ 드롭 알림** — 해당 소스를 라이브 재검증한다.
  대개 셀렉터 · feed_url 드리프트다 (`config/sources.yaml`) .
  어댑터 단독 `fetch()` 로 확인 (단위 테스트는 모킹이라 못 잡음) — `docs/troubleshooting/2026-06-12-live-source-selector-drift.md` 참조.
- **▲ 스파이크 알림** — 원문 중복 · 페이지 구조 변화 여부를 확인. 대개 무해하나 dedup · 파싱 회귀 신호일 수 있다.
- **❌ 실패 알림** — `로그` 링크로 스택트레이스 확인.
  흔한 원인 = Mongo · MariaDB 연결 실패 · Gemini 인증 · 미처리 예외.
- **🚨 수집 0건 — fmkorea** — 응답 코드가 430 이면 자동 수집 차단이다.
  대개 한 회차 (3시간) 안에 풀리므로 즉시 조치가 필요하지 않다.
  풀렸는지 확인할 때도 직접 접촉하지 말고 다음 회차 로그를 본다 (`docs/troubleshooting/2026-08-03-fmkorea-430-not-explained-by-our-requests.md`) .
- **🚨 수집 0건 — 그 외 소스** — 응답 코드 줄이 없으면 어댑터 단독 `fetch()` 로 라이브 재검증한다.
  대개 셀렉터 · feed_url 드리프트다.
- **🚨 선수 검색 실패 알림** — 같은 선수들을 다음 차례가 재시도하므로 한 번은 지켜본다.
  연속으로 오면 fmkorea 접촉 경로 (터널 · 프록시) 를 확인한다.
- **🔍 채택 누락 알림** — 링크를 열어 기사가 실제 1군 이적 · 계약 공식 발표인지 먼저 확인한다.
  맞다고 판단해도 이 알림이 수집 여부를 대신 정하지 않는다 — 현재 채택 기준 (Men + 이적 태그) 을 그대로 둘지,
  `Club` 태그 이적 정리 기사까지 받을지는 제품 판단이다.
  놓친 기사를 소급 수집할지는 `backfill_arsenal.py` 검토가 선행돼야 한다.
  실측 사례 · 원인은 `docs/troubleshooting/2026-08-07-arsenal-official-transfer-tag-omission.md` 참조.

### 알림에 적힌 fmkorea 접촉 시각을 확인할 때

접촉 경로가 셋이라 VM 저널만 보면 하나가 통째로 빠진다.

- **정기 회차** (`bullet-in.service`) · **선수 검색 배치** (`bullet-in-watchlist.service`) — `journalctl` 에 남는다.
- **보충 수집** (`collect_fmkorea`) — Mac launchd (`com.bulletin.fmkorea-supplement`) 가 15분마다 ssh 로 실행한다.
  systemd 유닛이 아니라 **저널에 남지 않고** Mac 의 `/tmp/fmkorea-supplement.err` 에만 쌓인다.
  3시간 접촉 가드가 걸려 있어 실제 접촉은 훨씬 드물다.
- 세 경로가 접촉 스탬프 `~/.bullet-in/fmkorea_last_contact` (naive UTC) 를 공유한다.
  값만 보고 어느 경로가 썼는지는 알 수 없다.
- 배치가 매번 남기는 `fmkorea 접촉 기준 (UTC) — 스탬프 ... · 워터마크 ... · 채택 ...` 로 판정 입력을 되짚는다.
  이 값은 알림 표기뿐 아니라 배치를 돌릴지 정하는 60분 가드의 입력이다.
- 저널만 보고 "그 시각엔 접촉이 없었다" 고 단정해 코드 결함으로 오진한 사례가 있다
  — `docs/troubleshooting/2026-08-04-fmkorea-contact-paths-invisible-in-journal.md`.

## 튜닝 노브

임계값은 경험적이며 코드 상수로만 조정한다 (`src/bullet_in/quality.py` · `src/bullet_in/run.py`) .

- **`min_baseline` (기본 3.0)** — history 평균이 이 미만인 저volume 소스는 평가에서 제외 (오탐 억제) .
  뜸한 소스에서 오탐이 잦으면 올린다.
- **`sigma` (기본 2.0)** — 이상 판정 밴드 폭.
  오탐이 많으면 올리고 (둔감) , 미탐이면 내린다 (민감) .
- **history 윈도우 (기본 12 회, run.py 의 `LIMIT 12`)** — 이상 판정에 쓰는 과거 회차 수 (약 3 일) .
  파이프라인은 6 시간마다 4 회/일 도므로 12 회 ≈ 3 일 평균.
- **시간대 계절성 주의** — 12 회 윈도우는 하루 4 슬롯을 뭉갠 평균이라, 밤 시간대에 뜸한 소스가 소폭 오탐할 수 있다.
  주 신호 ("평소 >0 인데 0") 는 시간대와 무관하게 강건하므로 현재는 단순 윈도우를 쓴다.
  오탐이 실제로 관찰되면 동일 시각 (HOUR) 비교로 개선한다 (2 주 이상 이력 필요) .
- **수집 0건 판정 (`quality.candidate_cliffs`)** — 임계가 없다.
  직전 회차에 후보가 1건 이상이었는데 이번에 0 이면 발화한다.
  상태가 아니라 전이를 보므로 후보가 끊긴 지 오래인 소스는 발화하지 않는다.
  연속 차단도 두 번째 회차부터는 직전이 0 이라 조용하다.
- **수집 0건 이력 윈도우 (`run.py` 의 `CANDIDATE_HISTORY_SQL` · `LIMIT 5`)** — 판정에는 첫 행만 쓴다.
  나머지 4행은 알림 본문의 최근 추이 표시용이라 늘리거나 줄여도 판정이 바뀌지 않는다.
- **선수 검색 실패 조건 (`watchlist_fmkorea.main`)** — 검색 실패 수가 그 차례 인원과 같을 때만 발화.
  부분 실패에도 알리려면 이 등호를 비율 비교로 바꾼다.

## 검증

webhook 없이도 발송 로직을 확인할 수 있다.

```bash
uv run pytest tests/test_notify.py -v          # 발송 · 폴백 · 예외 삼킴 · 포맷 빌더
uv run pytest tests/test_quality.py -v          # 소스별 이상탐지 (volume_anomalies)
```

DAG 콜백 배선은 airflow 미설치 환경에서 다음으로 구조 검증한다 (`test_dag_import` 는 skip) .

```bash
uv run python -m py_compile airflow/dags/bullet_in_daily.py         # DAG 구문
uv run python -c "from bullet_in import notify; assert callable(notify.build_failure_alert)"   # 앱 계약
```

- **참고** — 로컬 `airflow/` 디렉터리가 pip `airflow` 패키지명을 가려, airflow 미설치 시 `test_dag_import` 는 `importorskip("airflow.models")` 로 skip 된다.
  전체 DAG 로드 검증은 airflow 가 설치된 환경 (Docker `apache/airflow:3.0.0`) 에서 DagBag 으로 확인.

### 실발송 스모크

단위 테스트는 httpx 를 모킹하므로 "Discord 가 payload 를 수락하고 의도대로 렌더링하는가" 는 실발송으로만 확인된다.
알림 포맷을 바꿨거나 webhook 을 새로 발급했으면 아래로 채널마다 한 건씩 실발송한다.

```bash
set -a; source .env; set +a        # 기본 웹훅 + 채널 셋 주입
uv run python - <<'EOF'
import logging
logging.basicConfig(level=logging.WARNING)   # 실패 시 WARNING · 무음이면 2xx 수락
from datetime import datetime, timedelta, timezone
from bullet_in import notify
from bullet_in.quality import SourceFreshness, Anomaly
from bullet_in.score import load_sources

now = datetime.now(timezone.utc).replace(tzinfo=None)
sources = load_sources("config/sources.yaml")   # 검색 키워드 · 표시 이름을 설정에서 그대로

# 장애 채널 — 수집 0건 (fmkorea 검색 전멸 모양)
notify.send_alert(**notify.build_cliff_alert(
    ["fmkorea"], history=[{"fmkorea": 12}] * 4, sources=sources,
    failure_codes={"fmkorea": {430: 4}}, success_rate=1.0, run_id="smoke-test-0000"))

# 관측 채널 — 링크 선수 후보 등재
notify.send_alert(**notify.build_candidate_alert(
    [{"ko": "스모크", "full_name": "Smoke Test", "stage": "rumour",
      "title": "실발송 스모크"}], run_id="smoke-test-0000"))

# 경향 채널 — 신선도 · 수집량
records = [SourceFreshness("x_ornstein", now - timedelta(hours=291), 120.0, 291.0, True)]
notify.send_alert(**notify.build_freshness_alert(
    records, 48, targets=records, sources=sources, run_id="smoke-test-0000",
    checked_at=now, candidates={"x_ornstein": 5}))
hist = [{"fmkorea": 14}, {"fmkorea": 13}, {"fmkorea": 15}, {"fmkorea": 12}]
notify.send_alert(**notify.build_anomaly_alert(
    [Anomaly("fmkorea", 0, 14.0, "drop")], 12, hist=hist, sources=sources,
    run_id="smoke-test-0000", candidates={}))
EOF
```

- **판독** — WARNING 없이 끝나면 Discord 2xx 수락 · 채널에서 불릿 · 상대시간 · 시퀀스 렌더링을 눈으로 확인.
- **채널 판정** — 네 건이 **어느 채널에 떨어졌는지**로 본다 ( 장애 1 · 관측 1 · 경향 2 ) .
  넷이 한 채널에 모였으면 채널 변수가 안 주입된 것이다.
  코드가 아니라 `.env` · 프로세스 환경을 본다.
  발송 성공만으로는 갈렸는지 알 수 없다 — 폴백이 조용히 받아 주기 때문이다.
- **캡처 갱신** — embed 형식을 바꾼 변경이면 `docs/assets/discord-alert-embed-after.png` 를 새 캡처로 교체해 문서와 실물을 맞춘다.
- **함정** — webhook 미설정이면 알림 기능 전체가 WARNING 폴백으로만 돌아 "코드는 정상 · 도달은 0" 상태가 된다.
  SLO-6 머지 후 이 상태가 한동안 지속된 적 있음 — 알림 기능 배포 시 실발송 스모크를 필수 체크로.

## 실패 모드

- **webhook 오설정 · 만료** — `send_alert` 가 모든 예외를 삼켜 파이프라인을 죽이지 않는다 (미설정과 동일하게 WARNING 만) .
  좁은 except 로 인한 파이프라인 crash 함정은 `docs/troubleshooting/2026-07-13-alert-exception-swallow-gap.md` 참조.
- **알림 폭주** — 여러 소스가 동시에 드리프트하면 한 회차에 소스당 필드로 한 embed 에 묶여 온다 (소스당 별도 메시지 아님) .
- **초기 데이터 부족** — 파이프라인 초기엔 소스별 history 가 2 회 미만이라 이상탐지가 무발화한다 (안전한 무알림) .

## 롤백

- 알림 기능은 신규 테이블 · 컬럼 · 마이그레이션이 없다 (기존 `pipeline_runs.source_counts` 읽기만) .
- `git revert` 로 롤백 가능하며 데이터 영향이 없다.
- **채널 분리만 되돌리려면 세 채널 변수를 지운다** — 코드를 안 고쳐도 기존 웹훅 하나로 다시 모인다.
- 임시로 끄려면 웹훅 변수를 **넷 다** 해제한다 (코드 변경 없이 WARNING 폴백으로 전환) .
  기본 변수만 지우고 채널 변수를 남기면 그 채널로는 계속 나간다.

## 참고

- PR #34 · spec/plan `docs/superpowers/{specs,plans}/2026-07-13-slo6-collection-alerts*`.
- 채택 누락 관측 알림: `docs/superpowers/specs/2026-08-07-alert-f2-unit-attribution-and-observability-design.md` §3.3.
- 함정: `docs/troubleshooting/2026-07-13-alert-exception-swallow-gap.md` (예외 삼킴) · `docs/troubleshooting/2026-07-13-sparse-source-counts-trend-bias.md` (희소 표현 추세 왜곡) ·
  `docs/troubleshooting/2026-08-07-arsenal-official-transfer-tag-omission.md` (채택 필터 태그 누락) .
- 로드맵: `docs/superpowers/2026-06-28-v1-completion-roadmap.md` (Tier 3 · SLO-6) .
