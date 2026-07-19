# SP-C 스케줄 상시 가동 구현 계획 — seoulnow VM 동거 · systemd timer (2026-07-20)

> **For agentic workers:** 이 계획은 원격 VM 조작 · 시크릿 전송이 대부분이라 컨트롤러가 인라인으로 실행한다 (subagent 위임 없음). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** bullet-in 파이프라인을 seoulnow Oracle Free VM 에 함께 올리고, systemd timer 가 하루 4회 자동 실행하게 만들어 "맥을 꺼도 사이트가 갱신되는" 상태를 만든다.

**Architecture:** VM 에 저장소 + 자체 docker compose (mongo · mariadb) 를 배치하고, oneshot service (`uv run python -m bullet_in.run`) + timer (UTC 6시간 간격 · Persistent) + OnFailure Discord 알림 유닛으로 스케줄한다.
유닛 파일은 저장소 `infra/systemd/` 에 커밋해 SoT 로 두고, VM 에는 설치 스크립트로 반영한다 (seoulnow `install-units.sh` 패턴 차용).

**Tech Stack:** systemd (service · timer) · docker compose · uv · Playwright chromium (linux arm64).

**Spec:** `docs/superpowers/specs/2026-07-20-deployment-mvp-track-design.md` §2.1 · §2.2 · §3.2 · §4.

## 선행 게이트 실측 (2026-07-20 완료 — 3-b 동거 확정)

- VM: ubuntu@155.248.164.17 (Oracle A1 arm64 · Ubuntu · KST) — 접속 키 `~/.ssh/seoulnow_deploy`.
- 메모리: 총 23Gi · available **11Gi** — bullet-in 추가분 (상시 ~1GB + 회차 피크 ~1.5GB) 수용 충분.
- 디스크: 48G 중 33G 여유. 포트: 27017 · 3306 미사용 (충돌 없음). ubuntu 는 docker 그룹 (sudo 불요).
- 스왑 0B — 당장 불요, 관찰 항목으로 기록.

## Global Constraints

- seoulnow 무영향 원칙 — seoulnow 의 compose · systemd 유닛 · 파일을 일절 건드리지 않는다.
- 원격 실행은 전부 `ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17` 경유, VM 쪽 작업 디렉터리는 `/home/ubuntu/bullet-in`.
- 시크릿 (.env · x_cookies.json) 은 scp 로만 전송 — 커밋 금지 (기존 gitignore 준수).
- 타이머 주기는 기존 DAG 와 동일 (UTC 0 · 6 · 12 · 18시) — Gemini 무료 티어 멱등 누적 설계 전제 유지.
- 커밋 컨벤션 · 서식 규칙은 저장소 표준 (§1.1 · §2.2) 그대로.

## 파일 구조 (저장소 커밋 대상)

- 생성: `infra/systemd/bullet-in.service` — 회차 oneshot (compose 기동 → run.py).
- 생성: `infra/systemd/bullet-in.timer` — UTC 6시간 간격 · Persistent · 지터 300초.
- 생성: `infra/systemd/bullet-in-fail-notify.service` — OnFailure Discord 알림.
- 생성: `infra/systemd/install-units.sh` — 유닛 설치 · 갱신 스크립트 (VM 에서 실행).
- 생성: `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` — 부트스트랩 · 운영 런북 (Task 6 에서 실측 출력과 함께 작성).

---

### Task 1: systemd 유닛 파일 + 설치 스크립트 (로컬 작성 · 커밋)

- [ ] `infra/systemd/bullet-in.service`:

```ini
[Unit]
Description=bullet-in pipeline cycle (collect -> enrich -> gate -> site)
Wants=docker.service network-online.target
After=docker.service network-online.target
OnFailure=bullet-in-fail-notify.service

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/bullet-in
EnvironmentFile=/home/ubuntu/bullet-in/.env
ExecStartPre=/usr/bin/docker compose up -d --wait
ExecStartPre=/bin/sleep 10
ExecStart=/home/ubuntu/.local/bin/uv run python -m bullet_in.run --concurrency 8
TimeoutStartSec=1800
```

  - `--wait` + `sleep 10`: 재부팅 콜드 스타트에서 mariadb 가 기동 직후 접속을 못 받는 틈을 흡수 (헬스체크 미정의 이미지 대비).
  - `TimeoutStartSec=1800`: 평시 회차는 수 분 — 30분 초과는 행 (hang) 으로 보고 실패 처리 → OnFailure 알림.

- [ ] `infra/systemd/bullet-in.timer`:

```ini
[Unit]
Description=bullet-in 4x daily (same cadence as DAG: 0 */6 UTC)

[Timer]
OnCalendar=*-*-* 00/6:00:00 UTC
Persistent=true
RandomizedDelaySec=300

[Install]
WantedBy=timers.target
```

  - `Persistent=true`: 재부팅으로 놓친 회차를 부팅 후 보정 실행.
  - `RandomizedDelaySec=300`: 정각 고정 접촉 패턴 완화 (X 자동화 탐지 노출 감소) + 부하 분산.

- [ ] `infra/systemd/bullet-in-fail-notify.service`:

```ini
[Unit]
Description=bullet-in cycle failure alert (Discord)

[Service]
Type=oneshot
User=ubuntu
WorkingDirectory=/home/ubuntu/bullet-in
EnvironmentFile=/home/ubuntu/bullet-in/.env
ExecStart=/home/ubuntu/.local/bin/uv run python -c "from bullet_in.notify import send_alert; send_alert('bullet-in 회차 실패 (systemd)', 'bullet-in.service 실패 — VM 에서 journalctl -u bullet-in -n 100 확인', color=0xE74C3C)"
```

