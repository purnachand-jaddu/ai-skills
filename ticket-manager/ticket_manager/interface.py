from abc import ABC, abstractmethod


class TicketError(Exception):
    """A tracker operation failed; the message says what and how to recover."""


class TicketBackend(ABC):
    """The operations ticket-manager needs, implemented once per tracker.

    A ticket is a dict: {id, key, title, status, project_id, url}; a column is
    {slug, name, is_final}.
    """

    name: str

    @abstractmethod
    def get(self, key: str) -> dict:
        """The ticket with this key (e.g. ACME-154)."""

    @abstractmethod
    def search(self, query: str, limit: int) -> list[dict]:
        """Tickets matching the query, best first."""

    @abstractmethod
    def projects(self) -> list[dict]:
        """Projects a ticket can be created in: {id, slug, name}."""

    @abstractmethod
    def columns(self, project_id: str) -> list[dict]:
        """The project's columns in board order."""

    @abstractmethod
    def move(self, ticket_id: str, status: str) -> None:
        """Move the ticket to the column with this slug."""

    @abstractmethod
    def comment(self, ticket_id: str, text: str) -> None:
        """Add a comment to the ticket."""

    @abstractmethod
    def create(self, project_id: str, title: str, description: str) -> dict:
        """Create a ticket in the project's to-do column."""

    @abstractmethod
    def list(self, project_id: str, status: str | None) -> list[dict]:
        """Every ticket in the project, optionally in one column."""

    @abstractmethod
    def history(self, ticket_id: str) -> list[dict]:
        """Comments and activity, oldest first: {at, by, kind, text}."""

    @abstractmethod
    def relations(self, ticket_id: str) -> list[dict]:
        """Links to other tickets: {kind, source_id, target_id}."""
