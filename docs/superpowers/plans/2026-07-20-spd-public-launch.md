# SP-D 공개 전환 구현 계획 (2026-07-20)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 회차 끝 site/ 를 Cloudflare Pages 에 자동 배포하고, README 를 실서비스와 일치시킨 뒤, 배포 전 게이트 체크리스트를 통과시켜 MVP 를 공개한다 (spec §3.3).

**Architecture:** VM 회차 (systemd oneshot) 끝에 `ExecStartPost=` 로 wrangler direct upload 를 붙이는 push 모델.
저장소에는 배포 스크립트 + 유닛 수정 + 문서만 들어가고, 산출물 (site/) 은 저장소를 거치지 않는다.
배포 실패는 기존 `OnFailure=` → Discord 경로가 그대로 잡는다.

**Tech Stack:** bash · systemd · Node 22 + wrangler 4 (Pages direct upload) · 기존 파이프라인 무변경.

## 확정 결정 (2026-07-20 사용자 승인)

- 배포 방식: A안 — 회차 끝 VM 에서 wrangler 직접 push (GitHub 연동 빌드 제외 — 공개 repo 히스토리에 발췌 본문 영구 잔존).
- 프로젝트명: `bullet-in` → https://bullet-in.pages.dev (선점 시 폴백 `bulletin-afc`).
- README 정비: B안 — 정합 갱신 (어긋난 서술만 수술적 정정 + 공개 URL + 공개 규칙 점검).

## Global Constraints

- 공개 저장소 규칙: README · PR · 커밋에 Claude 서명 · 포트폴리오/이직 프레이밍 · 회사 실명 금지 (CLAUDE.md).
- 문서 서식: 컨벤션 §2.2 — `→` · `—` 는 줄 시작, 한 줄 = 한 문장, `·` · `+` · 여는 괄호 양옆 띄우기 (코드 · URL · 경로 제외).
- 커밋: `<type>(<scope>): 한국어 제목` + 도입 1–2문장 + 명사형 불릿 + `Refs:` + `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- git 신원: `benidjor <94089198+benidjor@users.noreply.github.com>`.
- PR 머지는 사용자가 직접 — 세션은 push + PR 생성까지.
- 운영 SoT = seoulnow VM (`ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17`, 저장소 `~/bullet-in`) — 데이터 · 운영 검증은 VM 에서.
- X 수동 접촉 금지 — 수집 상태는 mart 신규 행으로만 판단.
- 분기 전 `git log origin/main..main` 으로 로컬 main 이 앞서 있지 않은지 확인.
- 사용자 개입 지점: Task 2 시작 전 Cloudflare API 토큰 (Account / Cloudflare Pages / Edit 최소 권한) + Account ID 필요.

## 선행 게이트 상태 (계획 시점 실측)

- 무인 회차 1/4 완주 (2026-07-20 09:01 KST 트리거 · 정상 종료) — 4회차 게이트는 Task 6 에서 최종 확인 (내일 03시 KST 회차 후).
- X (DC IP) 수집 정상 — x_afcstuff 48h 신규 10건, 최신 행 = 오늘 무인 회차.
- fmkorea 430 지속 (키워드 3건 스킵, 회차는 완주) — 관찰 항목 유지, SP-D 차단 사유 아님.

---

### Task 1: 배포 스크립트 `infra/deploy-site.sh` + 유닛 `ExecStartPost` 연결

**Files:**
- Create: `infra/deploy-site.sh`
- Modify: `infra/systemd/bullet-in.service`

**Interfaces:**
- Consumes: 회차가 생성한 `site/` (index.html + article/*.html + ops.html), `.env` 의 `CLOUDFLARE_API_TOKEN` · `CLOUDFLARE_ACCOUNT_ID` (Task 2 에서 VM 에 주입).
- Produces: `infra/deploy-site.sh` — 인자 없음, 성공 시 exit 0. Task 2 (수동 1회 배포) 와 Task 3 (자동 연결) 이 이 스크립트를 그대로 실행한다.

- [ ] **Step 1: 배포 스크립트 작성**

```bash
#!/usr/bin/env bash
# 회차 끝 site/ -> Cloudflare Pages 직접 업로드 (배포 spec §2.1 · SP-D).
# systemd bullet-in.service 의 ExecStartPost 에서 실행 — 실패 시 유닛 실패 -> OnFailure 알림.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN 미설정 — .env 확인}"
: "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID 미설정 — .env 확인}"

