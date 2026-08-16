from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QThreadPool

from .services.config import ConfigurationService
from .services.database import DatabaseService
from .services.game import GameService
from .services.memory import MemoryDiscoveryService
from .services.paths import WorkspacePaths
from .services.zen_builder import ZenBuilderService
from .workers import TaskWorker


@dataclass
class AppContext:
    paths: WorkspacePaths
    database: DatabaseService
    config: ConfigurationService
    game: GameService
    memory: MemoryDiscoveryService
    zen_builder: ZenBuilderService
    thread_pool: QThreadPool
    workers: list[TaskWorker]

    @classmethod
    def create(cls) -> AppContext:
        paths = WorkspacePaths.discover()
        paths.ensure_workspace()
        return cls(
            paths=paths,
            database=DatabaseService(paths),
            config=ConfigurationService(paths),
            game=GameService(paths),
            memory=MemoryDiscoveryService(),
            zen_builder=ZenBuilderService(),
            thread_pool=QThreadPool.globalInstance(),
            workers=[],
        )

    def start_worker(self, worker: TaskWorker) -> None:
        self.workers.append(worker)
        worker.signals.finished.connect(lambda: self._release_worker(worker))
        self.thread_pool.start(worker)

    def _release_worker(self, worker: TaskWorker) -> None:
        if worker in self.workers:
            self.workers.remove(worker)
