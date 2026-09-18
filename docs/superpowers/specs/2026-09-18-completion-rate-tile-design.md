# 수집 현황 화면에 완주율 타일 (2026-09-18)

「파이프라인이 끝까지 갔는가」 를 답하는 값이 제품 어디에도 없다.
수집 현황 화면의 「Success Rate」 는 소스 단위 성공률이고, `pipeline_runs` 에는 완주한 실행만 행이 생겨 분모가 안 된다.
경위와 셈법의 정본은 `docs/troubleshooting/2026-09-11-three-success-rates-and-the-one-nobody-measured.md` 다.
이 문서는 그 셈법을 화면 타일 하나로 옮기는 설계다.

## 1. 셈법 (트러블슈팅 09-11 §2 그대로)

완주율 = (저널 완주 + Airflow 완주) ÷ (저널 시작 + Airflow 시작).

- 저널 = systemd 시절 (2026-07-20 09:01 KST 부터 09-04 15:04 까지) 의 `bullet-in.service` 저널.
  시작 = 「Starting bullet-in.service」 줄 수 (358), 완주 = 「Finished bullet-in.service」 줄 수 (354), 실패 = 「Failed with result」 줄 수 (4).
  2026-09-04 이후 이 유닛은 비활성이라 세 값은 더 늘지 않는다.
- Airflow = `airflow dags list-runs bullet_in_cycle -o json` 의 실행 목록.
  완주 = `state == success`, 실패 = `state == failed`, 시작 = 완주 + 실패.
  `running` · `queued` 는 아직 답이 없으므로 분모에서 뺀다.
  `manual__` 실행도 센다 (손으로 시작한 것도 파이프라인 한 번이다).
- 2026-09-18 17시 값 = 저널 358 · 354 + Airflow 118 · 118 → 476회 중 472회, 99.2%.
  트러블슈팅의 09-11 값 417 · 413 (99.0%) 과 창이 다를 뿐 셈은 같다.

## 2. 데이터원과 경로

값을 읽을 수 있는 자리는 파이프라인 밖에만 있다.
`publish` 태스크는 Airflow 태스크 셸이라 메타 DB 접근이 막혀 있고 (`airflow-db-not-allowed:///`), 저널은 회차와 무관한 시스템 기록이다.

- **매시 도는 감시 타이머가 센다.**
  `bullet_in.airflow_watch` 는 이미 매시 :37 UTC 에 `dags list-runs -o json` 을 부르고 (`airflow.env` 를 유닛이 소싱한다), `ubuntu` 는 `adm` 그룹이라 저널을 읽는다.
  거기에 `journalctl -u bullet-in.service --no-pager -q -o short-iso` 한 번을 더해 두 묶음을 세고 `state/completion.json` 에 쓴다.
- **`publish` 는 파일만 읽는다.**
  `write_ops` 가 `state/completion.json` 을 받아 뷰모델에 넘기고, 타일은 그 값으로 그린다.
  파일이 없으면 타일은 「—」 와 「감시 기록 없음」 이다.
  회차와 감시가 따로 도니 값은 최대 한 시간 늦고, 타일의 보조 줄에 계산 시각을 적는다.
- **저널을 못 읽으면 지난 값을 쓴다.**
  `journalctl` 이 실패하면 (rc ≠ 0) 직전 파일의 `journal` 블록을 그대로 두고 경고 로그를 남긴다.
  저널 값은 09-04 이후 상수라 낡을 일이 없다.
- **list-runs 가 실패하면 파일을 안 바꾼다.**
  기존 감시의 경고 경로 그대로다.

파일 모양은 이렇다.

```json
{"computed_at": "2026-09-18T08:37:00+00:00",
 "journal": {"started": 358, "finished": 354, "failed": 4},
 "airflow": {"started": 118, "success": 118, "failed": 0, "in_progress": 0,
             "first_start": "2026-09-04T09:00:00+00:00", "last_end": "2026-09-18T06:03:30+00:00"}}
```

## 3. 화면

- 타일 이름 「완주율 · 07-20 이후」, 값 「99.2%」, 보조 줄 「472/476 · 진행 중 제외 · 감시 08:37 UTC」.
  자리는 「Success Rate」 바로 오른쪽이다.
  같은 「성공」 이 둘 나란히 서므로 「Success Rate」 의 보조 줄을 「소스 단위 · SLO-2 목표 99%」 로 바꿔 단위를 적는다.
- 타일이 일곱이 되므로 수집 현황 화면만 7열이다 (`.tiles.seven`).
  행동 지표 화면은 여섯 그대로다.
  모바일 (760px 이하) 은 지금처럼 2열이다.
- 분모가 0 이면 값은 「—」 다.
  빈 칸끼리 나누지 않는다.

## 4. 검증

- 단위 테스트 = 셈 (진행 중 제외 · 실패 포함 · manual 포함 · 저널 실패 시 이전 값 유지 · 분모 0) · 감시가 파일을 쓰는 것 · 뷰모델 타일 (파일 있음 · 없음 · 분모 0) · 렌더 (7열 클래스).
- 라이브 = 머지 뒤 감시 타이머가 한 번 돌고 (`systemctl start bullet-in-airflow-watch.service` 로 앞당길 수 있다) 다음 회차의 `ops.html` 에 타일이 뜨는지, 값이 §1 의 손 셈과 같은지.
