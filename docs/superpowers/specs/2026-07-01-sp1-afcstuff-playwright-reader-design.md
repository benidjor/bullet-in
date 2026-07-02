# SP1 — Playwright afcstuff 리더 설계 (2026-07-01)

afcstuff (X) 발굴 트랙 ([[afcstuff-aggregator-direction]])의 첫 하위 프로젝트.
깨진 twikit을 Playwright로 대체하고, `[ @handle ]` 인용 트윗을 **2순위 (트윗=뉴스)** 항목으로 파이프라인에 흘린다.
1순위 언론사 원문 (역추적)은 SP2에서 이 토대 위에 얹는다.

## 배경

- twikit 2.3.3 (방치)은 현재 X와 호환 불가
  → Playwright (쿠키주입 · headless)로 해결 (spike 검증). 근거: [[afcstuff-x-access-blocker]].
- afcstuff는 출처를 인라인 텍스트 `[ @handle ]` (대괄호 안 공백)로 표기, link-card · quote는 거의 없음.
  → SP1은 이 인용 트윗 자체를 2순위 항목으로 수집한다 (원문 역추적은 SP2).

## 3층 방어 모델 (설계 핵심)

세 가지 관심사 (노이즈 · 429 · 품질)를 **한 게이트로 뭉치지 않고 층으로 분리**한다.

| 층 | 담당 | 역할 |
|---|---|---|
| **① 수집 게이트** | 어댑터 **cited-only 필터** (`[ @handle ]` 없으면 미수집) | 노이즈 (월드컵 반응 · 잡담) · Gemini 429 차단 — **무인용은 파이프라인 진입 자체를 못 함** |
| **② 품질 (신호)** | credibility `x_mentions` + tier | 등록 기자 = 정확한 tier / 미등록 cited = `fallback_tier` (4)로 **생존 · 최하위**. drop 아님, 랭킹으로 표현 |
| **③ 이적무관 숨김** | transfer_stage 분류 + 'other' 서빙 토글 (별도 트랙) | 이적무관을 서빙에서 숨김 |

핵심: **노이즈 · 429를 막는 진짜 게이트는 ①** (credibility와 무관).
②는 "배제"가 아니라 "신뢰 신호"다
— 사용자 결정 (미등록 인용 루머도 담되 후순위 표시)에 부합.
cited-only가 잡담을 이미 걷어내므로 번역 대상은 인용된 실제 뉴스뿐이고, 429 대응 (하루 4회 멱등 누적 스케줄)이 이 volume을 흡수한다.

## 아키텍처 · 컴포넌트

### 1. `src/bullet_in/adapters/x_playwright.py` (신규)

- **순수 파서** `parse_afcstuff_tweets(raw_tweets, handle, now) -> list[RawItem]`.
  DOM에서 뽑은 트윗 dict 리스트 (`{text, created_at, status_id, image_url}`)를 받는다.

  ```
  raw_tweets → [ @handle ] 인용 추출(regex \[\s*@([A-Za-z0-9_]{1,15})\s*\])
             → 인용 ≥1개인 트윗만 통과 → RawItem 생성
  ```

  **단위 테스트는 여기 (브라우저 불필요).**
- **`XPlaywrightAdapter(source_id, handle, max_tweets, cookies_path="x_cookies.json")`** — `fetch()` 흐름:

  ```
  fetch(): chromium(headless) → 쿠키 주입 → x.com/<handle> 이동
           → max_tweets 스크롤 → DOM eval(raw_tweets) → 브라우저 종료
           → parse_afcstuff_tweets()
  ```

  브라우저 I/O는 라이브 검증 대상.
- **재사용 쿠키 헬퍼**: `auth_token` · `ct0`를 `.x.com`/`.twitter.com`에 주입하는 함수.
  → SP2 기자 검색이 그대로 재사용.
- DOM 셀렉터 (spike 확인): `article[data-testid="tweet"]` · `[data-testid="tweetText"]` · `time[datetime]` · `a[href*="/status/"]`.
  **셀렉터 드리프트 상습 함정**
  → 머지 전 라이브 `fetch()` 검증 필수.

### 2. `src/bullet_in/credibility.py` — `resolve_tier` x_mentions에 fallback 추가

등록 기자 미매칭 시 config `fallback_tier`가 있으면 그 값, 없으면 종전대로 `None` (drop)이다.
registry=None 경로는 불변 (방어).
기존 x_mentions/drop 테스트는 플래그가 없으면 종전 동작이라 그대로 통과한다.

```python
    if mode == "x_mentions":
        if registry is None:
            return None
        text = item.raw_payload.get("text", "")
        handles = {("@" + h).lower() for h in _HANDLE_RE.findall(text)}
        tiers = [registry.journalists[k] for k in handles if k in registry.journalists]
        if tiers:
            return min(tiers)
        fb = src.get("fallback_tier")
        return float(fb) if fb is not None else None
```

### 3. `config/credibility.yaml` — 레지스트리 정합화 (tier 정확도)

