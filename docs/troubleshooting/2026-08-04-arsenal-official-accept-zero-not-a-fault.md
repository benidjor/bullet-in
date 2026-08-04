# arsenal_official 채택 0 은 장애가 아니었다 (2026-08-04)

신선도 경고가 `arsenal_official` 을 두고 매 회차 `이번 회차 후보 0건 — 수집 끊김 의심` 이라고 알린다.
2026-08-04 기준 266시간 (11일) 경과로 표기됐고 마지막 수집은 7월 24일이다.
**11일째 이어지는 수집 장애로 보였으나 장애가 아니다.**
알림 문구가 원인을 잘못 지목한 것이고, 감시 불변식에는 이 상태를 담는 조건이 없다.

## 1. 증상

- 신선도 경고가 하루 8회 (매 회차) 발화하며 `수집 끊김 의심` 을 붙인다.
- 공홈 커버리지 알림은 같은 기간 **0건** 발화했다.
- 어댑터 로그를 보면 발견은 되고 채택만 0 이다.

```
arsenal_official: 창 후보 23 · Men 11 · accept 0
arsenal_official: 창 후보 16 · Men  7 · accept 0
```

- 7월 28일부터 8월 4일까지 매일 같은 모양이었다 (후보 13 ~ 25 · 채택 0) .

## 2. 확인한 것

접촉 없이 로그와 코드로 좁힌 뒤, arsenal.com 을 직접 조회해 확정했다.

