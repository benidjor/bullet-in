# dbt `accepted_values` deprecation 경고 (dbt 1.11)

- **날짜**: 2026-05-27
- **영역**: dbt
- **심각도**: 낮음 (경고만, 동작은 정상)

## 증상
`dbt build` 실행 시 `tier` 컬럼의 `accepted_values` 테스트에서 deprecation 경고가 뜬다 (테스트 자체는 PASS).

## 진단 과정 (왜 이렇게 판단했는가)
1. 경고 메시지가 "인자를 `arguments` 아래로 중첩하라"는 취지였다 → 테스트 동작이 깨진 게 아니라 **정의 형식이 구버전 문법**임을 가리킨다고 판단.
2. 설치된 dbt 버전 (1.11) release note의 test 인자 형식 변경 (generic test arguments를 `arguments:`로 명시화)과 일치함을 확인.

## 원인
dbt 1.11에서 generic test의 인자를 `arguments:` 키 아래로 중첩하도록 형식이 바뀌었다. 기존 평면 형식 (`values:`를 곧바로)이 deprecated.

## 해결
`dbt/models/sources.yml`에서 `accepted_values` 인자를 `arguments:` 아래로 옮긴다.

```yaml
      - name: tier
        tests:
          - accepted_values:
              arguments:
                values: [0, 1, 1.5, 2, 3, 4]
```

## 예방
dbt 마이너/메이저 업그레이드 시 release note의 deprecation 항목을 먼저 확인하고, generic test 정의 형식을 맞춘다. 경고를 방치하면 다음 메이저에서 빌드 실패로 승격될 수 있다.
