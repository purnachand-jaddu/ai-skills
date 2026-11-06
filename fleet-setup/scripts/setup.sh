#!/usr/bin/env bash
# Set up (or check) the agent fleet on this machine. Safe to re-run.
#
#   setup.sh doctor                     check everything; prints what to fix (default)
#   setup.sh deps [--with-claude]       apt: git python3 curl tmux ttyd glab; cloudflared .deb;
#                                       --with-claude also runs Claude Code's native installer
#   setup.sh install                    symlink skills, put `fleet` on PATH, seed ~/.agent-fleet
#   setup.sh config KEY=VALUE ...       set config.env values (use --gen-token for DASHBOARD_TOKEN)
#   setup.sh project add <tracker-project-id> <repo-path|git-url> [base-branch]
#   setup.sh project list
#   setup.sh schedule on [minutes] | off   systemd timer running `fleet tick` (default every 5 min)
#   setup.sh services on [tunnel-name hostname] | off
#                                       systemd units: dashboard, and a named tunnel if given
#   setup.sh bundle [out-file]          pack ~/codebase/ai-skills into one file to copy to another VM
#   setup.sh all [--with-claude]        deps → install → doctor
set -euo pipefail

AI="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
FLEET_HOME="${FLEET_HOME:-$HOME/.agent-fleet}"
CONFIG="$FLEET_HOME/config.env"
PROJECTS="$FLEET_HOME/projects.json"
REPOS_DIR="${FLEET_REPOS_DIR:-$HOME/repos}"
UNIT_DIR=/etc/systemd/system

ok()   { printf '  \033[32m✓\033[0m %s\n' "$*"; }
bad()  { printf '  \033[31m✗\033[0m %s\n' "$*"; FAILS=$((FAILS+1)); }
warn() { printf '  \033[33m!\033[0m %s\n' "$*"; }
hdr()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
need_root() { [ "$(id -u)" = 0 ] || { echo "run as root (or with sudo) for: $1" >&2; exit 1; }; }
cfg_get() { python3 "$AI/lib/fleet.py" config | python3 -c "import json,sys; print(json.load(sys.stdin).get('$1',''))"; }

# ---------------------------------------------------------------------------
cmd_deps() {
  need_root "installing packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq git python3 curl ca-certificates tmux ttyd glab >/dev/null
  # Ubuntu's ttyd package starts a web *login* service on :7681. The fleet runs its own
  # ttyd on a private socket, so switch the stock one off.
  if systemctl list-unit-files ttyd.service >/dev/null 2>&1; then
    systemctl disable --now ttyd >/dev/null 2>&1 || true
  fi
  if ! command -v cloudflared >/dev/null; then
    tmp="$(mktemp -d)"; arch="$(dpkg --print-architecture)"
    curl -fsSL -o "$tmp/cloudflared.deb" \
      "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-${arch}.deb"
    dpkg -i "$tmp/cloudflared.deb" >/dev/null && rm -rf "$tmp"
  fi
  if [ "${1:-}" = "--with-claude" ] && ! command -v claude >/dev/null && [ ! -x "$HOME/.local/bin/claude" ]; then
    curl -fsSL https://claude.ai/install.sh | bash
  fi
  echo "deps installed: $(tmux -V), ttyd $(ttyd --version | awk '{print $3}'), glab $(glab --version | head -1 | awk '{print $3}'), $(cloudflared --version 2>&1 | head -1 | awk '{print $1,$3}')"
}

cmd_install() { bash "$AI/install.sh"; }

