#!/usr/bin/env bash
# Expose the fleet dashboard through a Cloudflare tunnel.
#
#   tunnel.sh quick                      throwaway https://*.trycloudflare.com URL (no account)
#   tunnel.sh named <name> <hostname>    stable hostname on your Cloudflare zone
#   tunnel.sh install                    install cloudflared (Debian/Ubuntu, amd64/arm64)
#
# The dashboard itself must already be running (server.py) on DASHBOARD_PORT.
set -euo pipefail

PORT="${DASHBOARD_PORT:-$(python3 "$(dirname "$(readlink -f "$0")")/../../../lib/fleet.py" config | python3 -c 'import json,sys; print(json.load(sys.stdin)["DASHBOARD_PORT"])')}"
TARGET="http://127.0.0.1:${PORT}"

need_cloudflared() {
  command -v cloudflared >/dev/null || { echo "cloudflared not installed — run: $0 install" >&2; exit 1; }
}

case "${1:-}" in
  install)
    arch="$(dpkg --print-architecture)"
    tmp="$(mktemp -d)"
    curl -fsSL -o "$tmp/cloudflared.deb" \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}.deb"
    dpkg -i "$tmp/cloudflared.deb"
    rm -rf "$tmp"
    cloudflared --version
    ;;
  quick)
    need_cloudflared
    curl -s -o /dev/null "$TARGET/" || { echo "dashboard not reachable on $TARGET — start server.py first" >&2; exit 1; }
    echo "Starting quick tunnel to $TARGET (URL printed below, changes every restart)"
    exec cloudflared tunnel --no-autoupdate --url "$TARGET"
    ;;
  named)
    need_cloudflared
    name="${2:?tunnel name}"; host="${3:?public hostname, e.g. fleet.example.com}"
    [ -f "$HOME/.cloudflared/cert.pem" ] || { echo "run 'cloudflared tunnel login' once first" >&2; exit 1; }
    cloudflared tunnel list -o json | grep -q "\"name\":\"$name\"" || cloudflared tunnel create "$name"
    cloudflared tunnel route dns "$name" "$host" || true
    echo "Serving $TARGET at https://$host — protect it with Cloudflare Access (Zero Trust → Applications)."
    exec cloudflared tunnel --no-autoupdate run --url "$TARGET" "$name"
    ;;
  *)
    sed -n '2,9p' "$0"; exit 1 ;;
esac
