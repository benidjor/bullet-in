# 알림 발송 예외가 파이프라인을 죽이는 함정 (2026-07-13)

## 배경

SLO-6 수집 이상 알림 (PR #34) 의 `notify.send_alert` 는 알림 발송 실패가 수집 파이프라인 · Airflow 태스크를 죽이지 않아야 한다.
이는 스펙의 Global Constraint ("알림 실패 무해") 이자, 소프트 드리프트 알림이 run.py `main()` 안에서 동기 호출되기 때문이다.
최초 구현은 `except httpx.HTTPError` 로 예외를 삼켰고 단위 테스트도 통과했으나, 최종 리뷰에서 이 방어가 불완전함이 드러났다.

## 증상

webhook URL 이 오설정된 상태에서 파이프라인이 이상 소스를 만나 알림을 발송하려 하면, `send_alert` 안에 `try/except` 가 있는데도 예외가 밖으로 새어 `main()` 을 중단시킨다.

- 소프트 드리프트 알림은 `run.py` 의 수집 · 서빙 흐름 안에서 호출된다.
- 따라서 알림 단계의 예외가 곧 그 회차의 수집 파이프라인 실패가 된다 — 알림 부가기능이 본체를 끌어내리는 역전.

## 원인 — `httpx.InvalidURL` 은 `httpx.HTTPError` 의 서브클래스가 아님

`except httpx.HTTPError` 는 이름의 직관과 달리 httpx 의 모든 오류를 잡지 않는다.

- `httpx.HTTPError` 계열 (`TimeoutException` · `ConnectError` · `ReadError` 등) 은 잡히지만, `httpx.InvalidURL` 은 이 계층 밖의 별도 예외다.
- 검증: `issubclass(httpx.InvalidURL, httpx.HTTPError)` 는 `False`.
- webhook URL 이 스킴 누락 · 형식 오류면 `httpx.post` 가 `InvalidURL` 을 던지고, 이는 `except httpx.HTTPError` 를 그대로 통과해 호출자 (`main()`) 로 전파된다.
- 흔한 네트워크 실패 (timeout · connect · read) 는 `HTTPError` 로 커버되므로 단위 테스트 (`HTTPError` 를 raise) 는 통과했고, 이 갭은 정적 · 동적으로 드러나지 않았다.

## 해결 — 알림 경로는 모든 예외를 삼킴

`send_alert` 의 `except` 를 예외 타입 계층에 의존하지 않게 넓힌다.

```python
    try:
        resp = httpx.post(url, json={"embeds": [embed]}, timeout=10)
        if resp.status_code >= 300:
            logger.warning("알림 발송 실패 (status %s): %s", resp.status_code, title)
    except Exception as e:          # httpx.HTTPError → Exception 로 확대
        logger.warning("알림 발송 오류: %s (%s)", title, e)
```

- 근거 — 알림은 부가 기능이므로, 발송 경로에서 발생하는 어떤 예외도 본체를 죽여선 안 된다.
  여기서는 좁은 `except` 가 오히려 위험하다 (놓친 예외가 파이프라인 실패로 승격) .
- 회귀 방지 — `HTTPError` 가 아닌 예외 (`ValueError` 등) 를 raise 해도 삼켜지는지 검증하는 테스트를 추가했다 (`tests/test_notify.py::test_send_alert_swallows_non_httperror`) .
- fix 커밋 `e04182f`.

## 예방 — "실패가 무해해야 하는" 부수 경로의 except 넓히기

- 로깅 · 알림 · 텔레메트리처럼 **실패해도 본체를 멈추면 안 되는** 부수 경로는, 특정 라이브러리 예외 계층 (`httpx.HTTPError` · `requests.RequestException` 등) 대신 `except Exception` 으로 감싼다.
- 좁은 except 로 특정 예외만 삼키는 패턴은, 그 라이브러리의 예외 계층을 **완전히** 알 때만 안전하다.
  `InvalidURL` 처럼 계층 밖 예외가 하나라도 있으면 갭이 생긴다.
- 단위 테스트가 대표 예외 하나 (`HTTPError`) 만 raise 하면 이런 갭을 못 잡는다.
  "무해" 를 주장하려면 계층 밖 예외 (`Exception` 서브클래스 아무거나) 를 raise 하는 테스트를 둔다.

## 참고

- PR #34 · fix 커밋 `e04182f`.
- spec: `docs/superpowers/specs/2026-07-13-slo6-collection-alerts-design.md` (Global Constraint "알림 실패 무해") .
- 운영: `docs/runbook/2026-07-13-collection-alerts-ops.md`.