# 오배포 방어: 산출물이 없거나 비정상적으로 적으면 (렌더 실패 잔해) 배포하지 않음.
# 기준 50 은 현재 정상 산출물 (약 210 파일) 의 1/4 수준 — write_site 오삭제 방어 (spec §2.6) 와 같은 철학.
[ -f site/index.html ] || { echo "site/index.html 없음 — 배포 중단"; exit 1; }
page_count=$(find site -name '*.html' | wc -l)
if [ "$page_count" -lt 50 ]; then
  echo "site HTML ${page_count}건 (< 50) — 비정상 산출물로 판단, 배포 중단"
  exit 1
fi

export PATH="/usr/local/bin:/usr/bin:$PATH"
wrangler pages deploy site --project-name bullet-in --branch main --commit-dirty=true
```

프로젝트명 폴백: Task 2 에서 `bullet-in` 이 선점돼 있으면 이 스크립트의 `--project-name` 을 `bulletin-afc` 로 함께 바꾼다.

- [ ] **Step 2: 실행 권한 + 문법 검사**

Run: `chmod +x infra/deploy-site.sh && bash -n infra/deploy-site.sh && echo OK`
Expected: `OK`

- [ ] **Step 3: 가드 동작 검증 (토큰 미설정 → 즉시 실패)**

Run: `env -u CLOUDFLARE_API_TOKEN bash infra/deploy-site.sh; echo "exit=$?"`
Expected: `CLOUDFLARE_API_TOKEN 미설정` 메시지 + `exit=1` — 실제 배포 시도 없이 종료.

- [ ] **Step 4: 가드 동작 검증 (산출물 부족 → 배포 중단)**

Run:

```bash
tmp=$(mktemp -d) && mkdir -p "$tmp/infra" && cp infra/deploy-site.sh "$tmp/infra/" \
  && mkdir "$tmp/site" && touch "$tmp/site/index.html" \
  && CLOUDFLARE_API_TOKEN=x CLOUDFLARE_ACCOUNT_ID=x bash "$tmp/infra/deploy-site.sh"; echo "exit=$?"
rm -rf "$tmp"
```

Expected: `site HTML 1건 (< 50) — 비정상 산출물로 판단, 배포 중단` + `exit=1` — wrangler 호출 전에 멈춤.

- [ ] **Step 5: 유닛에 ExecStartPost 추가**

`infra/systemd/bullet-in.service` 의 `ExecStart=` 다음 줄에 추가:

```ini
ExecStart=/home/ubuntu/.local/bin/uv run python -m bullet_in.run --concurrency 8
ExecStartPost=/home/ubuntu/bullet-in/infra/deploy-site.sh
```

oneshot 유닛은 `ExecStartPost` 실패도 유닛 실패로 집계되어 `OnFailure=` 알림이 발동한다.
`TimeoutStartSec=1800` 은 배포 (약 1분) 를 포함해도 여유.

- [ ] **Step 6: 커밋**

```bash
git add infra/deploy-site.sh infra/systemd/bullet-in.service
git commit -m "feat(infra): 회차 끝 Cloudflare Pages 자동 배포 — wrangler 직접 push"
```

본문: 도입 (spec §2.1 push 모델 · OnFailure 재사용) + 불릿 (스크립트 가드 2종 · ExecStartPost 연결) + `Refs: #97` + Co-Authored-By 트레일러.