- [ ] `infra/systemd/install-units.sh`:

```bash
#!/usr/bin/env bash
# systemd 유닛 설치 · 갱신 — VM 의 저장소에서 실행 (sudo 필요). seoulnow install-units.sh 패턴.
set -euo pipefail
cd "$(dirname "$0")"
sudo cp bullet-in.service bullet-in.timer bullet-in-fail-notify.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bullet-in.timer
systemctl list-timers bullet-in.timer --no-pager
```

- [ ] 검증: `systemd-analyze verify` 는 VM 등재 시점 (Task 5) 에 수행. 로컬에서는 `bash -n infra/systemd/install-units.sh` 로 문법만 확인.
- [ ] 커밋: `feat(infra): systemd 유닛 3종 + 설치 스크립트 — VM 동거 스케줄` (트레일러 단독 Fable 5).

### Task 2: VM 부트스트랩 (uv · 저장소 · 의존성 · chromium)

- [ ] uv 설치: `curl -LsSf https://astral.sh/uv/install.sh | sh` → `~/.local/bin/uv --version` 확인.
- [ ] 저장소 배치: `git clone https://github.com/benidjor/bullet-in.git /home/ubuntu/bullet-in`.
- [ ] 의존성: `cd /home/ubuntu/bullet-in && uv sync --extra dev` (dev 포함 — VM 에서 pytest 검증 가능하게).
- [ ] Playwright: `uv run playwright install chromium` + `sudo uv run playwright install-deps chromium` (arm64 시스템 라이브러리).
- [ ] 검증: `uv run python -c "import bullet_in"` 정상 · `uv run playwright --version`.

### Task 3: 시크릿 전송 + compose 기동

- [ ] `scp .env x_cookies.json ubuntu@VM:/home/ubuntu/bullet-in/` (로컬 프로젝트 루트에서).
- [ ] `.env` 의 URL 이 127.0.0.1 기준인지 확인 (로컬과 동일 구성이므로 수정 없이 동작해야 함).
- [ ] `docker compose up -d` → `docker compose ps` 두 컨테이너 running.
- [ ] 검증: `uv run python -c "sqlalchemy 접속 1회"` 로 mariadb 응답 확인 (스키마는 run.py 의 ensure_schema 가 첫 실행에서 적용).

### Task 4: 수동 1회차 종단 실행 (스케줄 등재 전 게이트)

- [ ] `set -a; source .env; set +a; uv run python -m bullet_in.run --concurrency 8` 을 VM 에서 실행.
- [ ] 기대: 수집 성공 (소스별 카운트) · enrich 수행 (429 시 중단 · 다음 회차 누적은 정상 동작) · `site/` 생성 · 잔여 페이지 정리 로그.
- [ ] X 접촉 주의: 이 실행이 DC IP 에서의 첫 접촉 — 실패해도 소스 격리로 타 소스 무영향 (spec §2.4 의 수용된 리스크). 결과를 기록.
- [ ] seoulnow 무영향 확인: `free -h` 재실측 + seoulnow 컨테이너 상태 변화 없음.

### Task 5: 유닛 등재 + 타이머 활성

- [ ] VM 저장소를 main 최신으로 (`git pull --ff-only`) 한 뒤 `bash infra/systemd/install-units.sh`.
- [ ] `systemd-analyze verify /etc/systemd/system/bullet-in.*` 경고 없음.
- [ ] `systemctl list-timers bullet-in.timer` — 다음 발화 시각이 UTC 6시간 격자.
- [ ] 실패 알림 경로 검증: `sudo systemctl start bullet-in-fail-notify.service` 수동 1회 → Discord 수신 확인.
- [ ] 서비스 경로 검증: `sudo systemctl start bullet-in.service` 수동 트리거 1회 → `journalctl -u bullet-in` 정상 완주.

### Task 6: 무인 검증 계획 + 런북 + PR

- [ ] spec §4 의 "4회차 연속 자동 완주" 는 24시간 관찰이라 세션 내 완결 불가 — 검증 방법 (Discord 알림 부재 + ops 뷰 회차 이력 + `systemctl list-timers`) 을 런북에 명시하고 다음 세션 확인 항목으로 이월.
- [ ] `docs/runbook/2026-07-20-vm-cohost-bootstrap.md` 작성: 접속 정보 얻는 법 · 부트스트랩 절차 (Task 2~5 실측 출력 요약) · 일상 운영 (로그 보는 법 · 수동 트리거 · 유닛 갱신) · 실패 모드 (쿠키 만료 · OOM · 콜드 스타트) · 롤백 (timer disable).
- [ ] 전체 테스트 로컬 회귀 (`uv run pytest -q`) — infra · 문서만 추가라 무회귀 확인.
- [ ] 커밋 · push · PR 생성 (7섹션 · --body-file). 머지는 사용자.

## 완료 기준 (spec §4 대응)

- 세션 내: 수동 종단 1회차 완주 · 타이머 등재 · 실패 알림 실수신 · seoulnow 무영향 실측.
- 이월 (다음 세션): 무인 4회차 연속 완주 확인 — 이것이 SP-C 의 최종 닫힘 조건.

## 리스크 · 대응

- mariadb 콜드 스타트 레이스 → `--wait` + sleep 10 (Task 1). 재발 시 헬스체크 추가 검토.
- X 첫 DC IP 접촉 차단 → 소스 격리로 회차는 완주, SLO-5 알림 감지 → 폴백 (spec §2.4).
- Gemini 429 → 기존 설계 (중단 · 다음 회차 누적) 그대로 — 실패 아님.
- VM 메모리 압박 → 스왑 0 상태 관찰, 문제 시 스왑 파일 추가 (런북 실패 모드에 기재).
