from abc import ABC, abstractmethod


class SessionError(Exception):
    """A backend operation failed; the message says what and how to recover."""


class SessionBackend(ABC):
    """The operations session-manager promises, implemented once per harness."""

    @abstractmethod
    def available(self) -> bool:
        """Whether this session can run helpers here."""

    @abstractmethod
    def self_address(self) -> str:
        """This session's own address, named as the caller in a helper's first message."""

    @abstractmethod
    def names_in_use(self) -> set[str]:
        """Names of live helpers, so a new one can take the next free name."""

    @abstractmethod
    def start(self, name: str, cwd: str, agent: dict, message: str,
              labels: dict[str, str], visible: bool = True, worktree: dict | None = None) -> dict:
        """Start a helper with its first message, in a pane beside the caller unless hidden.

        worktree = {"ref", "branch" or None}: run it in a new git worktree of cwd's repo at ref.
        Returns {address, delivered, pane, worktree}."""

    @abstractmethod
    def delegate(self, helper: str, message: str) -> dict:
        """Send a task to a running helper."""

    @abstractmethod
    def collect(self, timeout: int) -> dict:
        """Wait for the next report or notice from this session's helpers."""

    @abstractmethod
    def status(self, feature: str) -> list[dict]:
        """This feature's helpers: name, address, agent, role, state."""

    @abstractmethod
    def read(self, helper: str, lines: int) -> str:
        """The helper's recent screen."""

    @abstractmethod
    def stop(self, helper: str) -> dict:
        """End a helper and clean it up."""

    @abstractmethod
    def report_command(self, caller: str) -> str:
        """The shell command prefix a helper runs to send one line to caller."""
