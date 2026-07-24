# VM 라이브 재처리 배포 — 머지된 백필성 변경의 운영 반영 (2026-07-24)

트랙 B PR-A (#125) 의 공신력 값 · 영입 단계 · 제목 재처리를 seoulnow VM 운영 DB 에 반영하며 실측한 절차다.
로컬 mock 검증 런북 (`docs/runbook/2026-07-23-config-tier-backfill-local-verify.md`) 의 VM 판이며, 재수집이 필요 없는 백필성 변경 (config 값 · 프롬프트 · 게이트) 의 라이브 반영에 재사용한다.

## 1. 작업 창 확보 — 정기 회차와의 충돌 회피

백필 도중 정기 회차가 겹치면 DB 쓰기와 Gemini 속도 한도를 두고 경합한다.
착수 전 다음 발화 시각을 확인하고, 작업 예상 시간 안이면 타이머를 세운다.

```bash
systemctl list-timers bullet-in.timer --no-pager   # NEXT 확인
sudo systemctl stop bullet-in.timer                # 정지 (작업 후 반드시 재가동)
```

- **실측 (2026-07-24)** — 착수 시점에 다음 발화가 5분 뒤라 정지하고 진행했다.
- **재가동하면 놓친 회차가 즉시 캐치업 실행된다** (`Persistent=true`).
X 접촉 1회와 사이트 재배포가 곧바로 일어나므로 작업 계획에 포함할 것.
- 백필로 고친 값 (tier · transfer_stage · title_ko) 은 캐치업 회차가 덮지 않는다.
실측으로 캐치업 후 세 값 모두 유지를 확인했다 (upsert 가 기존 행의 해당 컬럼을 건드리지 않는 설계).

## 2. 스냅샷 (필수)

VM 의 mariadb 컨테이너에는 `mariadb-dump` 가 있다 (로컬 mock 검증 런북의 "덤프 도구 없음" 은 로컬 환경 이야기).

```bash
mkdir -p ~/bullet-in-backups
docker exec bullet-in-mariadb-1 mariadb-dump -uroot -pbulletin \
  bulletin articles > ~/bullet-in-backups/$(date +%F-%H%M)-articles-pre-<작업명>.sql
```

한 벌을 로컬 맥으로 내려 이중 보관한다 (`scp -i ~/.ssh/seoulnow_deploy …`).
롤백은 enrich 전용 런북 §5.4 의 임시 테이블 복원 방식.

## 3. old 레지스트리 기준 — pull 순서 함정

tier 델타 재계산의 old 는 **VM 이 실제로 돌리던 커밋** (pull 전 HEAD) 이다.
로컬 검증 때 쓴 기준 커밋을 그대로 옮기지 말고 VM 에서 `git log --oneline -1` 로 확인한다.

- 정찰 (dry-run) 은 pull 전에 돌리면 작업 트리가 곧 old 라 단순하다.
- 적용은 pull 후에 하되, old 는 `git show <pull 전 HEAD>:config/credibility.yaml` 로 읽는다.

## 4. 재처리 실행 순서

1. **정찰 (읽기 전용)** — 세 백필의 대상 행을 dry-run 으로 뽑아 건수 · 내용을 눈으로 확정한다.
쓰기 전에 대상이 의도와 일치하는지 (부수 드리프트 0 · 비아스날 행 제외) 여기서 거른다.
2. **스냅샷** (§2).
3. **git pull** — 이후 작업 트리가 new 레지스트리 · 새 코드가 된다.
4. **B1 tier 델타** — old vs new 두 번 resolve 해 다른 행만 update (전건 재계산 금지, `docs/troubleshooting/2026-07-23-tier-recompute-stale-drift.md`).
`confidence_score` 는 SQL 로 재구현하지 말고 `score.confidence_from_tier` 를 import 해 같이 갱신한다.
5. **B2 타깃 재분류** — 대상 행만 `transfer_stage` NULL 복원 후 `classify_stage_rows` 재실행.
예상 밖 값이 나오면 스냅샷 값으로 원복하고 보고한다.
6. **B5 재큐** — 대상 행 `title_ko` NULL 후 enrich 전용 런북 §3 수렴 패스.
7. **렌더 · 배포** — enrich 전용 런북 §4 재생성 후 `./infra/deploy-site.sh`.
8. **검증 3단** — ① VM 산출물 grep → ② 프리뷰 URL → ③ 최상위 도메인 (VM 동거 런북 §8).
상세 페이지 공신력은 `<dt>공신력</dt><dd>…</dd>` 패턴으로 grep 해야 사이드바 라벨 오매치를 피한다.
9. **타이머 재가동** — `sudo systemctl start bullet-in.timer`.
캐치업 회차가 즉시 돌 수 있으니 (§1) `journalctl` 로 종료를 지켜보고 백필분 유지를 재확인한다.

## 5. 실측 기록 (2026-07-24 · PR-A)

| 항목 | 대상 | 결과 |
|---|---|---|
| B1 tier 델타 | 8행 (`@garyjacob` 5 · `@JacobsBen` 인용 3) | 3→2 · 4→3, 부수 드리프트 0 |
| B2 재분류 | `5e35e51a2` 1행 | negotiating → agreed (새 프롬프트 검증) |
| B5 재큐 | `7341690b` 1행 | 재번역이 게이트 통과 → 한국어 해소 |
| 캐치업 회차 | 타이머 재가동 직후 | 2분 56초 · 신규 18건 · 백필분 유지 |

B5 는 결정적 오탐으로 진단됐던 행이 이번 재번역에서 게이트를 통과했다.
매번 걸리는 행도 LLM 변동성으로 가끔 풀리는 경로가 실재함을 확인 — 다만 근본 해소는 게이트 오탐 후속 트랙 몫.

## 5.1. 실측 기록 (2026-07-24 · PR #128 arsenal 백필)

| 항목 | 대상 | 결과 |
|---|---|---|
| label (precision) | arsenal 5행 | dry-run 5행 확인 → `time` 적용 · 잔존 NULL 0 |
| reverify (소급) | sitemap 6/1 이후 351건 | accept 6 = 기존 5 중복 + Tzolis 신규 1 적재 (`official` 태깅) |
| 재생성 · 배포 | 299행 | Tzolis 상세 · 인덱스 노출 (번역은 다음 회차 흡수) |

- **타이머는 정지하지 않았다** — 다음 발화가 2시간 밖이라 §1 기준 (작업 예상 시간 안) 에 걸리지 않음.
정지 여부는 관례가 아니라 남은 시간으로 판단한다.
- **reverify 는 VM 에서 dry-run 을 한 번 더 떴다** — 로컬과 발신 IP 가 달라
대상 사이트의 IP 차단 여부가 갈릴 수 있다 (fmkorea 사례:
`docs/troubleshooting/2026-07-24-fmkorea-vm-ip-persistent-430.md`).
로컬 검증을 VM 검증으로 갈음하지 말 것.
- **백필로 신규 행이 생겼으면 렌더 전에 enrich 수렴 패스 (§4 의 enrich 런북 §3) 를 끼울 것** — 실측 실수.
정기 회차는 수집 → 번역 → 렌더가 연속이라 번역 전 상태가 배포될 수 없지만,
백필 후 곧장 재생성 · 배포하면 그 상태가 라이브에 실린다
(Tzolis 가 영문 제목 · 빈 본문으로 노출 → enrich 전용 패스로 사후 해소).
§4 재처리 순서의 "B5 재큐 → 수렴 패스 → 렌더" 가 이 순서의 원형이다
— 값 백필 (tier · precision) 은 렌더 직행 가능, **행 추가 백필은 수렴 패스 필수**.

## 6. 참고

- 로컬 mock 검증: `docs/runbook/2026-07-23-config-tier-backfill-local-verify.md`
- tier 재계산 함정: `docs/troubleshooting/2026-07-23-tier-recompute-stale-drift.md`
- enrich 전용 패스 (수렴 · 렌더 · 롤백): `docs/runbook/2026-07-19-enrich-only-pass.md`
- VM 접속 · 배포 · 캐시 3단 검증: `docs/runbook/2026-07-20-vm-cohost-bootstrap.md`
