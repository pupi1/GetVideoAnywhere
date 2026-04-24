from dataclasses import dataclass, asdict, field
from datetime import datetime
from threading import Lock
from typing import Any
import uuid


@dataclass
class DownloadTask:
    id: str
    url: str
    status: str
    progress: float = 0.0
    title: str | None = None
    format_id: str | None = None
    file_path: str | None = None
    error: str | None = None
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class InMemoryTaskStore:
    def __init__(self) -> None:
        self._tasks: dict[str, DownloadTask] = {}
        self._lock = Lock()

    def create(self, url: str, format_id: str | None = None) -> DownloadTask:
        with self._lock:
            task_id = str(uuid.uuid4())
            task = DownloadTask(id=task_id, url=url, status="queued", format_id=format_id)
            self._tasks[task_id] = task
            return task

    def get(self, task_id: str) -> DownloadTask | None:
        with self._lock:
            return self._tasks.get(task_id)

    def update(self, task_id: str, **kwargs: Any) -> DownloadTask | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if not task:
                return None
            for key, value in kwargs.items():
                setattr(task, key, value)
            task.updated_at = datetime.utcnow().isoformat()
            return task

    def list_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [task.to_dict() for task in self._tasks.values()]


task_store = InMemoryTaskStore()