# ---------------------------------------------------------------------------
cmd_config() {
  [ $# -gt 0 ] || { echo "usage: setup.sh config KEY=VALUE ... | --gen-token" >&2; exit 1; }
  mkdir -p "$FLEET_HOME"; [ -f "$CONFIG" ] || install -m 600 "$AI/config/config.env.example" "$CONFIG"
  args=()
  for a in "$@"; do
    if [ "$a" = "--gen-token" ]; then
      args+=("DASHBOARD_TOKEN=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')")
    else
      args+=("$a")
    fi
  done
  python3 - "$CONFIG" "${args[@]}" <<'PY'
import re, sys
path, pairs = sys.argv[1], sys.argv[2:]
lines = open(path).read().splitlines()
for pair in pairs:
    if "=" not in pair or not re.match(r"^[A-Z][A-Z0-9_]*=", pair):
        sys.exit(f"not KEY=VALUE: {pair}")
    key = pair.split("=", 1)[0]
    pat = re.compile(rf"^\s*#?\s*{key}=")
    for i, l in enumerate(lines):
        if pat.match(l):
            lines[i] = pair; break
    else:
        lines.append(pair)
    shown = pair if not any(s in key for s in ("KEY", "TOKEN", "SECRET")) else f"{key}=…"
    print(f"set {shown}")
open(path, "w").write("\n".join(lines) + "\n")
PY
  chmod 600 "$CONFIG"
}

# ---------------------------------------------------------------------------
cmd_project() {
  case "${1:-list}" in
    list) cat "$PROJECTS" 2>/dev/null || echo "{}";;
    add)
      id="${2:?tracker project id}"; src="${3:?repo path or git url}"; base="${4:-}"
      if [[ "$src" =~ ^(https?://|git@|ssh://|file://) ]]; then
        name="$(basename "${src%.git}")"; dest="$REPOS_DIR/$name"
        if [ -d "$dest/.git" ]; then echo "using existing clone $dest"
        else mkdir -p "$REPOS_DIR"; git clone -q "$src" "$dest"; echo "cloned $src → $dest"; fi
        src="$dest"
      fi
      repo="$(cd "$src" && pwd)"
      [ -d "$repo/.git" ] || { echo "$repo is not a git repository" >&2; exit 1; }
      [ -n "$base" ] || base="$(git -C "$repo" symbolic-ref --short refs/remotes/origin/HEAD 2>/dev/null | sed 's#^origin/##')"
      [ -n "$base" ] || base=main
      python3 - "$PROJECTS" "$id" "$repo" "$base" <<'PY'
import json, os, sys
path, pid, repo, base = sys.argv[1:]
data = json.load(open(path)) if os.path.exists(path) else {}
for k in [k for k in data if k.startswith("<")]:  # drop example entries
    data.pop(k)
data[pid] = {"repo": repo, "base": base}
json.dump(data, open(path, "w"), indent=2)
print(f"mapped tracker project {pid} → {repo} (base {base})")
PY
      ;;
    *) echo "usage: setup.sh project add <id> <path|url> [base] | list" >&2; exit 1;;
  esac
}

# ---------------------------------------------------------------------------
cmd_schedule() {
  need_root "systemd units"
  case "${1:-on}" in
    on)
      mins="${2:-5}"
      cat > "$UNIT_DIR/fleet-tick.service" <<EOF
[Unit]
Description=Agent fleet dispatch tick (Haiku router)
After=network-online.target

[Service]
Type=oneshot
User=$(id -un)
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=$HOME
ExecStart=$HOME/.local/bin/fleet tick
EOF
      cat > "$UNIT_DIR/fleet-tick.timer" <<EOF
[Unit]
Description=Run the agent fleet dispatch tick every ${mins} minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=${mins}min
Persistent=true

[Install]
WantedBy=timers.target
EOF
      systemctl daemon-reload && systemctl enable --now fleet-tick.timer
      echo "fleet tick every ${mins} min — logs: journalctl -u fleet-tick";;
    off) systemctl disable --now fleet-tick.timer 2>/dev/null || true; echo "schedule off";;
    *) echo "usage: setup.sh schedule on [minutes] | off" >&2; exit 1;;
  esac
}

cmd_services() {
  need_root "systemd units"
  case "${1:-on}" in
    on)
      cat > "$UNIT_DIR/fleet-dashboard.service" <<EOF
[Unit]
Description=Agent fleet dashboard
After=network-online.target

