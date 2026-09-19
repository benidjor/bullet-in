# 공개 주간 순 사용자 890 은 표 전체 값이었고 827 은 두 달째 대시보드 캡처에 찍혀 있었다 (2026-09-19)

- **영역**: 행동 로그 / README 의 수치 / VM 자격
- **관련 문서**: `docs/troubleshooting/2026-09-04-two-keys-double-the-visitor-count.md` · `docs/runbook/2026-08-24-wiring-analytics-and-proving-it-arrives.md` §7.1

## 1. 증상

README 에 GA4 캡처를 붙이려고 공개 주간 (08-29 부터 09-04) 보고서를 열었더니 총 사용자가 827 이었다.
README 는 같은 7일을 「순 사용자 890명 (하한선)」 이라고 적어 두었다.
하한선이라는 말이 붙어 있어서 더 낮은 값이 나올 리 없다고 여기고 있었다.

## 2. 원인

890 의 출처는 09-04 트러블슈팅 §3 의 확인 코드다.

```python
print(pc.count_distinct(t["user_pseudo_id"]).as_py(), ...)   # 891 · 0
```

날짜 조건이 없다.
그때 표에는 공개 전 08-24 (1명) 와 08-28 (94명) 도 들어 있었으니 891 은 「표 전체의 순 사용자」 이고, 문서는 그것을 「7일 사용자」 라고 불렀다.

같은 7일을 네 출처가 827 로 센다.

| 출처 | 08-29 부터 09-04 순 사용자 | 공개일 | 09-04 까지 누적 |
| --- | --- | --- | --- |
| BigQuery 원본 `events_*` | 827 | 688 | 896 |
| Iceberg `behavior.ga4_events_flat` | 827 | 688 | 896 |
| GA4 보고서 총 사용자 | 827 | | |
| 행동 지표 대시보드 「Users · 7일」 (09-06 캡처) | 827 | | |

공개일 DAU 688 은 맞다.
비율은 달라진다.
688 ÷ 827 은 83% 이지 77% 가 아니다.

## 3. 재확인이 두 번 막힌 이유

VM 에서 BigQuery 와 Iceberg 를 손으로 세려다 403 을 두 번 받았다.

- BigQuery: `User does not have bigquery.jobs.create permission in project bullet-in-analytics`
- REST 카탈로그: `Caller does not have required permission to use project 601205180150`

권한 문제로 읽었지만 권한은 이미 있었다.
VM 의 `.env` 가 가리키는 `GOOGLE_APPLICATION_CREDENTIALS` 는 백업 서비스 계정 키 (`~/.bullet-in-backup.json`) 이고, DAG 는 `warehouse_load` 태스크에만 레이크하우스 계정 키 (`/home/ubuntu/.bullet-in-lakehouse.json`) 를 따로 준다 (`airflow/dags/bullet_in_cycle.py` 의 `LAKEHOUSE_KEY`).
레이크하우스 계정에는 `bullet-in-analytics` 의 `bigquery.dataViewer` 와 `jobUser` 가 둘 다 붙어 있다 (`gcloud projects get-iam-policy` 로 확인).
ssh 셸에서 `.env` 만 소싱하면 백업 계정으로 부르게 되고, 그 계정은 어느 쪽 권한도 없다.

```bash
# VM · ~/bullet-in · 손으로 BigQuery · Iceberg 를 볼 때
set -a; . ./.env; set +a
export GOOGLE_APPLICATION_CREDENTIALS=/home/ubuntu/.bullet-in-lakehouse.json
```

## 4. 처방

- README 는 PR #485 에서 827 로 고쳤다 (창을 「08-29 부터 09-04」 로 명시).
- 09-04 트러블슈팅 §5 의 「7일 사용자 890명」 은 별도 PR 로 정정한다.
- 방문자 수를 적을 때는 창 (날짜 범위) 을 붙인다.

## 5. 배운 것

- **확정값이라도 출처가 문서 하나면 화면 · 외부 도구와 한 번은 대 본다.**
  827 은 09-06 대시보드 캡처 안에 두 달 동안 찍혀 있었다.
- **「하한선」 은 값을 못 낮춘다는 뜻이 아니다.**
  광고 차단으로 빠지는 방문이 있다는 뜻이지, 셈의 창이 맞다는 보증이 아니다.
- **403 은 권한이 아니라 신원일 수 있다.**
  어느 키로 부르고 있는지 (`client_email`) 를 먼저 찍는다.
