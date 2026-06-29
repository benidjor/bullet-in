# GitHub Contributors에 모르는 계정 노출 — co-author 매핑 + 사이드바 캐시

- **날짜**: 2026-06-28
- **영역**: git / GitHub / 공개 저장소
- **심각도**: 낮음 (기능 영향 없음, 평판/공개 노출 이슈)

## 증상
저장소 홈 우측 사이드바 **Contributors**에 소유자 (`benidjor`) 외에 모르는 계정 노출:
- 과거: `meta-chain-developer`(선점자) — 작업과 무관한 제3자.
- 정상 기대: `claude`("Claude") — co-author 트레일러로 의도된 표시.

공개 저장소라 그대로 드러남.

## 핵심 메커니즘
co-author 아바타/귀속은 **트레일러 이메일이 매핑되는 GitHub 계정**으로 결정된다. `noreply` 이메일은
이름이 아니라 **계정이 그 주소를 소유 (등록)했는지**로 매핑된다. 즉 `noreply@anthropic.com`이 어느
계정에 등록돼 있느냐에 따라 co-author가 그 계정으로 귀속된다 — 그리고 **이 매핑은 시간에 따라 바뀔 수 있다.**

## 진단 과정 (왜 이렇게 판단했는가)
1. **현재 git 히스토리는 깨끗.** 모든 ref (브랜치 · 태그) 통틀어 해당 흔적 0건:
   ```bash
   git fetch --all --tags
   git log --all --source --format='%H %S %ae | %(trailers:only,valueonly)' \
     | grep -iE 'anthropic|meta-chain|50160766'   # 0건
   git branch -r   # origin에 백업/옛 브랜치 없음 확인
   ```
2. **권위 있는 집계 (REST/Insights)는 이미 깨끗.** 홈 사이드바 위젯만 다름:
   ```bash
   gh api repos/<owner>/<repo>/contributors --jq '.[].login'   # → benidjor 1명뿐
   ```
   REST `contributors`(=Insights 그래프)는 author 기준이고, 홈 사이드바 위젯은 co-author 포함 +
   **별도로 · 끈질기게 캐시**된다. meta-chain이 남은 건 이 사이드바 캐시뿐.
3. **계정 ID 확인** — `noreply@anthropic.com`이 현재 어느 계정인지 정황 확인:
   ```bash
   gh api users/claude --jq '{login,id}'                 # 81847  ("Claude")
   gh api users/meta-chain-developer --jq '{login,id}'   # 50160766
   ```
   다른 저장소에서 `Co-Authored-By: ... <noreply@anthropic.com>` 커밋이 **"Claude" 아바타로 렌더링**됨을
   확인 → 현재 이 주소는 `claude`(81847) 계정으로 매핑된다 (과거엔 `meta-chain-developer`였음).

## 원인
- 과거: `noreply@anthropic.com`이 선점자 (`meta-chain-developer`)에게 매핑되던 시기에 만든 co-author 커밋이
  그 계정으로 귀속됨.
- 이후 히스토리를 정리 (트레일러 재작성 · force-push)해 git은 깨끗해졌지만, **GitHub 홈 Contributors 위젯
  캐시가 옛 값을 오래 유지**한다 (재계산이 매우 느림, 강제 수단 없음).

## 해결
- **git 히스토리 · Insights는 이미 깨끗하므로 추가 코드 조치 불필요.**
- 홈 사이드바 캐시는 GitHub 재계산 시 사라진다. **강제 트리거 수단 없음** — 새 푸시가 재계산을 앞당기는
  경향이 있고, 끝내 안 사라지면 GitHub Support에 캐시 갱신 요청이 유일한 강제 수단.
- (과거 정리) 전체 히스토리 (main 포함) 트레일러 이메일 재작성 + force-push. **Contributors는 모든 브랜치
  기준이라 백업 브랜치까지 삭제**해야 제3자가 완전히 빠진다.

## 현재 정책 (2026-06-28~)
- co-author 트레일러는 **`Co-Authored-By: Claude Opus <버전> (1M context) <noreply@anthropic.com>`**.
  현재 이 주소가 "Claude" 계정으로 매핑돼 **co-author 아바타가 정상 표시**되고 Anthropic Claude Code
  기본값과도 일치한다. (과거 소유자-noreply 우회는 선점자 시절의 방어책이었다.)
- **author / git 신원은 소유자 noreply 유지** (`94089198+benidjor@users.noreply.github.com`). co-author만
  anthropic noreply — 둘은 별개 축.
- ⚠️ 이메일→계정 매핑은 재선점으로 또 바뀔 수 있다. **가끔 Contributors를 점검**하고, 모르는 계정이
  보이면 위 진단 절차로 git 클린 여부부터 확인할 것.
- SoT: `docs/conventions/2026-06-11-commit-pr-convention.md` §1.3.
