# 런북 — fmkorea 맥 릴레이 (터널 · 보충 수집) 설치 · 검증 · 롤백

fmkorea 는 IP 차단으로 VM 직접 접속이 430 으로 강등되는 상태다 (`docs/troubleshooting/2026-07-24-fmkorea-vm-ip-persistent-430.md`).
이 런북은 맥을 주거 IP 릴레이로 써서 VM 이 SOCKS 프록시 경유로 fmkorea 에 접속하게 하는 절차다.
정기 회차 (systemd 타이머) 와 보충 수집 (맥 깨어남 트리거) 두 경로 모두를 다룬다.
SoT: `docs/superpowers/specs/2026-07-25-fmkorea-recovery-ornstein-x-design.md`.

## 0. 구성 요소

- `infra/mac-fmkorea-relay/com.bulletin.fmkorea-tunnel.plist` — 맥에서 상주하는 autossh 역SSH 터널.
  VM 의 로컬 포트 1080 을 맥의 SOCKS 동적 포워딩으로 연결한다.
- `infra/mac-fmkorea-relay/com.bulletin.fmkorea-supplement.plist` — 맥 깨어남 · 900 초 주기로 `supplement.sh` 를 실행하는 트리거.
  스크립트 내부 접촉 가드 (3 시간) 가 실제 fmkorea 접촉 빈도를 제한하므로 짧은 주기도 안전하다.
- `infra/mac-fmkorea-relay/supplement.sh` — 터널이 붙어 있을 때 VM 에서 보충 수집을 1 회 실행하는 원격 명령.
  실행 권한 (`chmod +x`) 이 커밋에 포함돼 있어 launchd 가 별도 설정 없이 직접 실행한다.

## 1. 설치 (맥)

```bash
brew install autossh
cp infra/mac-fmkorea-relay/*.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.bulletin.fmkorea-tunnel.plist
```

- 두 plist 는 절대 경로 (`/Users/aryijq/...`) 를 쓰므로 저장소 위치가 다르면 값을 맞춰 고친다.
- `launchctl load` 는 `~/Library/LaunchAgents/` 에 있는 plist 만 재부팅 후 자동 재등록한다.
  저장소 경로에서 바로 load 하면 현재 부팅 세션에만 등록되고, 재부팅 후 터널 · 트리거가 조용히 사라진다.
- `com.bulletin.fmkorea-supplement` 의 load 는 §5 (보충 수집 1 회 검증) 로 미룬다.
  그 단계의 RunAtLoad 최초 실행이 검증을 겸하기 때문이다.
- `com.bulletin.fmkorea-tunnel` 은 `KeepAlive` 로 상주하고, autossh 로그는 `/tmp/fmkorea-tunnel.err` 에 쌓인다.
- `com.bulletin.fmkorea-supplement` 은 `RunAtLoad` 로 로드 직후 1 회, 이후 900 초마다 실행을 시도한다.
  파이썬 `logging` 모듈은 기본적으로 stderr 로 출력하므로, "적재 N" 등 실행 로그는 `/tmp/fmkorea-supplement.err` 에 쌓이고, 순수 stdout 은 `/tmp/fmkorea-supplement.out` 에 쌓인다.
- plist 를 수정했을 때는 `~/Library/LaunchAgents/` 로 재복사한 뒤 `unload` → `load` 를 다시 실행해야 변경이 반영된다.

## 2. VM 코드 배포

맥 릴레이가 동작하려면 VM 쪽에 Task 1~3 의 코드 (proxy 주입 · 가드 · `collect_fmkorea` 모듈) 와
`httpx[socks]` 의존성이 먼저 반영돼 있어야 한다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -lc "cd /home/ubuntu/bullet-in && git pull && uv sync"'
```

## 3. supplement.sh 실행 권한

launchd 는 `supplement.sh` 를 직접 실행하므로 실행 비트가 없으면 트리거가 조용히 실패한다.
저장소에는 이미 100755 로 커밋돼 있지만, 배포 환경에 따라 clone 방식이 비트를 보존하지 않을 수 있어 재확인한다.

```bash
chmod +x infra/mac-fmkorea-relay/supplement.sh
```

## 4. 터널 로드 · 프록시 경유 확인

터널을 올린 뒤, VM 에서 SOCKS5 경유로 fmkorea 검색 페이지에 접속해 프록시가 실제로 붙는지 확인한다.
**직전 fmkorea 접촉으로부터 2 시간이 지난 뒤 1 회만** 실행한다 (접촉 예산 준수, 로컬 직접 접속으로 갈음 금지 — 발신 IP 가 다르다).

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "curl -s -o /dev/null -w '%{http_code}\n' --socks5-hostname 127.0.0.1:1080 \
   'https://www.fmkorea.com/search.php?mid=football_news&search_target=title&search_keyword=%EC%95%84%EC%8A%A4%EB%82%A0'"
# 기대: 200 (직접 접속이면 430)
```