afcstuff가 실제 인용하는 핸들을 반영한다.
**드롭 방지가 아니라 tier 정확도**다 (정합화 안 하면 fallback 4로 생존은 하나 신뢰 출처가 최하위로 오분류됨).
spike에서 관찰된 미스매치 · 누락:
- **Sami Mokbel**: 별칭에 `@SamiMokbel_BBC` 추가 (기존 `@SamiMokbel1_DM` 유지). tier 1.
- **gunnerblog** (`@gunnerblog`), **Matt Law** (`@Matt_Law_DT`, Telegraph) 등 관찰된 핸들 신규 등록.
- **팟캐스트/구두 출처** (예: `@LatteFirm`)
  — 2순위로 담고 싶은 대상이므로 tier 부여해 등록한다 (초기 tier는 편집 판단).
- tier 값은 초기 제안일 뿐, 편집적으로 조정 · 확장 가능 (관찰 누적 시 별칭 추가).

### 4. `src/bullet_in/adapters/factory.py` · `config/sources.yaml`

- factory: 어댑터 키 `x_playwright` 배선 (기존 `x_twikit` 분기 대체).
- sources.yaml `x_afcstuff`:

  ```yaml
  - source_id: x_afcstuff
    display_name: afcstuff (aggregator)
    medium: x
    adapter: x_playwright
    credibility: x_mentions
    fallback_tier: 4
    config: { handle: "afcstuff", max_tweets: 30, cookies_path: "x_cookies.json" }
    enabled: true
  ```

  cited-only로 수율이 줄어 `max_tweets`를 30으로 둔다.
  `enabled: true`는 유효 `x_cookies.json` 전제
  — 없으면 소스 격리 에러로 로깅되고 다른 소스엔 영향 없음.

### 5. 죽은 코드 제거

`x_twikit.py`가 factory에서 참조 제거되어 고아가 된다 (내 변경이 만든 고아).
→ `src/bullet_in/adapters/x_twikit.py`와 `tests/test_x_adapter.py` 삭제.

## raw_payload → 기사 매핑 (기존 `to_articles` 그대로)

`RawItem.raw_payload = {text, created_at, journalist=주 핸들, handles=[전체], image_url}`, `url=permalink`, `source_type="x"`.
`to_articles`가 `title←text` · `published_at←created_at` · `journalist←journalist` · `image_url`을 자동 매핑한다.
**주 핸들 = 마지막 `[ @X ]`** (afcstuff 관례상 출처 인용이 문미).
credibility는 text의 모든 `@handle`을 스캔하므로 tier는 전체 인용 중 `min`이다.
outlet은 미설정이라 config `display_name`으로 폴백한다.

## 데이터 흐름

```
adapter(cited-only) → gather_all → to_articles(dedup · resolve_tier x_mentions/fallback)
  → mart → enrich(EN→KO 번역·요약) → classify(transfer_stage)
  → serve(2순위 항목, 신뢰도순 정렬 시 tier 반영)
```

dedup: `url`=트윗 permalink (고유) + `content_hash(text, url)`
→ 기존 UNIQUE로 중복 제거.

## 테스트 (성공 기준)

- **`parse_afcstuff_tweets` 단위** (브라우저 X): 샘플 dict에서 text/handle/timestamp/permalink 정확 추출 · **무인용 트윗 drop** · 다중 핸들 시 주 핸들=마지막 · image_url 전달.
- **`resolve_tier` fallback**: `x_mentions` + `fallback_tier: 4`.
  미등록 핸들 → 4.0 반환. 등록 핸들 → 기존대로 `min`.
  **fallback 미설정 시 여전히 None (drop)** — 기존 테스트 회귀 없음.
- **레지스트리 정합화**: `@SamiMokbel_BBC`가 Sami Mokbel (tier 1)로 조회됨.
- **라이브 검증** (머지 전, CLAUDE.md 함정): 실제 afcstuff에 `fetch()` 단독 실행.
  → 인용 트윗이 흐르고 월드컵 반응 등 무인용은 걸러지는지 육안 확인 (쿠키 필요).

## 범위 밖 (SP2 · YAGNI)

- 기자 타임라인 **역추적 → 1순위 언론사 원문** (SP2).
- 핸들 → 아웃렛 도메인 매핑 (원문 사이트) — SP2 원문 fetch용.
- 엔티티 (선수명) 추출 — SP2 검색 앵커용. **SP1은 raw text만 저장** (SP2가 필요 시 추출).
- 선수명 · 라우팅 비율 실측은 SP1 라이브 후 별도 관찰.

## SP2 전방 호환

raw_payload에 `text` (선수명 추출 원천) · `handles` (역추적 기자) · `created_at` (매칭 시간창) · `url` (permalink)을 담는다.
이로써 SP2가 afcstuff를 재스크레이프하지 않고 저장된 raw에서 바로 역추적한다.
쿠키 헬퍼도 SP2 검색이 공유한다.

## 참조

- 방향 · 모델: 메모리 [[afcstuff-aggregator-direction]]
- X 접근: 메모리 [[afcstuff-x-access-blocker]]
- 어댑터 인터페이스: `src/bullet_in/adapters/base.py` (`fetch() -> list[RawItem]`), 선례 `playwright_news.py`
- 매핑 · credibility: `src/bullet_in/pipeline.py` (`to_articles`), `src/bullet_in/credibility.py` (`resolve_tier`)
