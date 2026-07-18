# SLO 실측 런북 — 중복 적재율 · 성공률 · 완전성 · 이상 감지 (2026-07-19)

README §4 SLO 표의 실측 4칸 (SLO-1 병렬화 제외 전부) 을 채운 측정 절차와 실행 로그.
"실측값만 기입 · 추정 금지" 원칙의 증빙이자, 향후 재측정 시 같은 명령을 재사용하기 위한 문서다.
SLO-1 (병렬화 시간 단축) 은 별도 런북 (`2026-07-14-slo1-benchmark.md`) 을 따른다.

## 1. 측정 창 — 지표별 자연 창

지표마다 의미에 맞는 근거 범위가 달라 단일 창을 강제하지 않는다.

| 지표 | 자연 창 | 이유 |
|---|---|---|
| 중복 적재율 | 현재 mart 전체 스냅샷 | 중복은 회차가 아니라 저장소 상태의 속성 |
| 일일 수집 성공률 | `pipeline_runs` 전 이력 평균 | 회차 단위 지표 — 이력 전체가 모집단 |
| 필수 필드 완전성 | 현재 mart 전체 스냅샷 | 행 단위 품질 — 저장소 상태의 속성 |
| 수집량 이상 감지 | 가동 실적 | 비율이 아닌 감시 지표 — 가동 여부 + 실발송 검증이 실측 |

측정은 신규 회차 실행 직후에 한다
— 성공률 · 이상 감지에 최신 회차가 포함되고, 캡처와 같은 상태를 가리키게 하기 위함.

## 2. 측정 명령

### 2.1. dbt 게이트 (중복 · 완전성의 선언적 근거)

```bash
set -a; source .env; set +a
cd dbt && uv run dbt build --profiles-dir . && cd ..
```

`unique` (content_hash · url) · `not_null` (content_hash · url · title_original) 이 전부 PASS 여야 한다.

### 2.2. SQL 실측 (교차 확인 · 비율 산출)

dbt test 는 이진 판정이라 비율은 SQL 로 직접 계산한다.

```bash
uv run python - <<'EOF'
import os
from sqlalchemy import create_engine, text
eng = create_engine(os.environ["MARIADB_URL"])
with eng.connect() as c:
    total = c.execute(text("SELECT COUNT(*) FROM articles")).scalar()
    dup_hash = c.execute(text(
        "SELECT COUNT(*) FROM (SELECT content_hash FROM articles "
        "GROUP BY content_hash HAVING COUNT(*) > 1) d")).scalar()
    dup_url = c.execute(text(
        "SELECT COUNT(*) FROM (SELECT url FROM articles "
        "GROUP BY url HAVING COUNT(*) > 1) d")).scalar()
    incomplete = c.execute(text(
        "SELECT COUNT(*) FROM articles WHERE content_hash IS NULL "
        "OR url IS NULL OR title_original IS NULL")).scalar()
    n_runs, avg_sr = c.execute(text(
        "SELECT COUNT(*), AVG(success_rate) FROM pipeline_runs")).one()
print(f"mart 전체        : {total}건")
print(f"중복 (hash/url)  : {dup_hash}/{dup_url} → 중복 적재율 {(dup_hash + dup_url) / total * 100:.1f}%")
print(f"필수 필드 위반   : {incomplete}건 → 완전성 {(total - incomplete) / total * 100:.2f}%")
print(f"성공률           : {n_runs}회 평균 {avg_sr * 100:.2f}%")
EOF
```

## 3. 2026-07-19 실행 로그

측정 직전 종단 회차 1회 실행 (신규 52 · dup 64 · 에러 0 · success_rate 1.0 · fetch 64.5s).
Gemini 파싱 실패 8건은 enrich 전용 재시도 패스 (fetch 없음 — fmkorea 2h 규칙 무접촉) 로 잔존 0 수렴 후 측정.

dbt:

```
Done. PASS=16 WARN=0 ERROR=0 SKIP=0 NO-OP=0 TOTAL=16
```

SQL:

```
mart 전체        : 358건
중복 (hash/url)  : 0/0 → 중복 적재율 0.0%
필수 필드 위반   : 0건 → 완전성 100.00%
성공률           : 17회 평균 99.26%
```

## 4. 판독 기준

- **중복 적재율**: dbt `unique` PASS 와 SQL 중복 그룹 0행이 일치해야 0% 로 기입한다.
  둘이 어긋나면 dbt 소스 연결 (DuckDB attach) 이 옛 스냅샷을 보는지 먼저 의심한다.
- **완전성**: 대상 컬럼은 dbt `not_null` 과 같은 집합 (content_hash · url · title_original) 으로 고정한다
  — 집합을 넓히면 회차 간 비교가 깨진다.
- **성공률**: `AVG(success_rate)` 는 회차 평균이다.
  초기 부트스트랩 회차 (셀렉터 드리프트 등) 가 포함된 값이므로, 목표 미달 시 최근 N회 창을 병기해 판단한다.
- **이상 감지**: 수치가 아닌 가동 실적으로 서술한다 (`가동 (실발송 검증 YYYY-MM-DD)`).
  근거 = SLO-6 상시 감시 (run.py 연결) + Discord 실발송 검증 (2026-07-13, `2026-07-13-collection-alerts-ops.md` §실발송 스모크).

## 5. 재측정 절차

1. 종단 회차 1회 실행 (fmkorea 2h 규칙 확인 후).
2. 미번역 잔존 확인 — 잔존이 있으면 enrich 전용 패스로 수렴시킨 뒤 측정 (§3 선례).
3. §2 명령 실행 → README §4 실측 컬럼 갱신 (값 + 날짜 + 방법).
4. 목표 미달 값은 그대로 기입하고 각주로 사유를 단다
— 목표 재조정은 사용자 확인 후에만 (SLO-1 의 ≥ 55% 재조정 선례).
