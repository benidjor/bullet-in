# LLM 번역 응답 JSON 파싱이 깨지면 배치 전체가 중단되던 문제

- **날짜**: 2026-05-27
- **영역**: enrich
- **심각도**: 중 (한 행 때문에 그 실행의 나머지 번역이 전부 유실)

## 증상
번역/요약 인리치먼트에서, LLM 응답 한 건이라도 순수 JSON이 아니면 `json.loads`가 예외를 던지고, 루프가 거기서 멈춰 **그 이후 모든 기사의 번역이 유실**된다.

문제의 코드:
```python
data = json.loads(msg.content[0].text)   # 응답이 깔끔한 JSON이라고 가정
result[r["content_hash"]] = (data["title_ko"], data["summary_ko"])
```

## 진단 과정 (왜 이렇게 판단했는가)
1. **외부 출력 신뢰 점검**: LLM 출력은 우리가 통제하지 못하는 외부 입력이다. 그런데 코드는 "항상 깔끔한 JSON"을 가정하고 곧바로 `json.loads`.
2. **실제 LLM 행동 상기**: 모델은 종종 ```` ```json ... ``` ```` 코드펜스나 "Here is the JSON:" 같은 설명 문장을 덧붙인다. 그러면 `json.loads`가 `JSONDecodeError`.
3. **폭발 반경 확인**: 이 호출이 `for r in rows:` 루프 안에 있고 예외를 잡지 않으므로, **한 행의 실패가 함수 전체를 중단** → 그 실행의 나머지 번역 손실. 단위 테스트는 클린 JSON만 줘서 못 잡음.

## 원인
(1) 파싱이 비관대(코드펜스/프로즈 미허용), (2) 행 단위 실패 격리 없음.

## 해결
응답에서 첫 `{...}` 블록을 추출해 파싱하고, **행 단위 try/except로 격리**한다(한 행 실패가 배치를 죽이지 않음).

```python
def _extract(text: str) -> tuple[str, str] | None:
    m = re.search(r"\{.*\}", text, re.DOTALL)   # 펜스/프로즈 안의 JSON만 추출
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        return d["title_ko"], d["summary_ko"]
    except (json.JSONDecodeError, KeyError, TypeError):
        return None

# enrich_rows 내부: 행마다 try/except, 실패 행은 건너뛰고 계속
```

회귀 테스트 2건 추가: 코드펜스로 감싼 JSON 정상 파싱, 불량 행이 있어도 정상 행은 번역됨.

## 예방
- 외부(LLM/API) 출력 파싱은 **항상 관대하게**(추출 + 검증) 하고, **항목 단위로 실패를 격리**해 부분 실패가 전체를 무너뜨리지 않게 한다.
- 가능하면 LLM 호출에 structured output/JSON 모드를 쓰고, 그래도 방어 파싱을 둔다.
- (멱등 설계 덕에) 실패한 행은 `title_ko`가 NULL로 남아 다음 실행에서 자동 재시도된다.
