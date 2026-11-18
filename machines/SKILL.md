---
name: machines
description: >-
  Run work on the user's own machines over Tailscale: pick the right machine
  for a job from a config of the user's machines (a Mac for a macOS e2e, a
  Linux box, a Windows PC), check it is online and SSH works without a prompt,
  run commands on it, copy builds to it and results back, and get sudo only
  through T3's request_secret. Asks before changing anything installed and
  leaves the machine as it was. Use when the user says "run this on my Mac",
  "e2e on a real Mac", "test it on the Windows box", "which of my machines
  can…", "copy the build to the Mac", "is my Mac online", "add a machine", or
  "machines". Not a Tailscale guide: for installing or configuring Tailscale
  itself (ACLs, exit nodes, Serve, Funnel), use the `tailscale` skill.
---

# Machines

You run jobs on the user's own machines, reached over their tailnet from the
machine you are on. What each machine is for lives in a config file; whether it
is online right now you look up live, every time.

## Config

`~/.config/machines/config.toml`, one `[machines.<magicdns-host>]` table per
machine (`config/machines.toml.example` in this repo shows the keys: `os`,
`arch`, `login`, `role`, `installed`, `notes`). Stable facts only. Never IPs,
online state or last-seen times (those come from `tailscale status --json`),
and never a password, key or token. Machine facts live only there, never in
this skill or anywhere else in the repo.

- Missing: copy the example there and ask the user for their machines.
- A machine without `login` or `role`: ask the user for both before using it.
  Don't guess a login from a name or another machine.
- Learned something stable (a login that works, a tool's path, a policy
  refusal): update its table and say so in the report.

## Ground rules

- **Ask before changing anything installed** on a machine: a daemon, a launchd
  plist, a service, a package, a system setting. Say what changes, where the
  backup goes, and the restore command. Running a build you copied to a temp
  dir, or reading anything, needs no yes.
- **Sudo only through `request_secret`** with `delivery: "file"`, fed to
  `sudo -S` on the remote over ssh's stdin (step 5). Never ask for a password in
  chat, never copy the file to the remote, never put the password in argv, env
  or a log. No `request_secret` (not in T3): give the user the exact command to
  run in their own terminal.
- **Leave the machine as it was**: restore every backup and remove what you
  copied, unless the user says keep it. Anything left changed goes in the
  report.
- **Every ssh and scp is non-interactive**: `$O` below
  (`-o BatchMode=yes -o ConnectTimeout=10`), so a prompt or an asleep machine
  fails fast instead of hanging.
- **Ask everything at once, before starting**: missing logins, the yes for each
  change, the sudo secret. A deadline is no reason to skip any of them.
- Phones and tablets are not run targets.

## 1. Pick the machine

Match the job against each machine's `os`, `arch` and `role` in the config, then check it
live:

```bash
tailscale status --json | python3 -c '
import json, sys
for p in (json.load(sys.stdin).get("Peer") or {}).values():
    print(p["DNSName"].split(".")[0], p["OS"], "online" if p["Online"] else "offline since " + p.get("LastSeen", "?"))'
```

Key on the first label of `DNSName` (the MagicDNS name, e.g.
`example-mac-1`); `HostName` is the machine's own name and often differs.
Offline: say since when, offer another machine with the same role, or wait for
the user. Never pick a machine the user didn't mean without saying so.

## 2. Check it's reachable

```bash
H=<login>@<magicdns-host>; O="-o BatchMode=yes -o ConnectTimeout=10"
tailscale ping -c 1 --until-direct=false --timeout 5s <magicdns-host>   # a relayed (DERP) pong counts
ssh $O "$H" 'uname -sm; whoami'   # Windows: 'ver & whoami'
```

Both must pass before step 3. See Failure modes for each refusal.

## 3. Run commands

```bash
ssh $O "$H" '<command>'
```

- macOS logins run zsh: an unmatched glob aborts the whole command
  (`no matches found`). Use `find`, quote the glob, or wrap in `bash -c '…'`.
- A non-login shell may not have Homebrew on `PATH`: use the full paths
  under `installed`.
- A job longer than a few minutes: `nohup <cmd> > /tmp/<job>.log 2>&1 &`, then
  poll the log, so a dropped connection doesn't kill it.

## 4. Copy builds and fetch results

```bash
scp $O ./build/app "$H":/tmp/                 # to the machine
scp $O "$H":/tmp/<job>.log <scratchpad>/      # results back
```

Cross-compile for the target's arch from step 2 (`uname -m`: `arm64` →
`GOARCH=arm64`). Put copies in `/tmp` (or `%TEMP%` on Windows), never over an
installed binary without step 6. Only when scp is refused, `tailscale file cp
<file> <magicdns-host>:` sends it by Taildrop; it lands in the receiver's
Taildrop folder (Downloads on macOS) and needs the user to find it.

## 5. Sudo

