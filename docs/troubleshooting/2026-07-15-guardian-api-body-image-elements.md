# Guardian API body HTML에는 img가 없다 — 인라인 이미지는 elements 경로

인라인 이미지 트랙 (#50) 에서 Guardian은 `show-fields`에 `body` (HTML) 를 추가해
공통 파서 (`extract_body_images`) 로 이미지를 뽑는 설계였다.
단위 테스트 (모킹) 와 태스크 리뷰를 통과했지만, API 키 확보 후 라이브 검증에서 이미지가 0건으로 나왔다.

## 증상

- `guardian: 3건 / 이미지 보유 0건` — 어댑터 단독 fetch에서 body 필드는 오지만 이미지가 비어 있음.
- 파싱 에러 · 예외 없음 (파서가 빈 목록 폴백이라 침묵 실패와 구분 안 됨).

## 원인

- Guardian Content API의 `body` HTML에는 **`<img>` 태그가 아예 없다**.
  본문 내 figure는 interactive 임베드뿐이고, 사진은 별도 `elements` 구조로만 제공된다.
- 즉 "body HTML에서 img를 뽑는다"는 spec 가정이 라이브에서 파기된 사례
  — 문서화된 API라도 필드 구성은 실측 전까지 가정이다 (셀렉터 드리프트와 같은 계열).

## 해결

- 요청에 `show-elements: image` 추가 → 결과별 `elements` (type=image) 의 `assets`에서 URL 채택.
- **asset 선택은 최대 폭 기준** (`typeData.width` max)
  — 마지막 asset이 140px 썸네일인 사례를 실측했으므로 배열 순서에 의존하면 안 된다.
- body HTML 추출은 폴백으로 유지 (향후 API가 body에 img를 포함하는 경우 대비), `bodyText` 본문 경로는 무변경.
- 재검증: guardian 3건 / 이미지 보유 3건.

## 교훈 · 예방

- **외부 API 필드 가정은 머지 게이트의 라이브 검증 대상에 포함**할 것
  — 이 건은 키 부재로 라이브 검증이 뒤로 밀리며 머지 후에야 드러났다.
- 이미지 파서의 빈 목록 폴백은 수집을 보호하지만 **가정 파기도 침묵**시킨다.
  소스별 "이미지 보유 0건"은 신선도 0건과 같은 의심 신호로 취급한다.
- 시크릿 (API 키) 은 worktree `.env`에만 두면 worktree 제거와 함께 소실된다
  — 이 트랙에서 GUARDIAN_API_KEY가 그렇게 사라져 사용자 재발급 · 재주입이 필요했다.

## 참조

- 수정 커밋: `5701321` (PR #50)
- spec: `docs/superpowers/specs/2026-07-15-inline-body-images-design.md`
- 유사 계열: `docs/troubleshooting/2026-06-12-live-source-selector-drift.md`
