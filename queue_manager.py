"""
bot/queue_manager.py
Per-chat async queue that drives song playback.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class Track:
    """Represents a single song in the queue."""
    title: str
    url: str
    duration: int
    thumbnail: str = ""
    requested_by: str = ""

    def duration_str(self) -> str:
        m, s = divmod(self.duration, 60)
        return f"{m}:{s:02d}" if self.duration else "?:??"

    def __str__(self) -> str:
        return f"🎵 *{self.title}* [{self.duration_str()}]"


PlayCallback = Callable[[Track], Coroutine]


class QueueWorker:
    """Manages a song queue for one Telegram chat."""

    def __init__(self, chat_id: int, play_fn: PlayCallback):
        self.chat_id = chat_id
        self._play_fn = play_fn
        self._tracks: List[Track] = []
        self._paused = False
        self._stopped = False
        self._current: Optional[Track] = None
        self._task: Optional[asyncio.Task] = None
        self._event = asyncio.Event()
        self._event.set()

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def is_stopped(self) -> bool:
        return self._stopped

    @property
    def current(self) -> Optional[Track]:
        return self._current

    @property
    def queue_list(self) -> List[Track]:
        return list(self._tracks)

    def queue_size(self) -> int:
        return len(self._tracks)

    def add(self, track: Track) -> int:
        self._tracks.append(track)
        self._stopped = False
        self._event.set()
        return len(self._tracks)

    def pause(self) -> bool:
        if not self._paused:
            self._paused = True
            self._event.clear()
            return True
        return False

    def resume(self) -> bool:
        if self._paused:
            self._paused = False
            self._event.set()
            return True
        return False

    def stop(self) -> None:
        self._tracks.clear()
        self._current = None
        self._stopped = True
        self._paused = False
        self._event.set()
        if self._task and not self._task.done():
            self._task.cancel()

    def ensure_running(self) -> None:
        if self._task is None or self._task.done():
            loop = asyncio.get_event_loop()
            self._task = loop.create_task(self._worker_loop())

    async def _worker_loop(self) -> None:
        while True:
            await self._event.wait()

            if self._stopped:
                break

            if not self._tracks:
                self._event.clear()
                continue

            self._current = self._tracks.pop(0)
            try:
                await self._play_fn(self._current)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Error playing '%s': %s", self._current.title, exc)
            finally:
                self._current = None


class QueueRegistry:
    """Maps chat_id → QueueWorker."""

    def __init__(self) -> None:
        self._workers: Dict[int, QueueWorker] = {}

    def get_or_create(self, chat_id: int, play_fn: PlayCallback) -> QueueWorker:
        if chat_id not in self._workers:
            self._workers[chat_id] = QueueWorker(chat_id, play_fn)
        return self._workers[chat_id]

    def get(self, chat_id: int) -> Optional[QueueWorker]:
        return self._workers.get(chat_id)

    def remove(self, chat_id: int) -> None:
        worker = self._workers.pop(chat_id, None)
        if worker:
            worker.stop()


registry = QueueRegistry()

