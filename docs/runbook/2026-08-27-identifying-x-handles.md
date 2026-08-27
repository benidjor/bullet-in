# X 핸들의 주인을 확인하는 절차 (2026-08-27)

집계 계정 (afcstuff) 은 인용한 사람의 **핸들만** 남긴다.
그래서 사이드바 기자 목록에 `@alex_crook` · `@MailSport` 처럼 핸들이 그대로 뜬다.

등재로 접으려면 그 핸들의 주인을 알아야 하는데, **짐작으로 매칭하면 엉뚱한 사람이 붙는다.**
아래는 2026-08-27 에 63종을 1종까지 줄이며 쓴 순서다.

## 1. 먼저 가진 것을 센다 (외부 접촉 0)

핸들이 실제로 몇 건이고 이미 등재된 것은 무엇인지부터 본다.

```sql
SELECT journalist, COUNT(*) c FROM articles WHERE journalist LIKE '@%' GROUP BY journalist ORDER BY c DESC;
```

**트윗 본문에는 실명이 거의 없다.**
Mongo `raw_items` 의 `raw_payload` 는 `text` · `created_at` · `journalist` · `handles` · `image_url` 뿐이고, 본문은 인용된 문장이라 「누가 썼다」 가 안 적혀 있다.
그래서 여기서 끝나는 것은 **이미 등재된 사람의 별칭 누락** 뿐이다.

## 2. 핸들에 이름이 그대로 있는 것부터 접는다

`@alex_crook` · `@LucaBendoni` · `@MarioCortegana` 처럼 이름이 보이는 것은 추가 조회 없이 짝이 확정된다.
이때도 **이미 등재된 사람인지 먼저 본다** — 별칭만 더하면 되는 자리가 섞여 있다.

## 3. 남은 것은 프로필을 연다

WebFetch 는 X 에서 **HTTP 402** 를 돌려준다.
브라우저로 열어 표시 이름과 소개글만 읽는다.

```javascript
// 프로필 열고 2초쯤 뒤
(document.querySelector('[data-testid="UserName"]')?.innerText?.replace(/\n/g, ' ') || '?')
  + ' :: ' + (document.querySelector('[data-testid="UserDescription"]')?.innerText?.replace(/\n/g, ' ').slice(0, 120) || '')
```

- **한 번에 5 ~ 6개씩 묶어 연다** (browser_batch) — 왕복이 줄고 X 쪽 부담도 적다.
- `document.title` 은 비어 있을 때가 많다 (SPA 가 늦게 채운다) — `UserName` 을 읽는다.
- 소개글이 소속을 알려 준다 (예 — `Journalist at @diarioas` → AS · `Sports Reporter @standardsport` → Evening Standard).
- **가끔 값 대신 `[BLOCKED: Cookie/query string data]` 가 온다** — 같은 탭에서 한 번 더 읽으면 나온다.

## 4. 갈래를 나눠 등재한다

프로필을 보면 셋으로 갈린다.

| 갈래 | 처방 | 예 |
| --- | --- | --- |
| 사람 | 정식명으로 등재 · 소속이 확실하면 함께 | `Eduardo Burgos` (AS) · `Sam Tabuteau` (Evening Standard) |
| 매체 · 조직 계정 | **기자 사전에 매체 이름으로** 등재 (언론사 사전은 기자 축이 안 본다) | `Daily Mail` · `Cadena SER` |
| ITK · 팬 계정 | 이름 뒤에 `(ITK)` 를 붙여 성격을 드러냄 | `HandofArsenal (ITK)` |

**등급은 기본적으로 안 매긴다.**
표기만 접는 등재는 미등재 폴백 (4) 을 유지하고, 등급은 사전 소유자가 따로 정한다.

**기자가 아닌 계정이 나올 수 있다.**
2026-08-27 에 `@clubgame` 은 판타지 축구 게임 앱이었고, 그 글은 「선수 능력치」 였다.
이런 것은 등재가 아니라 **수집에서 빼는 자리**다 (`journalist_denylist` · PR #350).

## 5. 확인은 「@ 로 남는 항목 수」 로 한다

등재는 조용히 실패한다 (철자 하나만 달라도 안 걸린다 · `2026-08-27-registered-but-never-matched.md`).
그래서 **전후로 이 수치를 잰다.**

```
기자 항목 180 → 171 · @ 로 남는 항목 63 → 1
```

숫자가 안 움직이면 등재가 아니라 조회 축을 잘못 고른 것이다.

## 관련

- `docs/troubleshooting/2026-08-27-registered-but-never-matched.md`
- `docs/superpowers/specs/2026-08-14-tweet-article-absorption-design.md` §2.4 — 기자 등재로 흡수 판정을 넓히는 층
- PR — #348 (신원 확인 · 등재) · #350 (기자가 아닌 인용처 제외)
