# 알림 트랙 (F-2) — 실패 유닛 특정 · arsenal_official 알림 정비 · 채택 누락 관측

- 날짜: 2026-08-07
- 선행: 수집 차단 알림 트랙 (PR #218 · #220) · 진단 `docs/troubleshooting/2026-08-04-arsenal-official-accept-zero-not-a-fault.md`
- 상태: 설계 확정 (2026-08-07 사용자 승인 4건 반영)

## 1. 배경

수집 차단 알림 배포 첫날 이후 드러난 미결 2건과 새 오진 1건을 처리하는 트랙이다.
설계 도중 라이브 실측에서 네 번째 문제 (채택 필터 누락) 가 새로 발견돼 범위에 추가됐다.

### 1.1 실패 알림이 실패한 유닛을 특정하지 못한다

2026-08-06 19:35 에 워치리스트 배치 (`bullet-in-watchlist.service`) 가 SOCKS 프록시 오류로 죽었는데,
알림 문구는 "bullet-in.service 실패" 였다.
`bullet-in-fail-notify.service` 의 ExecStart 에 유닛명이 하드코딩돼 있고,
정기 회차와 워치리스트 배치가 같은 유닛을 `OnFailure` 대상으로 공유하기 때문이다.

VM 실물 대조 결과 (2026-08-07):

- VM 의 유닛 5종은 저장소본과 기능적으로 동일하다 (`bullet-in.timer` 의 Description 문구만 다름 · 스케줄 동일).
- 워치리스트 유닛 2종은 2026-08-02 에 수동 설치된 것이며 내용은 저장소본과 같다.
- `install-units.sh` 는 워치리스트 유닛 2종을 설치 대상에 넣지 않는다 (bullet-in.service · timer · fail-notify 3종만 복사).

### 1.2 arsenal_official 신선도 알림 — 원인 추정과 임계

신선도 알림이 매 회차 "이번 회차 후보 0건 — 수집 끊김 의심" 으로 원인을 지목하지만,
진단 문서가 확인했듯 경로는 정상이고 1군 공식 발표가 없었을 뿐이다.

운영 DB 실측 (2026-08-07) — 채택 기사 6건 (06-25 ~ 07-23) 의 발행 간격:

```
28h · 120h · 143h · 187h · 193h
07-23 이후 공백 약 360h 진행 중 (정상 — 1군 발표 없음)
```

채택 필터 (Men + 이적 · 계약 태그) 특성상 이 소스는 이벤트 구동이라 정상 공백의 상한이 없다.
유한한 임계는 어떤 값을 골라도 비수기 정상 공백에서 오발화가 재발한다 (하루 8회 도배).

### 1.3 워치리스트 배치의 SOCKS 오류가 유닛 실패까지 간다

정기 회차는 `ingest.gather_all` 이 `except Exception` 으로 소스별 예외를 흡수하는데,
워치리스트 배치는 `adapter.fetch()` 를 감싸지 않는다.
어댑터 내부는 `httpx.HTTPError` 만 잡으므로 httpx 로 감싸지지 않는
`socksio.exceptions.ProtocolError` 가 유닛까지 새어 나갔다.
빈도 실측: 07-25 이후 약 52회 실행 중 유닛 실패 1회 (08-06).

### 1.4 새 발견 — 채택 필터가 실제 1군 이적 오피셜을 놓쳤다 (2026-08-07 실측)

「Christian Norgaard joins Everton」 (08-05 21:09 UTC 발행) 이 수집되지 않았다.
96시간 창 후보 47건 전수 + 과거 채택 6건 재조회로 원인을 확정했다:

- 발견 경로는 정상 — 기사는 sitemap 창 후보에 들어왔고 GetArticle 조회도 됐다 (Men 계수 포함).
- 탈락 지점은 태그 판별 — `Men` · `News` 는 있는데 `Transfer news` · `Contract news` 가 없다.
- 어휘 소멸이 아니다 — 과거 채택 6건은 지금 재조회해도 전부 `Transfer news` 를 달고 있다.
방출이라서 빠진 것도 아니다 (Trossard 방출 07-15 는 태그가 있었다).
- 편집 측 태깅 누락인지 방침 변화인지는 표본 1건이라 단정하지 않는다.
- 기존 감시로는 못 잡는다 — 커버리지 알림은 창 후보 0 · Men 소멸만 보고,
신선도 알림은 정상 공백과 실수집을 같은 문구로 알려 변별력이 없다.

08-04 진단의 "채택 0 은 산술적으로 맞다" 는 그 시점까지는 사실이었으나 08-05 부로 깨졌다.

## 2. 확정 결정 (2026-08-07 사용자 승인)

| # | 결정 | 선택 |
| --- | --- | --- |
| 1 | 채택 누락 관측 알림 | 이번 트랙으로 앞당김 — 수집 범위 무변경 · 알림만 추가 |
| 2 | arsenal_official 신선도 임계 | 감시 제외 (`freshness_hours: 0` 규약 신설) |
| 3 | SOCKS 오류 처리 | 현행 유지 — 코드 변경 없음 · 유닛 실패 알림 보존 |
| 4 | systemd 반영 주체 | 머지 후 이 세션이 VM 반영 · 시험 발화 · 다음 회차 확인 |

## 3. 설계

### 3.1 실패 알림 유닛 특정 — 템플릿 유닛 전환

systemd 템플릿 유닛 패턴을 쓴다.

- `infra/systemd/bullet-in-fail-notify@.service` 신설 — 메시지에 `%i` (실패 유닛명) 를 넣는다.
제목 "bullet-in 유닛 실패 (systemd)" · 본문 "%i 실패 — VM 에서 journalctl -u %i -n 100 확인".
- `bullet-in.service` · `bullet-in-watchlist.service` 의 `OnFailure=bullet-in-fail-notify@%n.service` 로 교체.
- 구본 `bullet-in-fail-notify.service` 는 저장소에서 삭제.
- `install-units.sh` 개정 — 5종 복사 (bullet-in.service · timer · watchlist.service · watchlist.timer · fail-notify@.service),
구본 파일 제거, `daemon-reload`, 두 타이머 `enable --now`, `list-timers 'bullet-in*'` 출력.

VM 반영 절차 (머지 후 · 회차 발화 시각 회피):

1. `cd /home/ubuntu/bullet-in && git pull`
2. `sudo bash infra/systemd/install-units.sh`
3. `systemctl cat bullet-in.service bullet-in-watchlist.service | grep OnFailure` 로 템플릿 참조 확인
4. `sudo systemctl start bullet-in-fail-notify@test.service` 시험 발화 — Discord 에 "test 실패" 1건으로 유닛명 자리 확인
5. 다음 정기 회차 정상 종료 확인

### 3.2 신선도 알림 정비

- (a) 원인 추정 제거 — `notify.build_freshness_alert` 의
"이번 회차 후보 0건 — 수집 끊김 의심" 을 "이번 회차 후보 0건" 으로 바꾼다 (관측만 남김).
`tests/test_notify.py` 의 해당 단언도 함께 갱신한다.
- (b) 감시 제외 규약 — `freshness_hours: 0` 이면 그 소스를 신선도 판정 대상에서 뺀다.
적용 지점은 `run.py` 의 판정 입력 구성 (제외 소스는 `evaluate_freshness` 에 넘기지 않음).
`config/sources.yaml` 의 arsenal_official 을 `freshness_hours: 0` 으로 바꾸고 사유 주석을 남긴다.
- 경로 하드 실패 (fetch 예외) 는 당분간 저널 · `pipeline_runs` 로만 남는 사각이 된다.
실측상 이 유형은 일시 오류 (503) 로만 발생했고 다음 회차에 자가 회복했다.
후속 "커버리지 불변식 보강" 트랙이 흡수할 자리다.

### 3.3 채택 누락 관측 알림 — 이적성 제목 · 채택 0

수집 범위 판단 (필터 수정 · Club 태그 수용) 은 건드리지 않고, 놓쳤을 가능성만 알린다.

- 어댑터 (`arsenal_api`) — 창 후보 중 `articleType == "News"` 이고 `Men` 이 있는데 채택되지 않은 기사의
제목 · URL · 발행 시각을 관측용 속성으로 남긴다 (수집 동작 무변경).
- 판정 (`quality.py`) — 제목에 이적성 패턴 (joins · signs · transfer · loan) 이 있고
발행이 최근 6시간 이내인 기사만 추린다.
6시간 창은 3시간 회차 기준 기사당 최대 2회 발화로 도배를 막는 무상태 설계다.
sitemap lastmod 갱신으로 되살아나는 옛 기사 (2019년 글 등) 도 발행 시각 조건이 걸러 준다.
- 알림 (`notify.py`) — 제목 · URL · 태그 목록을 관측 사실로만 싣는다.
원인 추정 금지 · 내부 용어 금지 원칙은 기존 두 알림과 동일하게 적용한다.
- 96시간 창 실측 대조: Men + News 비채택 기사 중 이적성 패턴 매치는
「Christian Norgaard joins Everton」 1건뿐 — 오탐 0.

### 3.4 SOCKS 오류 — 변경 없음 (결정 기록)

현행 유지를 확정한다.
3.1 반영 후에는 알림이 정확한 유닛명을 실으므로 오진이 해소되고,
빈도 (2주 1회) 가 낮으며, 프록시 장기 장애 시 실패 신호가 보존되고,
넓은 except 가 코드 버그를 검색 실패로 위장할 위험도 피한다.

## 4. 문서 · 후속

- 트러블슈팅 신설 — 뇌르고르 태그 누락 실측 (1.4).
08-04 문서의 결론 중 "채택 0 은 산술적으로 맞다" 가 08-05 부로 깨졌음을 상호 링크로 정정한다.
- 런북 `2026-07-13-freshness-watermark-ops.md` — 문구 변경 · 제외 규약 반영 (알림 문구 변경 시 런북 동기화 원칙).
- 런북 `2026-07-13-collection-alerts-ops.md` — 관측 알림 판독법 절 추가.
- 놓친 기사 회수 (`backfill_arsenal.py`) 와 필터 · Club 태그 판단은 사용자 제품 결정 대기로 남긴다.

## 5. PR 분할

| PR | 내용 | 검증 |
| --- | --- | --- |
| spec | 이 문서 | 서식 훅 통과 |
| infra | 3.1 (유닛 3파일 + install-units.sh) | VM 반영 · 시험 발화 · 다음 회차 확인 |
| 알림 | 3.2 + 3.3 + 문서 | pytest + 다음 회차 라이브 확인 |

## 6. 범위 밖

- 채택 필터 수정 · Club 태그 이적 기사 수용 — 화면에 실리는 기사가 바뀌는 제품 판단 (사용자 결정).
- 커버리지 불변식 보강 ("후보 있는데 채택 N회 연속 0") — 위 판단 뒤가 순서.
- 후보 등재 오추출 수정 — 재추출 (H) 트랙 소유.
- 알림 채널 분리 — 발화량 관망 지속.
