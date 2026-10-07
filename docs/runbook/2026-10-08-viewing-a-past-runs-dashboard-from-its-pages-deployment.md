# 지나간 실행의 수집 현황 대시보드를 Pages 배포 고유 주소로 다시 보는 절차 (2026-10-08)

특정 실행이 끝난 시점의 수집 현황 대시보드 (`ops.html`) 를 나중에 다시 확인할 때 쓰는 절차다.
문서에 적을 지표 값을 정해 둔 실행 기준으로 맞추거나, 그 시점의 캡처가 필요할 때 쓴다.

## 1. 왜 따로 절차가 필요한가

라이브 주소 (`https://bullet-in.pages.dev/ops.html`) 는 3시간마다 다음 실행이 새로 배포해 덮어쓴다.
그래서 기준으로 정한 실행이 지나면 라이브 주소로는 그 시점의 값을 볼 수 없다.

Cloudflare Pages 는 배포마다 고유 주소 (`https://<배포 id 앞 8자>.bullet-in.pages.dev`) 를 따로 남긴다.
이 주소는 뒤 배포가 나가도 바뀌지 않는다.

| 항목 | 2026-10-08 실측 |
| --- | --- |
| 운영 배포 기록 수 | 718건 |
| 가장 오래된 배포 | 2026-07-20 03:04 UTC (`a860cdbc`) |
| 가장 오래된 배포의 `ops.html` | 열림 (제목 「bullet-in 수집 현황」) |

보존 기한은 확인하지 않았다.
지금까지는 첫 배포부터 모두 남아 있다.

## 2. 절차

### 2.1. 실행 시각에 맞는 배포를 찾는다

`wrangler pages deployment list` 는 생성 시각을 「8 hours ago」 처럼 상대 시각으로만 보여 준다.
정확한 시각은 Cloudflare API 의 `created_on` 으로 본다.
키는 VM 의 `.env` 에 있다 (`CLOUDFLARE_API_TOKEN` · `CLOUDFLARE_ACCOUNT_ID`).

```bash
# VM 에서 실행 · 운영 배포 최근 12건의 생성 시각 · 고유 주소 · 커밋
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'cd ~/bullet-in && set -a && . ./.env && set +a &&
curl -s -H "Authorization: Bearer $CLOUDFLARE_API_TOKEN" \
  "https://api.cloudflare.com/client/v4/accounts/$CLOUDFLARE_ACCOUNT_ID/pages/projects/bullet-in/deployments?per_page=12&env=production" |
python3 -c "import sys,json;[print(x[\"created_on\"],x[\"url\"],x[\"deployment_trigger\"][\"metadata\"].get(\"commit_hash\",\"\")[:7]) for x in json.load(sys.stdin)[\"result\"]]"'
```

- 정규 실행은 3시간마다 정각 (UTC 0 · 3 · 6 · … · 21시) 에 시작하고, 배포는 시작 2 ~ 3분 뒤에 나간다.
  2026-10-07 09:00 UTC 실행의 배포는 `09:02:24Z` 의 `f7b20d33` 이었다.
- 더 오래된 배포는 `page=2` 처럼 쪽을 넘겨 찾는다 (`result_info.total_pages`).
- 커밋 칸은 그 실행이 내려받은 `origin/main` 이다.
  저장소 수치 (PR 수 · 테스트 수 등) 를 같은 시점으로 맞출 때 이 커밋에서 센다.

### 2.2. 그 배포의 페이지를 받아 시점을 확인한다

```bash
curl -sSL -A "Mozilla/5.0" -o ops-f7b20d33.html https://f7b20d33.bullet-in.pages.dev/ops.html
grep -o '[0-9-]* [0-9:]* UTC 생성' ops-f7b20d33.html | head -1    # 2026-10-07 09:02 UTC 생성
```

- `-L` 과 User-Agent 를 함께 붙인다.
  둘 중 하나가 빠지면 리다이렉트나 403 으로 빈 응답이 오는데, 그 빈 응답을 「이상 없음」 으로 읽기 쉽다.
- **응답 코드 200 은 그 페이지가 있었다는 뜻이 아니다.**
  없는 경로를 요청해도 Pages 는 인덱스와 같은 내용을 200 으로 돌려준다 (2026-10-08 실측 · 306,620 바이트).
  받은 파일의 제목 (`<title>bullet-in 수집 현황</title>`) 과 「… UTC 생성」 문구로 확인한다.

### 2.3. 값을 읽고 DB 로 한 번 더 맞춰 본다

대시보드는 시점이 서로 다른 값을 한 화면에 담는다.

| 값 | 기준 |
| --- | --- |
| SLO-2 · 기사 수 · 실행 수 | 그 배포를 만든 실행까지 |
| SLO-3 · SLO-4 | 직전 실행의 dbt 게이트 결과 |
| 완주율 타일 | 매시 37분에 도는 `bullet-in-airflow-watch` 타이머가 계산한 값 · 진행 중인 실행은 빠진다 |

SLO-2 처럼 DB 로 셀 수 있는 값은 같은 실행까지로 잘라 다시 세어 대시보드 값과 맞는지 본다.

```bash
# VM 에서 실행 · 2026-10-07 09:00 UTC 실행까지 최근 30회의 success_rate 평균과 실패한 실행
.venv/bin/python - <<'EOF'
import os
from sqlalchemy import create_engine, text
e = create_engine(os.environ["MARIADB_URL"])
with e.connect() as c:
    rows = c.execute(text("SELECT run_id, success_rate FROM pipeline_runs "
                          "WHERE started_at <= '2026-10-07 09:00:59' ORDER BY started_at DESC LIMIT 30")).all()
    print(round(sum(float(r[1]) for r in rows) / len(rows) * 100, 3), [r[0] for r in rows if float(r[1]) < 1])
EOF
```

2026-10-07 09:00 UTC 실행은 대시보드 99.2% · DB 99.167 로 맞았다.

### 2.4. 캡처한다

라이브 주소 대신 고유 주소를 열어 찍는다.
뷰포트 · 잘라 낼 영역은 라이브를 찍을 때와 같게 둔다 ([README 캡처 런북](2026-09-06-capturing-live-screens-for-the-readme.md)).

```python
# Playwright · 수집 현황 대시보드 위쪽 1500px (라이트)
await page.goto("https://f7b20d33.bullet-in.pages.dev/ops.html", wait_until="networkidle")
box = await page.locator(".wrap").first.bounding_box()
await page.screenshot(path="ops-light.png", clip={"x": box["x"], "y": 0, "width": box["width"], "height": 1500})
```

## 3. 주의

- 고유 주소의 행동 지표 대시보드 (`behavior.html`) 도 그 배포 시점의 것이다.
  다만 행동 지표 원자료는 하루 단위로 갱신되므로 날짜 범위는 대시보드에 적힌 값을 따른다.
- 기준 실행을 정한 뒤에는 값이 마음에 들지 않아도 다른 실행으로 옮기지 않는다.
  SLO-2 같은 최근 30회 지표는 실행을 고르는 것만으로 값이 달라진다.

## 4. 관련

- [배포 판정 런북](2026-09-04-when-the-cycle-deploys-itself.md) — `wrangler pages deployment list` 로 배포가 나갔는지 확인하는 자리
- [SLO 측정 런북](2026-07-19-slo-measurement.md) — 지표 정의
- [README 캡처 런북](2026-09-06-capturing-live-screens-for-the-readme.md) — 캡처 영역과 테마
