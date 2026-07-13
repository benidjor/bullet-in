# 신선도 판정의 시계 혼합 함정 — naive DATETIME 과 `SELECT NOW()` (2026-07-13)

## 배경

SLO-5 신선도 감시 (PR #36) 는 소스별 `age = now − MAX(fetched_at)` 이 임계를 초과하면 stale 로 판정한다.
스펙 §4.1 은 `now` 를 DB `SELECT NOW()` 로 받아 "TZ · 시계 불일치 제거" 를 의도했고, 최초 구현도 스펙 문언대로 `NOW()` 를 썼다.
단위 · 통합 테스트를 전부 통과했으나, 최종 whole-branch 리뷰에서 잠재 왜곡이 드러났다.

## 증상 (잠재 — 현 배포에서는 미발현)

DB 컨테이너 · 세션 TZ 가 UTC 가 아니게 되는 순간, 모든 소스의 `age_hours` 가 그 오프셋만큼 일괄 왜곡된다.

- 예: DB TZ 를 Asia/Seoul 로 바꾸면 모든 age 가 +9h → 전 소스 동시 오탐 (신선도 경고 폭주) 가능.
- 현 배포 (`mariadb:11` 컨테이너, 시스템 TZ UTC) 에서는 `NOW() == UTC_TIMESTAMP()` 라 발현하지 않았다 — 그래서 테스트로도 안 잡혔다.

## 원인 — 두 시계의 출처가 다른데 naive 로 섞임

`age` 의 두 항이 서로 다른 시계에서 왔다.

- **워터마크 측** — `fetched_at` 은 어댑터가 `datetime.now(timezone.utc)` 로 만든 **앱 UTC** 시각이고, DATETIME 컬럼에 naive 로 저장된다.
- **now 측** — `SELECT NOW()` 는 **DB 세션 TZ** 의 현재 시각이다.
- naive 끼리 빼면 값 차이에 "시각 경과" 와 "시계 오프셋" 이 섞여 들어간다.
- 스펙의 "DB 시계로 통일" 문언은 워터마크도 DB 가 만든다는 가정이었으나, 실제로는 앱이 만들고 DB 는 저장만 한다 — 절반은 스펙 서술의 문제.

## 해결 — 양쪽 시계를 UTC 로 고정

`MartStore.db_now()` 를 `SELECT UTC_TIMESTAMP()` 로 바꿔 now 측을 세션 TZ 와 무관하게 UTC 로 고정했다 (PR #36 최종 리뷰 fix).

```python
    def db_now(self) -> datetime:
        """UTC 기준 DB 시각. fetched_at (어댑터가 UTC 저장) 과 같은 시계로 비교."""
        with self.engine.connect() as c:
            return c.execute(text("SELECT UTC_TIMESTAMP()")).scalar_one()
```

- **회귀 고정** — `tests/integration/test_source_freshness.py::test_db_now_returns_utc_datetime` 이 반환값을 UTC 현재 시각 ±300초로 단언한다.
  DB 세션 TZ 가 비 UTC 로 바뀌면 (오프셋 ≥ 1h) 이 테스트가 즉시 실패해 계약 위반을 알린다.
- **문서 정합** — 런북의 "DB 시계 기준 · 컨테이너 TZ 무관" 주장을 "양쪽 시계가 UTC 로 고정" 이라는 정확한 근거로 교체했다.

## 예방 — naive 시각 비교는 시계 출처를 계약으로 고정

- naive DATETIME 두 값을 비교할 때는 **양쪽 값의 시계 출처** 를 코드에서 명시적으로 통일한다 (여기서는 양쪽 UTC).
  한쪽이 앱 · 한쪽이 DB 라면 "지금은 우연히 같은 TZ" 가 기본 상태다.
- "이 값은 UTC 다" 는 주석이 아니라 **계약 테스트** 로 고정한다 (±허용오차 단언) — 환경 설정 변경이 테스트 실패로 드러나게.
- 스펙의 메커니즘 서술 ( `SELECT NOW()` ) 보다 의도 ( "시계 불일치 제거" ) 를 우선한다.
  문언 준수가 의도를 깨면 그건 스펙 버그다.

## 참고

- PR #36 (§2.4 의사결정) · spec: `docs/superpowers/specs/2026-07-13-slo5-freshness-watermark-design.md` §4.1.
- 운영: `docs/runbook/2026-07-13-freshness-watermark-ops.md` (실패 모드 "UTC 시계 기준").
