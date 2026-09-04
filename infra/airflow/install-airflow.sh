#!/usr/bin/env bash
# Airflow 3 를 프로젝트와 다른 venv 에 깐다 — VM 에서 실행 (스펙 2026-09-04 §4.1).
set -euo pipefail
VERSION="${AIRFLOW_VERSION:-3.3.1}"
VENV=/home/ubuntu/airflow-venv
HOME_DIR=/home/ubuntu/airflow
UV=/home/ubuntu/.local/bin/uv
cd "$(dirname "$0")"
[ -d "$VENV" ] || $UV venv --python 3.11 "$VENV"
$UV pip install --python "$VENV/bin/python" \
  "apache-airflow==$VERSION" "apache-airflow-providers-standard" "psycopg2-binary" \
  --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-$VERSION/constraints-3.11.txt"
mkdir -p "$HOME_DIR"
cp airflow.env "$HOME_DIR/airflow.env"
set -a; . "$HOME_DIR/airflow.env"; set +a
(cd /home/ubuntu/bullet-in && /usr/bin/docker compose up -d --wait airflow-db)
"$VENV/bin/airflow" db migrate
"$VENV/bin/airflow" version
echo "관리자 비밀번호는 첫 api-server 기동 때 $HOME_DIR/simple_auth_manager_passwords.json.generated 에 생긴다"
