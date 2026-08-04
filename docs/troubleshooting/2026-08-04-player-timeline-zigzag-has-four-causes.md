# 선수 타임라인이 오르내리는 원인은 넷이다 (2026-08-04)

선수 페이지의 단계 흐름이 뒤죽박죽으로 보인다.
`2026-08-03-player-stage-not-grounded-in-article.md` 는 이것을 "남의 기사에 단계가 붙는다" 로 설명했는데, 실측해 보니 **원인이 넷이고 그 문서가 다룬 것은 하나뿐이다.**

원인마다 해결 경로와 비용이 달라서, 하나를 고치고 화면이 그대로라고 놀라지 않도록 갈라 적는다.

## 실측 — 트로사르 타임라인 11노드 분해

라이브 화면의 노드를 DB 와 하나씩 대조한 결과다.
화면은 KST · DB 는 UTC 라 날짜가 하루 어긋난다.

| 화면 | 소스 | 기사 단계 | 선수 단계 | 원인 |
| --- | --- | --- | --- | --- |
| 07-19 이적 합의 | BBC | agreed | agreed | 정상 |
| 07-16 오피셜 | Arsenal.com | official | official | 정상 |
| 07-15 이적 합의 | fmkorea | interest | **agreed** | A |
| 07-15 협상 중 | Goal | agreed | **medical** | A |
| 07-14 이적 합의 | Guardian | agreed | agreed | 정상 |
| 07-14 오피셜 | Arsenal.com | official | official | B |
| 07-14 루머 | afcstuff | negotiating | **rumour** | A |
| 07-14 이적 합의 | afcstuff | agreed | agreed | 정상 |
| 07-14 루머 | afcstuff | negotiating | **rumour** | A |
| 07-05 개인 합의 | fmkorea | agreed | **personal_terms** | A |
| 06-29 협상 중 | BBC Gossip | rumour | **negotiating** | A |

**이 11건은 전부 진짜 트로사르 기사다.**
남의 기사가 섞인 것이 아닌데도 오르내린다.

## 원인 A — 선수 단계가 그 기사 내용과 다르다

**선수가 한 명뿐인 기사 164건 중 75건 (46%) 에서 기사 단계와 선수 단계가 어긋난다.**
선수가 하나면 두 값이 같아야 하는데 절반 가까이 다르다.

**어긋남이 한 방향이 아니다.**
선수 단계 쪽이 맞는 경우도 있다.

| 기사 | 기사 단계 | 선수 단계 | 어느 쪽이 맞나 |
| --- | --- | --- | --- |
| 브루노 기마랑이스, 아스날 메디컬 테스트 예정 (`bbc_gossip`) | rumour | medical | **선수 쪽** — 기사 쪽이 가십 소스 규칙에 묶여 고정됨 |
| 브루노 기마랑이스, 아스날 이적 임박 (`x_afcstuff`) | agreed | negotiating | **기사 쪽** |

**그래서 "기사 단계를 정답으로 놓고 선수 단계를 맞춘다" 는 접근은 쓸 수 없다.**

버킷 자체도 오염돼 있다.

- `personal_terms` 여덟 건 중 진짜 개인 합의는 **한 건**이다 (나머지는 구단 간 협상 · 가십 라운드업 · 남의 기사).
- `medical` 여덟 건도 절반가량이 메디컬 기사가 아니다 — "영입 위해 뉴캐슬과 협상 착수" 가 `medical` 로 들어 있다.

**해결 경로** — 추출 프롬프트에 근거 조건을 넣고 재추출한다.
Gemini 과금이 따르므로 별도 트랙이다.

## 원인 B — 오피셜은 이적 완료가 아니라 구단 공식 발표다

07-14 Arsenal.com 기사 제목이 `아스날 트로사르, 베식타스 이적 합의 완료` 인데 `오피셜` 배지가 붙는다.
합의 소식에 오피셜이 붙은 것처럼 보이지만 **설계대로다.**

`docs/runbook/2026-06-30-transfer-stage-classification-ops.md` 가 `official` 을 소스 권한으로 정의하고 불변량까지 박아 뒀다.
공홈은 합의 때 한 번 · 확정 때 한 번 올리므로 오피셜이 여러 번 · 진행 순서와 무관하게 나오는 것이 정상 동작이다.

**해결 경로** — 재추출로 안 고쳐진다.
`official` 의 의미를 바꾸려면 스펙 재설계와 전건 재분류가 따른다.
"오피셜 = 이적 확정" 으로 읽히는 문제 자체는 별도 안건으로 뺐다.

이 원인은 날짜 역전도 만든다.
공식 발표 뒤에도 상위 매체가 그 이적을 계속 보도하는데, `official` 이 공홈 전용이라 그 기사들이 전부 `이적 합의` 로 들어온다.

| 날짜 | 매체 | 단계 |
| --- | --- | --- |
| 07-15 | Arsenal.com | 오피셜 |
| 07-18 | BBC | 이적 합의 |
| 07-22 | Guardian | 이적 합의 |

## 원인 C — 발행일이 수집 시각으로 대체됐다

위 표의 BBC 07-18 은 **실제 발행일이 아니다.**
원문은 7월 14일 발행인데, 수집 당시 발행일 추출에 실패해 수집 시각이 대신 저장됐다.

진단 쿼리다.

```sql
-- 발행일이 수집 시각으로 대체된 행
SELECT source_id, COUNT(*)
  FROM articles
 WHERE published_precision IS NULL
   AND ABS(TIMESTAMPDIFF(SECOND, published_at, fetched_at)) < 300
 GROUP BY 1;
```

**해결 경로** — PR #223 이 복구 모듈을 넣었다.
설계는 `docs/superpowers/specs/2026-08-04-published-date-recovery-design.md` 에 있다.

## 원인 D — 매체마다 아는 시점이 다르다

afcstuff 가 07-13 에 "이적 확정" 을 전하고 07-14 에 "베식타스 회장 발언" 을 루머로 전한다.
**이건 데이터가 틀린 것이 아니다.**

**해결 경로** — 표시 정책 문제다.
단계별로 대표 기사 하나만 보여 주는 방식이 후보로 올라와 있다.

## 정리

| 원인 | 재추출로 고쳐지나 | 비용 | 규모 |
| --- | --- | --- | --- |
| A 선수 단계 오분류 | 예 | Gemini 과금 | 선수 1명 기사 164건 중 75건 |
| B 오피셜이 구단 공지 | 아니오 | 스펙 재설계 | 공홈 6건 · 후속 보도 다수 |
| C 발행일 대체 | 아니오 | 없음 (HTTP 만) | 102건 · #223 으로 해결 |
| D 보도 시차 | 아니오 | 없음 (표시 정책) | 상시 |

**하나를 고쳐도 화면이 크게 안 바뀔 수 있다.**
A 만 고치면 B · C · D 가 남고, C 만 고치면 A 가 남는다.

## 참고

- 선수 단위 단계 문제 — `docs/troubleshooting/2026-08-03-player-stage-not-grounded-in-article.md`
- 단계 정의 · 불변량 — `docs/runbook/2026-06-30-transfer-stage-classification-ops.md`
- 발행일 복구 — `docs/superpowers/specs/2026-08-04-published-date-recovery-design.md`
- 같은 세션의 오진 기록 — `docs/troubleshooting/2026-08-04-called-design-a-defect-without-reading-it.md`
