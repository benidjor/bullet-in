# 테스트가 통과한 이유가 내 기계에 브라우저가 있어서였다 (2026-08-29)

CI 를 처음 붙인 날 첫 실행이 빨간불을 냈다.
깨진 것은 새 코드가 아니라 **오래 통과해 오던 테스트 하나**였고, 통과의 이유가 저장소 밖에 있었다.

## 증상

`.github/workflows/ci.yml` 을 올린 첫 PR 실행에서 `1 failed, 1369 passed, 1 skipped`.

```
tests/test_playwright_adapter.py::test_playwright_adapter_reads_js_rendered_links
playwright._impl._errors.Error: BrowserType.launch: Executable doesn't exist at
/home/runner/.cache/ms-playwright/chromium_headless_shell-1223/chrome-headless-shell-linux64/chrome-headless-shell
```

## 원인

이 테스트는 어댑터를 모킹하지 않고 **실제 크로미움을 띄운다.**
브라우저 바이너리는 파이썬 의존이 아니라 `playwright install` 이 따로 받아 사용자 캐시에 두는 것이라, `uv sync` 로는 안 들어온다.

개발 기계에는 셋업 절차 (`CLAUDE.md` 의 `uv run playwright install chromium`) 를 한 번 밟아 둔 캐시가 있었다.
그래서 로컬에서는 늘 통과했고, **의존이 있다는 사실 자체가 안 보였다.**

## 고친 방법

워크플로의 pytest 앞에 설치 단계를 넣었다.

```yaml
- name: 크로미움 설치
  run: uv run playwright install --with-deps chromium
```

두 번째 실행에서 세 작업 (pytest · 문서 서식 · PR 규약) 전부 통과했고, pytest 작업은 1분 15초가 걸렸다.

## 이 사례가 말해 주는 것

- **로컬 통과는 「이 코드가 맞다」 가 아니라 「이 기계에서 맞다」 이다.** 기계에 쌓인 것 (브라우저 캐시 · 전역 설치 · 열려 있는 터널 · 예전에 만든 DB) 이 통과를 떠받치고 있으면 그 사실은 로컬에서 원리상 안 보인다.
- **아무것도 없는 기계에서 한 번 돌리는 것이 그 층을 드러낸다.** CI 의 값은 검사 항목이 늘어서가 아니라 **매번 빈 기계에서 돈다** 는 데 있다.
- **새 기계에서 이 저장소를 처음 받는 사람은 `uv sync` 만으로 이 테스트가 깨진다.** 셋업 절차의 `playwright install` 은 문서에 적혀 있으므로 절차를 다 밟으면 문제가 없다.

## 같은 모양을 또 만날 자리

기계에 쌓인 것에 기대는 다른 자리들이다. CI 는 이 중 첫 둘만 본다.

- **통합 테스트의 MariaDB** — 러너에 서비스로 띄웠고, 안 띄우면 69건이 건너뛴 채 초록불이 난다 (건너뜀 허용치 검사가 이 자리를 지킨다).
- **dbt 파싱** — DB 없이 도는 부분만 CI 가 본다. 컬럼 테스트 10개는 라이브 MariaDB 가 필요해 여전히 아무 데서도 안 돈다.
- **운영 VM 의 `.env`** — 저장소에 없고, 워크트리에는 `.worktreeinclude` 가 복사한다. CI 는 이것 없이 도는 범위만 검사한다.
