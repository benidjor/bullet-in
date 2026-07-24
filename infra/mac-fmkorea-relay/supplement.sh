#!/usr/bin/env bash
set -euo pipefail
ssh -i /Users/aryijq/.ssh/seoulnow_deploy ubuntu@155.248.164.17 \
  'bash -lc "cd /home/ubuntu/bullet-in && set -a && source .env && set +a && export FMKOREA_PROXY=socks5://127.0.0.1:1080 && uv run python -m bullet_in.collect_fmkorea"'
