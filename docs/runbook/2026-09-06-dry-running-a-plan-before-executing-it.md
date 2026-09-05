# 런북 — 계획서의 코드를 실행 전에 한 번 돌려 보는 법

계획서 (`docs/superpowers/plans/`) 에 코드와 테스트 전문이 있을 때, 구현에 넘기기 전에 그 코드를 그대로 꺼내 워크트리에서 돌려 보고 원복하는 절차다.
2026-09-05 안건 2φ PR 2 계획서에서 처음 썼고 결함 둘 (주 수 12 · 13 불일치 · 픽스처 기본 키 충돌) 을 구현 전에 잡았다.
비용은 코드 블록을 꺼내는 파이썬 스무 줄과 테스트 한 번이다.

## 1. 왜 하나

계획서의 코드는 실물과 대조해 썼어도 돌려 본 것이 아니다.
PR 1 (#469) 에서는 옮겨 적은 코드가 실물과 열한 곳 어긋났고 셋은 렌더를 돌려야 드러났다 (`docs/troubleshooting/2026-09-05-what-only-showed-up-when-the-plan-was-run.md`).
계획서를 쓴 세션이 바로 돌리면 그 결함이 계획서 안에서 고쳐지고 기대 수집 수 같은 값이 추정 대신 실측이 된다.

이 절차가 잡는 것과 못 잡는 것은 다르다.
잡는 것은 형식 · 셈 · 픽스처 충돌 · 없는 이름처럼 테스트가 실패로 말해 주는 것이다.
못 잡는 것은 테스트가 통과한 채로 화면에 틀린 값이 나오는 것이고 그것은 리뷰어가 값을 손으로 따라가야 나온다 (`docs/troubleshooting/2026-09-06-passing-tests-said-nothing-about-the-values.md`).
그러므로 이 절차는 리뷰를 대신하지 않는다.

## 2. 절차

워크트리는 계획서를 쓴 그 워크트리를 쓴다.
코드는 커밋하지 않고 끝에 원복한다.

### 2.1. 코드 블록을 꺼낸다

계획서의 펜스 블록을 첫 줄로 찾아 파일로 쓴다.
각 파일의 첫 줄 (모듈 docstring · import 줄 · 함수 정의) 을 접두어로 삼으면 블록을 고유하게 고를 수 있다.

```python
import re
src = open("docs/superpowers/plans/<계획서>.md", encoding="utf-8").read()
blocks = re.findall(r"```(\w*)\n(.*?)```", src, flags=re.S)

def find(prefix):
    return next(b for lang, b in blocks if b.startswith(prefix))

open("src/bullet_in/serve/ops_view.py", "w").write(find('"""수집 현황 화면의 뷰모델'))
open("tests/test_ops_view.py", "w").write(find('"""수집 현황 화면의 뷰모델 — 절 열이'))
# 기존 파일의 한 함수만 바뀌는 태스크는 그 함수의 정의 줄부터 다음 정의 줄 앞까지를 잘라 붙인다
r = open("src/bullet_in/serve/render.py").read()
start = r.index("def render_ops(view: dict, unmatched")
end = r.index("def render_behavior(")
r = r[:start] + find("def render_ops(view: dict) -> str:") + "\n\n" + r[end:]
open("src/bullet_in/serve/render.py", "w").write(r)
```

접두어가 둘 이상에 걸리면 `find` 가 앞의 것을 돌려주므로 접두어를 길게 잡는다.
같은 접두어의 블록이 정말 둘이면 (테스트 파일과 그 안의 한 함수) 긴 것을 먼저 쓴다.

### 2.2. 새 테스트 파일부터 돌린다

```bash
uv run --project . --extra dev pytest tests/test_ops_view.py tests/test_serve_ops.py tests/test_dbt_gate.py -q
```

실패가 나면 계획서를 고친다.
코드를 고치지 않는다.
계획서의 코드 블록을 고치고 다시 꺼내 돌린다.
기대값이 틀렸으면 기대값을 고치되, 픽스처 주석에 적은 셈을 먼저 다시 한다.

### 2.3. 통합 테스트와 전체를 돌린다

DB 를 읽는 태스크가 있으면 컨테이너를 확인한 뒤 통합 테스트를 돈다.

```bash
docker ps --format '{{.Names}}' | grep mariadb
uv run --project . --extra dev pytest tests/integration/test_ops_snapshot.py -q
uv run --project . --extra dev pytest -q 2>&1 | tail -3
uv run --project . --extra dev pytest -q --co 2>/dev/null | tail -1
```

전체 수집 수를 계획서의 「기대 수집 수」 에 실측으로 적는다.
skip 이 늘었으면 어느 테스트가 왜 skip 됐는지 본다 (통합 테스트가 컨테이너를 못 찾으면 조용히 skip 된다).

### 2.4. 렌더나 실행을 한 번 한다

템플릿 · 화면이 있는 태스크는 테스트와 별개로 실제 렌더를 한 번 부른다.

```bash
set -a; source .env; set +a
uv run --project . python -c "
from pathlib import Path
from sqlalchemy import create_engine
import os
from bullet_in.storage.mariadb import MartStore
from bullet_in.score import load_sources
from bullet_in.serve.render import write_ops
mart = MartStore(create_engine(os.environ['MARIADB_URL']))
write_ops(mart.ops_snapshot(), load_sources('config/sources.yaml'), '<스크래치패드>/ops-local', anomaly_count=0, now=mart.db_now(), unmatched=[], gate_path=Path('dbt/target/run_results.json'))
html = Path('<스크래치패드>/ops-local/ops.html').read_text()
print('sec', html.count('class=\"sec\"'), 'svg', html.count('<svg'))
"
```

로컬 DB 는 데이터가 적어 값은 재지 못하지만 템플릿 · 매크로 · 뷰모델의 조립은 여기서 깨진다.
Playwright 가 있으면 파일을 열어 콘솔 오류와 절 수를 함께 본다.

### 2.5. 원복한다

```bash
git checkout -- src tests
rm -f src/bullet_in/serve/ops_view.py        # 새로 만든 파일은 하나씩
find . -name __pycache__ -path "*serve*" -prune -exec rm -rf {} +
git status --short                            # 계획서 파일만 남아야 한다
uv run --project . --extra dev pytest -q --co 2>/dev/null | tail -1   # 기준선 수와 같아야 한다
```

원복 뒤 수집 수가 기준선과 같으면 끝이다.
계획서만 커밋한다.

## 3. 함정

- `echo =====` 를 구분선으로 쓰면 zsh 가 `=cmd` 확장으로 읽어 명령이 실패하고 뒤 출력이 잘린다.
  구분선은 `echo '-----'` 로 쓴다.
- 접두어로 고른 블록이 계획서의 「정정」 표나 다른 태스크의 인용과 겹칠 수 있다.
  꺼낸 파일의 줄 수를 계획서와 대조한다.
- 테스트 수의 계획서 셈은 대체로 틀린다 (PR 1 은 1,750 대 1,754 · PR 2 는 16 대 17).
  실측을 적고 셈은 지운다.
- 이 절차가 통과했다고 값이 맞는 것은 아니다.
  리뷰는 그대로 받는다.
