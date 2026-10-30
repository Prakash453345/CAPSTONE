"""Process supervision for the stack the site drives.

Four things can be running: Redis (the event bus), `api-service` (the REST +
WebSocket surface), a simulation, and at most one offline gate/benchmark
script. Each is a `Managed` -- one `Popen` in its own process group, with a
reader thread draining stdout+stderr into a bounded ring buffer the browser
tails by sequence number.

Own-process-group + signal-the-group on stop is deliberate: a simulation
spawns a real `sumo` child through TraCI, and `uvicorn` can spawn workers.
Signalling only the parent leaves those orphaned holding port 8000 or a TraCI
socket, which is the single most annoying failure mode of a tool like this.
"""

from __future__ import annotations

import os
import signal
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

from simlab import paths

LOG_CAPACITY = 4000


class Managed:
    """One supervised child process plus its log tail."""

    def __init__(self, name: str, label: str):
        self.name = name
        self.label = label
        self.proc: subprocess.Popen | None = None
        self.argv: list[str] = []
        self.started_at: float | None = None
        self.exit_code: int | None = None
        self.meta: dict = {}
        self._lines: deque[tuple[int, float, str]] = deque(maxlen=LOG_CAPACITY)
        self._seq = 0
        self._lock = threading.Lock()
        self._reader: threading.Thread | None = None

    # -- logs --------------------------------------------------------------
    def log(self, line: str) -> None:
        with self._lock:
            self._seq += 1
            self._lines.append((self._seq, time.time(), line.rstrip("\n")))

    def tail(self, since: int = 0, limit: int = 400) -> dict:
        with self._lock:
            rows = [r for r in self._lines if r[0] > since][-limit:]
            return {
                "name": self.name,
                "seq": self._seq,
                "lines": [{"n": n, "t": t, "s": s} for n, t, s in rows],
            }

    def clear_logs(self) -> None:
        with self._lock:
            self._lines.clear()

    # -- lifecycle ---------------------------------------------------------
    @property
    def running(self) -> bool:
        if self.proc is None:
            return False
        if self.proc.poll() is None:
            return True
        if self.exit_code is None:
            self.exit_code = self.proc.returncode
        return False

    def start(
        self,
        argv: list[str],
        *,
        cwd: Path | None = None,
        env: dict[str, str] | None = None,
        meta: dict | None = None,
    ) -> dict:
        if self.running:
            return {"ok": False, "reason": f"{self.label} is already running"}
        self.argv = [str(a) for a in argv]
        self.exit_code = None
        self.meta = dict(meta or {})
        self.log(f"$ {' '.join(self.argv)}")
        try:
            self.proc = subprocess.Popen(
                self.argv,
                cwd=str(cwd or paths.REPO),
                env=env or paths.repo_env(),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
                start_new_session=True,
            )
        except (OSError, ValueError) as exc:
            self.log(f"!! could not start: {exc}")
            self.proc = None
            return {"ok": False, "reason": f"could not start {self.label}: {exc}"}

        self.started_at = time.time()
        self._reader = threading.Thread(target=self._drain, daemon=True)
        self._reader.start()
        return {"ok": True, "pid": self.proc.pid}

    def _drain(self) -> None:
        proc = self.proc
        if proc is None or proc.stdout is None:
            return
        try:
            for line in proc.stdout:
                self.log(line)
        except Exception as exc:  # pragma: no cover
            self.log(f"!! log reader stopped: {exc}")
        code = proc.wait()
        self.exit_code = code
        self.log(f"-- {self.label} exited with code {code}")

    def stop(self, *, timeout_s: float = 8.0) -> dict:
        if not self.running or self.proc is None:
            return {"ok": True, "reason": f"{self.label} was not running"}
        pid = self.proc.pid
        self.log(f"-- stopping {self.label} (pid {pid})")
        for sig, wait in ((signal.SIGTERM, timeout_s), (signal.SIGKILL, 3.0)):
            try:
                os.killpg(os.getpgid(pid), sig)
            except (ProcessLookupError, PermissionError):
                try:
                    self.proc.send_signal(sig)
                except Exception:
                    break
            deadline = time.monotonic() + wait
            while time.monotonic() < deadline:
                if self.proc.poll() is not None:
                    return {"ok": True}
                time.sleep(0.1)
        return {"ok": self.proc.poll() is not None, "reason": "process did not exit"}

    def info(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "running": self.running,
            "pid": self.proc.pid if self.proc and self.running else None,
            "started_at": self.started_at,
            "uptime_s": round(time.time() - self.started_at, 1)
            if (self.started_at and self.running)
            else None,
            "exit_code": self.exit_code,
            "argv": self.argv,
            "meta": self.meta,
        }


