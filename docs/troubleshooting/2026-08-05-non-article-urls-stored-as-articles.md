# 기사가 아닌 주소가 기사로 저장된다 (2026-08-05)

발행일 복구를 돌리다가 "발행일을 못 읽어 건드리지 않음" 으로 빠진 두 건이 나왔다.
열어 보니 **애초에 기사 주소가 아니었다.**

## 실측 — 3건, 전부 fmkorea 경로

| 저장된 제목 | `url` | 무엇인가 |
| --- | --- | --- |
| 아스날, 레안드로 트로사르 베식타스 이적설에 대한 팬들의 반응 | `bbc.com/sport/football/teams/arsenal?post=cm2r2kk4dmyo` | 아스날 팀 페이지 |
| 아스날, 월드컵 기간 주축 선수들의 부상 및 체력 관리 비상 | `bbc.com/sport/football/teams/arsenal?post=c0ey55j8x0do` | 아스날 팀 페이지 |
| 아스날, 에즈리 콘사 영입 제안 준비 | `dailymail.com/profile-201/tom-collomosse.html` | 기자 프로필 페이지 |

전수 조회다.

```sql
SELECT source_id, LEFT(COALESCE(title_ko, title_original), 44) t, url
  FROM articles
 WHERE url REGEXP '/(teams|profile|author|tag|topic|search|category)[-/?]'
    OR url LIKE '%?post=%';
```

세 건 모두 `source_id = 'fmkorea'` 이고 `transfer_stage` 는 `interest` 다.
본문과 번역은 정상이라 화면에 기사로 나온다.

## 왜 이렇게 되나

fmkorea 어댑터는 게시글 본문에서 원문 링크를 뽑아 그것을 `articles.url` 로 쓴다 (`adapters/fmkorea.py` 의 `url=orig`).
게시자가 기사 링크 대신 팀 페이지나 기자 프로필을 걸어 두면 그 주소가 그대로 들어온다.
어댑터는 "링크가 있느냐" 만 보고 "그 링크가 기사냐" 는 보지 않는다.

## 지금 무엇이 잘못되나

- **원문 링크가 엉뚱한 곳으로 간다.**
상세 페이지의 `원문 기사 보기` 가 그 주소를 그대로 쓴다 (라이브에서 확인).
독자가 누르면 기사가 아니라 팀 페이지나 기자 프로필로 간다.
- **재수집 도구가 무관한 내용을 가져올 수 있다.**
발행일 복구는 그 페이지에서 날짜를 못 읽어 무변경으로 빠졌지만, 날짜가 읽히는 목록 페이지였다면 무관한 날짜를 채택했을 것이다.
본문을 다시 받아 오는 도구라면 더 위험하다.
- **`content_hash` 가 그 주소로 만들어진다.**
같은 팀 페이지를 링크한 게시글이 여럿이면 제목이 달라 해시는 갈리지만, 중복 판정 축이 흔들린다.

## 지금은 급하지 않다

세 건뿐이고 본문 · 번역 · 분류는 정상이라 화면이 깨지지 않는다.
원문 링크 하나가 어긋날 뿐이다.

## 고친다면 어디를

세 갈래가 있고 아직 정하지 않았다.

- **수집에서 거른다** — `_extract_original_url` 이 뽑은 주소가 기사 형태인지 확인하고, 아니면 그 글을 스킵한다.
가장 근본적이지만 무엇이 "기사 형태" 인지 정의해야 하고 언론사마다 다르다.
- **서빙에서 링크를 숨긴다** — 기사 주소가 아니면 `원문 기사 보기` 를 안 그린다.
싸지만 원인은 남는다.
- **운영으로 지운다** — 세 건을 지우거나 URL 을 고친다.
지금 규모에는 맞지만 다시 쌓인다.

## 참고

- fmkorea 어댑터 운영 — `docs/runbook/2026-07-13-fmkorea-search-adapter-ops.md`
- 발행일 복구 (이 건이 드러난 경로) — `docs/superpowers/specs/2026-08-04-published-date-recovery-design.md` §9.2