Check first: `ssh $O "$H" 'sudo -n true'`. Passes: no secret needed; run
`sudo` without `-S -p ""` and without `< "$file"`. Otherwise
call `request_secret` (label "sudo password for <login>@<host>", `delivery:
"file"`, the reason naming the commands), then:

```bash
ssh $O "$H" 'sudo -S -p "" sh -c "<cmd1> && <cmd2>"' < "$file"
```

The password goes over ssh's stdin to sudo and nowhere else. Each ssh is a new
session, so every sudo call feeds the file again; group commands to need fewer.
The command can't read stdin itself. `rm -f "$file"` once the last sudo call
is done.

Windows has no sudo: ask the user to run the elevated step in their own admin
terminal, and give the exact command.

## 6. Change something installed (after the user's yes)

1. Back up to a new `/var/tmp/machines-<YYYYMMDD-HHMMSS>/` on the machine:
   `mkdir` without `-p`, so a rerun never copies the changed files over the
   originals, then `cp -p`.
2. Make the change; check the thing still works (health check, `launchctl
   print`, `systemctl status`).
3. When done, restore from the backup unless the user said keep it, and check
   again.

## 7. Report

```
Machine: <magicdns-host> (<login>, <OS arch>)
Ran: <what>, results in <file>
Changed: <what> — restored | left changed: <what, backup path, restore command>
Left behind: <files> | nothing
Config: <machine updated> | unchanged
```

## Example: daemon latency e2e on a real Mac

Does a change to a daemon (new binary and launchd plist) keep its local
health endpoint fast while it is busy? Time it on the installed daemon, then
on the new one, on the config's macOS e2e machine. The swap replaces two
installed files, so it needs the user's yes (step 6), asked up front with the
sudo secret. Names, paths and the port come from the project being tested.

```bash
H=<login>@<mac>; O="-o BatchMode=yes -o ConnectTimeout=10"   # from the config, checked in steps 1-2
B=/var/tmp/machines-$(date +%Y%m%d-%H%M%S)   # new per run: a rerun never backs up the swapped files
P=/Library/LaunchDaemons/com.example.agent.plist; BIN=/usr/local/bin/agent

# build and copy (step 4), from the change's checkout
GOOS=darwin GOARCH=arm64 go build -o /tmp/agent ./cmd/agent
scp $O /tmp/agent ./com.example.agent.plist "$H":/tmp/

# health 20 times during one job; "job-done" marks samples after it ended
measure() { ssh $O "$H" '
  U=http://127.0.0.1:8080
  for i in $(seq 30); do curl -sf -m2 -o /dev/null $U/health && break; sleep 1; done
  curl -s -X POST $U/job -o /dev/null & S=$!
  for i in $(seq 20); do
    curl -s -o /dev/null -m10 -w "%{time_total} %{http_code}" $U/health
    kill -0 $S 2>/dev/null && echo " busy" || echo " job-done"
    sleep 0.5
  done; wait'; }
measure > before.txt

# swap (step 6): back up both files first; set -e stops before any change if that fails
ssh $O "$H" "sudo -S -p '' sh -c 'set -e; mkdir -m 700 $B; cp -p $P $BIN $B/
  launchctl bootout system $P || true
  install -m 755 /tmp/agent $BIN; install -m 644 /tmp/$(basename $P) $P
  launchctl bootstrap system $P'" < "$file"
measure > after.txt

# restore, check, clean up
ssh $O "$H" "sudo -S -p '' sh -c 'set -e; launchctl bootout system $P || true
  cp -p $B/agent $BIN; cp -p $B/$(basename $P) $P; launchctl bootstrap system $P'" < "$file"
rm -f "$file"
ssh $O "$H" 'sleep 5; curl -sf -m5 http://127.0.0.1:8080/health' &&
  ssh $O "$H" 'rm -f /tmp/agent /tmp/com.example.agent.plist'
```

Report median and max of each file (20 samples: no p95), how many samples
were `job-done` or not `200`, and whether the restore's health check passed.
Keep `$B` until the user has seen the report.

## Failure modes

- **`tailnet policy does not permit you to SSH as user`**: wrong login for
  this machine. Use the config's `login`; note the refused one in `notes`.
- **`Tailscale SSH requires an additional check`** with a URL: give the user
  the URL to approve, then retry once. Don't loop.
- **`Permission denied (publickey)`** or **`Host key verification failed`**:
  report it. Don't edit `~/.ssh/known_hosts` or add keys without a yes.
- **Ping times out but status says online**: report it; try once more after a
  minute. Don't fall back to the machine's public IP.
- **`sudo: a password is required`** after feeding the file: wrong password or
  the login isn't an admin. Ask once more through `request_secret`, then stop.
- **A change broke the service**: restore from the backup at once, then report.

## When the output misses

If the user is unhappy with what this skill produced, load the `skill-improve` skill.
