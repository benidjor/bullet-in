# 런북 — 장애 복구

수집 파이프라인이 잘못됐을 때의 대응 절차. 설계상 각 소스는 격리되어 한 소스 실패가 전체를 멈추지 않는다.

## 특정 소스 수집 실패
- 증상: 실행 요약 `errors` 맵에 `{source_id: 사유}` 가 찍힘.
- 대응: 해당 소스만 격리되어 나머지는 정상 적재됨. 사유를 보고 troubleshooting/ 에 기록 · 조치.
  - 셀렉터 변경 (파서 깨짐) → 어댑터 셀렉터 갱신 후 재실행.
  - 일시적 네트워크/rate limit → 다음 스케줄에 자동 재시도.

## 원문 재처리 (재스크래핑 없이)
- MongoDB `raw_items` 에 원문이 불변 보존되므로, 파서 · 스코어링 로직이 바뀌면 재수집 없이 변환 단계만 재실행해 mart를 다시 채울 수 있다.

## X (twikit) 세션 만료
- 증상: X 어댑터가 인증 오류로 실패.
- 대응: `x_cookies.json` 삭제 후 재실행하면 버너 계정으로 재로그인하여 세션 재생성.

## 품질 게이트 실패 (dbt test 실패)
- 증상: `dbt build` 에서 `unique`/`not_null`/`accepted_values` 테스트 FAIL.
- 대응: 실패한 테스트가 가리키는 행을 조사.
  - `unique` 실패 → dedup 키 (content_hash/url) 충돌. canonicalization 로직 점검.
  - `not_null` 실패 → 어댑터가 필수 필드를 못 채움. 파서 점검.
  - `accepted_values` 실패 → sources.yaml의 tier 값 오류.
- 데이터 또는 파서를 수정한 뒤 재실행.

## 멱등성 보장
- `articles` 는 content_hash/url UNIQUE 제약 + ON DUPLICATE KEY 로 재실행해도 중복 적재되지 않는다.
- LLM enrich는 번역이 비어 있는 신규 행만 처리하므로 재실행 시 재호출 · 중복 비용이 없다.

## 전체 롤백
- 코드 문제면 `git revert` 로 비파괴 롤백. 데이터는 raw_items에서 재처리.