[Service]
User=$(id -un)
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=$HOME
ExecStart=$HOME/.local/bin/fleet dashboard
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF
      units=(fleet-dashboard.service)
      if [ -n "${2:-}" ]; then
        name="$2"; host="${3:?hostname for the named tunnel}"
        [ -f "$HOME/.cloudflared/cert.pem" ] || { echo "run 'cloudflared tunnel login' first" >&2; exit 1; }
        cat > "$UNIT_DIR/fleet-tunnel.service" <<EOF
[Unit]
Description=Agent fleet Cloudflare tunnel ($host)
After=network-online.target fleet-dashboard.service

[Service]
User=$(id -un)
Environment=PATH=$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin
Environment=HOME=$HOME
ExecStart=$HOME/.local/bin/fleet tunnel named $name $host
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
        units+=(fleet-tunnel.service)
      fi
      systemctl daemon-reload && systemctl enable --now "${units[@]}"
      echo "enabled: ${units[*]}";;
    off)
      systemctl disable --now fleet-dashboard.service fleet-tunnel.service 2>/dev/null || true
      echo "services off";;
    *) echo "usage: setup.sh services on [tunnel-name hostname] | off" >&2; exit 1;;
  esac
}

# ---------------------------------------------------------------------------
cmd_bundle() {
  out="${1:-$PWD/ai-skills.bundle}"
  git -C "$AI" diff --quiet && git -C "$AI" diff --cached --quiet \
    || echo "warning: ~/codebase/ai-skills has uncommitted changes; they are NOT in the bundle" >&2
  git -C "$AI" bundle create "$out" --all >/dev/null 2>&1
  echo "wrote $out ($(du -h "$out" | cut -f1)). On the new VM:"
  echo "  scp $out <vm>:/tmp/"
  echo "  git clone /tmp/$(basename "$out") ~/codebase/ai-skills"
  echo "  ~/codebase/ai-skills/fleet-setup/scripts/setup.sh all --with-claude"
  echo "Config and secrets are per machine and not included; re-run 'setup.sh config' there."
}

