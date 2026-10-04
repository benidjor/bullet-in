# 런북 — PR 브랜치를 VM 임시 클론에서 운영 데이터로 재현하는 법

머지 전 코드가 운영 데이터 위에서 런북의 기준값을 그대로 찍는지 볼 때 쓴다.
2026-09-05 안건 2φ PR 1 (#469) 이 `docs/runbook/2026-09-04-measuring-visitors-funnel-and-retention-from-bronze.md` §9 의 일곱 줄을 이 절차로 재현했고, PR 2 (수집 현황) 도 같은 길을 쓴다.

## 1. 왜 임시 클론인가

VM 의 주 체크아웃 `~/bullet-in` 은 회차의 `advance` 태스크만 옮긴다 (`docs/superpowers/specs/2026-09-03-deploy-automation-design.md`).
세션이 거기서 `git checkout` 이나 `pull` 을 하면 배포 자동화의 전제가 깨진다.
그래서 브랜치를 `/tmp` 에 따로 받아 돌리고, 끝나면 지운다.

## 2. 절차

로컬에서 브랜치를 올린 뒤 VM 에서 한 번에 돌린다.
아래는 PR 1 에서 실제로 돌린 명령이고 브랜치 이름과 날짜만 바꾸면 된다.

```bash
# 로컬 · 브랜치를 올린다
git -C <워크트리> push -u origin <브랜치>

# VM · 임시 클론 → .env 복사 → 자격 → gold 재작성 → 기준값
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 '
  set -e
  rm -rf /tmp/bi-dash
  git clone -q --depth 1 --branch <브랜치> https://github.com/benidjor/bullet-in /tmp/bi-dash
  cd /tmp/bi-dash && cp ~/bullet-in/.env . && set -a && . ./.env && set +a
  export GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-lakehouse.json
  ~/.local/bin/uv run --python 3.11 --project . python -c "
from datetime import datetime, timezone
from bullet_in import warehouse as w
c = w.load_catalog()
print(\"build_gold facts:\", w.build_gold(c, datetime.now(timezone.utc)))
"
  ~/.local/bin/uv run --python 3.11 --project . python -m bullet_in.warehouse show --from 2026-08-28 --to 2026-09-03
' 2>&1 | tee <스크래치패드>/vm-reproduction.txt
```

명령마다 이유가 있다.

- `--depth 1 --branch` 는 그 브랜치 하나만 받는다 (2026-09-05 실측 약 10초).
- `.env` 는 이 프로젝트가 dotenv 를 안 쓰므로 셸에 직접 올려야 한다.
- `GOOGLE_APPLICATION_CREDENTIALS` 는 웨어하우스 전용 서비스 계정이다.
  회차의 `warehouse_load` 태스크가 같은 파일로 감싸 돈다.
- `--python 3.11` 은 저장소에 `.python-version` 이 없어 uv 가 VM 의 시스템 3.12 를 고르는 것을 막는다.
  메인 · CI · VM 주 체크아웃이 전부 3.11 이다.
- `tee` 로 받아 두고 여러 번 센다.
  출력을 다시 보려고 재실행하지 않는다.

## 3. 무엇을 쓰고 무엇을 안 쓰나

기준값 재현에 필요한 쓰기는 `build_gold` 하나다.
silver 에서 gold 표 다섯 (`fact_card_click` · `dim_date` · `fact_session` · `fact_user_daily` · `dim_user`) 을 통째로 다시 만들어 운영 카탈로그에 덮어쓴다.
회차의 `warehouse_load` 가 매번 같은 일을 하므로 상태 차이가 남지 않는다.

`python -m bullet_in.warehouse load` 는 쓰지 않는다.
`run_load` 는 MariaDB 의 변경 이력 · 스냅샷 · 운영 표 적재까지 운영 카탈로그에 쓰고 워터마크를 옮긴다.
재현에는 필요 없고 회차와 겹치면 같은 표에 두 번 쓴다.

`state/behavior_metrics.json` 은 임시 클론 안에 떨어지므로 운영 파일은 건드리지 않는다.

회차와 겹치지 않게 돌린다.
회차는 3시간마다 (00 · 03 · 06 · 09 · 12 · 15 · 18 · 21시 KST) 돌고 `warehouse_load` 는 시작 3분에서 4분 뒤에 gold 를 다시 쓴다.
정각 앞뒤 5분은 피한다.
PR 1 은 05:23 에서 05:24 에 돌렸다.

## 4. 결과를 읽는 법

기대는 런북 §9 표의 일곱 줄 그대로다.

```
사용자 7일 · 세션 · 참여 세션 비율 | 890 · 1,502 · 61%
공개일 DAU · 신규 | 688 · 666
퍼널 | 863 → 221 → 97 → 71
신뢰도 · 기자 필터 사용자 · 원문 이동 | 53 · 7
기사 상세를 본 사용자 | 254
선수 페이지 뷰 · 목록 뷰 | 108 · 71
모바일 비율 · fmkorea 참조 비율 | 66% · 70%
```

줄 하나라도 다르면 표를 고치지 않는다.
런북 §3 에서 §7 의 절차와 코드가 어디서 갈리는지를 먼저 찾는다.
기기 · 유입 두 비율은 런북이 이벤트 단위로 세고 코드는 사용자 × 날짜 · 세션 단위로 세므로 1 포인트 차이는 정의 차이일 수 있는데, PR 1 에서는 그 차이도 없었다.

출력에 섞이는 줄 둘은 기존 현상이다.

- `Failed to delete metadata file gs://…/fact_card_click/…` 와 `dim_date` 의 같은 줄은 pyiceberg 가 덮어쓴 뒤 옛 메타데이터 파일을 지우려다 실패한 경고다.
  정규 회차의 `warehouse_load` 로그에도 같은 두 줄이 있다.
  GCS 삭제 권한 쪽으로 보이고 재현 결과와는 무관하다.
- `UserWarning: Delete operation did not match any records` 는 빈 표를 덮어쓸 때 나는 pyiceberg 경고다.

## 5. 정리

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'rm -rf /tmp/bi-dash'
```

임시 클론을 남기면 `.env` 사본이 `/tmp` 에 남는다.
같은 세션 안에서 지운다.

## 6. dbt 게이트를 리허설할 때 (2026-10-03 추가)

웨어하우스 대신 dbt 게이트를 PR 브랜치로 미리 돌려 볼 때의 절차다.
DuckDB 판을 1.5.3 에서 1.5.5 로 올린 PR (#520) 에서 실제로 두 번 돌렸다.

### 6.1. 절차

임시 클론과 `.env` 복사는 §2 와 같다.
운영과 같은 게이트 함수를 재시도 없이 부르고, 결과 파일에서 모델별 상태를 함께 읽는다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 '
  set -e
  rm -rf /tmp/bi-duck && git clone -q --depth 1 --branch <브랜치> https://github.com/benidjor/bullet-in /tmp/bi-duck
  cd /tmp/bi-duck && cp ~/bullet-in/.env . && set -a && . ./.env && set +a
  ~/.local/bin/uv run -q --python 3.11 --project . python -c "
import os, json, duckdb
from pathlib import Path
from bullet_in.dbt_gate import run_gate
print(duckdb.__version__, run_gate(Path(\"dbt\"), os.environ[\"MARIADB_URL\"], crash_retries=0))
for x in json.load(open(\"dbt/target/run_results.json\"))[\"results\"]:
    if x[\"status\"] not in (\"success\", \"pass\") or \"gold_slo_rollup\" in x[\"unique_id\"]:
        print(x[\"unique_id\"], x[\"status\"], (x.get(\"message\") or \"\")[:160])
"
' 2>&1 | tee <스크래치패드>/vm-gate-rehearsal.txt
```

- 모델은 DuckDB 기본 스키마에만 만들어지므로 쓰기가 일어나는 곳은 임시 클론 안의 `bullet_in.duckdb` 하나다 (`dbt_project.yml` · `dbt/models` 에 `database` · `schema` 재지정과 hook 이 없다).
  운영 MariaDB 는 attach 로 읽기만 한다.
- 확장은 `~/.duckdb/extensions/<판>/` 에 내려받는다.
  폴더가 판마다 따로라 운영이 쓰는 판과 섞이지 않는다.
- `crash_retries=0` 을 주면 세그폴트가 났을 때 재시도에 가려지지 않는다.

### 6.2. 「끝까지 돌았다」 를 그대로 믿지 않는다

첫 리허설은 세그폴트 없이 10초 만에 끝났지만 차단이 하나 있었다.
`stg_source_freshness` 가 `Binder Error: Referenced column "state" not found` 로 막혔고, 그 뒤의 `gold_slo_rollup` 이 skip 됐다.
세그폴트가 나는 바로 그 모델이 돌지 않았으니, 이 리허설은 보려던 것을 보지 못했다.

결과를 읽을 때는 두 가지를 따로 본다.

- 게이트의 성공 · 실패
- 보려던 모델이 실제로 실행됐는가 (`run_results.json` 에서 그 모델의 상태)

### 6.3. PR 코드와 운영 스키마의 시점이 다를 수 있다

위 차단의 원인은 DuckDB 판이 아니었다.
새 칼럼을 더한 PR (#515) 이 이미 머지돼 있었지만, 운영 DB 에는 그 코드가 아직 한 번도 돌지 않아 칼럼이 없었다.

이 프로젝트는 스키마 이전을 실행 시점에 한다.
회차의 `collect` 가 `_materials()` 에서 `ensure_schema()` (`ALTER TABLE … ADD COLUMN IF NOT EXISTS`) 를 부르므로, 머지된 코드가 운영에서 한 번 돌기 전까지 DB 는 옛 모양이다.
그 틈에 새 dbt 모델을 대 보면 이렇게 막힌다.

- 리허설 전에 최근 머지된 PR 에 스키마 변경이 있는지 본다.
- 있으면 그 코드가 운영 회차에서 한 번 돈 뒤에 리허설한다 (이번에는 다음 회차를 기다려 06:17 에 다시 돌렸고 30개가 모두 성공했다).
- 운영 스키마를 손으로 바꾸지 않는다 (운영 데이터 변경은 승인 대상이고 회차가 같은 일을 한다).

### 6.4. 머지 뒤 확인

머지 커밋이 배포된 첫 회차에서 세 가지를 본다.

- `build.json` 의 커밋이 머지 커밋 이후인가
- 프로젝트 venv 가 새 판을 쓰는가 (`~/bullet-in/.venv/bin/python -c "import duckdb; print(duckdb.__version__)"` · 확장 폴더)
- 그 회차 `gate` 태스크 로그에 「dbt 게이트 통과」 와 종료 코드 0 이 있고 시도가 한 번인가

커밋이 맞아도 잠금 파일 동기화가 실패하면 옛 판으로 돈다.
VM 은 ARM (`linux_arm64`) 이고 CI 는 x86 이라 확장 빌드 파일이 다르므로, 세그폴트 관측은 VM 과 CI 를 따로 센다.
