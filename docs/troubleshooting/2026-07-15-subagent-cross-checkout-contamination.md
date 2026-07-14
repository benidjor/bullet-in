# 병렬 세션 중 subagent 가 남의 체크아웃에 커밋 — 오염 커밋 진단 · 복구 (2026-07-15)

소스 확장 트랙 (PR #41) 의 최종 리뷰 fix 단계에서 발생.
worktree 격리로 두 세션 (SLO-1 벤치마크 · 소스 확장) 이 같은 저장소를 병행하던 중, fix subagent 가 자기 worktree 가 아니라 **메인 체크아웃 (다른 세션이 점유한 `feat/slo1-parallel-speedup`)** 에서 `git commit` 을 실행했다.

## 1. 증상

- subagent 는 DONE 보고 (커밋 SHA · 테스트 통과 포함) — 보고만 보면 정상.
- 컨트롤러가 리뷰 패키지를 만들 때 **기대 커밋 수 (2) 와 실제 (1) 불일치**로 처음 발각.
- `git log <자기 브랜치>` 에 보고된 SHA 부재.

## 2. 진단

```bash
git show <SHA> --stat            # 의도한 2파일 외 22개 파일 (다른 세션의 미커밋 작업) 포함
git branch --all --contains <SHA>   # → feat/slo1-parallel-speedup (메인 체크아웃 점유 브랜치)
git -C <메인 체크아웃> status --short   # clean — 그 세션의 dirty 상태가 커밋에 흡수됨
```

- 오염 커밋에는 점유 세션의 미커밋 runbook · spec 수정과 untracked `site-preview/` 전체가 쓸려 들어갔다.
- 점유 세션 관점에서는 **작업 중 상태가 사라진 것처럼 보이는** 상태 (실제로는 커밋 안에 보존).

## 3. 원인

- subagent 프롬프트의 "Work from: <worktree 경로>" 한 줄은 **cwd 가 어긋났을 때의 방어가 아니다** — subagent 는 자기 위치를 검증하지 않고 커밋했다.
- 광역 스테이징 (`git add -A` 류) 이 그 체크아웃의 dirty 파일 전부를 흡수 — 의도 파일 2개가 22개 동승자를 데려옴.
- 선례: SLO-5 트랙에서도 fix subagent 가 `add -A` 로 untracked `site-preview/` 를 포함시킨 적 있음 (그때는 같은 브랜치라 재커밋으로 끝).

## 4. 복구

- **타이밍이 핵심** — 점유 세션이 장기 프로세스 (벤치 3회차, ~4분) 에 묶여 있는 동안이 유일한 무레이스 창.
  프로세스는 git 을 건드리지 않고, 세션은 프로세스 종료까지 대기 상태.
  창을 놓치면 점유 세션이 오염 tip 위에 후속 커밋을 쌓아 복구가 히스토리 수술로 번진다.
- 절차 ( 메인 체크아웃에서 ):

```bash
git reset HEAD~1        # mixed — 22개 파일이 원래의 미커밋 (modified · untracked) 상태로 복원
git checkout -- <이물질 파일들>   # 그 세션 것이 아닌 파일만 폐기
git status --short      # 사전 스냅샷 (세션 시작 시 git status) 과 대조해 원상 복구 확인
```

- 오염 커밋이 **푸시 전**이었으므로 reset 만으로 충분했고, SHA 는 reflog 에 남아 안전망이 된다.
- 이물질 파일의 올바른 버전은 원래 worktree 에서 컨트롤러가 직접 재적용 · 재커밋.

## 5. 예방 — 4계약

- **subagent 커밋 전 자기검증** — 디스패치 프롬프트에 명시: `git rev-parse --show-toplevel` 이 worktree 경로이고 `git branch --show-current` 가 기대 브랜치인지 확인, 불일치 시 커밋 없이 BLOCKED 보고.
- **컨트롤러 즉시 검증** — 보고된 SHA 가 자기 브랜치 tip 에 실존하는지 `git log --oneline -1` 로 확인 (이번 건은 리뷰 패키지 단계에서야 발각 — 한 단계 늦음).
- **커밋 수 불일치 = 이상 신호** — 리뷰 패키지의 커밋 카운트가 기대와 다르면 진행을 멈추고 SHA 소재부터 추적.
- **광역 스테이징 금지** — subagent 커밋은 파일 명시 `git add <파일…>` 만 (add -A 는 남의 dirty 를 흡수하는 사고 경로).

## 6. 관련

- 복구 후 정상 재적용 커밋: PR #41 의 `9f9b3ba` (trailText fix).
- 메모리: `subagent-worktree-commit-guard` (전역 재발 방지 규칙).
- 계열 함정: PR #34→#35 문서 누락 (squash 가 옛 head 까지만 합침) — "보고와 실제 git 상태의 괴리" 라는 같은 뿌리.
