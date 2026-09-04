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
