# 런북 — 회차가 코드를 스스로 반영할 때 오는 알림 여섯과 각각 할 일

머지된 코드는 사람이 내려받지 않는다.
`bullet-in.service` 가 시작에서 `bullet_in.deploy advance` 로 `origin/main` 을 내려받고, 끝에서 `bullet_in.deploy judge` 로 첫 회차를 판정한다.
설계는 `docs/superpowers/specs/2026-09-03-deploy-automation-design.md` 에 있다.

상태는 VM 의 `~/bullet-in/state/deploy.json` 한 파일이다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 'cat ~/bullet-in/state/deploy.json'
```

`pending` 이 참이면 「전진했는데 아직 판정 안 함」 이고, `blocked` 는 판정에 실패한 커밋이다.

## 1. 알림 여섯

| 알림 | 채널 | 뜻 | 할 일 |
| --- | --- | --- | --- |
| ✅ 코드 반영 완료 | 리뷰 | 첫 회차 통과 · 라이브 표지 일치 | 없음 |
| ⏸ 코드 반영 판정 보류 | 리뷰 | 게이트가 신호로 죽었다 (안건 2ν) · 다음 회차에 다시 판정 | `coredumpctl info -1` (게이트 런북 §3.2) |
| ⏪ 코드 롤백 | 사고 | 첫 회차 실패 · 직전 커밋으로 되돌림 | §2 |
| 🚧 코드 전진 거부 — 사전 점검 실패 | 사고 | 새 코드가 import 안 되거나 필수 키가 없다 | §3 |
| 🚧 코드 전진 — VM 트리가 갈라졌다 | 사고 | 누가 VM 에서 직접 커밋했다 | §4 |
| 🚧 배포는 나갔는데 라이브 표지가 다르다 | 사고 | Cloudflare 캐시 · 배포 지연 | §5 |

표 밖의 알림이 둘 더 있다.
「🚧 코드 전진 — 예외」 와 「🚧 deploy <명령> — 예외」 는 전진기 · 판정기 자신이 예외로 죽었다는 뜻이다.
회차는 그대로 돌고 코드는 안 바뀐다.
저널의 스택 트레이스를 보고 고친 PR 을 머지한다.

## 2. 롤백 알림을 받았을 때

되돌린 것은 VM 의 코드뿐이다.
화면은 배포가 안 나갔으므로 직전 그대로이고, DB 에 그 회차가 쓴 행은 남는다.

먼저 저널로 어디까지 갔는지 본다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'journalctl -u bullet-in.service -n 200 --no-pager | grep -E "ERROR|게이트|deploy"'
```

알림의 종료 코드가 `0` 이면 회차는 성공했는데 배포 스크립트 (`ExecStartPost`) 가 실패한 것이다.
`?` 이면 주 프로세스가 돌기 전에 (`docker compose` 등 `ExecStartPre`) 실패한 것이다.

- **코드 탓이면** — 고친 PR 을 머지한다.
  새 커밋이 오면 다음 회차가 알아서 전진한다.
- **코드 탓이 아니면 (DB 다운 · 데이터 부채)** — 원인을 고친 뒤 같은 커밋을 다시 보게 한다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -m bullet_in.deploy unblock <커밋 앞 7자리>'
```

## 3. 사전 점검 거부를 받았을 때

알림의 「사유」 에 빠진 키 이름이나 import 오류 한 줄이 있다.
그 커밋은 차단 목록에 올라 있으므로 원인을 고친 뒤 `unblock` 을 쳐야 다시 전진한다 (§2 의 명령).

- **키가 없다** — VM `.env` 에 넣는다.
- **import 오류** — 코드다.
  고친 PR 을 머지하면 새 커밋이라 `unblock` 없이 전진한다.
- **의존 동기화 실패 (네트워크 · 빌드)** — 사유에 uv 의 출력이 실린다.
  다시 시도하려면 `unblock` 을 친다.

## 4. VM 트리가 갈라졌을 때

자동으로 되돌리지 않는다.
사람이 VM 에서 `git status` · `git log --oneline -3` 을 보고, 그 커밋이 필요 없으면 `git reset --hard origin/main` 을 친다.

## 5. 라이브 표지가 다를 때

코드는 되돌리지 않았다.
몇 분 뒤 직접 받아 본다.

```bash
curl -sL https://bullet-in.pages.dev/build.json
```

`commit` 이 `state/deploy.json` 의 `current` 와 같으면 캐시였다.
계속 다르면 `wrangler pages deployment list --project-name bullet-in` 으로 배포가 실제로 나갔는지 본다.

## 6. 화면이 틀린데 판정은 통과했을 때 (사람 눈에만 보이는 실패)

자동 판정은 조판 · 수치 오류를 못 본다.
사람이 되돌린다.

```bash
ssh -i ~/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'cd ~/bullet-in && set -a && . ./.env && set +a &&
   /home/ubuntu/.local/bin/uv run python -m bullet_in.deploy rollback'
```

자동 롤백과 같은 함수라 알림 · 차단 목록이 같은 모양으로 남는다.
화면은 다음 회차가 직전 코드로 덮는다.
급하면 Cloudflare 대시보드의 Deployments 에서 직전 배포로 Rollback 한다.
`bullet_in.deploy` 를 들여온 커밋 (2026-09-03 의 배포 자동화 PR) 보다 앞으로는 되돌리지 않는다.
그 앞 커밋에는 이 모듈이 없어서 `unblock` · `advance` · `judge` 가 전부 「모듈 없음」 으로 죽고 손 `git pull` 만이 복구 경로다.

## 함께 볼 것

- `docs/runbook/2026-08-31-when-the-dbt-gate-blocks-a-deploy.md` — 게이트가 막았을 때
- `docs/runbook/2026-09-02-shipping-a-screen-change-after-merge.md` — 회차를 안 기다리고 재렌더 · 배포만 앞당길 때
