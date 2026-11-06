#!/usr/bin/env python3
"""Read-only web dashboard for the agent fleet (stdlib only).

  server.py [--port 8787] [--host 127.0.0.1]

Binds to localhost; expose it with tunnel.sh (cloudflared). If DASHBOARD_TOKEN
is set in config.env, the first visit must be /?token=<TOKEN> (then a cookie
is set).

Read-only by default. With DASHBOARD_CONTROL=1 (requires DASHBOARD_TOKEN) it also
lets the browser steer live workers and take them over in a web terminal (ttyd,
bound to a private Unix socket and reachable only through this server's auth).
That is a shell on this machine: put Cloudflare Access in front of the tunnel.

Endpoints:
  GET  /                          the UI
  GET  /api/state                 runs, recent events, slot usage
  GET  /api/runs/<id>/log         the worker's transcript, condensed
  POST /api/runs/<id>/control     {"op": say|steer|stop|takeover, "text": ...}   (control mode)
  GET  /term/?arg=<run>           web terminal attached to a taken-over run      (control mode)
"""
import argparse
import atexit
import hmac
import json
import re
import signal
import socket
import subprocess
import sys
import threading
from collections import deque
from http import cookies
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

HERE = Path(__file__).resolve().parent
AI_SKILLS = HERE.parents[1]
sys.path.insert(0, str(AI_SKILLS / "lib"))
sys.path.insert(0, str(AI_SKILLS / "agent-launcher" / "scripts"))
import fleet  # noqa: E402
import supervisor  # noqa: E402

COOKIE = "fleet_token"
TTYD_SOCK = fleet.FLEET_HOME / "ttyd.sock"
CONTROL_OPS = {"say", "steer", "stop", "takeover"}
RUN_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


def tail_events(n=300):
    if not fleet.EVENTS.exists():
        return []
    with open(fleet.EVENTS) as fh:
        lines = deque(fh, maxlen=n)
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out[::-1]


def short(v, n=160):
    s = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "…"


def condensed_log(run_id, limit=400):
    """Turn claude stream-json into readable rows: text, tool calls, tool errors, result."""
    path = fleet.run_dir(run_id) / "stream.jsonl"
    rows = []
    if not path.exists():
        return rows
    with open(path) as fh:
        for line in fh:
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = ev.get("type")
            if t == "assistant":
                for c in ev.get("message", {}).get("content", []):
                    if c.get("type") == "text" and c.get("text", "").strip():
                        rows.append({"k": "text", "v": c["text"].strip()[:2000]})
                    elif c.get("type") == "tool_use":
                        inp = c.get("input", {})
                        detail = inp.get("command") or inp.get("file_path") or inp.get("pattern") \
                            or inp.get("skill") or inp
                        rows.append({"k": "tool", "name": c.get("name"), "v": short(detail)})
            elif t == "user":
                for c in ev.get("message", {}).get("content", []) or []:
                    if isinstance(c, dict) and c.get("type") == "tool_result" and c.get("is_error"):
                        rows.append({"k": "error", "v": short(c.get("content"), 400)})
            elif t == "result":
                rows.append({"k": "result", "v": (ev.get("result") or "")[:3000],
                             "cost": ev.get("total_cost_usd"), "turns": ev.get("num_turns")})
    return rows[-limit:]