---

### Task 2: VM 부트스트랩 — node + wrangler 설치 · Pages 프로젝트 생성 · 수동 1회 배포

**사용자 개입 (시작 전):** Cloudflare API 토큰 (Custom token — Account / Cloudflare Pages / Edit 권한만) + Account ID (대시보드 우측 사이드바) 를 받는다.

**Files:**
- Modify: `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` (Pages 배포 섹션 추가)
- VM 전용 (커밋 안 됨): `~/bullet-in/.env` 에 `CLOUDFLARE_API_TOKEN` · `CLOUDFLARE_ACCOUNT_ID` 추가

**Interfaces:**
- Consumes: Task 1 의 `infra/deploy-site.sh` (임시 scp 반영 — Task 3 참조).
- Produces: Pages 프로젝트 `bullet-in` + 공개 URL https://bullet-in.pages.dev, wrangler 실행 가능한 VM.

- [ ] **Step 1: Node 22 + wrangler 4 설치 (VM)**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
sudo apt-get install -y nodejs
sudo npm install -g wrangler@4
node --version && wrangler --version
```

Expected: `v22.x` · `4.x`.
설치 전후 `free -h` 로 seoulnow 무영향 확인 (디스크 약 200MB · 상주 메모리 0).

- [ ] **Step 2: VM .env 에 Cloudflare 크리덴셜 추가**

```bash
# VM 에서 — 값은 사용자 제공분
printf 'CLOUDFLARE_API_TOKEN=<토큰>\nCLOUDFLARE_ACCOUNT_ID=<계정ID>\n' >> ~/bullet-in/.env
```

`.env` 는 systemd `EnvironmentFile=` 로 유닛의 모든 Exec 단계에 주입되므로 별도 배선 불필요.

- [ ] **Step 3: Pages 프로젝트 생성**

```bash
cd ~/bullet-in && set -a && source .env && set +a
wrangler pages project create bullet-in --production-branch main
```

Expected: `Successfully created the 'bullet-in' project` + `bullet-in.pages.dev` 주소.
이름 선점 시: `bulletin-afc` 로 재시도하고 `infra/deploy-site.sh` 의 `--project-name` 도 같이 수정.

- [ ] **Step 4: 수동 1회 배포 + 접속 확인**

```bash
# VM 에서 (env 로드된 셸)
./infra/deploy-site.sh
```

Expected: `Deployment complete!` + 배포 URL 출력.

로컬 맥에서 (외부 네트워크 관점):

```bash
curl -s https://bullet-in.pages.dev/ | grep -o '<title>[^<]*'
curl -s -o /dev/null -w '%{http_code}\n' https://bullet-in.pages.dev/article/$(ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'ls ~/bullet-in/site/article | head -1')
```

Expected: 인덱스 title 출력 + 상세 페이지 `200`.

- [ ] **Step 5: 런북에 Pages 배포 섹션 추가**

`docs/runbook/2026-07-20-vm-cohost-bootstrap.md` §8 (참고) 앞에 새 섹션:

```markdown
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
```

(기존 §8 참고는 §9 로 밀린다.)

- [ ] **Step 6: 커밋**

```bash
git add docs/runbook/2026-07-20-vm-cohost-bootstrap.md
git commit -m "docs(runbook): VM 런북에 Pages 배포 셋업 · 진단 절차 추가"
```

---

### Task 3: 자동 배포 연결 — 유닛 임시 반영 + 다음 회차 자동 배포 확인

머지 전 라이브 검증이 필요하므로 (셀렉터 드리프트 교훈과 같은 원칙), 브랜치 파일을 VM 에 임시 반영해 실제 회차로 검증한다.
머지 후 `git pull` + `install-units.sh` 재실행으로 정식 반영해 VM 상태 = main 을 회복한다 (런북 §5 절차).

**Files:**
- VM 전용: `/etc/systemd/system/bullet-in.service` (install-units.sh 경유 갱신)

**Interfaces:**
- Consumes: Task 1 스크립트 · 유닛, Task 2 의 Pages 프로젝트 · 크리덴셜.
- Produces: 회차 → 배포 자동 연결 (이후 태스크는 손대지 않음).

- [ ] **Step 1: 브랜치 파일 임시 반영 (scp)**

```bash
scp -i ~/.ssh/seoulnow_deploy infra/deploy-site.sh ubuntu@155.248.164.17:~/bullet-in/infra/
scp -i ~/.ssh/seoulnow_deploy infra/systemd/bullet-in.service ubuntu@155.248.164.17:~/bullet-in/infra/systemd/
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'chmod +x ~/bullet-in/infra/deploy-site.sh && cd ~/bullet-in/infra/systemd && ./install-units.sh'
```

Expected: `list-timers` 출력에 다음 회차 (UTC 정각 6시간 격자) 표시.

- [ ] **Step 2: 다음 회차에서 자동 배포 확인**

다음 timer 회차 (15:04 또는 21:04 KST) 이후:

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'journalctl -u bullet-in.service --no-pager -n 40 --output=short-iso | grep -E "Finished|Deployment|deploy"'
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'cd ~/bullet-in && set -a && source .env && set +a && wrangler pages deployment list --project-name bullet-in 2>/dev/null | head -5'
```

