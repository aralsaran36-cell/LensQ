import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from backend.config import settings
from backend.utils.logger import get_logger, log_event

logger = get_logger(__name__)


@dataclass
class Session:
    session_id: str
    image_bytes: bytes
    image_mime: str
    created_at: float = field(default_factory=time.monotonic)
    last_active: float = field(default_factory=time.monotonic)

    def touch(self) -> None:
        self.last_active = time.monotonic()


class SessionStore:
    """In-memory only. Nothing is written to disk.
    Data is lost on server restart (by design)."""

    def __init__(self) -> None:
        self._sessions: dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    # ---------- lifecycle ----------
    def start_cleanup(self) -> None:
        """Call once at app startup (inside a running event loop)."""
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._cleanup_loop())

    async def stop_cleanup(self) -> None:
        """Call at app shutdown. Also wipes every session."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
        async with self._lock:
            self._sessions.clear()

    # ---------- operations ----------
    async def create_or_replace(
        self, image_bytes: bytes, image_mime: str, session_id: Optional[str] = None
    ) -> Session:
        """New image uploaded: replaces the old image of that session
        (old bytes are dropped), or creates a brand new session."""
        async with self._lock:
            if session_id and session_id in self._sessions:
                sid = session_id
            else:
                sid = uuid.uuid4().hex  # matches SESSION_ID_PATTERN
            session = Session(session_id=sid, image_bytes=image_bytes, image_mime=image_mime)
            self._sessions[sid] = session
            return session

    async def get(self, session_id: Optional[str]) -> Optional[Session]:
        """Returns the session if it exists and is not expired, else None."""
        if not session_id:
            return None
        async with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                return None
            if self._is_expired(session):
                del self._sessions[session_id]
                return None
            session.touch()
            return session

    async def delete(self, session_id: Optional[str]) -> bool:
        if not session_id:
            return False
        async with self._lock:
            return self._sessions.pop(session_id, None) is not None

    async def count(self) -> int:
        async with self._lock:
            return len(self._sessions)

    # ---------- cleanup ----------
    @staticmethod
    def _is_expired(session: Session) -> bool:
        return (time.monotonic() - session.last_active) > settings.session_ttl_seconds

    async def purge_expired(self) -> int:
        async with self._lock:
            expired = [sid for sid, s in self._sessions.items() if self._is_expired(s)]
            for sid in expired:
                del self._sessions[sid]
            return len(expired)

    async def _cleanup_loop(self) -> None:
        while True:
            await asyncio.sleep(settings.session_cleanup_interval_seconds)
            removed = await self.purge_expired()
            if removed:
                log_event(logger, "sessions_purged", status="ok", status_code=removed)


# One shared instance for the whole app
session_store = SessionStore()