## 5. 보충 수집 1 회 검증

```bash
launchctl load ~/Library/LaunchAgents/com.bulletin.fmkorea-supplement.plist
```

RunAtLoad 로 곧바로 1 회 실행되므로, 맥의 `/tmp/fmkorea-supplement.err` 로그와 VM DB 를 확인한다.
로그에 "적재 N" 대신 "보충 수집 스킵 — 마지막 접촉" 이 찍히면 3 시간 가드에 걸린 것이다.
이때는 VM 에서 `--force` 로 가드를 우회해 1 회만 수집한다 (직전 접촉 2 시간 대기는 그대로 지킨다).

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -lc "cd /home/ubuntu/bullet-in && set -a && source .env && set +a && export FMKOREA_PROXY=socks5://127.0.0.1:1080 && uv run python -m bullet_in.collect_fmkorea --force"'
```

## 6. VM `.env` 에 정기 회차용 프록시 등록

보충 경로의 `FMKOREA_PROXY` 는 `supplement.sh` 가 SSH 원격 명령 안에서 직접 `export` 하므로 누락될 수 없다.
반면 systemd 타이머로 도는 정기 회차는 이 export 를 거치지 않으므로, 정기 회차에도 프록시를 태우려면 VM `.env` 에 별도로 등록해야 한다.
미설정 상태로 두면 정기 회차는 계속 직접 접속 (430) 으로 강등된 채 동작한다 (기존 키워드 스킵 경로로 안전하게 degrade — 장애 아님).

```bash
# VM: /home/ubuntu/bullet-in/.env 에 추가
FMKOREA_PROXY=socks5://127.0.0.1:1080
```

systemd 서비스는 `EnvironmentFile=/home/ubuntu/bullet-in/.env` 로 이 값을 로드한다 (2026-07-25 실측 확인).
맥이 꺼져 터널이 없으면 정기 회차의 프록시 연결이 실패해 `httpx.HTTPError` 가 나고, `_discover` 의 키워드 스킵 강등 (기존 동작) 으로 안전하게 degrade 한다.

## 7. 검증 성공 기준

다음 세 가지를 모두 확인해야 검증 완료로 본다.

- VM 이 SOCKS 프록시 경유로 접속한 fmkorea 응답이 **200** (§4).
- 보충 수집 로그에 **"적재 N"** 문구 (N ≥ 0, 스크립트가 실행 자체는 완료했다는 근거).
- DB fmkorea 소스의 **`MAX(fetched_at)`** 이 실행 시각 이후로 갱신됨.

라이브 검증은 반드시 VM 기준으로 한다 — 로컬 맥에서 fmkorea 에 직접 접속해 200 이 나오는 것으로 갈음하지 않는다.
발신 IP 가 VM 과 다르므로, 로컬 성공이 VM 의 프록시 경유 성공을 보장하지 않는다.

재부팅 영속성도 별도로 확인한다.
맥을 재부팅한 뒤 `launchctl list | grep com.bulletin` 을 실행해, `com.bulletin.fmkorea-tunnel` · `com.bulletin.fmkorea-supplement` 두 서비스가 모두 남아 있는지 본다.

## 8. 롤백

정기 회차 · 보충 경로 모두를 프록시 도입 이전 상태로 되돌리는 절차다.

```bash
# 맥: launchd 언로드 · 복사본 삭제
launchctl unload ~/Library/LaunchAgents/com.bulletin.fmkorea-supplement.plist
launchctl unload ~/Library/LaunchAgents/com.bulletin.fmkorea-tunnel.plist
rm ~/Library/LaunchAgents/com.bulletin.fmkorea-supplement.plist
rm ~/Library/LaunchAgents/com.bulletin.fmkorea-tunnel.plist
```

```bash
# VM: .env 에서 FMKOREA_PROXY 제거
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  "cd /home/ubuntu/bullet-in && sed -i '/^FMKOREA_PROXY=/d' .env"
```

롤백 후 정기 회차는 프록시 없이 직접 접속을 시도해 430 으로 강등되고, 기존 키워드 스킵 경로로 되돌아간다 (spec §11 과 정합).
보충 수집 launchd 트리거도 더는 실행되지 않는다.

## 9. 참고

- 설계 근거 · 접촉 예산 · 가드 재설계: `docs/superpowers/specs/2026-07-25-fmkorea-recovery-ornstein-x-design.md`
- fmkorea VM IP 차단 진단: `docs/troubleshooting/2026-07-24-fmkorea-vm-ip-persistent-430.md`
- VM 접속 · 배포 절차: `docs/runbook/2026-07-20-vm-cohost-bootstrap.md`
