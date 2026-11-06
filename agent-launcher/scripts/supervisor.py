"""Worker supervisor with a control channel.

One supervisor process per run. It owns the worker's stdin/stdout (claude -p with
stream-json in and out) and listens on a per-run Unix socket so other processes
(fleet CLI, dashboard) can steer the worker while it runs:

  {"op": "ping"}                         -> state, busy, session_id
  {"op": "say",   "text": "..."}         queue a message for the worker's next turn
  {"op": "steer", "text": "..."}         interrupt the current turn, then send the message
  {"op": "interrupt"}                    interrupt the current turn only
  {"op": "stop"}                         interrupt, end the session, kill leftovers
  {"op": "takeover"}                     stop, then reopen the session interactively in tmux

Requests and replies are one JSON object per line. Every op except ping also
carries "by" (who sent it), which lands in the event log and on the ticket.

Behaviour verified against the CLI: an interrupt ends the turn within ~0.1s and the
session keeps its context; commands the worker started can outlive the interrupt,
so stop/takeover always finish by killing the worker's process group.
"""
import json
import os
import signal
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

import fleet

IDLE_GRACE = 60          # seconds to keep an idle worker open for steering before finishing
STOP_GRACE = 10          # seconds between asking politely and killing the process group
SOCK_MAX = 100           # AF_UNIX path limit is 108 bytes on Linux


def control_sock_path(run_id):
    p = fleet.run_dir(run_id) / "control.sock"
    if len(str(p)) <= SOCK_MAX:
        return p
    d = Path(tempfile.gettempdir()) / f"fleet-{os.getuid()}"
    d.mkdir(mode=0o700, exist_ok=True)
    return d / f"{run_id}.sock"


def tmux_session(run_id):
    return f"fleet-{run_id}"


def tmux_alive(run_id):
    return subprocess.run(["tmux", "has-session", "-t", tmux_session(run_id)],
                          capture_output=True).returncode == 0


def run_processes(run_id):
    """PIDs whose environment carries this run's FLEET_RUN_ID (the worker and everything it spawned,
    including tool commands Claude Code starts in their own process group)."""
    marker = f"FLEET_RUN_ID={run_id}".encode()
    me, pids = os.getpid(), []
    for d in Path("/proc").iterdir():
        if not d.name.isdigit() or int(d.name) == me:
            continue
        try:
            if marker in (d / "environ").read_bytes().split(b"\0"):
                pids.append(int(d.name))
        except OSError:
            pass
    return pids


def kill_run_processes(run_id, exclude_tmux=True):
    tmux_pids = set()
    if exclude_tmux and tmux_alive(run_id):
        r = subprocess.run(["tmux", "list-panes", "-s", "-t", tmux_session(run_id), "-F", "#{pane_pid}"],
                           capture_output=True, text=True)
        tmux_pids = {int(x) for x in r.stdout.split() if x.isdigit()}
    killed = []
    for pid in run_processes(run_id):
        if pid in tmux_pids:
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except ProcessLookupError:
            pass
    return killed


def ctl(run_id, op, text=None, by=None, timeout=45):
    """Client: send one control request to a run's supervisor and return its reply."""
    meta = fleet.read_meta(run_id)
    if not meta:
        return {"ok": False, "error": "no such run"}
    path = meta.get("control_sock")
    if not path or not os.path.exists(path):
        return {"ok": False, "error": f"run is {meta.get('state')}; no live worker to control"}
    req = {"op": op}
    if text is not None:
        req["text"] = text
    if by:
        req["by"] = by
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
        s.settimeout(timeout)
        s.connect(path)
        s.sendall((json.dumps(req) + "\n").encode())
        buf = b""
        while not buf.endswith(b"\n"):
            chunk = s.recv(65536)
            if not chunk:
                break
            buf += chunk
    return json.loads(buf or b'{"ok": false, "error": "empty reply"}')