- **발견 경로 정상** — sitemap 에서 창 후보가 매 회차 16 ~ 27건 잡힌다.
`glideId 추출 실패` · `GetArticle 실패` · `GetArticle 응답 없음` 경고는 0건이다.
- **taxonomy 어휘도 그대로** — `Transfer news` · `Contract news` 가 여전히 존재한다.
어휘 개편 가설은 기각.
- **필터는 무변경** — `_accept` 는 2026-07-19 (#68) 이후 한 글자도 바뀌지 않았다.
우리 쪽 회귀가 아니다.

채택 조건은 셋이다 (`src/bullet_in/adapters/arsenal_api.py`) .

```python
def _accept(article):
    tax = set(article.get("taxonomies") or [])
    return (article.get("articleType") == "News"
            and "Men" in tax
            and bool({"Transfer news", "Contract news"} & tax))
```

## 3. 원인 — 두 태그가 거의 만나지 않는다

14일 창의 이적 관련 기사 16건을 전부 조회했다.

```
Men 8건 · 이적 태그 5건 · 둘 다 가진 것 1건
```

| 기사 | 태그 | 채택 |
| --- | --- | --- |
| Christos Tzolis signs for Arsenal | `Men` + `Transfer news` | 통과 |
| Transfer window 2026: Former Gunners on the move | `Club` + `Transfer news` | 탈락 |
| Arsenal transfers: All the ins and outs in 2026/27 | `Club` + `Transfer news` | 탈락 |
| Callan Hamill signs professional contract | `Academy` + `Contract news` | 탈락 |
| Elijah Upson signs for Arsenal | `Academy` + `Transfer news` | 탈락 |

- 통과한 한 건은 2026-07-23 12:10 UTC 발행이고, 마지막 수집 시각 (7월 24일) 과 일치한다.
**그 기사가 마지막으로 수집된 기사다.**
- arsenal.com 은 **1군 영입 · 계약 공식 발표에만** `Men` 과 이적 태그를 함께 붙인다.
구단 차원 이적 정리와 아카데미 계약은 `Club` · `Academy` 로 분류한다.
- 즉 7월 23일 이후 1군 공식 발표가 없었을 뿐이고, 채택 0 은 산술적으로 맞다.

## 4. 진짜 문제 둘

### 4.1. 알림이 원인을 지어낸다

`수집 끊김 의심` 은 경로가 멀쩡한데 원인을 지목한다.
읽는 사람은 "사이트 접속이 안 되나 보다" 로 오해하기 쉽다.
실제로는 접속도 목록 수신도 정상이고 어댑터 내부에서 16 ~ 27건을 받아 전부 떨어뜨리는 중이다.

- 같은 함정으로 SLO-5 를 두 번 고쳤다 (#169 · #174) .
- 임계 168시간도 1군 영입 발표 간격보다 짧다.

### 4.2. 감시 불변식에 이 상태가 없다

`quality.evaluate_coverage` 는 두 가지만 본다.

```python
if coverage.get("candidates", 0) == 0:   # 발견 경로 장애
if coverage.get("men_tagged", 0) == 0:   # taxonomy 드리프트
# accept 0 은 비수기 정상이라 판정하지 않는다 (spec 2026-07-24 §5)
```

현재 상태는 **후보 있음 · Men 있음 · 채택 0** 이라 셋 중 감시하지 않기로 한 자리에 정확히 들어간다.
`accept 0 = 비수기` 라는 전제가 8일 연속에는 성립하지 않는다.

## 5. 남은 판단

- **알림 문구** — 후보 0 의 원인을 적지 않도록 고친다.
차단 알림 (#218) 이 같은 원칙으로 문구를 짜 놓았으니 그 방식을 따르면 된다.
- **필터 범위 (제품 판단)** — `Club` 태그 이적 정리 기사는 이 서비스 성격에 맞는데 `Men` 이 없어 버려진다.
받을지 말지는 제품 결정이라 이 문서에서 정하지 않는다.
- **불변식 보강** — "후보는 있는데 채택이 N회 연속 0" 을 감시에 넣을지.
원인을 모르는 채로 감시만 더하면 알림이 하나 늘 뿐이므로, 위 두 판단이 먼저다.

## 6. 재현 방법

접촉 1회로 확인된다 (arsenal.com 은 접촉 예산 제약이 없다) .

```bash
uv run python -c "
import asyncio, httpx
from datetime import datetime, timezone
from bullet_in.adapters.arsenal_api import (SITEMAP_URL, GRAPHQL_URL, ARTICLE_QUERY,
                                            _sitemap_candidates, _glide_id, _accept)
async def main():
    now = datetime.now(timezone.utc)
    async with httpx.AsyncClient(timeout=20, headers={'User-Agent': 'bullet-in/0.1'}) as c:
        r = await c.get(SITEMAP_URL); r.raise_for_status()
        for url in _sitemap_candidates(r.text, now, 336.0)[:10]:
            resp = await c.post(GRAPHQL_URL, json={'operationName': 'GetArticle',
                'query': ARTICLE_QUERY,
                'variables': {'articleId': '', 'glideId': _glide_id(url), 'glidePath': ''}})
            art = (resp.json().get('data') or {}).get('getArticle') or {}
            print(art.get('articleType'), art.get('taxonomies'), _accept(art))
asyncio.run(main())
"
```

## 7. 앞선 문서와의 관계

`docs/troubleshooting/2026-07-24-arsenal-official-filter-starvation.md` 가 같은 모호성을 이미 지적했다.

> 이 소스는 영입 없는 평시에 0건이 정상이라, "0건" 신호만으로 기아와 평시를 구분할 수 없다.

- 그 문서는 **기아** 쪽 사례다 — 여자팀 콘텐츠가 50건 창을 도배해 남자 이적 뉴스가 밀려났다.
- 이 문서는 **평시** 쪽 사례다 — 창은 정상이고 1군 공식 발표가 없었을 뿐인데 11일이나 이어졌다.
- 두 사례를 합치면 결론은 하나다.
**`accept 0` 은 그 자체로 정상 · 비정상을 판정할 수 없고, 지금 알림은 그것을 판정한 것처럼 말한다.**

## 8. 참고

- 어댑터: `src/bullet_in/adapters/arsenal_api.py` · 불변식: `src/bullet_in/quality.py` 의 `evaluate_coverage`.
- 발견 경로 전환: PR #128 (sitemap) · 필터 재설계: PR #68.
- 선행 사례: `docs/troubleshooting/2026-07-24-arsenal-official-filter-starvation.md`.
