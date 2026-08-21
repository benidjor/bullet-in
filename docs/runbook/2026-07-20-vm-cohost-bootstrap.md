# VM 동거 부트스트랩 · 스케줄 운영 (2026-07-20)

bullet-in 을 seoulnow Oracle Free VM 에 함께 올려 (동거) systemd timer 로 하루 8회 무인 실행하는 절차와 일상 운영.
SP-C 트랙 (plan `docs/superpowers/plans/2026-07-20-spc-schedule-cohost.md`) 에서 실제 수행한 명령 · 출력 기준이다.

## 1. 접속

- 대상: `ubuntu@155.248.164.17` (Oracle A1 arm64 · Ubuntu · 시스템 TZ 는 KST, 타이머는 UTC 지정).
- 키: 로컬 맥의 `~/.ssh/seoulnow_deploy` (seoulnow 배포용 키 공용).

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17
```

## 2. 선행 게이트 — 메모리 실측 (동거 판정)

동거 착수 · 증설 판단 전 반드시 실측한다 (spec §2.1 의 선행 조건).

```bash
free -h                      # available 이 bullet-in 추가분 (상시 ~1GB + 피크 ~1.5GB) 이상인지
docker stats --no-stream    # seoulnow 컨테이너 점유 확인
```

- 2026-07-20 실측: 총 23Gi · available 11Gi · 디스크 33G 여유 · 포트 27017 / 3306 미사용 — 통과.
- 스왑 0B 관찰 항목: available 이 2GB 미만으로 내려가면 스왑 파일 추가 또는 유료 VM (3-a) 전환 재검토.

## 3. 부트스트랩 (1회)

```bash
# ① uv + 저장소
curl -LsSf https://astral.sh/uv/install.sh | sh
git clone https://github.com/benidjor/bullet-in.git /home/ubuntu/bullet-in
cd /home/ubuntu/bullet-in
uv sync --extra dev
uv run playwright install chromium
sudo uv run playwright install-deps chromium

# ② 시크릿 (로컬 맥에서 — 커밋 금지 파일)
scp -i ~/.ssh/seoulnow_deploy .env x_cookies.json ubuntu@155.248.164.17:/home/ubuntu/bullet-in/

# ③ DB 컨테이너
docker compose up -d --wait
```

- .env 는 로컬과 동일 (DB 가 localhost 라 수정 불요).
- 스키마는 첫 회차의 `ensure_schema()` 가 멱등 적용 — 수동 작업 없음.

## 4. 데이터 이관 (로컬 → VM, 1회)

VM 의 DB 는 빈 상태로 시작하므로, 기존 이력 (기사 · 정정 · 백필 · 회차 이력) 을 옮겨야 연속성이 유지된다.

```bash
# 로컬 맥에서 — 덤프
docker exec bullet-in-mariadb-1 mariadb-dump -uroot -pbulletin --databases bulletin > /tmp/mart.sql
docker exec bullet-in-mongo-1 mongodump --archive=/tmp/raw.gz --gzip --db "$MONGO_DB"
docker cp bullet-in-mongo-1:/tmp/raw.gz /tmp/raw.gz
scp -i ~/.ssh/seoulnow_deploy /tmp/mart.sql /tmp/raw.gz ubuntu@155.248.164.17:/tmp/

