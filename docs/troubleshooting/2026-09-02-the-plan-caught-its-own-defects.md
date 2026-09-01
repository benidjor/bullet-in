# 계획서의 결함 셋을 계획서 자신이 적어 둔 절차가 잡았다 (2026-09-02)

홈 시간순 개편 (PR #421) 의 계획서에는 실제 코드가 다 적혀 있었다.
그대로 옮겨 적으면 되는 작업이었는데, **그 코드 셋이 틀려 있었다.**

셋 다 계획서가 **함께 적어 둔 확인 절차**에 걸렸다.
코드는 틀렸고 절차는 맞았다.

같은 주제의 앞선 사례는 `2026-07-14-plan-artifact-defect-propagation.md` 다.
그때는 계획서 결함이 그대로 구현으로 전파됐고, 이번에는 막혔다.
차이는 계획서가 코드 옆에 검증 절차를 함께 적어 두었는지에 있다.

## 1. 삭제 목록 15개 중 셋을 지우면 코드가 죽는다

계획서 태스크 6 은 「쓰이지 않게 된 함수 15개를 지운다」 였고 목록에 `recent_days` ·
`PROMOTE_DAYS` · `PROMOTE_PER_PLAYER_DAY` 가 있었다.
뒤의 둘은 함수가 아니라 상수인데 목록이 그것까지 「함수」 로 묶고 있었다.

**셋 다 `pick_empty_day_gossip` 이 살아 있는 한 지울 수 없다.**

```
src/bullet_in/serve/render.py:1210:
    picked = pick_empty_day_gossip(gossip, carded, recent_days(ordered), players)
src/bullet_in/serve/render.py:1950:
    cap: int = PROMOTE_PER_PLAYER_DAY) -> list[dict]:
src/bullet_in/serve/render.py:1985:
def recent_days(articles: list[dict], n: int = PROMOTE_DAYS) -> set:
```

앞의 둘은 `pick_empty_day_gossip` 이 직접 쓰고, `PROMOTE_DAYS` 는 그 함수가 부르는
`recent_days` 의 기본값이다.
**한 겹 건너 매달린 이름이라 눈으로는 더 안 보인다.**

그냥 지웠으면 `NameError` 로 홈 화면 생성이 통째로 실패했을 것이다.

### 1.1. 왜 계획서가 틀렸나

**이름이 함정이었다.**
`PROMOTE_*` 라는 접두사가 「승격 (`promote_recent`) 전용」 처럼 읽히는데,
실제로는 **두 기능이 같은 상수를 공유**하고 있었다.

`pick_empty_day_gossip` 은 카드가 한 장도 없는 날 가십에서 기사를 꺼내는 다른 장치이고,
설계 문서 §6 이 「안 건드리는 것」 에 명시한 함수다.
**설계가 보존하라고 한 함수가 쓰는 것도 보존 대상이다.**

### 1.2. 무엇이 막았나

계획서 태스크 6 의 첫 단계가 이렇게 적혀 있었다.

> **Step 1: 지울 것을 먼저 센다** — 지우기 전에 부르는 곳이 정말 없는지 확인한다.
> **하나라도 호출부가 남아 있으면 지우지 말고 그 자리를 먼저 본다.**

그 grep 이 위의 세 줄을 그대로 뱉었다.
삭제 목록은 15개에서 12개로 줄었다.

## 2. 테스트 도우미 함수 이름이 같은 파일에서 충돌했다

계획서가 `_staged` 라는 도우미 함수를 새로 정의하라고 했는데,
**같은 파일 아래쪽에 같은 이름이 이미 있었다.**

```python
# 247줄 — 계획서가 추가하라고 한 것
def _staged(h, day, stage, title, hour=12): ...

# 391줄 — 이미 있던 것
def _staged(h, stage, hour): ...
```

파이썬은 이것을 오류로 보지 않고 **뒤에 정의된 쪽을 채택한다.**
그래서 위쪽 테스트가 아래쪽 도우미를 부르고, 증상은 엉뚱한 곳에서 나온다.

```
TypeError: _staged() takes 3 positional arguments but 4 were given
```

### 2.1. 무엇이 막았나

TDD 의 「실패를 먼저 확인한다」 단계다.
구현부터 썼다면 이 오류를 **새 코드 탓으로 오진**했을 것이다.
실패 메시지를 읽는 단계가 절차에 있어서 이름 충돌을 짚어냈다.

이름을 `_on_day` 로 바꿔 해결했다.
기존 `_staged` 는 다른 테스트들이 쓰므로 건드리지 않았다.

## 3. 테스트가 쓰는 선수 이름이 명단에 없었다

계획서의 테스트가 「말릭 포파나」 를 제목에 썼다.
그런데 `tests/conftest.py` 가 서빙 선수 사전을 `bullet_in.roster_seed.ROSTER` 로 대체하고,
**그 명단에 포파나가 없다.**

```python
@pytest.fixture(autouse=True)
def stub_serving_player_names(monkeypatch):
    from bullet_in.roster_seed import ROSTER
    names = sorted((r["ko_name"] for r in ROSTER), key=len, reverse=True)
    monkeypatch.setattr("bullet_in.serve.render.load_player_names", lambda engine=None: names)
```

명단에 없으면 `protagonist` 가 주인공을 못 찾고, 그러면 **기사가 아예 묶이지 않는다.**
테스트는 「같은 선수 기사가 한 카드로 묶이는가」 를 보려던 것이라 검사가 통째로 헛돈다.

명단에 있는 「에제」 로 바꿔 해결했다.

## 4. 곁다리로 걸린 것 — 실패해야 할 테스트가 통과했다

위 셋과 별개로, 새로 쓴 테스트 하나가 **실패 대신 통과**했다.

```python
html = render_index(rows, SOURCES, NOW)
assert "reltoggle" not in html      # 접기 버튼이 없어야 한다 → 통과해 버렸다
```

접기 버튼을 아직 안 없앤 시점이라 반드시 실패해야 하는 검사였다.

### 4.1. 원인 — 1면이 목록보다 먼저 기사를 가져간다

`render_index` 는 목록을 만들기 전에 `pick_top_stories` 로 **1면 (히어로 · 주요 소식) 을 먼저 떼어 간다.**
남은 것 (`rest`) 만 묶음이 된다.

테스트에 넣은 기사 둘 중 하나가 1면으로 올라가면서 묶음이 한 건이 됐고,
묶음이 한 건이면 접을 것이 없으므로 버튼이 애초에 안 그려졌다.

**검사하려던 코드 경로를 한 번도 안 밟은 것이다.**

### 4.2. 처방 — 검사 대상을 1면 지평 밖에 둔다

1면 후보는 최근 10일 (`_TOP_HORIZON_DAYS`) 안의 상위 세 등급이다.
그보다 오래된 날짜에 두면 확실히 목록으로 내려온다.

```python
def _same_news_rows():
    """같은 날 · 같은 선수 · 같은 단계 보도 둘 — 1면 지평 (10일) 밖에 둔다.

    1면에 뽑히면 목록에서 빠져 묶음이 한 건이 되고, 그러면 접힘도 줄도 안 생겨
    검사가 헛돈다."""
    return [_row(..., published_at=datetime(2026, 6, 17, 1, 38)), ...]
```

기존 테스트가 `fill` 로 최신 날짜를 채워 두던 이유가 이것이었다.
주석에 그 의도가 적혀 있었는데 처음에 읽지 않았다.

## 5. 남은 것 — 설계 문서 안에서 두 절이 어긋나 있었다

계획서가 아니라 설계 문서 쪽 문제다.

설계 §8 이 검증 기대값으로 「8월 28일에 카드와 줄을 합치면 그날 기사 16건」 을 적었는데,
같은 문서 §6 은 「가십 절 (공신력 최하) 은 안 건드린다」 고 못박고 있었다.
그날 17건 중 10건이 최하 등급이라 가십 구역으로 가므로 두 문장이 동시에 참일 수 없다.

실제 내역은 이렇다.

```
17건 = 카드 5 + 줄 1 + 가십 10 + 머리기사 0 + 숨김 카드 1
```

**코드를 기대값에 맞췄다면 §6 의 가십 규칙이 깨졌을 것이다.**
계획서가 「수가 안 맞으면 **먼저 손계산을 다시 보라**」 고 적어 둔 자리이고, 그대로 따랐다.

## 6. 무엇을 남기나

- **계획서에 코드를 적을 때는 그 코드를 검증할 절차도 함께 적는다.**
   → 이번에 걸린 셋은 전부 절차가 잡았다 · 코드만 있었으면 셋 다 통과했을 것이다
- **「지우기 전에 호출부를 센다」 는 절차는 값이 크다.**
   → 이름이 비슷한 상수를 두 기능이 공유하는 상황은 눈으로 안 보인다
- **TDD 의 「실패를 먼저 확인한다」 는 형식이 아니다.**
   → 실패 메시지가 이름 충돌을 알려 줬고, 통과해 버린 테스트가 1면 구조를 알려 줬다
- **테스트가 통과했다고 검증된 것이 아니다.**
   → 「그 검사가 실제로 실패할 수 있는 상태를 한 번은 보았는가」 를 물어야 한다

## 함께 볼 것

- `docs/troubleshooting/2026-07-14-plan-artifact-defect-propagation.md` — 같은 종류의 결함이 막히지 않고 전파된 사례
- `docs/superpowers/specs/2026-09-02-home-chronological-design.md` — 이 회차의 설계 문서 (§6 · §8 이 어긋나 있던 곳)
- `docs/superpowers/plans/2026-09-02-home-chronological.md` — 절차가 적혀 있던 계획서