Expected: `Finished bullet-in.service` + 배포 성공 로그, deployment list 최신 항목 시각 = 방금 회차.
실패 시: 유닛이 실패로 집계되어 Discord 알림이 왔는지 교차 확인 (알림 경로 실증을 겸함) 후 원인 진단.

---

### Task 4: README 정합 갱신 + 스크린샷 교체

**Files:**
- Modify: `README.md`
- Replace: `docs/assets/serving-page-live.png` · `docs/assets/article-detail-live.png`

**Interfaces:**
- Consumes: Task 2 의 공개 URL (라이브 페이지를 스크린샷 원본으로 사용).
- Produces: 실서비스와 일치하는 공개 README.

- [ ] **Step 1: 공개 URL 추가 (제목 직하)**

기존:

```markdown
> 영국 현지 언론 · ITK (X)의 Arsenal FC 소식을 매일 병렬 수집하고, 공신력으로 스코어링 · 중복제거한 뒤 LLM으로 번역 · 요약하여 신뢰도순으로 보여주는 뉴스 수집 파이프라인.
```

변경 (다음 줄에 추가):

```markdown
> 영국 현지 언론 · ITK (X)의 Arsenal FC 소식을 매일 병렬 수집하고, 공신력으로 스코어링 · 중복제거한 뒤 LLM으로 번역 · 요약하여 신뢰도순으로 보여주는 뉴스 수집 파이프라인.
>
> **공개 서비스**: https://bullet-in.pages.dev — VM 스케줄이 하루 4회 자동 수집 · 배포.
```

- [ ] **Step 2: §2 오케스트레이션 서술 정정**

기존 (아키텍처 코드 블록 마지막 줄):

```
오케스트레이션: Airflow (2.9 구축 → 3.0 마이그레이션) 가 전 단계를 하루 4회 조율
```

변경:

```
스케줄: systemd timer (VM) 가 전 단계를 하루 4회 실행 · 회차 끝 Cloudflare Pages 자동 배포
        Airflow DAG (2.9 구축 → 3.0 마이그레이션) 는 확장 자산으로 보존
```

- [ ] **Step 3: §5 기술 스택 표의 Airflow 행 정정**

기존:

```markdown
| 오케스트레이션 | **Airflow 3.0** | 하루 4회 DAG. 2.9→3.0 마이그레이션 직접 수행 ([docs/MIGRATION.md](docs/MIGRATION.md)) |
```

변경:

