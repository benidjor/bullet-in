# 변경 기사가 영구 `changed` 루프에 빠지고 번역이 고착되던 문제

- **날짜**: 2026-05-27
- **영역**: storage / dedup / enrich
- **심각도**: 높음 (핵심 dedup · 변경감지 · 멱등 enrich가 깨짐)

## 증상
기사 제목/본문이 실제로 바뀌면:
1. 매 실행마다 `changed`로 재판정되어 `revision`이 끝없이 증가하고,
2. 한국어 번역 (`title_ko`)이 **옛 내용에 고정**된 채 새 제목으로 갱신되지 않는다.

ITK 트윗 · 이적설은 수정이 잦으므로 정상 운영에서 반드시 터지는 경로.

## 진단 과정 (왜 이렇게 판단했는가)
1. **데이터 흐름 추적**: 변경 케이스를 손으로 따라갔다.
   - `seen_map()` → `{url: (last_hash, last_rev)}` 반환.
   - `classify(url, new_hash, seen)` → 같은 url인데 `last_hash != new_hash`면 `("changed", rev+1)`.
   - `to_articles`는 changed면 새 해시 · rev로 Article을 emit → `upsert`.
2. **"왜 매번 changed지?" 추궁**: 변경이 한 번 반영됐다면 다음 실행엔 `seen_map`이 *새* 해시를 줘야 한다. 그런데 계속 옛 해시를 준다 → "upsert가 `content_hash`를 갱신하지 않는 것 아닌가?"
3. **SQL 점검**: `ON DUPLICATE KEY UPDATE` 절을 보니 `title_original` · `revision`만 갱신하고 **`content_hash`는 빠져 있었다.** url UNIQUE 충돌이라 행은 유지되지만 해시는 옛값 그대로 → 다음 실행에서 또 `changed`.
4. **번역 고착 연결**: enrich는 "`title_ko IS NULL`인 신규 행만" 처리하는 구조 (멱등)다. 변경 시 `title_ko`를 리셋하지 않으니, 옛 번역이 새 제목에 그대로 붙어 영원히 갱신 안 됨.

## 원인
dedup 키 (`content_hash`)를 갱신하는 upsert인데 **정작 키 컬럼을 ON DUPLICATE 절에서 갱신하지 않았다.** 또 변경 시 번역 무효화 경로가 없었다. 통합 테스트가 "동일 재삽입 (중복)" 케이스만 덮고 "변경" 케이스를 안 덮어 놓침.

## 해결
ON DUPLICATE 절에서 해시 · 메타를 갱신하고, **해시가 실제로 바뀐 경우에만** 번역을 NULL로 재설정한다. `content_hash` 재대입을 **절 마지막**에 둬서, 그 앞의 `IF`가 *옛* 해시를 평가하도록 한다 (MySQL은 좌→우 평가, 컬럼 참조는 재대입 전까지 옛값).

```sql
ON DUPLICATE KEY UPDATE
  title_ko   = IF(articles.content_hash = VALUES(content_hash), articles.title_ko, NULL),
  summary_ko = IF(articles.content_hash = VALUES(content_hash), articles.summary_ko, NULL),
  title_original = VALUES(title_original),
  body_excerpt   = VALUES(body_excerpt),
  published_at   = VALUES(published_at),
  tier           = VALUES(tier),
  confidence_score = VALUES(confidence_score),
  fetched_at     = VALUES(fetched_at),
  revision       = VALUES(revision),
  content_hash   = VALUES(content_hash)   -- 마지막: 위 IF가 옛 해시를 본 뒤 갱신
```

통합 테스트 `test_changed_url_updates_hash_and_resets_translation`로 (a) 해시 갱신, (b) `title_ko` NULL 재설정, (c) 행 1개 유지를 검증.

## 예방
- **dedup 키를 갱신하는 upsert는 키 컬럼 자체도 반드시 갱신**한다.
- upsert의 "신규"뿐 아니라 "변경" 경로를 테스트로 커버한다.
- 멱등성이 "특정 컬럼이 NULL인지"에 의존하면, 변경 시 그 컬럼을 무효화하는 경로가 있는지 함께 점검한다.