# VM 에서 — 복원 (기존 테이블 대체)
docker exec -i bullet-in-mariadb-1 mariadb -uroot -pbulletin < /tmp/mart.sql
docker cp /tmp/raw.gz bullet-in-mongo-1:/tmp/raw.gz
docker exec bullet-in-mongo-1 mongorestore --archive=/tmp/raw.gz --gzip --drop
```

- 2026-07-20 실측: articles 205 · pipeline_runs 19 · mongo raw 442 복원 확인.
- 주의: 복원은 VM 쪽 기존 행을 대체한다.
  이관 전 VM 에서 돌린 회차의 신규 건은 사라지지만, 소스 페이지에 남아 있는 한 다음 회차가 재수집한다 (실측: 신규 2건이 잔여 페이지로 정리된 뒤 재수집 대상화).

## 5. 스케줄 등재 (systemd)

유닛 파일 SoT 는 저장소 `infra/systemd/` — VM 반영은 설치 스크립트로.

```bash
cd /home/ubuntu/bullet-in && bash infra/systemd/install-units.sh
sudo systemd-analyze verify /etc/systemd/system/bullet-in.*   # 경고 없어야 함
systemctl list-timers bullet-in.timer --no-pager              # NEXT 가 UTC 3시간 격자 + 지터
```

- 주기: UTC 3시간 격자 (0 · 3 · 6 · 9 · 12 · 15 · 18 · 21시 · 지터 최대 300초) — 보존된 DAG `0 */3 * * *` 와 같은 값.
- `Persistent=true` 라 재부팅으로 놓친 회차는 부팅 후 보정 실행된다.
- 유닛 수정 시: 저장소에서 파일을 고쳐 머지 → VM 에서 `git pull` → `install-units.sh` 재실행.

## 6. 일상 운영

```bash
journalctl -u bullet-in.service -n 100 --no-pager   # 최근 회차 로그
systemctl list-timers bullet-in.timer --no-pager    # 다음 발화 확인
sudo systemctl start bullet-in.service              # 수동 회차 (X 접촉 1회 소모 — 남용 금지)
sudo systemctl disable --now bullet-in.timer        # 스케줄 중지 (롤백)
```

- 무인 정상 판정: Discord 실패 알림이 없고, ops 뷰 (site/ops.html) 회차 이력이 6시간 간격으로 쌓이면 정상.
- 실패 시 `bullet-in-fail-notify.service` 가 Discord 로 알린다 (수동 검증 완료 — 2026-07-20).

### 6.1. 머지분 반영 — 자동 pull 이 없다

**main 에 머지해도 실서비스는 바뀌지 않는다.**
systemd 유닛은 `docker compose up` → `run.py` → `deploy-site.sh` 만 실행하고 `git pull` 을 하지 않는다.
VM 체크아웃이 옛 커밋에 머물러 있으면 다음 회차도 옛 코드로 돈다.
머지와 실서비스 반영 시점을 따로 고를 수 있다는 뜻이라 결함은 아니지만, "머지했는데 왜 화면이 그대로지" 로 헷갈리기 쉽다.

```bash
cd ~/bullet-in && git log --oneline -1     # VM 이 어느 커밋인지 먼저 확인
git pull --ff-only
```

반영 방법은 무엇이 바뀌었는지에 따라 갈린다.

- **수집 · 번역 로직이 바뀐 경우** — 다음 회차를 기다린다. 급하면 수동 회차 (X 접촉 1회 소모).
- **서빙 · 템플릿 · CSS 만 바뀐 경우** — 회차를 돌릴 필요 없이 사이트만 다시 만들고 배포한다.
enrich 전용 런북 §4 의 재생성 스니펫을 쓴 뒤 `./infra/deploy-site.sh` 를 실행한다.
- 재생성 SELECT 는 `bullet_in.run.SERVING_SELECT_SQL` 을 import 해서 쓴다 (컬럼을 옮겨 적으면 어긋난다 — #107).
- **컬럼이 새로 생긴 경우** — 스키마를 먼저 반영한다 (아래 6.2).
- **설정만 바뀐 경우 ( `config/*.yaml` )** — 회차를 기다리지 않고 **로더를 직접 돌려 적용값을 확인한다** (아래 6.1.2).

#### 6.1.1. 회차 직전에 얹을지 회차 뒤로 미룰지

`git pull` 을 회차 사이 어디에 넣느냐로 결과가 갈린다.
묻는 것은 둘이고 서로 충돌하지 않는다.

**「이 회차를 놓치면 되돌릴 수 없는가」 — 그렇다면 직전에 얹는다.**

2026-08-13 에 공홈 6건의 번역을 초기화해 두었고 다음 회차가 그것을 **딱 한 번** 다시 번역할 참이었다.
번역 용어 지침을 고친 머지분이 안 올라가 있으면 옛 지침으로 번역된 채 굳고 **아무도 다시 번역하지 않는다.**
그 머지분을 올린 세션은 「급하지 않다」 고 했지만 그것은 그쪽 기준이었고, 초기화해 둔 쪽에는 마감이 있었다.

**「어긋났을 때 원인을 가릴 수 있는가」 — 못 가리겠으면 회차 뒤로 미룬다.**

같은 회차에 재번역 · 신규 적재 · 표시 규칙 변경이 함께 들어가면 화면이 예상과 다를 때 무엇 때문인지 못 가린다.
그래서 표시 규칙 머지분은 회차 뒤에 얹어 다음 회차가 그것만 그리게 했다.

**뒤로 못 미룰 때는 두 판본 계산으로 가른다** — 절차는 `2026-08-13-separating-two-changes-in-one-render.md` 에 있다.
운영 사본에 코드 두 판본을 대 각자의 몫을 미리 재는 방법이라 배포를 미루지 않고도 판독이 선다.

**대조값을 잴 계획이면 그 사이에 다른 쓰기가 끼지 않는지 본다.**

병렬 세션의 소급 · 재추출이 기준선과 배포 사이에 들어가면 기준선이 조용히 어긋난다.
2026-08-13 에는 상대 세션이 「내 재추출도 표시 쌍을 바꾼다」 고 알려 줘서 순서를 바꿔 막았다.

**화면 수치는 렌더가 만든다 — DB 를 중간에 재는 것으로는 표시 규칙 변경이 안 갈린다.**

서빙 규칙만 바꾸는 머지분은 DB 를 안 바꾸므로 **다음 렌더 한 번에만 드러난다.**
세는 방법의 함정은 `2026-08-11-premerge-screen-check-with-prod-copy.md` §3.1 에 있다.

#### 6.1.2. 설정만 바뀐 배포는 회차를 기다리지 않고 확인한다

`config/*.yaml` 한 줄을 고친 배포에서 회차를 기다리면 **두 가지가 한꺼번에 확인되고, 어긋났을 때 어느 쪽인지 못 가린다.**

- **파일이 VM 에 도달했는가** — `git pull` 과 `git log --oneline -1` 이 답한다.
- **그 값이 코드에 읽히는가** — 별개다.
키 이름을 잘못 적었거나 들여쓰기가 어긋나면 파일은 최신인데 값은 기본값으로 떨어진다.

두 번째는 **파이프라인이 쓰는 그 로더를 직접 돌려** 떼어 확인한다 ( 읽기 전용 · 회차와 무관 ) .

```bash
ssh <호스트> 'cd ~/bullet-in && /home/ubuntu/.local/bin/uv run python -c "
from bullet_in.score import load_sources
for sid, v in sorted(load_sources(\"config/sources.yaml\").items()):
    h = v.get(\"freshness_hours\")
    if h is not None:
        print(sid, h)
"'
```

- **값을 옮겨 적은 상수가 아니라 실제 로더를 부른다** — `yaml.safe_load` 로 직접 읽으면 로더가 하는 변환 · 필터를 건너뛰어 다른 답이 나올 수 있다.
- `.env` 가 필요 없는 조회라 `source .env` 없이 돈다.
- 2026-08-22 에 신선도 임계 세 줄을 이렇게 확인했다 ( 회차를 두 시간 기다리지 않았고, 다음 회차 결과가 예상과 달랐다면 후보가 「설정이 코드에 도달했다」 를 뺀 나머지로 좁혀졌을 것이다 ) .

**남는 것은 회차가 실제로 그 값으로 판정했는가뿐이고, 그것은 다음 정기 회차에 자연히 확인된다.**
알림이 몰릴지는 회차를 기다리지 않고 **직전 회차의 경과를 새 임계에 대 보면** 미리 안다.

### 6.2. 새 컬럼은 회차를 기다리거나 손으로 먼저 반영한다

`schema.sql` 의 `ALTER TABLE … ADD COLUMN IF NOT EXISTS` 를 적용하는 `ensure_schema()` 는 **정기 회차 안에서만 돈다.**
런북 §4 의 재생성 스니펫도 그것을 부르지 않는다.

그래서 `git pull` 직후 백필이나 재렌더를 돌리면 `Unknown column …` 으로 죽는다.
회차를 기다려도 되지만, 기다리지 않으려면 이 한 줄을 먼저 돌린다 (2026-08-04 실측).

```bash
cd ~/bullet-in && set -a && source .env && set +a
/home/ubuntu/.local/bin/uv run python - <<'EOF'
import os
from sqlalchemy import create_engine
from bullet_in.storage.mariadb import MartStore
MartStore(create_engine(os.environ["MARIADB_URL"])).ensure_schema()
print("스키마 반영 완료")
EOF
```

- **`uv` 를 절대 경로로 쓴다.**
`ssh <호스트> '<명령>'` 처럼 비대화형으로 실행하면 PATH 에 없어 `uv: command not found` 가 난다.
systemd 유닛도 `/home/ubuntu/.local/bin/uv` 를 박아 쓴다.
- 컬럼이 실제로 붙었는지는 `SHOW COLUMNS FROM <테이블>` 로 확인한다.

반영 후 라이브에서 확인한다.

```bash
curl -sL https://bullet-in.pages.dev/ | grep -o 'article/[0-9a-f]\{64\}\.html' | sort -u | wc -l   # 카드 수
curl -sL "https://bullet-in.pages.dev/article/<hash>" | grep -c 'excerpt-note'                     # 서빙 범위 확인
```

- `curl` 은 `-L` 을 붙인다 — Pages 가 확장자 없는 경로로 308 리다이렉트를 준다.
- 배포 스크립트는 산출물이 50개 미만이면 배포를 거부한다 (렌더 실패 잔해 방어).

## 7. 실패 모드

| 증상 | 판단 | 대응 |
|---|---|---|
| 회차 실패 알림 + journalctl 에 mariadb 접속 오류 | 콜드 스타트 레이스 (sleep 10 초과) | 재발 시 compose 헬스체크 추가 검토, 단발성이면 다음 회차가 보정 |
| x_afcstuff 만 조용히 0건 (SLO-5 X 24h 알림) | 쿠키 만료 또는 DC IP 차단 | 쿠키 재추출 (X 어댑터 런북) 후 scp 재전송. 반복 차단이면 spec §2.4 폴백 (소스 비활성) |
| Gemini 파싱 실패 · 429 로그 | 정상 동작 (멱등 누적 설계) | 무대응 — 다음 회차가 수렴. 잔존 시 enrich-only 런북 |
| available 메모리 2GB 미만 | 동거 한계 접근 | 스왑 파일 추가 또는 3-a (유료 VM) 전환 — 이 런북 절차 그대로 이주 |
| 회차 30분 초과 실패 (TimeoutStartSec) | 행 (hang) | journalctl 로 단계 확인, 소스 셀렉터 드리프트 의심 |

## 8. Pages 배포 (SP-D)

회차 끝 `ExecStartPost=` 가 `infra/deploy-site.sh` 로 site/ 를 Cloudflare Pages 에 직접 업로드한다.
프로젝트 `bullet-in` → https://bullet-in.pages.dev — 배포 실패는 유닛 실패로 집계되어 Discord 알림.

### 1회 셋업

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo npm install -g wrangler@4
# .env 에 CLOUDFLARE_API_TOKEN (Pages Edit 최소 권한) · CLOUDFLARE_ACCOUNT_ID 추가
wrangler pages project create bullet-in --production-branch main   # 1회만
```

### 수동 배포 · 진단

```bash
cd ~/bullet-in && set -a && source .env && set +a
./infra/deploy-site.sh                                   # 수동 배포
wrangler pages deployment list --project-name bullet-in  # 배포 이력
```

- 배포만 실패한 회차: site/ 는 VM 에 정상 생성돼 있으므로 수동 배포로 즉시 복구.
- 토큰 만료 · 권한 오류: Cloudflare 대시보드에서 토큰 재발급 후 .env 갱신 (재시작 불필요 — 다음 회차부터 반영).

### 배포 직후 검증 — 최상위 도메인에는 잠깐 이전 배포본이 남는다

`wrangler` 가 `Deployment complete!` 를 찍은 직후에 https://bullet-in.pages.dev 를 그대로 요청하면 이전 배포본이 돌아올 수 있다.
2026-07-22 실측에서 방금 고친 제목이 그대로 옛 값으로 보여, 배포가 실패한 줄 알고 원인을 찾아 나설 뻔했다.

**세 곳을 순서대로 본다.**
세 값이 같으면 정상이고, 최상위 도메인만 다르면 캐시 탓이다.

```bash
# ① VM 산출물 — write_site 결과 자체
grep -c "찾는 문자열" site/index.html

# ② 방금 배포된 프리뷰 URL — deploy-site.sh 출력 마지막 줄의 주소
curl -sL https://<배포해시>.bullet-in.pages.dev | grep -c "찾는 문자열"

# ③ 최상위 도메인 — 캐시를 우회해서
curl -sL -H 'Cache-Control: no-cache' "https://bullet-in.pages.dev/?cb=$RANDOM" | grep -c "찾는 문자열"
```

①이 틀렸으면 HTML 생성 문제, ②가 틀렸으면 배포 문제, ③만 틀렸으면 캐시가 풀릴 때까지 기다리면 된다.

### 라이브 확인의 함정 둘 (2026-08-04 실측)

**없는 경로가 404 가 아니라 200 으로 인덱스를 돌려준다.**
Cloudflare Pages 의 소프트 404 다.
그래서 **지운 페이지가 정말 사라졌는지를 상태 코드로 판정하면 안 된다.**

```bash
# 지웠다고 생각한 페이지와 아무 없는 경로를 함께 찍어 본문을 비교한다
curl -sL https://bullet-in.pages.dev/player/<지운slug>.html | grep -oE "<h2>[^<]*</h2>" | head -2
curl -sL https://bullet-in.pages.dev/player/zzznotexist.html | grep -oE "<h2>[^<]*</h2>" | head -2
```

둘의 본문이 같으면 정상적으로 지워진 것이다 (둘 다 인덱스로 떨어진 것).
페이지 목록이 맞는지는 산출물 쪽에서 세는 편이 확실하다 — `ls site/player/*.html | wc -l`.

**정적 자산은 사이트 루트에 있다.**
저장소 경로는 `src/bullet_in/serve/static/style.css` 이지만 배포본에서는 `/style.css` · `/app.js` 다.
`/static/style.css` 를 요청하면 소프트 404 로 인덱스 HTML 이 돌아와, CSS 를 grep 해도 아무것도 안 걸린다.

## 9. 참고

- 결정 배경: `docs/superpowers/specs/2026-07-20-deployment-mvp-track-design.md` §2.1 · §2.2.
- X 쿠키 절차: `docs/runbook/2026-07-03-afcstuff-playwright-adapter-ops.md`.
- 사이트 재생성 (렌더 전용 · X 무접촉): `docs/runbook/2026-07-19-enrich-only-pass.md` §4.