```markdown
| 스케줄 · 배포 | **systemd timer + wrangler** | oneshot 회차 하루 4회 · OnFailure Discord 알림 · 회차 끝 Pages 직접 업로드. Airflow DAG (2.9→3.0 [마이그레이션](docs/MIGRATION.md))는 확장 자산으로 보존 |
```

- [ ] **Step 4: 상세 페이지 캡션 · §9 서빙 원칙에 차등 서빙 반영**

캡션 기존:

```markdown
> 기사 상세. 3줄 요약 · 본문 전문 번역 · 인라인 이미지 · 기자 바이라인.
```

변경:

```markdown
> 기사 상세. 3줄 요약 · 소스별 차등 서빙 (언론사 = 발췌 + 원문 링크, X · 공식 = 전문) · 기자 바이라인.
```

§9 마지막 불릿 기존:

```markdown
- 원문 전체 재배포가 아니라 메타데이터 · 요약 · 원문 링크 중심으로 서빙.
```

변경:

```markdown
- 원문 전체 재배포가 아니라 메타데이터 · 요약 · 원문 링크 중심으로 서빙.
- 소스 성질에 비례한 차등 서빙 — 언론사 기사는 요약 + 짧은 발췌 + 원문 링크, 수십 단어 트윗과 구단 공식 발표문만 전문, 퍼가기 금지 커뮤니티는 헤드라인만.
```

- [ ] **Step 5: §8 한계 & 향후 갱신**

기존:

```markdown
- 현재는 얇은 정적 뷰 (수집 현황은 ops 뷰로 제공). 향후: 사용자 구독, AWS 배포.
```

변경:

```markdown
- 현재는 정적 서빙 (수집 현황은 ops 뷰로 제공). 향후: 방문 분석용 이벤트 로그, 사용자 구독.
```

- [ ] **Step 6: 스크린샷 교체 (라이브 페이지 기준)**

```bash
uv run playwright screenshot --viewport-size=1440,900 --wait-for-timeout=2000 \
  https://bullet-in.pages.dev/ docs/assets/serving-page-live.png
# 상세는 발췌 모드가 보이는 언론사 기사 (excerpt-note 포함 페이지) 를 골라 촬영
uv run playwright screenshot --viewport-size=1440,900 --wait-for-timeout=2000 \
  "https://bullet-in.pages.dev/article/<언론사 기사 hash>.html" docs/assets/article-detail-live.png
```

촬영 후 이미지를 열어 발췌 안내 문구 ( "요약과 앞부분 발췌만 제공" ) 가 화면에 보이는지 확인.

- [ ] **Step 7: 공개 규칙 점검**

Run: `grep -inE "claude|anthropic|포트폴리오|이직|취업" README.md; echo "exit=$?"`
Expected: `exit=1` (매치 없음).
회사 실명은 수동 육안 점검 (grep 패턴화 곤란) — README 전문을 한 번 통독.

- [ ] **Step 8: 커밋**

```bash
git add README.md docs/assets/serving-page-live.png docs/assets/article-detail-live.png
git commit -m "docs(readme): 실서비스 정합 갱신 — 공개 URL · systemd 운영 · 차등 서빙 반영"
```

---

### Task 5: X 폴백 절차 문서화 + 배포 전 게이트 체크리스트 실행

**Files:**
- Modify: `docs/runbook/2026-07-03-afcstuff-playwright-adapter-ops.md` (§실패 모드에 폴백 절차 구체화)

**Interfaces:**
- Consumes: VM 의 현재 site/ · mart (게이트 실측 대상).
- Produces: 게이트 체크 결과 (PR 본문 검증 섹션에 기록) · X 폴백 절차 SoT.

- [ ] **Step 1: X 폴백 절차 구체화**

`docs/runbook/2026-07-03-afcstuff-playwright-adapter-ops.md` §실패 모드 · 진단의 폴백 언급 줄 뒤에 추가:

