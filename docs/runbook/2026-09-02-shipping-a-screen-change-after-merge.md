# 머지된 화면 변경을 배포하고 배포본으로 확인하기까지 (2026-09-02)

서빙 코드가 머지된 뒤 라이브에 올리고 확인하는 절차다.
2026-09-02 회차에서 두 번 (PR #421 · #422) 그대로 돌렸다.

조각들이 여러 런북에 흩어져 있어 매번 문서 셋을 뒤져야 했다.
이 문서는 그 순서를 한 줄기로 모은다.

**데이터를 고치는 배포가 아니다.**
소급 배치 · 재분류가 함께 가는 경우는 `2026-07-24-vm-live-reprocess-deploy.md` 를 본다.

## 1. 배포 전 점검 둘

### 1.1. 회차가 도는 중인지

렌더 도중에 회차가 값을 바꾸면 중간 상태가 그대로 배포된다.

```bash
ssh -i ~/.ssh/<키> <운영> 'systemctl show bullet-in.service -p ActiveState --value'
# inactive 여야 한다

ssh -i ~/.ssh/<키> <운영> 'systemctl list-timers bullet-in.timer --no-pager | sed -n 2p'
# 다음 회차까지 남은 시간을 본다 — 렌더 · 배포에 5분쯤 걸린다
```

### 1.2. 다른 배치가 도는 중인지

```bash
ssh -i ~/.ssh/<키> <운영> 'ps aux | grep -E "[b]ullet_in|[b]ackfill" | grep -v "bash -c"'
```

`grep -v "bash -c"` 는 이 점검이 자기 자신을 잡지 않게 막는다.
이 점검을 `ssh <호스트> '<명령 모음>'` 으로 실행하면 감싼 bash 의 명령줄에 "bullet_in" 문자열이 들어 있어 그 bash 자신이 걸린다.

## 2. 코드 반영 — 손으로 하지 않는다 (2026-09-04 부터)

머지된 코드는 다음 회차가 시작할 때 스스로 내려받는다 (DAG `bullet_in_cycle` 의 첫 태스크 `advance` · `bullet_in.deploy advance`).
회차 끝에 첫 회차를 판정하고 디스코드 리뷰 채널에 「✅ 코드 반영 완료」 가 온다.
그 알림이 오면 이 문서의 §3 이하를 할 필요가 없다.

급하면 회차를 손으로 한 번 시작한다.

```bash
ssh -i ~/.ssh/<키> <운영> \
  'set -a; . ~/airflow/airflow.env; set +a; ~/airflow-venv/bin/airflow dags trigger bullet_in_cycle'
```

**`git pull` 을 손으로 치지 않는다.**
쳐도 되지만 상태 파일 (`state/deploy.json`) 이 「전진」 을 못 보고 지나가 첫 회차 판정과 롤백이 안 붙는다.

아래 §3 에서 §6 은 회차를 기다리지 않고 재렌더 · 배포만 앞당길 때 쓴다.
그때도 코드 반영은 위 명령으로 회차를 시작하는 편이 안전하다.

## 3. 재렌더 — 스니펫을 옮겨 적지 않는다

`bullet_in.confirm_player._render` 를 그대로 부른다.
이 함수는 `run.py` 서빙 경로와 1:1 로 유지된다.

```python
import logging, os
from sqlalchemy import create_engine
from bullet_in.confirm_player import _render

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
_render(create_engine(os.environ["MARIADB_URL"]))
```

```bash
scp -i ~/.ssh/<키> <스크래치패드>/vm_render.py <운영>:/tmp/vm_render.py
ssh -i ~/.ssh/<키> <운영> 'cd ~/bullet-in && set -a && . ./.env && set +a \
  && /home/ubuntu/.local/bin/uv run --project /home/ubuntu/bullet-in python /tmp/vm_render.py'
```

`uv` 는 `/home/ubuntu/.local/bin/uv` 로 부른다 — ssh 비대화형 셸의 `PATH` 에 그 자리가 없다.
`.env` 는 셸에서 소싱한다 — 이 프로젝트는 dotenv 를 안 쓴다.

**왜 스니펫을 안 옮겨 적나** — 서빙 경로에 필터가 추가될 때마다 복사본이 낡아
감춰 둔 기사가 화면으로 돌아온 사고가 네 번 재발했다
(`2026-07-19-enrich-only-pass.md` §4 · `2026-07-19-runbook-snippet-logic-drift.md`).

### 3.1. 출력에서 볼 것

```
INFO 서빙 제외 — 무관 51건 · 옛 글 22건
site 재생성: 925 행
```

- **제외 수치가 머지 전 검증 때와 같은지** — 크게 달라졌으면 그사이에 데이터가 움직인 것이다
- **행 수** — `find site -name '*.html' | wc -l` 이 50 미만이면 배포 스크립트가 스스로 막는다

### 3.2. `ops.html` 만 낡은 것은 정상

```bash
ssh ... 'cd ~/bullet-in && ls -l --time-style=+%H:%M site/index.html site/players.html site/ops.html'
```

`index.html` · `players.html` 은 방금 시각인데 `ops.html` 만 직전 정기 회차 시각으로 남는다.
운영 뷰는 `write_ops` 가 만드는데 그것은 `run.py` 안에서만 돌기 때문이다.

**이것을 「VM 에 코드가 안 올라갔다」 로 오해하기 쉽다** — 2026-08-03 에 실제로 그 오진이 나왔다.

## 4. 배포 전 마지막 확인 — 바꾼 것이 산출물에 있는지

배포하기 전에 **VM 의 `site/` 에서** 의도한 변화를 확인한다.
바뀐 것이 없는데 배포하면 되돌릴 일만 생긴다.

```bash
# 새 마크업이 나오고 옛 마크업이 사라졌는지
ssh ... 'cd ~/bullet-in && grep -c "sameline" site/index.html; grep -c "reltoggle" site/index.html'
```

특정 기사가 특정 자리에 서야 하는 변경이면 **제목이 아니라 해시로 대조한다.**
제목은 재번역으로 바뀌므로 「그 기사가 맞다」 는 확인이 헐거워진다.

## 5. 배포

```bash
ssh -i ~/.ssh/<키> <운영> 'cd ~/bullet-in && set -a && . ./.env && set +a && ./infra/deploy-site.sh'
```

스크립트가 `site/index.html` 존재와 HTML 50건 이상을 먼저 검사하고 `wrangler pages deploy` 를 부른다.
끝에 `Deployment complete!` 와 미리보기 주소가 찍힌다.

## 6. 배포본 확인

### 6.1. 받는 법

```bash
curl -sL -A "Mozilla/5.0" "https://bullet-in.pages.dev/" -o live_index.html
curl -sL -A "Mozilla/5.0" "https://bullet-in.pages.dev/all.html" -o live_all.html
```

**`curl` 을 쓴다** — 파이썬 `urllib` 은 403 · 308 로 전량 실패하고, 그 빈 결과가 「이상 없음」 으로 읽힌다.

최상위 도메인은 배포 직후 잠깐 이전 배포본을 돌려줄 수 있다
(`2026-07-20-vm-cohost-bootstrap.md` 의 「배포 직후 검증」).
수치가 안 맞으면 몇 초 뒤 다시 받아 본다.

### 6.2. 세는 법 — 파서로 세고 합계를 검산한다

```python
from bs4 import BeautifulSoup
soup = BeautifulSoup(open("live_index.html", encoding="utf-8").read(), "html.parser")
```

**정규식으로 중첩 `<div>` 를 자르지 않는다** — `.*` 가 파일 끝까지 먹어 가십 구역까지 들어온다.

홈에서 기사가 놓이는 자리를 다 세고 서빙 행 수와 떨어지는지 본다.

```
날짜 묶음의 카드 + 카드 안의 줄 + 숨김 카드 + 가십 구역 + 머리기사 = 서빙 행 수
```

자리를 빠뜨리면 나머지가 「홈 어디에도 없는 기사」 로 보고된다
(`2026-09-02-a-home-article-can-sit-in-four-places.md`).

### 6.3. 눈으로도 한 번 본다

계수가 맞아도 화면이 깨질 수 있다.
브라우저로 열어 첫 화면과 카드 하나를 확인한다.

## 7. 정리

```bash
ssh -i ~/.ssh/<키> <운영> 'rm -f /tmp/vm_render.py'
ssh -i ~/.ssh/<키> <운영> 'systemctl is-active bullet-in.timer bullet-in-watchlist.timer bullet-in-backup.timer'
# 셋 다 active 여야 한다
```

터널 · 로컬 서버를 열었으면 함께 닫는다.

```bash
pkill -f "<포트>:127.0.0.1:3306"
pkill -f "http.server <포트>"
```

## 함께 볼 것

- `docs/runbook/2026-08-28-rendering-the-home-page-before-you-deploy-it.md` — 머지 **전** 에 운영 데이터로 화면을 재현하는 절차
- `docs/runbook/2026-07-19-enrich-only-pass.md` §4 — 재렌더 스니펫과 그 표류 사고
- `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` — VM 접속 · 배포 직후 캐시 검증
- `docs/runbook/2026-07-24-vm-live-reprocess-deploy.md` — 데이터 소급이 함께 가는 배포
- `docs/troubleshooting/2026-09-02-a-home-article-can-sit-in-four-places.md` — 화면을 세는 범위
