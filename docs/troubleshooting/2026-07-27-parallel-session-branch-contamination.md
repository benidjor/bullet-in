# 병렬 세션의 커밋이 남의 브랜치에 섞인 사례

수집 라인 세션이 PR 을 올리려고 브랜치 커밋 목록을 확인하다가, 자기 작업과 무관한 serve 커밋 한 건이 브랜치에 얹혀 있는 것을 발견했다 (2026-07-27).
UI 세션이 워크트리가 아니라 **메인 체크아웃**에서 커밋해, 그때 그 체크아웃이 들고 있던 수집 라인 브랜치에 실렸다.

## 증상

```bash
git log --oneline origin/main..HEAD
# df9414a feat(collect): 단건 URL 재수집 CLI ...      ← 내 작업
# ...
# f27eb93 feat(serve): 선수 귀속 · 단계 확정 · 집계 헬퍼 ← 남의 작업 (섞임)
# 715cd13 docs(spec): URL 정합 통합 설계 ...          ← 내 작업
```

- 내 브랜치를 그대로 PR 로 올렸다면 무관한 serve 변경이 함께 머지됐을 것이다.
- 테스트는 전부 통과한다 — 섞인 커밋도 정상 코드라 자동 검증으로는 안 잡힌다.

## 판별 — 같은 변경이 원 브랜치에도 있는지 확인한다

지우기 전에 그 커밋이 **원래 있어야 할 브랜치에 이미 있는지** 확인한다.
있으면 내 쪽에서 빼도 작업이 사라지지 않는다.

```bash
git log --all --oneline --branches | grep "<커밋 제목 일부>"
# 93ca190 feat(serve): 선수 귀속 ...   ← UI 브랜치 쪽
# f27eb93 feat(serve): 선수 귀속 ...   ← 내 브랜치에 섞인 것

git branch --contains 93ca190          # feat/serve-player-pages
git show f27eb93 | git patch-id --stable
git show 93ca190 | git patch-id --stable
# 두 patch-id 가 같으면 내용이 동일한 중복 커밋이다
```

`patch-id` 는 커밋 해시와 무관하게 **변경 내용**을 식별한다 — cherry-pick · rebase 로 해시만 달라진 같은 변경을 판정할 때 쓴다.

## 조치 — rebase --onto 로 그 커밋만 들어낸다

```bash
git rebase --onto <섞인 커밋의 부모> <섞인 커밋> <내 브랜치>
# 예: git rebase --onto 715cd13 f27eb93 feat/url-integrity-guard
```

- 뒤따르던 커밋들은 새 해시로 다시 쌓인다 — 아직 push 전이면 부담이 없다.
- 이미 push 했다면 강제 푸시가 필요하므로, PR 을 열기 **전에** 확인하는 편이 싸다.
- 정리 후 전체 회귀를 다시 돌린다 (커밋이 빠지면서 의존이 끊길 수 있다).

## 예방

- 병렬 세션은 각자 워크트리에서 작업한다 (`.claude/worktrees/…`) — 메인 체크아웃은 한 세션만 쓴다.
- subagent 에게 커밋을 맡길 때 **커밋 직전 `git branch --show-current` 로 자기 위치를 확인**하게 지시한다 (기존 지침 — 이번엔 상대 세션 쪽에서 지켜지지 않았다).
- PR 생성 직전 `git log --oneline origin/main..HEAD` 로 커밋 목록을 눈으로 확인한다.
내 작업으로 설명되지 않는 커밋이 있으면 멈춘다.

## 참고

- subagent 커밋 위치 자기검증: 메모리 `subagent-worktree-commit-guard`
- 분기 전 base 확인 (다른 유형의 브랜치 오염): 메모리 `git-branch-base-before-squash`
