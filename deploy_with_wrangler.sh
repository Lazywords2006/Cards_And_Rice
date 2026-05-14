#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
WORKER_NAME="${1:-${CLOUDFLARE_WORKER_NAME:-}}"
WRANGLER_ARGS=""

if [[ -z "$WORKER_NAME" ]]; then
  echo "Usage: ./deploy_with_wrangler.sh <worker-name>"
  echo "Example: ./deploy_with_wrangler.sh lazywords"
  exit 1
fi

if [[ "${WRANGLER_DRY_RUN:-0}" == "1" ]]; then
  WRANGLER_ARGS="--dry-run"
fi

cd "$ROOT_DIR"

python3 "$ROOT_DIR/album-site-generator/build_album_site.py" \
  --source-root "$ROOT_DIR" \
  --output-root "$ROOT_DIR/dist" \
  --site-title "QQ群相册" \
  --sort-order asc \
  --ignore-dirs "dist,album-site-generator,qzone-album-mcp" \
  --clean-output

if [[ -d "$ROOT_DIR/dist/hugo" ]]; then
  rm -r "$ROOT_DIR/dist/hugo"
fi

if [[ -d "$ROOT_DIR/dist/logs" ]]; then
  rm -r "$ROOT_DIR/dist/logs"
fi

npm exec --package=wrangler@4.74.0 --package=@cloudflare/workerd-darwin-arm64 -- \
  wrangler deploy \
  --name "$WORKER_NAME" \
  --assets "$ROOT_DIR/dist/site" \
  --compatibility-date "2026-03-16" \
  --keep-vars \
  ${WRANGLER_ARGS}
