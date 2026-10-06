#!/usr/bin/env bash
# Open a Cloudflare quick tunnel to the worker and print the YAKSHA_PUBLIC_URL line to put in
# docker/.env. Quick tunnels need no account; the hostname changes every time the tunnel starts.
set -euo pipefail

cd "$(dirname "$0")/../docker"
compose=(docker compose -f compose.dev.yaml --profile tunnel)

"${compose[@]}" create --force-recreate tunnel >/dev/null
"${compose[@]}" start tunnel >/dev/null

url=""
for _ in $(seq 1 30); do
  url=$("${compose[@]}" logs --no-log-prefix tunnel 2>&1 | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' | tail -1 || true)
  [ -n "$url" ] && break
  sleep 1
done
if [ -z "$url" ]; then
  echo "the tunnel did not report a hostname; see: ${compose[*]} logs tunnel" >&2
  exit 1
fi

echo "YAKSHA_PUBLIC_URL=$url"
echo
echo "Put that line in docker/.env, then recreate the API and the worker so they pick it up (from the repo root):"
echo "  docker compose -f docker/compose.dev.yaml create --force-recreate api worker"
echo "  docker compose -f docker/compose.dev.yaml start api worker"