```markdown
### 폴백 절차 — 소스 비활성 (배포 spec §2.4)

차단 · 쿠키 만료가 SLO-5 (X 24h) 알림으로 감지되고 재추출로도 회복되지 않으면:

1. `config/sources.yaml` 의 `x_afcstuff` 항목에 `enabled: false` 지정 → 커밋 · 머지.
2. VM 에서 `cd ~/bullet-in && git pull --ff-only` — 다음 회차부터 X 수집 제외.
3. 기존 트윗 페이지는 mart 에 남아 있으므로 서빙 유지 — 신규 수집만 멈춘다.
4. 재활성: 쿠키 재추출 (§사전 준비) 후 `enabled: true` 되돌리고 같은 경로로 반영.
```

- [ ] **Step 2: 게이트 ① 잔여 페이지 — 파일 수 = DB 행 수 (VM)**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'cd ~/bullet-in \
  && ls site/article/*.html | wc -l \
  && URL=$(grep "^MARIADB_URL=" .env | cut -d= -f2-) \
  && USER=$(echo "$URL" | sed -E "s|.*//([^:]+):.*|\1|") && PASS=$(echo "$URL" | sed -E "s|.*//[^:]+:([^@]+)@.*|\1|") && DB=$(echo "$URL" | sed -E "s|.*/([^/?]+)(\?.*)?$|\1|") \
  && docker exec bullet-in-mariadb-1 mariadb -u"$USER" -p"$PASS" "$DB" -N -e "SELECT COUNT(*) FROM articles"'
```

Expected: 두 숫자 일치.

- [ ] **Step 3: 게이트 ② 차등 서빙 — 소스군별 상세 페이지 마커 (VM)**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'cd ~/bullet-in \
  && echo "excerpt-note 포함 (언론사, 0 이상이어야 함):" && grep -l "excerpt-note" site/article/*.html | wc -l \
  && echo "x_afcstuff 상세에 excerpt-note 없어야 함 (0):" \
  && URL=$(grep "^MARIADB_URL=" .env | cut -d= -f2-) \
  && USER=$(echo "$URL" | sed -E "s|.*//([^:]+):.*|\1|") && PASS=$(echo "$URL" | sed -E "s|.*//[^:]+:([^@]+)@.*|\1|") && DB=$(echo "$URL" | sed -E "s|.*/([^/?]+)(\?.*)?$|\1|") \
  && for h in $(docker exec bullet-in-mariadb-1 mariadb -u"$USER" -p"$PASS" "$DB" -N -e "SELECT content_hash FROM articles WHERE source_id=\"x_afcstuff\" LIMIT 5"); do grep -c "excerpt-note" "site/article/$h.html" || true; done'
```

Expected: 언론사 발췌 페이지 다수 (>0) · 트윗 페이지 5건 모두 0.

- [ ] **Step 4: 게이트 ③ SLO 알림 경로 — 기실증 기록 확인**

SP-C 에서 OnFailure → Discord 실발송이 이미 실증됐는지 `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` §실패 모드를 확인하고, 미실증이면 Task 3 Step 2 의 실패 교차 확인 또는 1회 강제 실패 (`sudo systemd-run --unit=bullet-in-test ... false` 대신 유닛 ExecStart 임시 오타는 금지 — `sudo systemctl start bullet-in-fail-notify.service` 직접 기동으로 알림 경로만 검증) 로 확인.
Discord 수신 여부는 사용자 확인 항목.

