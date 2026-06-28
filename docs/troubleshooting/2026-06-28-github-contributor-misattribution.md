# GitHub Contributors에 모르는 계정 노출 — co-author 오귀속 + 사이드바 캐시

- **날짜**: 2026-06-28
- **영역**: git / GitHub / 공개 저장소
- **심각도**: 낮음 (기능 영향 없음, 평판/공개 노출 이슈)

## 증상
저장소 홈 우측 사이드바 **Contributors**에 소유자(`benidjor`) 외에 모르는 계정이 노출:
- `claude` (이름 "Claude")
- `meta-chain-developer`

현재 작업과 무관한 제3자가 기여자처럼 보임. 공개 저장소라 그대로 드러남.

## 진단 과정 (왜 이렇게 판단했는가)
1. **현재 히스토리는 깨끗**. 로컬·원격 전체에서 author/committer/trailer를 집계해도 해당 계정·이메일 0건:
   ```bash
   git log --all --format='%an <%ae> | %cn <%ce>' | sort | uniq -c
   git log --all --format='%(trailers:only)' | grep -iE 'anthropic|claude|chain'   # 0건
   ```
2. **REST API와 사이드바의 집계 기준이 다름**:
   ```bash
   gh api repos/<owner>/<repo>/contributors --jq '.[].login'   # → benidjor 1명뿐
   ```
   REST `contributors`는 소유자만 반환하는데 사이드바는 3명 → 사이드바 위젯은 **co-author 트레일러까지 포함**하고 **REST와 별도로 캐시**된다.
3. **noreply 이메일은 이름이 아니라 계정 ID로 매핑**된다. `ID+이름@users.noreply.github.com`에서 GitHub는 **숫자 ID로 계정을 찾는다**(이름 부분은 표시용):
   ```bash
   gh api users/meta-chain-developer --jq .id   # 50160766
   gh api users/claude --jq .id                 # 81847
   gh api users/benidjor --jq .id               # 94089198
   ```
4. 종합: **과거 커밋의 `Co-Authored-By`가 공용 `noreply@anthropic.com`을 썼고**, 그 주소를 자기 계정에 등록(선점)한 제3자 `meta-chain-developer`에게 co-author로 귀속됐다. 이후 트레일러 이메일을 소유자 noreply로 **일괄 재작성**해 현재 히스토리엔 흔적이 없지만, **사이드바 Contributors 캐시가 옛 상태를 들고 있었다**.

## 원인
- 공용 도메인 noreply(`noreply@anthropic.com`)를 co-author 이메일로 사용 → 그 주소를 선점한 제3자 계정에 귀속.
- GitHub 홈 Contributors 위젯은 co-author 포함·캐시 기반이라, 히스토리를 정리한 뒤에도 갱신이 지연됨(수 시간~수일).

## 해결
- **현재 히스토리는 이미 깨끗하므로 추가 코드/커밋 조치 불필요.**
- 사이드바 캐시는 GitHub 재계산 시 **자동으로 사라진다**. 강제 트리거 수단은 없고, 새 푸시가 쌓이면 재계산이 앞당겨지는 경향. 끝내 안 사라지면 GitHub Support에 캐시 갱신 요청이 유일한 강제 수단.
- (과거에 한 정리) 전체 히스토리(main 포함) 트레일러 이메일을 소유자 noreply로 재작성 + force-push. **Contributors는 모든 브랜치 기준이라 백업 브랜치까지 삭제해야** 제3자가 완전히 빠진다.

## 예방
- 커밋 트레일러 이메일은 **반드시 저장소 소유자의 GitHub noreply**(`94089198+benidjor@users.noreply.github.com`)를 쓴다. 공용 도메인 noreply(`noreply@anthropic.com` 등) 금지 — SoT: `docs/conventions/2026-06-11-commit-pr-convention.md` §1.
- 새 작업 전 `git config user.email` 확인. co-author 트레일러도 동일 원칙.
