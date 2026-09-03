#!/usr/bin/env bash
# systemd 유닛 설치 · 갱신 — VM 의 저장소에서 실행 (sudo 필요). seoulnow install-units.sh 패턴.
# infra/airflow/install-airflow.sh 뒤에 실행할 것 — airflow-*.service 를 enable --now 하는
# 아래 줄이 venv 없이는 실패하고 set -e 가 거기서 스크립트를 멈춘다.
# 회차 · 웨어하우스 타이머는 복사만 한다 — Airflow 전환 뒤에는 비활성이 정상이고 (스펙 2026-09-04 §3.5),
# 되돌릴 때 사람이 `systemctl enable --now` 로 켠다.
set -euo pipefail
cd "$(dirname "$0")"
sudo cp bullet-in.service bullet-in.timer \
        bullet-in-watchlist.service bullet-in-watchlist.timer \
        bullet-in-backup.service bullet-in-backup.timer \
        bullet-in-warehouse.service bullet-in-warehouse.timer \
        bullet-in-warehouse-maint.service bullet-in-warehouse-maint.timer \
        bullet-in-fail-notify@.service \
        airflow-scheduler.service airflow-dag-processor.service airflow-api-server.service \
        bullet-in-airflow-watch.service bullet-in-airflow-watch.timer /etc/systemd/system/
sudo rm -f /etc/systemd/system/bullet-in-fail-notify.service   # 구본 (유닛명 하드코딩) 제거
sudo systemctl daemon-reload
sudo systemctl enable --now bullet-in-watchlist.timer \
        bullet-in-backup.timer bullet-in-warehouse-maint.timer \
        airflow-scheduler.service airflow-dag-processor.service airflow-api-server.service \
        bullet-in-airflow-watch.timer
systemctl list-timers 'bullet-in*' --no-pager
systemctl --no-pager status airflow-scheduler airflow-dag-processor airflow-api-server | grep -E "●|Active"
