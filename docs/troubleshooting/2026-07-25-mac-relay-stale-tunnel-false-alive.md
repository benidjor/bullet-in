# 맥 릴레이 터널의 거짓 생존 — 포트 선체크는 통과하는데 실통신은 죽어 있음

fmkorea 소급 백필 (PR #134) 라이브 검증 중, 터널이 살아 있다는 신호 두 가지 (launchd PID · VM 포트 응답) 가
모두 정상인데 실제 프록시 통신은 전부 실패한 사례다.
생존 신호가 여러 겹으로 거짓이어서 진단 순서를 모르면 헤매기 쉬운 유형이라 기록한다.
해결 절차는 백필 런북 사전 확인에 반영됐다.

## 1. 증상

- 백필 실행 시 모든 키워드가 연결 실패로 스킵:
  `fmkorea 검색 실패 kw=... err=All connection attempts failed — 스킵`
- 그런데 직전 확인은 전부 정상이었다:
  맥 `launchctl list` 에 터널 PID 존재 · VM 에서 `nc -z 127.0.0.1 1080` 성공.
- 발생 맥락: 맥북이 sleep 됐다 깨어난 직후.

## 2. 원인

- 맥이 잠들면 SSH 세션의 실제 통신은 끊기지만 양쪽에 잔해가 남는다.
  - 맥 쪽: launchd 가 관리하는 터널 프로세스가 살아 있는 것처럼 보인다 (PID 존재 ≠ 터널 생존).
  - VM 쪽: sshd 가 역터널용 1080 리스너를 keepalive 타임아웃 전까지 유지한다.
    이 리스너가 TCP connect 를 받아 주므로 포트 체크가 성공한다.
- 결과: "PID 있음 + 포트 열림 + 데이터는 안 흐름" 상태.
  `collect_fmkorea.tunnel_alive` (TCP connect 선체크) 도 같은 이유로 통과한다 — 이 가드의 알려진 한계다.

## 3. 왜 심각하지 않은가 (fail-safe 확인)

- 선체크를 통과해도 실제 요청은 프록시 연결 단계에서 실패하므로 **fmkorea 에 닿지 않는다**.
  접촉 예산 소모 없이 "적재 0 · 안전 종료"로 끝난다 (2026-07-25 실측).
- 백필은 멱등이라 터널 복구 후 같은 명령을 다시 돌리면 된다.

## 4. 진단 · 복구 절차

- 실통신 검증은 fmkorea 가 아닌 대상으로 한다 (VM 에서):

```bash
curl -s --max-time 10 --socks5-hostname 127.0.0.1:1080 https://ifconfig.me
# 주거 IP 가 나오면 정상 · 무응답이면 거짓 생존
```

- 거짓 생존이면 맥에서 터널을 강제 재기동한다:

```bash
launchctl kickstart -k gui/$(id -u)/com.bulletin.fmkorea-tunnel
```

- 재기동 후 위 curl 로 재검증하고 나서 백필 · 보충 수집을 재개한다.

## 5. 교훈

- 터널 생존 판정은 3단계다: PID (프로세스) → 포트 (리스너) → **실통신 (데이터)**.
  앞 두 단계는 sleep 직후 거짓 양성이 나므로 접촉량이 큰 작업 전에는 반드시 3단계까지 확인한다.
- `tunnel_alive` 가드를 실통신 검증으로 강화하는 것은 과설계로 판단해 두지 않았다
  — 가드의 실패 모드가 fail-safe (접촉 없이 종료 · 재실행 멱등) 이기 때문이다.

## 6. 참고

- 백필 런북 (사전 확인 절차 반영): `docs/runbook/2026-07-25-fmkorea-backfill-paging.md`
- 맥 릴레이 구성: `docs/runbook/2026-07-25-fmkorea-mac-relay-setup.md`
- 보충 수집 가드: `src/bullet_in/collect_fmkorea.py` (`tunnel_alive`)
