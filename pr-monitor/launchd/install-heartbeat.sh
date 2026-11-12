#!/bin/zsh
# install-heartbeat.sh [--uninstall]: runs stale-watches.sh --sync --restart every 10 minutes as a launchd agent.
set -euo pipefail
LABEL=com.ai-skills.pr-monitor-heartbeat
PLIST=$HOME/Library/LaunchAgents/$LABEL.plist
SCRIPT=${0:A:h:h}/scripts/stale-watches.sh
LOG=$HOME/.pr-monitor/heartbeat.log

launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
for _ in {1..50}; do launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1 || break; sleep 0.1; done
if [[ ${1:-} == --uninstall ]]; then
  rm -f "$PLIST"; echo "removed $LABEL"; exit 0
fi

mkdir -p "${PLIST:h}" "${LOG:h}"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array><string>/bin/zsh</string><string>-c</string><string>date -u +%FT%TZ; '$SCRIPT' --sync --restart</string></array>
  <key>EnvironmentVariables</key>
  <dict><key>PATH</key><string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string></dict>
  <key>StartInterval</key><integer>600</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict>
</plist>
EOF
launchctl bootstrap "gui/$UID" "$PLIST"
echo "installed $LABEL: every 10 minutes, log $LOG"
