#!/bin/sh
# Usage: detect-forge.sh [remote]  — prints forge, host, path and installed CLIs for the repo in the cwd.
set -eu

remote="${1:-origin}"
url="$(git remote get-url "$remote" 2>/dev/null)" || { echo "error: no git remote '$remote'" >&2; exit 1; }

# Normalise scp-style, ssh:// and https:// URLs to host + path.
case "$url" in
  *://*) rest="${url#*://}"; rest="${rest#*@}"; host="${rest%%/*}"; path="${rest#*/}" ;;
  *@*:*) rest="${url#*@}"; host="${rest%%:*}"; path="${rest#*:}" ;;
  *) host=""; path="$url" ;;
esac
host="${host%%:*}"
path="${path%.git}"
path="${path#/}"
case "$path" in v3/*) path="${path#v3/}" ;; esac

case "$host" in
  github.com|*.ghe.com|github.*) forge=github ;;
  gitlab.com|gitlab.*) forge=gitlab ;;
  bitbucket.org) forge=bitbucket ;;
  dev.azure.com|ssh.dev.azure.com|*.visualstudio.com) forge=azure ;;
  codeberg.org|gitea.*|forgejo.*) forge=gitea ;;
  *) forge=unknown ;;
esac

# Self-hosted hosts with neutral names: ask the authenticated CLIs.
if [ "$forge" = unknown ] && [ -n "$host" ]; then
  if command -v glab >/dev/null 2>&1 && glab auth status --hostname "$host" >/dev/null 2>&1; then forge=gitlab
  elif command -v gh >/dev/null 2>&1 && gh auth status --hostname "$host" >/dev/null 2>&1; then forge=github
  fi
fi

clis=""
for c in gh glab tea az; do
  command -v "$c" >/dev/null 2>&1 && clis="$clis $c"
done

echo "forge=$forge"
echo "host=$host"
echo "path=$path"
echo "remote_url=$url"
echo "clis=${clis# }"
