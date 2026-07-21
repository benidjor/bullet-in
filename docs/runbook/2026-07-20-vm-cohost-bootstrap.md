# VM 동거 부트스트랩 · 스케줄 운영 (2026-07-20)

bullet-in 을 seoulnow Oracle Free VM 에 함께 올려 (동거) systemd timer 로 하루 4회 무인 실행하는 절차와 일상 운영.
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
systemctl list-timers bullet-in.timer --no-pager              # NEXT 가 UTC 6시간 격자 + 지터
```

- 주기: UTC 0 · 6 · 12 · 18시 (+ 지터 최대 300초) — 기존 DAG `0 */6 * * *` 와 동일.
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

## 9. 참고

- 결정 배경: `docs/superpowers/specs/2026-07-20-deployment-mvp-track-design.md` §2.1 · §2.2.
- X 쿠키 절차: `docs/runbook/2026-07-03-afcstuff-playwright-adapter-ops.md`.
- 사이트 재생성 (렌더 전용 · X 무접촉): `docs/runbook/2026-07-19-enrich-only-pass.md` §4.