class Supervisor:
    def __init__(self, run_id, cmd, comment_fn):
        self.run_id = run_id
        self.cmd = cmd
        self.comment = comment_fn          # posts to the ticket, never raises
        self.meta = fleet.read_meta(run_id)
        self.dir = fleet.run_dir(run_id)
        self.lock = threading.Lock()       # guards stdin writes
        self.busy = True                   # a turn is in progress
        self.idle_since = None
        self.stdin_open = True
        self.session_id = None
        self.last_result = {}
        self.turn_ended = threading.Event()
        self.finish = None                 # None | "stop" | "takeover"
        self.finished = threading.Event()
        self.takeover_reply = None
        self.sock_path = control_sock_path(run_id)

    # ---- worker I/O -------------------------------------------------------
    def send(self, obj):
        with self.lock:
            if not self.stdin_open:
                return False
            try:
                self.proc.stdin.write(json.dumps(obj) + "\n")
                self.proc.stdin.flush()
                return True
            except (BrokenPipeError, ValueError):
                self.stdin_open = False
                return False

    def user(self, text):
        self.busy, self.idle_since = True, None
        self.turn_ended.clear()
        return self.send({"type": "user", "message": {"role": "user", "content": text}})

    def interrupt(self):
        return self.send({"type": "control_request", "request_id": f"int-{uuid.uuid4().hex[:8]}",
                          "request": {"subtype": "interrupt"}})

    def close_stdin(self):
        with self.lock:
            if self.stdin_open:
                self.stdin_open = False
                try:
                    self.proc.stdin.close()
                except OSError:
                    pass

    def read_stdout(self):
        with open(self.dir / "stream.jsonl", "a") as out:
            for line in self.proc.stdout:
                out.write(line)
                out.flush()
                try:
                    ev = json.loads(line)
                except json.JSONDecodeError:
                    continue
                t = ev.get("type")
                if t == "system" and ev.get("subtype") == "init":
                    self.busy, self.idle_since = True, None   # a turn started (also background wake-ups)
                    sid = ev.get("session_id")
                    if sid and sid != self.session_id:
                        self.session_id = sid
                        fleet.update_meta(self.run_id, session_id=sid)
                elif t == "result":
                    self.last_result = ev
                    self.busy, self.idle_since = False, time.time()
                    self.turn_ended.set()

    # ---- control socket ---------------------------------------------------
    def serve(self):
        try:
            self.sock_path.unlink()
        except FileNotFoundError:
            pass
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        old = os.umask(0o177)                      # socket readable by owner only
        srv.bind(str(self.sock_path))
        os.umask(old)
        srv.listen(8)
        fleet.update_meta(self.run_id, control_sock=str(self.sock_path))
        self.srv = srv
        while not self.finished.is_set():
            try:
                conn, _ = srv.accept()
            except OSError:
                break
            threading.Thread(target=self.handle, args=(conn,), daemon=True).start()

    def handle(self, conn):
        with conn:
            try:
                buf = b""
                while not buf.endswith(b"\n") and len(buf) < 65536:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
                req = json.loads(buf or b"{}")
                reply = self.dispatch(req)
            except Exception as e:  # noqa: BLE001 - always answer the client
                reply = {"ok": False, "error": repr(e)}
            try:
                conn.sendall((json.dumps(reply) + "\n").encode())
            except OSError:
                pass

    def dispatch(self, req):
        op, text, by = req.get("op"), (req.get("text") or "").strip(), req.get("by") or "unknown"
        ticket = self.meta["ticket_id"]
        if op == "ping":
            return {"ok": True, "busy": self.busy, "stdin_open": self.stdin_open,
                    "session_id": self.session_id}
        if self.finish:
            return {"ok": False, "error": f"run is already finishing ({self.finish})"}
        if op in ("say", "steer") and not text:
            return {"ok": False, "error": "text is required"}
        if op in ("say", "steer", "interrupt") and not self.stdin_open:
            return {"ok": False, "error": "worker input is closed; it is wrapping up"}

        if op == "say":
            self.user(f"[Message from {by} via fleet control]\n{text}")
            fleet.emit("run.say", self.run_id, ticket, text, by=by)
            return {"ok": True, "queued": self.busy}
        if op == "interrupt":
            self.interrupt()
            fleet.emit("run.interrupt", self.run_id, ticket, by=by)
            return {"ok": True}
        if op == "steer":
            if self.busy:
                self.interrupt()
                self.turn_ended.wait(5)
            self.user(f"[Course correction from {by}: your previous action was interrupted]\n{text}")
            fleet.emit("run.steer", self.run_id, ticket, text, by=by)
            self.comment(f"🧭 Run `{self.run_id}` was steered by {by}:\n\n> {text}")
            return {"ok": True}
        if op == "stop":
            self.finish = "stop"
            fleet.emit("run.stop.requested", self.run_id, ticket, by=by)
            self.comment(f"⏹️ Run `{self.run_id}` was stopped by {by}.")
            return {"ok": True}
        if op == "takeover":
            if not self.session_id:
                return {"ok": False, "error": "worker has no session yet; try again in a few seconds"}
            self.finish = "takeover"
            self.takeover_by = by
            self.finished.wait(STOP_GRACE + 20)
            return self.takeover_reply or {"ok": False, "error": "takeover timed out"}
        return {"ok": False, "error": f"unknown op {op!r}"}

    # ---- lifecycle --------------------------------------------------------
    def end_worker(self):
        """Polite interrupt, close input, then kill whatever is left (incl. commands it started)."""
        if self.busy:
            self.interrupt()
            self.turn_ended.wait(3)
        self.close_stdin()
        try:
            self.proc.wait(STOP_GRACE)
        except subprocess.TimeoutExpired:
            pass
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)   # also reaps stray children/background tasks
        except ProcessLookupError:
            pass
        try:
            self.proc.wait(5)
        except subprocess.TimeoutExpired:
            os.killpg(self.proc.pid, signal.SIGKILL)
        stray = kill_run_processes(self.run_id)   # tool commands live in their own process groups
        if stray:
            fleet.emit("run.reaped", self.run_id, self.meta["ticket_id"], f"{len(stray)} leftover process(es)")

    def start_tmux(self):
        m = self.meta
        resume = f"claude --resume {self.session_id} --model {m['model']}"
        # First open of a new worktree shows Claude Code's folder-trust prompt; that is the
        # human's call. If they exit by accident, the shell tells them how to get back in.
        inner = (f"{resume}; echo; echo '[claude exited — you are in the run worktree]'; "
                 f"echo 'Resume the session with:  {resume}'; exec bash -l")
        r = subprocess.run(
            ["tmux", "new-session", "-d", "-s", tmux_session(self.run_id), "-x", "220", "-y", "50",
             "-c", m["worktree"], "-e", f"FLEET_RUN_ID={self.run_id}",
             "-e", f"FLEET_TICKET_ID={m['ticket_id']}", "bash", "-lc", inner],
            capture_output=True, text=True)
        return r.returncode == 0, r.stderr.strip()

    def run(self, prompt, timeout):
        env = dict(os.environ, FLEET_RUN_ID=self.run_id, FLEET_TICKET_ID=self.meta["ticket_id"])
        with open(self.dir / "stderr.log", "w") as err:
            self.proc = subprocess.Popen(self.cmd, cwd=self.meta["worktree"], env=env, text=True,
                                         bufsize=1, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                         stderr=err, start_new_session=True)
        fleet.update_meta(self.run_id, state="running", worker_pid=self.proc.pid,
                          started_at=fleet.now())
        fleet.emit("run.started", self.run_id, self.meta["ticket_id"], self.meta["model"])
        reader = threading.Thread(target=self.read_stdout, daemon=True)
        reader.start()
        threading.Thread(target=self.serve, daemon=True).start()
        self.user(prompt)

        deadline = time.time() + timeout
        timed_out = False
        while self.proc.poll() is None:
            if self.finish:
                self.end_worker()
                break
            if time.time() > deadline:
                timed_out = True
                self.end_worker()
                break
            if not self.busy and self.stdin_open:
                meta = fleet.read_meta(self.run_id) or {}
                shipped = meta.get("mr_url") or meta.get("blocked") or meta.get("state") == "killed"
                idle_too_long = self.idle_since and time.time() - self.idle_since > IDLE_GRACE
                if shipped or idle_too_long:
                    self.close_stdin()   # let it exit; background tasks get to finish
            time.sleep(0.5)
        code = self.proc.wait()
        reader.join(5)

        outcome = {"exit_code": code, "timed_out": timed_out, "result": self.last_result}
        if self.finish == "takeover":
            ok, err = self.start_tmux()
            outcome["takeover"] = ok
            if ok:
                cmd = f"fleet attach {self.run_id}"
                self.takeover_reply = {"ok": True, "tmux": tmux_session(self.run_id), "attach": cmd}
                fleet.emit("run.taken-over", self.run_id, self.meta["ticket_id"],
                           f"{self.takeover_by} took over · {cmd}", by=self.takeover_by)
                self.comment(f"🙋 {self.takeover_by} took over run `{self.run_id}` interactively "
                             f"(same session, `{cmd}`).")
            else:
                self.takeover_reply = {"ok": False, "error": f"tmux failed: {err}"}
        self.finished.set()
        try:
            self.srv.close()
            self.sock_path.unlink()
        except (AttributeError, FileNotFoundError, OSError):
            pass
        return outcome
