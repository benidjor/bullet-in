#!/usr/bin/env bash
# 회차 끝 site/ -> Cloudflare Pages 직접 업로드 (배포 spec §2.1 · SP-D).
# systemd bullet-in.service 의 ExecStartPost 에서 실행 — 실패 시 유닛 실패 -> OnFailure 알림.
set -euo pipefail
cd "$(dirname "$0")/.."

: "${CLOUDFLARE_API_TOKEN:?CLOUDFLARE_API_TOKEN 미설정 — .env 확인}"
: "${CLOUDFLARE_ACCOUNT_ID:?CLOUDFLARE_ACCOUNT_ID 미설정 — .env 확인}"

# 오배포 방어: 산출물이 없거나 비정상적으로 적으면 (렌더 실패 잔해) 배포하지 않음.
# 기준 50 은 현재 정상 산출물 (약 210 파일) 의 1/4 수준 — write_site 오삭제 방어 (spec §2.6) 와 같은 철학.
[ -f site/index.html ] || { echo "site/index.html 없음 — 배포 중단"; exit 1; }
page_count=$(find site -name '*.html' | wc -l | tr -d ' ')
if [ "$page_count" -lt 50 ]; then
  echo "site HTML ${page_count}건 (< 50) — 비정상 산출물로 판단, 배포 중단"
  exit 1
fi

export PATH="/usr/local/bin:/usr/bin:$PATH"
wrangler pages deploy site --project-name bullet-in --branch main --commit-dirty=true
