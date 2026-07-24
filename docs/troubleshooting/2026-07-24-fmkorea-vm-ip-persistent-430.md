# fmkorea 가 VM 에서만 전 회차 430 — IP 단위 지속 차단 (2026-07-24)

fmkorea 수집이 VM 이관 (2026-07-20) 첫 회차부터 나흘간 0건이었다.
어댑터 코드 결함이 아니라 Oracle DC IP 가 fmkorea 에 지속 차단된 인프라 문제다.
전 소스 커버리지 감사에서 확인했고, 복구는 별도 트랙 (수집 경로 결정) 으로 확정됐다.

## 증상

- DB 의 fmkorea 마지막 신규 적재가 2026-07-19 13:36 UTC (로컬 실행분) 에 고정.
- 커버리지 감사의 라이브 대조에서 검색 3키워드 상위 60건 중 DB 존재 0건
→ 기마랑이스 사가 (BBC 비드 · 협상) · Athletic 한국어 번역본 다수가 통째로 누락.

## 원인 (라이브 실측)

- VM `journalctl` 에서 이관 첫 회차 (07-20 09:02 KST) 부터 감사 시점까지
**모든 회차 · 모든 키워드가 HTTP 430** (`fmkorea 검색 HTTP 430 kw=아스날 — 스킵` 반복).
- 회차 간격이 6시간이라 과속 (기존에 알던 2시간 규칙) 으로는 설명되지 않는다
→ 요청 빈도가 아니라 **발신 IP (Oracle DC 대역) 자체가 차단**된 것으로 판단.
- 같은 시각 로컬 (주거용 IP) 에서는 동일 검색 URL 이 정상 200 (감사 실측)
→ 코드 · 셀렉터 · 검색 URL 은 전부 유효하다.

## 왜 나흘간 몰랐나

- 어댑터의 오류 보존 설계 (키워드별 스킵 + WARNING) 대로 로그는 남았지만, 로그를 열어야 보이는 신호였다.
- SLO-5 신선도는 fmkorea 를 stale (최대 101h) 로 집계했으나,
알림 문구가 "오래 조용하다" 뿐이라 평소의 낮은 수집량과 구분되지 않았다
— arsenal 기아와 같은 패턴 (증상만 재는 신호로는 원인을 짚기 어렵다).

## 진단법

```bash
# VM 에서 — 430 이 언제부터, 어떤 간격으로 났는지
journalctl -u bullet-in.service --since '<이관일>' --no-pager | grep 'fmkorea.*430'
# 로컬에서 — 같은 검색 URL 이 IP 만 달리해 성공하는지 (2h 규칙 준수 후 1회)
curl -s -o /dev/null -w '%{http_code}' -A 'Mozilla/5.0' \
  'https://www.fmkorea.com/search.php?mid=football_news&search_target=title&search_keyword=아스날'
```

- VM 430 + 로컬 200 이면 IP 차단, 둘 다 430 이면 과속 · 전면 차단을 의심한다.

## 복구 가능성 (트랙 설계 입력)

- fmkorea 는 포럼 검색이라 리스트 롤오프가 없다
→ 차단 기간의 글도 **검색 페이징으로 소급 수집 가능** (arsenal API 아카이브와 같은 성질).
- 남는 결정은 수집 경로뿐: 프록시 · 로컬 보조 수집 · 기타
— 코드 수정으로는 해결되지 않으므로 브레인스토밍 → spec 이 선행한다 (사용자 확정 2026-07-24).

## 예방

- DC IP 로 옮겨 돌리는 어댑터는 이관 직후 **소스별 첫 성공 여부**를 확인할 것
— 이관 자체가 발신 IP 변경이라는 인프라 변수를 들여온다.
- "0건 + WARNING 로그" 조합은 로그를 열지 않으면 침묵과 같다
→ 원인을 직접 짚는 신호 (예: arsenal 의 후보 · accept 통과율 알림, PR #128) 를 소스별로 일반화할지는 후속 트랙에서 판단.

## 참고

- 감사 결과 전반: `docs/runbook/2026-07-24-source-coverage-audit.md`
- 430 의 원래 관찰 (과속 · 2h 규칙): `docs/troubleshooting/2026-07-13-fmkorea-search-endpoint-traps.md`
- 같은 침묵 패턴 (arsenal): `docs/troubleshooting/2026-07-24-arsenal-official-filter-starvation.md`