- [ ] **Step 5: 게이트 ④ ops.html 공개 적합성 확인**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'grep -oE "(token|password|webhook|api_key|mongodb://|mysql://)[^\"<]*" ~/bullet-in/site/ops.html | head; echo "exit=$?"'
```

Expected: 매치 없음 (`exit=1`) — 집계 수치만 있으면 공개 무방.
시크릿 유사 문자열이 나오면 배포 전 렌더에서 제거하고 재검.

- [ ] **Step 6: 커밋**

```bash
git add docs/runbook/2026-07-03-afcstuff-playwright-adapter-ops.md
git commit -m "docs(runbook): X 폴백 절차 구체화 — 비활성 · 재활성 명령 단위"
```

게이트 ①~④ 실측 결과는 PR 본문 검증 섹션에 수치로 기록한다.

---

### Task 6: SP-C 4회차 게이트 최종 확인 + MVP 공개 확정 + PR

4회차 게이트는 시간이 채워야 하는 조건이라 (마지막 회차 = 내일 03:04 KST 무렵) 이 태스크만 다음 날로 걸친다.

**Files:**
- 없음 (검증 + PR 만).

- [ ] **Step 1: 무인 4회차 연속 완주 확인 (VM)**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'journalctl -u bullet-in.service --no-pager --output=short-iso | grep -cE "Finished bullet-in"; journalctl -u bullet-in.service --no-pager --output=short-iso | grep -E "Failed|failure" | head'
```

Expected: Finished ≥ 4 (연속 · 6시간 격자) · Failed 없음.
freshness 이력 교차: `source_freshness` 의 checked_at 이 UTC 0 · 6 · 12 · 18 격자로 4건 쌓였는지 (Task 5 Step 2 의 DB 접속 패턴 재사용).
실패 회차 존재 시: SP-D 공개를 멈추고 원인 진단 먼저 (systematic-debugging).

- [ ] **Step 2: Discord 실패 알림 부재 — 사용자 확인**

사용자에게 지난 24h Discord 실패 알림 부재를 확인 요청 (세션은 접근 불가).

- [ ] **Step 3: MVP 완료 정의 검증 — 외부 접속 = 최신 회차 (spec §4)**

로컬 맥에서:

```bash
curl -s https://bullet-in.pages.dev/ops.html | grep -oE "2026-[0-9]{2}-[0-9]{2}[ T][0-9:]{5,8}" | head -3
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'grep -oE "2026-[0-9]{2}-[0-9]{2}[ T][0-9:]{5,8}" ~/bullet-in/site/ops.html | head -3'
```

Expected: 두 출력 일치 = 공개 URL 이 VM 최신 회차를 그대로 반영.

- [ ] **Step 4: 브랜치 · PR 생성**

```bash
git log origin/main..main   # 비어 있어야 함 — 앞서 있으면 분기 전 정리
git checkout -b feat/spd-public-launch   # Task 1 시작 전에 이미 분기했다면 생략
git push -u origin feat/spd-public-launch
gh pr create --title "feat(infra): SP-D 공개 전환 — Pages 자동 배포 · README 정합 · 공개 게이트" --body-file <(...)
```

PR 본문: 7섹션 한국어 · pull_request_template.md 주석 세칙 대조 · 게이트 ①~④ + 4회차 실측 수치를 검증 섹션에 기록 · Claude 서명 금지.
머지는 사용자 — 세션은 여기서 대기.

- [ ] **Step 5: 머지 후 VM 정식 반영**

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'cd ~/bullet-in && git pull --ff-only && cd infra/systemd && ./install-units.sh'
```

Expected: VM 상태 = main (임시 scp 반영분이 정식 이력으로 대체됨).
이후 첫 회차에서 자동 배포 1회 재확인하면 SP-D 종료 = MVP 완료 (spec §1.1).

---

## Self-Review 결과

- spec §3.3 대조: Pages 자동 배포 (Task 1~3) · README 정비 (Task 4) · 게이트 체크리스트 (Task 5) · 공개 = URL 확정 (Task 2 Step 3 · Task 6 Step 3) — 누락 없음.
- spec §4 SP-D 검증 기준 (외부 접속 = 최신 회차) 은 Task 6 Step 3 이 담당.
- 브랜치 분기는 Task 1 시작 전 (`git checkout -b feat/spd-public-launch`) — Global Constraints 의 분기 전 확인 선행.
