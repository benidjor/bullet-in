# 등재했는데 한 번도 안 걸렸다 (2026-08-27)

사이드바 기자 목록을 정리하면서 같은 종류의 고장을 세 번 만났다.
**조회 키나 축이 어긋나면 오류가 안 나고 그냥 「없음」 이 된다.**

셋 다 화면에는 「등재 안 된 것처럼」 보였고, 코드에도 데이터에도 잘못된 값은 없었다.

| 자리 | 등재한 것 | 실제로 조회된 것 | 증상 |
| --- | --- | --- | --- |
| 별칭 철자 | `@handofarsnal` | `@HandofArsenal` | 등재가 통째로 무효 |
| 사전의 축 | `outlets` 에 `@MailSport` | 기자 축은 `journalists` 만 봄 | 접기 효과 0 |
| 도구가 읽는 칸 | `journalist` | 화면은 `authors_json` | 없는 버그를 보고함 |

## 1. 별칭 철자가 한 글자 달랐다

`credibility.yaml` 에 `handofarsnal` 이라는 이름과 `@handofarsnal` 별칭이 있었다.
저장된 값은 `@HandofArsenal` 이다.

조회 키는 소문자 · 공백 제거 (`norm_alias`) 라 대소문자는 문제가 아니다.
**빠진 것은 `e` 한 글자다** (`arsnal` ↔ `arsenal`).

그래서 그 계정의 기사 10건이 등재 기자로 안 잡히고 화면에 `@HandofArsenal` 로 남아 있었다.
등급 1.5 도 한 번도 적용된 적이 없다.

**이런 자리는 「등재했다」 는 사실로는 못 잡는다.**
저장값 쪽에서 시작해야 한다.

```sql
SELECT journalist, COUNT(*) FROM articles WHERE journalist LIKE '@%' GROUP BY journalist;
```

이 목록을 등재 키 집합과 대조하면 「등재됐다고 믿었지만 안 걸리는 것」 이 드러난다.
실측에서 83종 중 63종이 그 상태였다.

## 2. 조직 계정을 언론사 사전에 넣었더니 아무 일도 안 일어났다

`@MailSport` · `@talkSPORT` 같은 매체 공식 계정이 기자 이름 자리에 들어온다.
사람이 아니라 매체이므로 `outlets` 에 별칭을 더했다.

**항목은 하나도 안 접혔다.**

`_journalist_view` 는 이름을 `journalists` 사전에서만 찾는다.
`outlet_directory` 는 그 항목의 **소속** 을 정규화할 때만 쓰인다.
즉 기자 축의 표시는 언론사 사전을 안 본다.

처방은 `journalists` 에 **매체 이름으로** 등재하는 것이다.

```yaml
- {name: Daily Mail, outlet: Daily Mail, aliases: ["@MailSport"]}
```

이름과 소속이 같으면 라벨에서 괄호가 생략돼 「Daily Mail」 로 보인다 (설계 §2.5 가).

**두 사전이 있는 곳에서는 「어느 사전을 보는 코드인가」 를 먼저 찾는다.**
넣고 나서 계수가 안 움직이면 그것이 신호다 — 실측 전후가 똑같으면 값이 아니라 축을 잘못 고른 것이다.

## 3. 검토 도구가 화면과 다른 칸을 읽었다

중복 후보 13묶음을 눈으로 보려고 검토 페이지를 만들었다.
바이라인 자리에 `journalist` 칸을 실었는데 그 칸은 fmkorea 경로에서 자주 비어 있다.

그래서 「Sami Mokbel 이 쓴 BBC 기사」 가 검토지에서 바이라인 「—」 로 보였고,
**사용자가 화면 버그로 오해할 자료를 내가 만들어 낸 셈이 됐다.**

실제 화면은 정상이었다.
`article_journalists` 는 `authors_json` 을 먼저 보고, 비어 있을 때만 `journalist` 를 쓴다.
상세 페이지에는 저자 전원이, 카드에는 대표 한 명이 나온다.

| 기사 | `journalist` | `authors_json` | 화면 |
| --- | --- | --- | --- |
| Athletic 7451792 | (비어 있음) | David Ornstein · Jacob Tanswell · James McNicholas | 셋 다 나옴 |
| BBC `cpq8ndn0g7go` | (비어 있음) | Sami Mokbel | 나옴 |

**교훈은 「검토 도구는 화면이 쓰는 경로를 그대로 불러야 한다」 다.**
칸을 손으로 골라 읽으면 도구가 실물과 다른 것을 보고, 그 차이가 사람에게는 버그로 읽힌다.

## 4. 같은 뿌리

셋 다 「조회가 실패했다」 가 아니라 **「조회가 조용히 없음을 돌려줬다」** 다.

- 별칭 오기 — 키가 달라 `None`.
- 사전의 축 — 안 보는 사전이라 `None`.
- 도구의 칸 — 값이 없는 칸이라 `None`.

`None` 은 예외를 안 던지고 폴백 경로로 흘러가 그럴듯한 화면을 만든다.
그래서 **「등재했다」 · 「고쳤다」 를 확인할 때는 그 변경이 실제로 움직여야 하는 수치를 함께 재야 한다.**
이번에는 「@ 로 남는 항목 수」 가 그 잣대였고 63 → 1 로 움직인 것이 유일한 증거였다.

## 관련

- 설계 — `docs/superpowers/specs/2026-08-20-journalist-sidebar-axis-design.md`
- 같은 계열 — `docs/troubleshooting/2026-08-22-code-was-fixed-but-our-notes-still-said-open.md`
- PR — #348 (등급 · 핸들 신원) · #345 · #347 (사이드바 · 대표 선정)
