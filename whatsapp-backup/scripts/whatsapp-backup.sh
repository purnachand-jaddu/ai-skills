#!/bin/zsh
# Back up an iPhone over USB/Wi-Fi with libimobiledevice, then export every
# WhatsApp chat to HTML + media with WhatsApp-Chat-Exporter. Phone must be unlocked.
set -uo pipefail
export PATH=/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin

ROOT=${WA_BACKUP_ROOT:-$HOME/Backups}       # output root
KEEP=${WA_KEEP:-4}                           # dated exports to retain
KEEP_DEVICE_BACKUP=${WA_KEEP_DEVICE_BACKUP:-0}  # 1 = keep the raw iPhone backup (enables fast incremental runs)
ARCHIVE=${WA_ARCHIVE:-1}                     # 1 = also write a single .tar.zst for cloud upload
VENV=$ROOT/tools/venv
LOG=$ROOT/logs/whatsapp-backup.log

mkdir -p "$ROOT/logs" "$ROOT/tools"
exec > >(tee -a "$LOG") 2>&1
echo "=== $(date '+%F %T') start"

command -v idevicebackup2 >/dev/null || { echo "missing: brew install libimobiledevice"; exit 1; }
[[ -x $VENV/bin/wtsexporter ]] || { python3 -m venv "$VENV" && "$VENV/bin/pip" -q install whatsapp-chat-exporter; } || exit 1

# Prefer USB, fall back to Wi-Fi.
UDID=${WA_UDID:-$(idevice_id -l 2>/dev/null | head -1)}
if [[ -n $UDID ]] && idevice_id -l 2>/dev/null | grep -q "$UDID"; then
  NET=()
elif [[ -n ${UDID:=$(idevice_id -n 2>/dev/null | head -1)} ]]; then
  NET=(-n)
else
  echo "no iPhone reachable (plug in, unlock, tap Trust)"; exit 1
fi
echo "device $UDID ${NET[*]:-usb}"

# Progress bars use \r; strip them so the log stays readable.
if ! idevicebackup2 -u "$UDID" "${NET[@]}" backup "$ROOT/iphone" | tr '\r' '\n' | grep -v '^\[='; then
  echo "backup FAILED. iOS error 208 means the phone was locked; unlock it and rerun."; exit 1
fi

OUT=$ROOT/whatsapp/$(date +%F)
rm -rf "$OUT"; mkdir -p "$OUT"
# Exporter extracts into its cwd before copying to -o; use a scratch dir so nothing is left behind.
WORK=$(mktemp -d)
( cd "$WORK" && "$VENV/bin/wtsexporter" -i -b "$ROOT/iphone/$UDID" -o "$OUT" --no-banner ) | tr '\r' '\n' | grep -v 'Generating HTML'
rc=${pipestatus[1]}
rm -rf "$WORK"
[[ $rc -eq 0 ]] || { echo "export FAILED"; exit 1; }
# Exporter nests media one level deeper than its HTML links expect.
ln -sfn AppDomainGroup-group.net.whatsapp.WhatsApp.shared/Message "$OUT/Message"

# Forwarded media repeats across chats; hardlink exact duplicates so each is stored once.
find "$OUT"/AppDomainGroup-*/Message/Media -type f -size +4k -exec md5 -r {} + | sort | python3 -c '
import sys, os
first = {}; n = 0; b = 0
for line in sys.stdin:
    h, p = line.rstrip("\n").split(" ", 1)
    if h in first:
        b += os.path.getsize(p); os.link(first[h], p + ".tmp"); os.replace(p + ".tmp", p); n += 1
    else:
        first[h] = p
print(f"deduplicated {n} files, {b/1e9:.2f} GB shared")'

if [[ $ARCHIVE == 1 ]]; then
  command -v zstd >/dev/null || { echo "missing: brew install zstd"; exit 1; }
  A=$ROOT/whatsapp-$(date +%F).tar.zst
  ( cd "$ROOT/whatsapp" && tar --format=pax -cf - "$(basename "$OUT")" | zstd -T0 -10 -q -f -o "$A" ) || { echo "archive FAILED"; exit 1; }
  zstd -t -q "$A" && shasum -a 256 "$A" > "$A.sha256"
  echo "archive $(du -h "$A" | cut -f1) -> $A"
fi

[[ $KEEP_DEVICE_BACKUP == 1 ]] || rm -rf "$ROOT/iphone"

# Keep the newest $KEEP exports.
ls -1d "$ROOT"/whatsapp/20*/ | sort -r | tail -n +$((KEEP+1)) | while read -r old; do
  echo "pruning $old"; rm -rf "$old"
done

echo "=== $(date '+%F %T') done: $(ls "$OUT"/*.html | wc -l | tr -d ' ') chats, $(du -sh "$OUT" | cut -f1) -> $OUT"
