#!/usr/bin/env bash
# systemd 유닛 설치 · 갱신 — VM 의 저장소에서 실행 (sudo 필요). seoulnow install-units.sh 패턴.
set -euo pipefail
cd "$(dirname "$0")"
sudo cp bullet-in.service bullet-in.timer bullet-in-fail-notify.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bullet-in.timer
systemctl list-timers bullet-in.timer --no-pager