# --------------------------------------------------------------------------
# health probes
# --------------------------------------------------------------------------
def tcp_open(host: str, port: int, timeout: float = 0.4) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def redis_ping(url: str) -> dict:
    """Inline-command PING over a raw socket -- no redis client needed, so the
    site's health check works before the repo's virtualenv exists."""
    host, port, db = parse_redis_url(url)
    if not tcp_open(host, port):
        return {"ok": False, "reason": f"nothing listening on {host}:{port}"}
    try:
        with socket.create_connection((host, port), timeout=1.0) as s:
            s.sendall(b"PING\r\n")
            data = s.recv(64)
        return {"ok": data.startswith(b"+PONG"), "raw": data.decode("utf-8", "replace").strip()}
    except OSError as exc:
        return {"ok": False, "reason": str(exc)}
    finally:
        del db


def parse_redis_url(url: str) -> tuple[str, int, int]:
    rest = url.split("//", 1)[-1]
    if "@" in rest:
        rest = rest.split("@", 1)[1]
    hostport, _, dbpart = rest.partition("/")
    host, _, port = hostport.partition(":")
    try:
        db = int(dbpart or 0)
    except ValueError:
        db = 0
    return (host or "localhost", int(port or 6379), db)


def port_owner(port: int) -> dict:
    """Who is listening on a localhost port, as (pid, command line).

    Needed because `api-service` can outlive the tool that started it: restart
    `server.py` and the old uvicorn is still holding port 8000 with the old API
    key, which this process has no `Popen` handle for. Answering "who is that"
    is what makes an honest restart possible instead of silently doing nothing.
    """
    import shutil
    import subprocess as sp

    pid = None
    if shutil.which("lsof"):
        try:
            out = sp.run(["lsof", "-nP", "-tiTCP:%d" % port, "-sTCP:LISTEN"],
                         capture_output=True, text=True, timeout=4)
            pid = next((int(x) for x in out.stdout.split() if x.strip().isdigit()), None)
        except (OSError, ValueError, sp.SubprocessError):
            pid = None
    if pid is None and shutil.which("fuser"):
        try:
            out = sp.run(["fuser", "-n", "tcp", str(port)], capture_output=True, text=True, timeout=4)
            pid = next((int(x) for x in out.stdout.split() if x.strip().isdigit()), None)
        except (OSError, ValueError, sp.SubprocessError):
            pid = None
    if pid is None:
        return {"pid": None, "cmd": ""}
    cmd = ""
    try:
        cmd = sp.run(["ps", "-o", "command=", "-p", str(pid)],
                     capture_output=True, text=True, timeout=4).stdout.strip()
    except (OSError, sp.SubprocessError):
        cmd = ""
    return {"pid": pid, "cmd": cmd}


def kill_port(port: int, *, must_match: tuple[str, ...] = ("uvicorn", "api_service")) -> dict:
    """Terminate the listener on a localhost port, but only when its command
    line looks like the thing we mean. Refusing to kill an unrecognised process
    matters: port 8000 is a popular port and this is not a process manager."""
    owner = port_owner(port)
    if owner["pid"] is None:
        return {"ok": True, "reason": "nothing listening"}
    if must_match and not any(m in owner["cmd"] for m in must_match):
        return {
            "ok": False,
            "reason": (
                f"port {port} is held by pid {owner['pid']} ({owner['cmd'][:90]}), which does "
                "not look like api-service. Left alone -- stop it yourself, or point this tool "
                "at a different port."
            ),
        }
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(owner["pid"], sig)
        except (ProcessLookupError, PermissionError) as exc:
            return {"ok": False, "reason": f"could not signal pid {owner['pid']}: {exc}"}
        for _ in range(20):
            if not tcp_open("127.0.0.1", port):
                return {"ok": True, "killed": owner["pid"]}
            time.sleep(0.15)
    return {"ok": False, "reason": f"pid {owner['pid']} is still holding port {port}"}


