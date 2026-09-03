# systemd 가 판정기를 죽였을 자리 — `ExecStopPost` 의 정지 시간 예산 (2026-09-04)

배포 자동화의 판정기 (`bullet_in.deploy judge`) 는 회차 유닛의 `ExecStopPost=` 로 돈다.
계획서 코드대로라면 판정기의 최악 경로가 100초를 넘는데, `ExecStopPost=` 는 `TimeoutStopSec=` (기본 90초) 의 제한을 받는다.
라이브가 응답하지 않는 바로 그 상황에서 systemd 가 판정기를 죽여 성공한 회차를 실패로 찍었을 것이다.
브랜치 전체 리뷰가 머지 전에 잡았다.

## 1. 증상 (일어났다면 이렇게 보였을 것)

1. 회차가 성공하고 배포가 나간다.
2. 판정기가 라이브의 `build.json` 을 받는데 Cloudflare 가 응답하지 않아 20초 타임아웃이 세 번, 그 사이 대기 20초가 두 번 걸린다.
   합이 100초이고 여기에 `uv run` 기동 시간이 붙는다.
3. 90초에 systemd 가 판정기를 `SIGTERM` 으로 죽이고 유닛 결과를 `timeout` 으로 바꾼다.
4. `OnFailure=` 가 사고 채널에 「회차 실패」 를 낸다.
   회차는 성공했는데 알림은 실패다.
5. 판정기가 `save_state` 전에 죽어 「표지 불일치」 알림은 사라지고 `pending` 은 남는다.
   다음 회차가 다시 판정하므로 자가 복구는 되지만, 그 사이 사람은 헛된 실패 알림을 좇는다.

## 2. 원인

`ExecStopPost=` 명령은 유닛의 정지 단계에 속하고 정지 단계 전체가 `TimeoutStopSec=` 안에 끝나야 한다.
유닛 파일에는 `TimeoutStartSec=1800` 만 있었고 정지 시간은 기본값 90초였다.

판정기의 시간은 설계에서 정한 값의 합이다.
표지 대조는 「배포 직후 최상위 도메인이 잠깐 옛 것을 돌려준다」 는 실측 때문에 20초 간격으로 3회 다시 받는다 (스펙 §6.1).
httpx 타임아웃도 20초다.
둘을 곱하면 90초를 넘는데, 스펙과 계획서 어디에도 정지 시간 예산이 없었다.

작업 단위로 여섯 번 나눠 한 리뷰는 각자의 diff 만 봤다.
유닛 파일을 고친 작업과 재시도 상수를 정한 작업이 달라서 둘을 곱해 볼 자리가 없었다.

## 3. 해결

`infra/systemd/bullet-in.service` 에 두 가지를 더했다.

```ini
ExecStopPost=-/home/ubuntu/.local/bin/uv run python -m bullet_in.deploy judge
TimeoutStartSec=1800
# 판정기 (ExecStopPost) 의 최악 경로 = 표지 대조 20초 × 3 + 대기 20초 × 2. 기본 90초면 systemd 가 판정기를 죽인다.
TimeoutStopSec=300
```

- `TimeoutStopSec=300` — 최악 경로의 세 배다.
- `ExecStopPost=-` 의 `-` — 판정기 자체가 못 떠도 (uv 동기화 실패 등) 유닛 결과를 안 바꾼다.
  스펙 §6.2 「판정기가 유닛 결과를 바꾸면 안 된다」 를 유닛 층에서도 지킨다.
  그 실패는 같은 `uv run` 을 쓰는 `ExecStart` 가 먼저 드러내므로 무음이 되지 않는다.

설치한 뒤 실제로 재 본 값이다.

```bash
systemctl show bullet-in.service -p TimeoutStopUSec -p TimeoutStartUSec
# TimeoutStartUSec=30min
# TimeoutStopUSec=5min
```

## 4. 예방

- **`ExecStopPost=` 에 무엇을 붙이든 그 시간은 `TimeoutStopSec=` 안이다.**
  재시도 · 대기 · 타임아웃을 정할 때 그 합을 유닛 파일 옆에 적는다.
- 유닛 파일을 고치는 변경은 `systemctl show -p Timeout*` 로 실측한다.
  파일에 적은 값과 systemd 가 읽은 값이 같은지 보는 데 명령 하나면 된다.
- 여러 작업이 각각 정한 상수의 곱이 어떤 한도에 걸리는지는 브랜치 전체 리뷰의 질문이다.
  「이 명령의 최악 경로는 몇 초이고 그것을 제한하는 것은 무엇인가」 를 리뷰 질문에 넣는다.

## 함께 볼 것

- `docs/superpowers/specs/2026-09-03-deploy-automation-design.md` §6.1 · §6.2
  — 재시도 설계와 판정기 고장의 원칙.
- `docs/runbook/2026-09-04-when-the-cycle-deploys-itself.md`
  — 판정기가 내는 알림 여섯.
- `docs/troubleshooting/2026-09-02-the-unit-line-that-never-took-effect.md`
  — 유닛 파일의 다른 함정 (`EnvironmentFile=` 이 `Environment=` 를 덮는다).