class Handler(BaseHTTPRequestHandler):
    server_version = "fleet-dashboard"

    def log_message(self, *args):
        pass

    def send(self, code, body, ctype="application/json", extra=None):
        data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def authorized(self, url):
        token = self.server.token
        if not token:
            return True, None
        q = parse_qs(url.query).get("token", [None])[0]
        if q and hmac.compare_digest(q, token):
            c = f"{COOKIE}={token}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=2592000"
            return True, {"Set-Cookie": c}
        jar = cookies.SimpleCookie(self.headers.get("Cookie", ""))
        if COOKIE in jar and hmac.compare_digest(jar[COOKIE].value, token):
            return True, None
        return False, None

    def do_GET(self):
        url = urlparse(self.path)
        ok, extra = self.authorized(url)
        if not ok:
            return self.send(401, b"unauthorized: open /?token=...", "text/plain")
        if url.path == "/":
            return self.send(200, (HERE / "index.html").read_bytes(), "text/html; charset=utf-8", extra)
        if url.path == "/api/state":
            cfg = fleet.load_config()
            runs = fleet.list_runs()
            for r in runs:
                if r.get("state") == "taken-over":
                    r["tmux_alive"] = supervisor.tmux_alive(r["run_id"])
            active = [r for r in runs if r.get("state") in fleet.ACTIVE_STATES]
            return self.send(200, {
                "now": fleet.now(), "runs": runs[:200], "events": tail_events(),
                "slots": {"used": len(active), "max": int(cfg["FLEET_MAX_PARALLEL"])},
                "control": self.server.control,
            })
        if url.path == "/term" or url.path.startswith("/term/"):
            if not self.server.control:
                return self.send(404, {"error": "control mode is off"})
            return self.proxy_ttyd()
        parts = url.path.strip("/").split("/")
        if len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "log":
            run_id = parts[2]
            if "/" in run_id or ".." in run_id or not fleet.read_meta(run_id):
                return self.send(404, {"error": "no such run"})
            return self.send(200, {"meta": fleet.read_meta(run_id), "log": condensed_log(run_id)})
        self.send(404, {"error": "not found"})

    def do_POST(self):
        url = urlparse(self.path)
        ok, _ = self.authorized(url)
        if not ok:
            return self.send(401, {"error": "unauthorized"})
        parts = url.path.strip("/").split("/")
        if not (len(parts) == 4 and parts[:2] == ["api", "runs"] and parts[3] == "control"):
            return self.send(404, {"error": "not found"})
        if not self.server.control:
            return self.send(403, {"error": "control mode is off (DASHBOARD_CONTROL=1)"})
        # CSRF: a custom header can't be sent cross-site without a CORS preflight we never grant.
        if self.headers.get("X-Fleet-Control") != "1":
            return self.send(403, {"error": "missing X-Fleet-Control header"})
        run_id = parts[2]
        if not RUN_ID.match(run_id) or not fleet.read_meta(run_id):
            return self.send(404, {"error": "no such run"})
        try:
            n = min(int(self.headers.get("Content-Length", 0)), 20000)
            body = json.loads(self.rfile.read(n) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self.send(400, {"error": "bad json"})
        op = body.get("op")
        if op not in CONTROL_OPS:
            return self.send(400, {"error": f"op must be one of {sorted(CONTROL_OPS)}"})
        by = self.headers.get("Cf-Access-Authenticated-User-Email") or "dashboard"
        try:
            reply = supervisor.ctl(run_id, op, body.get("text"), by=by)
        except OSError as e:
            reply = {"ok": False, "error": f"could not reach the run's supervisor: {e}"}
        if reply.get("ok") and op == "takeover":
            reply["terminal"] = f"/term/?arg={run_id}"
        self.send(200 if reply.get("ok") else 409, reply)

    def proxy_ttyd(self):
        """Splice this connection to ttyd's Unix socket (plain HTTP and the WebSocket upgrade)."""
        try:
            up = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            up.connect(str(TTYD_SOCK))
        except OSError:
            return self.send(502, {"error": "web terminal (ttyd) is not running"})
        head = f"{self.command} {self.path} HTTP/1.1\r\n"
        head += "".join(f"{k}: {v}\r\n" for k, v in self.headers.items()) + "\r\n"
        up.sendall(head.encode())

        def pump_up():
            try:
                while True:
                    data = self.rfile.read1(65536)
                    if not data:
                        break
                    up.sendall(data)
            except OSError:
                pass
            finally:
                try:
                    up.shutdown(socket.SHUT_WR)
                except OSError:
                    pass

        t = threading.Thread(target=pump_up, daemon=True)
        t.start()
        try:
            while True:
                data = up.recv(65536)
                if not data:
                    break
                self.connection.sendall(data)
        except OSError:
            pass
        finally:
            up.close()
            self.close_connection = True


def start_ttyd():
    try:
        TTYD_SOCK.unlink()
    except FileNotFoundError:
        pass
    proc = subprocess.Popen(
        ["ttyd", "-i", str(TTYD_SOCK), "-W", "-a", "-O", "-b", "/term",
         "-t", "titleFixed=fleet takeover", "-t", "fontSize=14",
         "bash", str(AI_SKILLS / "bin" / "fleet-attach")],
        stdout=subprocess.DEVNULL, stderr=open(fleet.FLEET_HOME / "ttyd.log", "a"))
    atexit.register(proc.terminate)
    for _ in range(50):
        if TTYD_SOCK.exists():
            break
        threading.Event().wait(0.1)
    TTYD_SOCK.chmod(0o600)
    return proc


def main():
    cfg = fleet.load_config()
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=int(cfg["DASHBOARD_PORT"]))
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    srv.token = cfg.get("DASHBOARD_TOKEN", "")
    srv.control = cfg.get("DASHBOARD_CONTROL") == "1"
    if not srv.token:
        print("warning: DASHBOARD_TOKEN is empty — anyone with the tunnel URL can view the dashboard",
              file=sys.stderr)
        if srv.control:
            print("refusing DASHBOARD_CONTROL=1 without DASHBOARD_TOKEN; control mode is OFF",
                  file=sys.stderr)
            srv.control = False
    if srv.control:
        fleet.ensure_dirs()
        start_ttyd()
        print("control mode ON: steering + web terminal. Put Cloudflare Access in front of the tunnel.",
              file=sys.stderr)
    # SIGTERM (systemd, kill) must still run atexit so the ttyd child goes down with us.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    print(f"fleet dashboard on http://{a.host}:{a.port}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
