"""Database credentials that can change while the service runs (Step 28).

OpenBao Agent writes a JSON file {"username": ..., "password": ...} and replaces it with a NEW
username and password before the old ones expire. Every new database connection calls
credentials() and so picks up the current pair; nothing restarts.

    creds = CredentialsFile(Path("/run/bao/rag_db.json"))
    user, password = creds()   # re-reads the file only when it has changed

Before OpenBao (or to roll back), StaticCredentials gives the old fixed user and password.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Protocol


class CredentialsUnavailable(Exception):  # noqa: N818 - a state, like AuditUnavailable
    """The credentials file is missing or unreadable. The message never contains a secret."""


class Credentials(Protocol):
    def __call__(self) -> tuple[str, str]: ...


class StaticCredentials:
    def __init__(self, username: str, password: str) -> None:
        self._pair = (username, password)

    def __call__(self) -> tuple[str, str]:
        return self._pair

    def __repr__(self) -> str:
        return f"StaticCredentials({self._pair[0]!r}, '**********')"


class CredentialsFile:
    """Reads {"username", "password"} from a JSON file, again whenever the file changes."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._stamp: tuple[int, int, int] | None = None  # (inode, mtime ns, size)
        self._pair: tuple[str, str] | None = None
        self.changes = 0  # how many different credential pairs have been loaded (for metrics/tests)

    def __call__(self) -> tuple[str, str]:
        try:
            st = os.stat(self.path)
        except OSError as e:
            raise CredentialsUnavailable(f"{self.path}: {e.strerror}") from None
        # The agent writes a temporary file and renames it over the old one, so the inode
        # changes even when two writes land within the same clock tick.
        stamp = (st.st_ino, st.st_mtime_ns, st.st_size)
        with self._lock:
            if stamp != self._stamp or self._pair is None:
                pair = self._read()
                if pair != self._pair:
                    self.changes += 1
                self._pair, self._stamp = pair, stamp
            return self._pair

    def _read(self) -> tuple[str, str]:
        try:
            data = json.loads(self.path.read_text())
            username, password = data["username"], data["password"]
        except (OSError, ValueError, KeyError, TypeError) as e:
            # ValueError covers bad JSON; never include the content: it may hold the password
            raise CredentialsUnavailable(
                f"{self.path}: not a credentials file ({type(e).__name__})"
            ) from None
        if not (isinstance(username, str) and isinstance(password, str) and username and password):
            raise CredentialsUnavailable(f"{self.path}: username/password missing or empty")
        return username, password

    def __repr__(self) -> str:
        return f"CredentialsFile({str(self.path)!r})"