# ---------------------------------------------------------------------------
cmd_doctor() {
  FAILS=0
  hdr "Tools"
  for t in git python3 curl tmux ttyd glab cloudflared; do
    if command -v "$t" >/dev/null; then ok "$t"; else bad "$t missing → setup.sh deps"; fi
  done
  if command -v claude >/dev/null || [ -x "$HOME/.local/bin/claude" ]; then ok "claude $(claude --version 2>/dev/null | awk '{print $1}')"
  else bad "claude missing → setup.sh deps --with-claude"; fi
  if systemctl is-enabled ttyd >/dev/null 2>&1; then warn "stock ttyd login service is enabled → setup.sh deps disables it"; fi

  hdr "Accounts"
  if claude auth status 2>/dev/null | grep -q '"loggedIn": true'; then ok "claude logged in"
  else bad "claude not logged in → run: claude  (then /login), or set ANTHROPIC_API_KEY"; fi
  if glab auth status >/dev/null 2>&1; then ok "glab logged in ($(glab auth status 2>&1 | grep -o 'as [^ ]*' | head -1))"
  else bad "glab not logged in → run: glab auth login"; fi

  hdr "Install"
  for s in "$AI"/*/; do
    [ -f "$s/SKILL.md" ] || continue
    n="$(basename "$s")"
    if [ "$(readlink -f "$HOME/.claude/skills/$n" 2>/dev/null)" = "${s%/}" ]; then ok "skill $n linked"
    else bad "skill $n not linked → setup.sh install"; fi
  done
  if command -v fleet >/dev/null; then ok "fleet on PATH"; else bad "fleet not on PATH → setup.sh install (and add ~/.local/bin to PATH)"; fi

  hdr "Config ($CONFIG)"
  if [ -f "$CONFIG" ]; then
    [ "$(stat -c %a "$CONFIG")" = 600 ] && ok "config.env is private (600)" || warn "config.env is not chmod 600"
    [ -n "$(cfg_get KANEO_API_KEY)" ] || bad "KANEO_API_KEY empty → setup.sh config KANEO_API_KEY=..."
    if out="$(timeout 20 python3 "$AI/lib/fleet.py" health 2>&1)"; then
      ok "ticket tracker reachable and authorised"
    else
      bad "ticket tracker failed: $(echo "$out" | tail -1 | cut -c1-140)"
      echo "      → check ~/.config/ticket-manager/config.toml and KANEO_API_KEY"
    fi
    ok "node name: $(cfg_get FLEET_NODE)"
    [ -n "$(cfg_get DASHBOARD_TOKEN)" ] && ok "DASHBOARD_TOKEN set" || warn "DASHBOARD_TOKEN empty → setup.sh config --gen-token (needed before any tunnel)"
    [ "$(cfg_get DASHBOARD_CONTROL)" = 1 ] && warn "control mode ON: only expose via a named tunnel with Cloudflare Access"
  else bad "no config.env → setup.sh install"; fi

  hdr "Projects ($PROJECTS)"
  if [ -f "$PROJECTS" ]; then
    python3 - "$PROJECTS" <<'PY' || FAILS=$((FAILS+1))
import json, os, subprocess, sys
data = json.load(open(sys.argv[1])); bad = 0
real = {k: v for k, v in data.items() if not k.startswith("<")}
if not real:
    print("  \033[31m✗\033[0m no projects mapped → setup.sh project add <tracker-project-id> <repo>   (ids: ticket-manager/tm projects)"); sys.exit(1)
for pid, p in real.items():
    repo = p.get("repo", "")
    if not os.path.isdir(os.path.join(repo, ".git")):
        print(f"  \033[31m✗\033[0m {pid}: {repo} is not a git repo"); bad = 1; continue
    email = subprocess.run(["git", "-C", repo, "config", "user.email"], capture_output=True, text=True).stdout.strip()
    remote = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"], capture_output=True, text=True).stdout.strip()
    if not email:
        print(f"  \033[31m✗\033[0m {pid}: no git identity for commits → git config --global user.name/user.email"); bad = 1
    elif not remote:
        print(f"  \033[31m✗\033[0m {pid}: {repo} has no origin remote"); bad = 1
    else:
        print(f"  \033[32m✓\033[0m {pid} → {repo} ({p.get('base','main')}, commits as {email})")
sys.exit(bad)
PY
  else bad "no projects.json → setup.sh install"; fi

  hdr "Running"
  systemctl is-active fleet-tick.timer >/dev/null 2>&1 && ok "fleet-tick timer active" \
    || warn "no schedule → setup.sh schedule on   (or cron: */5 * * * * fleet tick)"
  systemctl is-active fleet-dashboard >/dev/null 2>&1 && ok "dashboard service active" || warn "dashboard not running as a service → setup.sh services on"
  systemctl is-active fleet-tunnel >/dev/null 2>&1 && ok "tunnel service active" || warn "no tunnel service (optional)"

  echo
  if [ "$FAILS" -eq 0 ]; then echo "doctor: ready ✓"; else echo "doctor: $FAILS problem(s) to fix"; fi
  return "$FAILS"
}

# ---------------------------------------------------------------------------
case "${1:-doctor}" in
  doctor)   cmd_doctor ;;
  deps)     shift; cmd_deps "$@" ;;
  install)  cmd_install ;;
  config)   shift; cmd_config "$@" ;;
  project)  shift; cmd_project "$@" ;;
  schedule) shift; cmd_schedule "$@" ;;
  services) shift; cmd_services "$@" ;;
  bundle)   shift; cmd_bundle "$@" ;;
  all)      shift; cmd_deps "$@"; cmd_install; cmd_doctor || true ;;
  -h|--help|help) sed -n '2,17p' "$0" ;;
  *) sed -n '2,17p' "$0"; exit 1 ;;
esac
