# 런북 — dbt 품질 게이트 실행

dbt(DuckDB)가 MariaDB를 attach해 분석 마트를 만들고, 데이터 테스트를 **품질 게이트**로 돌린다. 이 게이트가 파이프라인의 "이상 점검"을 선언적으로 수행한다.

## 동작 개요
- DuckDB가 `mysql_scanner` 확장으로 MariaDB의 `bulletin` DB를 `maria`라는 별칭으로 attach.
- `stg_articles`(스테이징) → `daily_source_quality`(소스별 품질 집계) 모델 빌드.
- 데이터 테스트가 곧 게이트:
  - `unique`(content_hash, url) → **중복 적재 0** 검증
  - `not_null`(content_hash, url, title_original) → **필수 필드 완전성**
  - `accepted_values`(tier ∈ {0,1,1.5,2,3,4}) → **스키마 무결성**

`dbt docs generate`로 본 `daily_source_quality` 마트(컬럼·타입·의존성):

![dbt docs — daily_source_quality 모델](../assets/dbt-lineage.png)

## 사전조건 (중요 — 빠지면 빌드 실패)
1. MariaDB 컨테이너 기동: `docker compose up -d mariadb`.
2. **`bulletin` DB에 스키마가 적용돼 있어야 한다.** attach가 `maria.articles`를 읽는데, 테이블이 없으면 `Catalog Error: Table ... does not exist`로 실패한다.
   - 정상 경로: 파이프라인(`uv run python -m bullet_in.run`)을 한 번 돌리면 `articles`가 생성·적재된다.
   - 수동 적용(파이프라인 전에 게이트만 점검할 때): `src/bullet_in/storage/schema.sql`을 `bulletin` DB에 실행.
   ```bash
   uv run python - <<'PY'
   from sqlalchemy import create_engine, text
   from pathlib import Path
   e = create_engine("mysql+pymysql://root:bulletin@localhost:3306/bulletin")
   ddl = Path("src/bullet_in/storage/schema.sql").read_text()
   with e.begin() as c:
       for s in ddl.split(";"):
           if s.strip(): c.execute(text(s))
   print("schema applied")
   PY
   ```

## 실행
```bash
cd dbt && uv run dbt build --profiles-dir .
```
기대: 모델 2개 빌드 + 테스트 전부 PASS (예: `PASS=8 ERROR=0`).

<!-- 터미널 캡처 → docs/assets/dbt-build-pass.png 저장 후 아래 주석 해제 -->
<!-- ![dbt 품질 게이트 PASS](../assets/dbt-build-pass.png) -->

## 결과 해석 / 실패 시
- 전부 PASS = 품질 게이트 통과.
- 실패하면 데이터 이상이다. 어떤 테스트가 깨졌는지로 원인이 좁혀진다:
  - `unique` 실패 → dedup 키 충돌. canonicalization/`content_hash` 점검.
  - `not_null` 실패 → 어댑터가 필수 필드를 못 채움. 파서 점검.
  - `accepted_values` 실패 → `sources.yaml`의 tier 값 오류.
- 상세 복구: `docs/runbook/incident-recovery.md`의 "품질 게이트 실패" 절.

## 비고
- 산출물 `bullet_in.duckdb`, `dbt/target/`, `dbt/logs/`는 커밋하지 않는다(.gitignore).
- attach 접속 정보는 `dbt/profiles.yml`(localhost·root·`bulletin`).
- `accepted_values` 정의 형식은 dbt 1.11 기준 `arguments:` 중첩 → `docs/troubleshooting/2026-05-27-dbt-accepted-values-deprecation.md`.
