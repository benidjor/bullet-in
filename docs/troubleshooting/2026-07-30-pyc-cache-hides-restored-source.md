# 원복한 소스가 아니라 캐시된 바이트코드가 돈다 (2026-07-30)

테스트가 정말로 결함을 잡는지 확인하려고 구현을 일부러 망가뜨렸다가 되돌렸는데, 원복 후에도 같은 테스트가 계속 실패했다.
소스는 정상인데 실행되는 코드는 변이본이었다.
원인을 찾는 데 10분 넘게 썼고, 그 사이 소스를 두 번 다시 확인하고 pytest 밖에서 별도 스크립트로도 재현해 봤다.

같은 확인 방식 (변이 → 실패 확인 → 원복) 을 앞으로도 쓸 것이라 남긴다.

## 증상

`fmkorea` 어댑터에서 기자명 우선순위를 뒤집어 (`journalist or 추출값` → `추출값 or journalist`) 테스트가 잡는지 보고 원복한 뒤였다.

```
uv run pytest ... -k keeps_bracket_journalist   → FAILED   (변이 상태 · 의도한 결과)
cp /tmp/fm.bak src/bullet_in/adapters/fmkorea.py
uv run pytest ... -k keeps_bracket_journalist   → FAILED   (원복했는데도 그대로)
```

세 가지가 동시에 관측돼 판단이 흐려졌다.

- `grep` 으로 본 소스는 원복된 상태 (`journalist = journalist or extract_body_journalist(body)`).
- `inspect.getsource` 로 찍은 함수 본문도 원복된 상태.
- 그런데 `uv run python` 으로 어댑터를 직접 돌리면 변이본 동작 (본문 추출값이 말머리 값을 덮음).

## 원인 — mtime 초 + 파일 크기가 같으면 캐시가 유효로 판정된다

CPython 기본 무효화 방식은 소스의 **수정 시각 (초 단위 정수) 과 크기** 를 `.pyc` 헤더에 적어 두고 대조하는 것이다.
이 저장소의 `.pyc` 는 그 방식으로 만들어진다 (헤더 flags = 0 · 해시 기반이 아니다).

```
src/bullet_in/__pycache__/dedup.cpython-311.pyc
flags=0  src_mtime=1785370776  size=1155
```

문제는 두 가지가 겹쳐서 생겼다.

- **바꿔 넣은 문자열이 원본과 글자 수가 같았다** — 토큰 순서만 뒤집었으니 파일 크기가 그대로다.
- **원복이 변이와 같은 초 안에 일어났다** — 변이 → 단일 테스트 실행 → 원복 사이클을 세 번 재 보니 **0.23 · 0.23 · 0.36초** 였다.
1초를 넘지 않는 것이 예외가 아니라 기본이다.

그래서 원복본의 (mtime 초 · 크기) 가 변이본의 것과 같아지고, Python 은 캐시가 최신이라고 보고 변이 바이트코드를 그대로 불러온다.

`inspect.getsource` 때문에 헷갈린 이유도 여기 있다.
그 함수는 `.py` 파일을 다시 읽어 보여 주지만, 실제로 실행되는 코드 객체는 `.pyc` 에서 왔다.
두 창구가 서로 다른 것을 보여 준 셈이다.

## 결정적 재현

시간에 맡기지 않고 `os.utime` 으로 초를 맞추면 언제나 재현된다.

```bash
find src -name __pycache__ -type d -exec rm -rf {} +
uv run pytest tests/test_dedup.py -q                  # 10 passed — 정상 .pyc 생성

# 같은 바이트 수로 변이 (비교 방향만 뒤집는다)
python3 -c "
import pathlib; p=pathlib.Path('src/bullet_in/dedup.py'); s=p.read_text()
s2 = s.replace('if new_body_level > last_level:', 'if new_body_level< last_level :')
assert len(s2) == len(s); p.write_text(s2)"
uv run pytest tests/test_dedup.py -q                  # 4 failed — .pyc 가 변이본 mtime 기록

# 원복 + mtime 을 .pyc 에 적힌 초로 되돌린다
MUT=$(python3 -c "
import glob, struct
print(struct.unpack('<4sIII', open(glob.glob('src/bullet_in/__pycache__/dedup*.pyc')[0],'rb').read(16))[2])")
cp /tmp/dedup.bak src/bullet_in/dedup.py
python3 -c "import os; os.utime('src/bullet_in/dedup.py', ($MUT, $MUT))"
grep -c "new_body_level > last_level" src/bullet_in/dedup.py   # 1 — 소스는 정상
uv run pytest tests/test_dedup.py -q                  # 4 failed — 캐시된 변이본이 돈다
```

## 해결 · 예방

- **원복 후에는 `__pycache__` 를 지우고 다시 돌린다.**
확인 절차의 마지막 단계로 붙여 둔다.

```bash
find src tests -name __pycache__ -type d -exec rm -rf {} +
```

- **변이는 파일 크기가 달라지게 만든다** — 한 줄을 지우거나 문자를 더한다.
토큰 순서만 뒤집는 변이는 크기가 그대로라 이 함정에 정확히 걸린다.
- **원복이 정말 됐는지 소스로 판단하지 않는다.**
`grep` · `inspect` 는 `.py` 를 보여 줄 뿐이라 이 상황에서 무죄를 증명하지 못한다.
`python -c "import m; print(m.__cached__)"` 로 어느 `.pyc` 를 쓰는지 보거나, 캐시를 지우고 다시 돌리는 편이 빠르다.
- **결과가 앞뒤가 안 맞으면 실행 경로부터 의심한다** — 소스 · 테스트 · 로직을 다시 읽기 전에 무엇이 실행되는지를 본다.

## 관련

- `docs/troubleshooting/2026-07-26-repro-harness-loader-mismatch.md`
— 실행되는 것이 내가 보는 것과 다른 또 다른 형태 (재현 하네스의 로더 불일치).
- PR #156 — 이 확인 절차로 기자명 우선순위 테스트가 실제로 결함을 잡는다는 것을 증명한 변경.
