# 런북 — 공개 저장소 push 전 체크리스트

public 저장소(또는 처음 원격에 올릴 때)는 한 번 공개되면 캐시·인덱싱될 수 있다. push **전에** 아래를 확인한다.

## 1. 시크릿 노출 점검
- `.env`·자격증명·쿠키가 추적되지 않는지:
  ```bash
  git ls-files | grep -E '(^|/)\.env$|x_cookies' && echo "WARNING tracked secret" || echo OK
  ```
- 실제 키 패턴이 추적 파일에 없는지:
  ```bash
  git grep -nIE 'sk-ant-[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY' $(git rev-parse HEAD) || echo "OK no secrets"
  ```
- `.env.example`엔 placeholder만(`REPLACE` 등). 로컬 개발용 비밀번호(`bulletin` 등 localhost)는 무방.

## 2. 민감 프레이밍 정화
- 공개물(README·spec·plan·커밋)에 **회사 실명·취업/포트폴리오 프레이밍·내부 메모**가 없는지 점검한다. (체크리스트 자체도 공개되므로 실제 회사명은 적지 않고, 점검할 일반 키워드 + 그때그때의 민감어를 넣어 검색.)
  ```bash
  git grep -niE '포트폴리오|이직|취업|지원자|내부메모' -- README.md 'docs/**' || echo "OK clean"
  # 필요 시 점검할 고유명(회사명 등)을 추가해 한 번 더 검색
  ```
- 공개물은 *실제 제품 동기*로 작성한다. (Claude 서명 "Generated with Claude Code" 류 금지.)

## 3. 커밋 신원(author) 확인
- 의도한 GitHub 계정으로 귀속되는지. 로컬 `user.email`이 그 계정에 **검증된** 이메일이어야 한다(아니면 다른 계정에 잡힘).
  ```bash
  git config user.name && git config user.email          # 의도한 계정인지
  git log --format='%ae' | sort -u                        # 히스토리 전체 author 이메일
  ```
- 이메일 노출을 피하려면 GitHub 비공개 이메일 사용: `<id>+<login>@users.noreply.github.com` (id는 `gh api user --jq .id`).
- push 후 검증: `gh api repos/<owner>/<repo>/commits/<sha> --jq '.author.login'`.

## 4. 테스트 그린
- `uv run pytest -q` (단위/통합), 필요 시 dbt build·DAG 검증.

## 주의 — 이미 push한 뒤 문제를 발견했다면
- tip만 고치는 새 커밋은 **히스토리에 흔적이 남는다**(`git log -p`로 노출). 완전 제거하려면 히스토리 재작성(`filter-branch`/`filter-repo`) 후 `force-push`가 필요하다 — **파괴적 작업이므로 사용자 명시 동의 필수**, 협업 중인 브랜치에선 지양.
