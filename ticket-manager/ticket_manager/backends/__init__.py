import tomllib
from pathlib import Path

from ..interface import TicketBackend, TicketError

CONFIG_FILE = Path.home() / ".config" / "ticket-manager" / "config.toml"
KANEO_KEYS = ("base_url", "workspace_id", "workspace_slug")


def load_backend() -> TicketBackend:
    """The backend named in config.toml (default kaneo)."""
    config = tomllib.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
    name = config.get("backend", "kaneo")
    if name == "kaneo":
        from .kaneo import KaneoBackend
        opts = config.get("kaneo", {})
        missing = [k for k in KANEO_KEYS if k not in opts]
        if missing:
            raise TicketError(f"set {', '.join(missing)} under [kaneo] in {CONFIG_FILE}")
        return KaneoBackend(*(opts[k] for k in KANEO_KEYS))
    raise TicketError(f"unknown backend {name!r} in {CONFIG_FILE}; known: kaneo")
