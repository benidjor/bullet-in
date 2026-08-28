# 주소를 접는 규칙만 넓히고 저장된 주소는 그대로 뒀다 (2026-08-29)

트윗 역추적 (안건 σ) 이 페이월 기사를 어떻게 버리는지 재려다가, 그 옆에서 다른 것이 나왔다.
**저장된 기사 936건 중 156건의 주소가 지금 규칙으로 다시 접으면 다른 값이 된다.**
그리고 그 가운데 32건은 이미 같은 기사가 두 행으로 서 있다.

## 1. 무엇이 어긋나 있나

중복 판정은 `dedup.classify` 가 하고, 그것이 받는 목록은 `MartStore.seen_map()` 이다.

```python
def seen_map(self):
    rows = c.execute(text("SELECT url,content_hash,revision,source_id, ... FROM articles"))
    return {u: (h, rev, sid, int(lv)) for u, h, rev, sid, lv in rows}
```

**키가 저장된 주소 문자열 그대로다.**
새로 들어온 기사는 `canonical_url()` 을 통과한 주소로 조회되므로, 저장값이 옛 모양이면 그 행은 조회에 안 걸린다.
같은 기사가 다시 오면 **없는 것으로 보고 새 행을 만든다.**

2026-08-28 에 주소 정규화가 넓어졌다 (PR #366 · BBC 호스트 · 스카이 섹션 번호 · Athletic 슬러그 · 추적 인자 셋).
규칙은 넓어졌는데 **이미 저장돼 있던 주소는 옛 모양으로 남았다.**

```
저장 URL ≠ canonical_url(저장 URL)          156행 / 936행
  www.nytimes.com   108
  www.skysports.com  46
  www.bbc.co.uk       2
```

## 2. 화면에 이미 나와 있다

지금 규칙으로 접으면 한 키가 되는 묶음이 **16개 · 행 32개**다.
32행 전부 `title_ko` 가 채워져 있다
— 번역까지 끝난 행이라 렌더 입력에서 걸러지지 않는다.

```
https://www.nytimes.com/athletic/7526325/2026/08/21
   d4d1209c fmkorea 귀속 9 · 69c45b29 fmkorea 귀속 10
https://www.skysports.com/football/news/13576278
   02a632a5 skysports 귀속 4 · 36a4f6c9 skysports 귀속 11
```

소스별로는 fmkorea 24 · x_ornstein 4 · skysports 4 다.
합칠 때 옮겨야 할 선수 귀속은 최대 70건이다 (`article_players` 는 PK 가 `(content_hash, player_id)` 라 그 복합키로 센다).

**「두 모양이 다 들어온다」 가 원인이다.**
The Athletic 은 슬러그가 붙은 주소와 날짜까지만 있는 주소를 둘 다 내보낸다.
게시자가 어느 쪽을 붙일지는 우리가 못 정한다.
정규화는 그 둘을 접으라고 들어온 규칙이다.
그런데 접을 대상 가운데 **먼저 저장된 쪽**이 옛 모양이면 규칙이 닿지 않는다.

## 3. 이것이 다음 작업을 가른다

안건 σ 의 페이월 갈래는 트윗 주소를 기사 주소로 바꾸는 일이다.
바꾼 주소는 `canonical_url` 을 지나 짧은 모양이 되는데, 짝이 되는 fmkorea 행이 긴 모양으로 저장돼 있으면 **합쳐지는 대신 세 번째 행이 생긴다.**

같은 `classify` 를 두 잣대로 돌려 봤다 (저널 전 구간에서 페이월로 버려진 기사 14건).

| 잣대 | 합쳐짐 | 새 행 |
| --- | --- | --- |
| 지금 (저장 URL 그대로) | 6 | 8 |
| 재정규화 뒤 | **12** | 2 |

**재정규화를 먼저 하면 σ 의 효과가 두 배가 된다.**
순서를 뒤집으면 σ 가 중복을 줄이는 대신 늘린다.

## 4. 재는 법

두 줄이면 된다.
운영 DB 에 붙어 **제품이 쓰는 함수 그대로** 부른다.

```python
from bullet_in.canonical import canonical_url
drift = [r for r in rows if canonical_url(r["url"]) != r["url"]]

groups = defaultdict(list)
for r in rows:
    groups[canonical_url(r["url"])].append(r)
dup = {k: v for k, v in groups.items() if len(v) > 1}
```

**앞 줄이 「규칙이 안 닿는 행」 이고 뒤 줄이 「이미 두 행인 것」 이다.**
뒤 줄만 세면 아직 짝이 안 온 140행을 못 본다 — 그 행들은 짝이 오는 날 새 행을 만든다.

## 5. 규율

**정규화 규칙을 바꾸는 배포에는 저장값 재계산이 함께 들어간다.**
흡수 설계 (`docs/superpowers/specs/2026-08-14-tweet-article-absorption-design.md` §4.1) 에 그렇게 적혀 있다
— 「`canonical_url` 을 바꾸면 저장된 URL 과 새로 계산한 키가 어긋난다」.
적혀 있는데도 한 배포에서 병합만 들어갔다.

**병합과 재계산은 다른 일이다.**
병합은 **이미 충돌한** 묶음을 지운다 (16묶음).
재계산은 **아직 충돌하지 않은** 행까지 규칙 안으로 들여놓는다 (140행).
병합만 하면 다음 회차에 같은 묶음이 다시 생긴다.

**「묶음 0」 은 종결 신호가 아니다.**
병합 직후에는 언제나 0 이 나온다 — 방금 지웠기 때문이다.
닫혔는지는 **드리프트 행 수**로 본다.
그 수가 0 이 아니면 아직 열려 있다.

## 관련

- `docs/superpowers/specs/2026-08-14-tweet-article-absorption-design.md` — §2.2 · §4.1 에 이 선후가 적혀 있다
- `docs/troubleshooting/2026-08-29-measuring-with-inputs-the-product-does-not-use.md` — 재는 코드는 제품이 쓰는 함수를 그대로 부른다
- `docs/runbook/2026-08-08-onetime-db-batch-via-tunnel.md` — 운영 DB 1회성 배치 절차