def http_json(url: str, timeout: float = 1.5, method: str = "GET", body=None, headers=None):
    req = urllib.request.Request(url, method=method, data=body, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read()
            return {"ok": True, "status": resp.status, "body": payload.decode("utf-8", "replace")}
    except urllib.error.HTTPError as exc:
        return {
            "ok": False,
            "status": exc.code,
            "body": exc.read().decode("utf-8", "replace"),
        }
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return {"ok": False, "status": 0, "body": str(exc)}


# --------------------------------------------------------------------------
# the supervisor
# --------------------------------------------------------------------------
class Stack:
    def __init__(self, *, redis_url: str, api_port: int, api_key: str):
        self.redis_url = redis_url
        self.api_port = api_port
        self.api_key = api_key
        self.redis = Managed("redis", "Redis")
        self.api = Managed("api", "api-service")
        self.sim = Managed("sim", "simulation")
        self.gate = Managed("gate", "gate script")
        self.redis_mode: str | None = None

    def all(self) -> list[Managed]:
        return [self.redis, self.api, self.sim, self.gate]

    def get(self, name: str) -> Managed | None:
        return {m.name: m for m in self.all()}.get(name)

    # -- redis -------------------------------------------------------------
    def start_redis(self) -> dict:
        ping = redis_ping(self.redis_url)
        if ping.get("ok"):
            self.redis_mode = self.redis_mode or "external"
            self.redis.log("-- Redis already reachable; leaving it alone")
            return {"ok": True, "reason": "already reachable", "mode": self.redis_mode}

        import shutil

        if shutil.which("docker") and (paths.REPO / "docker-compose.yml").exists():
            self.redis_mode = "docker"
            self.redis.log("-- bringing up the repo's redis container (docker compose)")
            res = subprocess.run(
                ["docker", "compose", "up", "-d", "redis"],
                cwd=str(paths.REPO),
                capture_output=True,
                text=True,
            )
            for line in (res.stdout + res.stderr).splitlines():
                self.redis.log(line)
            if res.returncode != 0:
                return {"ok": False, "reason": "docker compose up redis failed -- see the log"}
            for _ in range(40):
                if redis_ping(self.redis_url).get("ok"):
                    return {"ok": True, "mode": "docker"}
                time.sleep(0.25)
            return {"ok": False, "reason": "redis container started but never answered PING"}

        if shutil.which("redis-server"):
            self.redis_mode = "local"
            host, port, _ = parse_redis_url(self.redis_url)
            return self.redis.start(
                ["redis-server", "--port", str(port), "--save", "", "--appendonly", "no"],
                cwd=paths.VAR_DIR,
                meta={"mode": "local"},
            )

        return {
            "ok": False,
            "reason": (
                "no Redis available: Docker is not installed (or docker-compose.yml is "
                "missing) and there is no redis-server on PATH. Start Redis yourself, or "
                "install Docker Desktop and retry."
            ),
        }

    def stop_redis(self) -> dict:
        if self.redis_mode == "docker":
            res = subprocess.run(
                ["docker", "compose", "stop", "redis"],
                cwd=str(paths.REPO),
                capture_output=True,
                text=True,
            )
            for line in (res.stdout + res.stderr).splitlines():
                self.redis.log(line)
            return {"ok": res.returncode == 0}
        if self.redis.running:
            return self.redis.stop()
        return {
            "ok": False,
            "reason": "this Redis was not started here, so it is not stopped here",
        }

    # -- api-service -------------------------------------------------------
    def start_api(self) -> dict:
        if self.api_health().get("ok"):
            self.api.log("-- api-service already answering /health; leaving it alone")
            return {"ok": True, "reason": "already running"}
        uvicorn = paths.venv_bin("uvicorn")
        if uvicorn is None:
            return {
                "ok": False,
                "reason": (
                    "uvicorn not found. Run `make setup` in the repo so .venv exists "
                    "with the services installed."
                ),
            }
        env = paths.repo_env({"REDIS_URL": self.redis_url, "API_KEY": self.api_key})
        return self.api.start(
            [
                str(uvicorn),
                "api_service.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.api_port),
                "--log-level",
                "info",
            ],
            cwd=paths.REPO,
            env=env,
            meta={"port": self.api_port},
        )

    def stop_api(self) -> dict:
        """Stop api-service whether or not this process started it. An
        api-service left over from `make dev` or an earlier run of this tool is
        the common case, and a Stop button that quietly does nothing to it is
        worse than no button."""
        if self.api.running:
            res = self.api.stop()
            if res.get("ok") and not tcp_open("127.0.0.1", self.api_port):
                return res
        if not tcp_open("127.0.0.1", self.api_port):
            return {"ok": True, "reason": "api-service was not running"}
        return kill_port(self.api_port)

    def api_health(self) -> dict:
        res = http_json(f"http://127.0.0.1:{self.api_port}/health")
        if not res["ok"]:
            return {"ok": False, "reason": res["body"][:200]}
        import json as _json

        try:
            return {"ok": True, **_json.loads(res["body"])}
        except ValueError:
            return {"ok": False, "reason": "unparseable /health response"}

    def status(self) -> dict:
        return {
            "redis": {
                **redis_ping(self.redis_url),
                "url": self.redis_url,
                "mode": self.redis_mode,
                "managed": self.redis.running,
            },
            "api": {
                **self.api_health(),
                "port": self.api_port,
                "managed": self.api.running,
                "ws_url": f"ws://127.0.0.1:{self.api_port}/v1/stream",
            },
            "sim": self.sim.info(),
            "gate": self.gate.info(),
        }

    def shutdown(self) -> None:
        for m in (self.gate, self.sim, self.api):
            if m.running:
                m.stop()
