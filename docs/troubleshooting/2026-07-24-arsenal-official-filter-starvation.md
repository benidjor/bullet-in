# arsenal_official 이 오피셜 기사를 조용히 놓치는 필터 기아 (2026-07-24)

공홈 (tier 0 · 최고 공신력) 어댑터가 에러 없이 남자팀 이적 오피셜을 통째로 놓치고 있었다.
사용자가 최신 오피셜 (Christos Tzolis signs for Arsenal) 이 사이트에 없음을 지적해 발견했다 — 내부 신호로는 잡히지 않던 결함이다.

## 증상

- DB 의 arsenal_official 은 5행뿐이고 마지막 수집이 2026-07-19 에 고정.
- Tzolis 영입 오피셜이 타 소스 (bbc_sport · skysports · goal · x_afcstuff) 엔 전부 있는데 공홈 원문만 없음.
- 수집 오류 로그 · 실패 알림 없음.

## 원인 (라이브 실측)

- 어댑터 (`src/bullet_in/adapters/arsenal_api.py`) 는 GraphQL 로 **전 카테고리 최신 50건 (page 1)** 만 받아 클라이언트에서 `_accept` (News + Men + Transfer/Contract news) 로 거른다.
- `taxonomy` 변수에 "Transfer news" 를 줘도 **서버가 무시한다** — 빈 문자열과 같은 50건 · 같은 total (46,895) 을 반환 (실측).
서버 필터가 처음부터 동작하지 않았고, 실질 필터는 클라이언트 `_accept` 뿐이었다.
- 2026-07-22 여자팀 영입 발표일의 영상 · 갤러리 · 포토 콘텐츠가 최신 50건을 도배하자, 남자 이적 뉴스가 50건 창 밖으로 밀려 accept 통과 0건이 됐다.

## 왜 조용한가

- 필터 통과 0건은 오류가 아니다 — fetch 는 성공하고 결과만 빈다.
- 이 소스는 영입 없는 평시에 0건이 정상이라, "0건" 신호만으로 기아와 평시를 구분할 수 없다.
- 수집량 이상탐지 (SLO-6) 도 baseline 이 낮은 소스라 침묵한다.

## 진단법

상위 50건의 accept 통과율과 taxonomy 서버 필터 동작을 직접 확인한다.

```python
# GraphQL 직접 호출 — 어댑터의 LIST_QUERY · _accept 재사용
data = await self._gql(c, "GetArticlesByTaxonomy", LIST_QUERY, {
    "taxonomy": "Transfer news", "pageNumber": 1, "pageSize": 50,
    "sortField": "publishedDate", "sort": "desc",
    "articleTypes": "", "excludedArticles": []})
# ① total 이 taxonomy 없이 부른 값과 같으면 서버 필터 무시
# ② sum(_accept(a) for a in articles) 가 0 이면 클라이언트 필터 기아
```

## 해결 방향 (이 문서 시점 미구현 · 후속 트랙)

- 서버 필터 인자 재조사 — 유효한 taxonomy 값 · articleTypes 조합을 프론트엔드 호출에서 다시 캡처.
- 서버 필터가 끝내 안 되면 페이징 확대로 창을 넓히되 요청 비용과 균형.
- **소급 수집 가능** — 이 API 는 아카이브 페이징을 제공하므로, 리스트 페이지에서 밀려나면 끝인 html 소스와 달리 놓친 기사를 나중에 복원할 수 있다.

## 예방

- "0건이 정상인 소스" 의 커버리지 구멍은 내부 신호 (오류 · 볼륨 · 신선도) 로 잡히지 않는다.
외부 기준 (공홈 사이트 · 타 소스의 같은 사건 보도) 과 대조하는 커버리지 감사가 필요하다.
- 클라이언트 필터 소스는 "받아온 창 안에 대상이 없으면 통째 누락" 구조임을 설계 시점에 명시할 것.

## 참고

- 어댑터 도입 spec: `docs/superpowers/specs/2026-07-19-arsenal-official-api-recovery-design.md`
- 관련 계획: `docs/superpowers/plans/2026-07-22-classification-relevance-track.md` (2026-07-24 정정 블록)
