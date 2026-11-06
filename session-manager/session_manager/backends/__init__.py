import os
import tomllib
from pathlib import Path

from ..interface import SessionBackend, SessionError

CONFIG_FILE = Path.home() / ".config" / "session-manager" / "config.toml"


def detect() -> str:
    """The harness this session runs in: T3 Code first, since it may itself run inside a Herdr terminal."""
    if os.environ.get("T3CODE_THREAD_ID"):
        return "t3"
    return "herdr"


def load_backend() -> SessionBackend:
    """The backend named in config.toml, else the detected harness."""
    name = detect()
    if CONFIG_FILE.exists():
        name = tomllib.loads(CONFIG_FILE.read_text()).get("backend", name)
    if name == "herdr":
        from .herdr import HerdrBackend
        return HerdrBackend()
    if name == "t3":
        from .t3 import T3Backend
        return T3Backend()
    raise SessionError(f"unknown backend {name!r} in {CONFIG_FILE}; known: herdr, t3")
