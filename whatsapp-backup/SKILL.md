---
name: whatsapp-backup
description: >-
  Export every WhatsApp chat on an iPhone (text + all media) to local HTML
  and raw SQLite by taking a local iOS backup with libimobiledevice and
  running WhatsApp-Chat-Exporter on it. Use when the user asks to back up,
  export, archive, or download their WhatsApp chats or media to the Mac.
  Requires the iPhone on USB or Wi-Fi, unlocked, and trusted.
---

# WhatsApp Backup (iPhone → Mac)

One command produces a dated folder of one HTML file per chat plus all media,
and the raw `ChatStorage.sqlite` / `ContactsV2.sqlite` for direct queries.

```bash
~/codebase/ai-skills/whatsapp-backup/scripts/whatsapp-backup.sh
```

Output: `~/Backups/whatsapp/<YYYY-MM-DD>/` (open any `*.html` in a browser)
and `~/Backups/whatsapp-<YYYY-MM-DD>.tar.zst` + `.sha256` for cloud upload.
Log: `~/Backups/logs/whatsapp-backup.log`.

## Why this route

- The WhatsApp desktop app's local DB only holds what the phone has synced
  (a fraction of the chats and messages) and no full-size media, only `.thumb` files. Not a backup.
- In-app "Export chat" is one chat at a time, capped at 40k messages.
- iCloud / Google Drive WhatsApp backups are opaque encrypted blobs.
- Unofficial client libraries (Baileys, whatsmeow) risk an account ban.
- An iOS device backup contains WhatsApp's full app-group container, so it
  is the only complete, ToS-safe, scriptable source.

## Prerequisites (one-time)

```bash
brew install libimobiledevice        # idevice_id, idevicebackup2, ideviceinfo
```
The script creates `~/Backups/tools/venv` and installs `whatsapp-chat-exporter`
on first run. Plug the phone in, unlock it, tap **Trust**, then verify:

```bash
idevice_id -l && idevicepair validate
```

For Wi-Fi runs later: open the phone in Finder once and tick
"Show this iPhone when on Wi-Fi".

## Settings (env vars)

| Var | Default | Meaning |
|---|---|---|
| `WA_BACKUP_ROOT` | `~/Backups` | where `iphone/`, `whatsapp/`, `logs/`, `tools/` live |
| `WA_KEEP` | `4` | dated export folders to retain |
| `WA_KEEP_DEVICE_BACKUP` | `0` | `1` keeps the raw iOS backup (≈ phone's used storage) so the next run is incremental |
| `WA_UDID` | first USB device | pin a specific phone |
| `WA_ARCHIVE` | `1` | also write the single `.tar.zst` archive |

## How it works

1. `idevicebackup2 backup` → unencrypted full device backup under
   `$ROOT/iphone/<UDID>/`. iOS backups are all-or-nothing; the first run
   moves the whole phone (≈15 GB / 57 min over USB for a 9 GB WhatsApp).
2. `wtsexporter -i -b <backup>` reads `Manifest.db`, pulls the
   `AppDomainGroup-group.net.whatsapp.WhatsApp.shared` domain, resolves
   contact names, copies media, renders HTML.
3. Symlink `Message -> AppDomainGroup-…/Message` at the output root: the
   exporter nests media one level deeper than its HTML links expect. Without
   it every image/video link in the HTML is broken.
4. Hardlink byte-identical media (forwarded photos/videos repeat across
   chats): 894 files / 1.04 GB on the first run. Lossless, links keep working.
5. `tar | zstd -10` into one archive, `zstd -t` integrity check, sha256.
   tar stores each hardlinked file once. Restore with
   `tar -xf whatsapp-<date>.tar.zst` (bsdtar handles zstd natively).
6. Delete the raw iOS backup unless `WA_KEEP_DEVICE_BACKUP=1`, prune old
   exports.

## Gotchas learned the hard way

- **Error 208 "Device locked"**: iOS demands the passcode on the phone
  screen before a backup starts. Unlock the phone, rerun. This makes an
  unattended cron/launchd schedule impossible; run it by hand.
- **Exporter litters its cwd**: it extracts the backup into the current
  directory before copying to `-o`. The script runs it inside `mktemp -d`.
- **Unencrypted by design**: `~/Backups` is readable by anyone with access
  to the Mac. Turn on iOS backup encryption only if you accept managing
  the password; the exporter then needs `pip install 'whatsapp-chat-exporter[backup]'`
  and the password.
- **Sizes**: media is 95% of an export. Each retained export is a full copy, so
  budget `WA_KEEP` × the export size.
- **Compression reality (measured)**: HTML+SQLite 459 MB → 58 MB with zstd;
  jpg/heic/mp4 save < 2%, pdf ~12%. The archive is only ~8% smaller than the
  folder; the wins are dedup and, if quality loss is acceptable, re-encoding
  videos (4.6 GB) to lower-bitrate HEVC via `hevc_videotoolbox` (~50% smaller
  on a 1-file test). `afsctool` (APFS compression) helps only the local
  folder, not an archive or upload.
- `ideviceinfo -q com.apple.disk_usage` returns nothing on iOS 26; don't
  rely on it for free-space checks.

## Verify a run

```bash
OUT=~/Backups/whatsapp/$(date +%F)
ls "$OUT"/*.html | wc -l                                   # chat count
sqlite3 "$OUT"/AppDomainGroup-*/ChatStorage.sqlite \
  'select count(*) from ZWACHATSESSION; select count(*) from ZWAMESSAGE;'
grep -oh 'src="[^"]*Media/[^"]*"' "$OUT"/*.html | sed 's/src="//;s/"$//' | sort -u \
  | while read p; do [ -e "$OUT/$p" ] || echo "MISSING $p"; done | wc -l   # expect 0
```

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
