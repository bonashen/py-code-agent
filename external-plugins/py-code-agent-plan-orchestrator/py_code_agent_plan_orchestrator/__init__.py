from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class TaskPriority(Enum):
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4


class TaskState(Enum):
    PENDING = auto()
    SCHEDULED = auto()
    RUNNING = auto()
    COMPLETED = auto()
    FAILED = auto()
    CANCELLED = auto()
    RETRYING = auto()


@dataclass
class TaskMetrics:
    task_id: str
    created_at: datetime = field(default_factory=datetime.now)
    scheduled_at: Optional[datetime] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    cpu_time_ms: float = 0.0
    memory_mb: float = 0.0
    retry_count: int = 0
    error_count: int = 0

    @property
    def total_duration_ms(self) -> float:
        if self.completed_at:
            return (self.completed_at - self.created_at).total_seconds() * 1000
        return (datetime.now() - self.created_at).total_seconds() * 1000

    @property
    def execution_time_ms(self) -> float:
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds() * 1000
        return 0.0


@dataclass
class ResourceAllocation:
    max_memory_mb: float = 512.0
    max_cpu_percent: float = 80.0
    max_io_mbps: float = 100.0
    timeout_seconds: float = 300.0


@dataclass
class OrchestratedTask:
    id: str
    name: str
    description: str
    priority: TaskPriority = TaskPriority.NORMAL
    state: TaskState = TaskState.PENDING
    dependencies: List[str] = field(default_factory=list)
    resources: ResourceAllocation = field(default_factory=ResourceAllocation)
    metrics: TaskMetrics = field(default_factory=lambda: TaskMetrics(task_id=""))

    executor: Optional[Callable[..., Any]] = None
    on_complete: Optional[Callable[[Any], None]] = None
    on_fail: Optional[Callable[[Exception], None]] = None

    result: Any = None
    error: Optional[Exception] = None

    def __post_init__(self):
        if not self.metrics.task_id:
            self.metrics.task_id = self.id


class AdaptiveParallelism:
    def __init__(self, min_workers: int = 1, max_workers: int = 8):
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.current_workers = min_workers
        self.load_history: List[float] = []

    def update_load(self, cpu_percent: float, memory_percent: float, active_tasks: int):
        load = (
            cpu_percent / 100.0 * 0.4
            + memory_percent / 100.0 * 0.4
            + min(active_tasks / self.current_workers, 1.0) * 0.2
        )

        self.load_history.append(load)
        if len(self.load_history) > 10:
            self.load_history.pop(0)

        avg_load = sum(self.load_history) / len(self.load_history)

        if avg_load > 0.8 and self.current_workers > self.min_workers:
            self.current_workers = max(self.min_workers, self.current_workers - 1)
            logger.info(f"Reduced workers to {self.current_workers} (load: {avg_load:.2f})")
        elif avg_load < 0.4 and self.current_workers < self.max_workers:
            self.current_workers = min(self.max_workers, self.current_workers + 1)
            logger.info(f"Increased workers to {self.current_workers} (load: {avg_load:.2f})")

    def get_optimal_workers(self) -> int:
        return self.current_workers


class OrchestratorMetrics:
    def __init__(self):
        self.start_time = datetime.now()
        self.total_tasks = 0
        self.completed_tasks = 0
        self.failed_tasks = 0
        self.retried_tasks = 0
        self.task_durations: List[float] = []

    def record_task_completion(self, duration_ms: float, success: bool):
        self.total_tasks += 1
        self.task_durations.append(duration_ms)
        if success:
            self.completed_tasks += 1
        else:
            self.failed_tasks += 1

    def record_retry(self):
        self.retried_tasks += 1

    def get_summary(self) -> Dict[str, Any]:
        elapsed = (datetime.now() - self.start_time).total_seconds()
        avg_duration = (
            sum(self.task_durations) / len(self.task_durations) if self.task_durations else 0
        )

        return {
            "elapsed_seconds": elapsed,
            "total_tasks": self.total_tasks,
            "completed": self.completed_tasks,
            "failed": self.failed_tasks,
            "retried": self.retried_tasks,
            "success_rate": self.completed_tasks / self.total_tasks if self.total_tasks > 0 else 0,
            "average_task_duration_ms": avg_duration,
            "throughput_tasks_per_second": self.total_tasks / elapsed if elapsed > 0 else 0,
        }


MAX_RETRY = 3


class AdvancedOrchestrator:
    def __init__(self, max_workers: int = 8):
        self.tasks: Dict[str, OrchestratedTask] = {}
        self.task_queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self.running_tasks: Dict[str, asyncio.Task] = {}
        self.max_workers = max_workers
        self.adaptive_parallelism = AdaptiveParallelism(min_workers=1, max_workers=max_workers)
        self.metrics = OrchestratorMetrics()
        self._shutdown = False
        self._scheduler_task: Optional[asyncio.Task] = None

    async def start(self):
        self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        logger.info(f"AdvancedOrchestrator started with max_workers={self.max_workers}")

    async def stop(self):
        self._shutdown = True
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        for task_id, task in list(self.running_tasks.items()):
            task.cancel()
        logger.info("AdvancedOrchestrator stopped")

    async def submit_task(self, task: OrchestratedTask) -> str:
        task_id = task.id or str(uuid.uuid4())
        task.id = task_id
        task.metrics.task_id = task_id

        self.tasks[task_id] = task
        await self.task_queue.put((task.priority.value, task_id))

        logger.info(f"Task {task_id} submitted with priority {task.priority.name}")
        return task_id

    async def _scheduler_loop(self):
        while not self._shutdown:
            try:
                current_workers = len(self.running_tasks)
                optimal_workers = self.adaptive_parallelism.get_optimal_workers()

                if current_workers < optimal_workers:
                    try:
                        priority, task_id = await asyncio.wait_for(
                            self.task_queue.get(), timeout=1.0
                        )

                        task = self.tasks.get(task_id)
                        if task and task.state == TaskState.PENDING:
                            if self._check_dependencies(task):
                                await self._start_task(task)
                            else:
                                await self.task_queue.put((priority, task_id))

                    except asyncio.TimeoutError:
                        pass

                await self._update_resource_allocation()
                await self._cleanup_completed_tasks()
                await asyncio.sleep(0.1)

            except Exception as e:
                logger.error(f"Scheduler loop error: {e}", exc_info=True)
                await asyncio.sleep(1.0)

    def _check_dependencies(self, task: OrchestratedTask) -> bool:
        for dep_id in task.dependencies:
            dep_task = self.tasks.get(dep_id)
            if not dep_task or dep_task.state != TaskState.COMPLETED:
                return False
        return True

    async def _start_task(self, task: OrchestratedTask):
        task.state = TaskState.RUNNING
        task.metrics.started_at = datetime.now()

        coro = self._execute_task_wrapper(task)
        self.running_tasks[task.id] = asyncio.create_task(coro)

        logger.info(f"Task {task.id} started")

    async def _execute_task_wrapper(self, task: OrchestratedTask):
        try:
            await self._execute_task(task)
        except Exception as e:
            logger.error(f"Task {task.id} failed: {e}")
            task.state = TaskState.FAILED
            task.error = e
            task.metrics.error_count += 1

            if task.metrics.retry_count < MAX_RETRY:
                await self._schedule_retry(task)

    async def _execute_task(self, task: OrchestratedTask):
        start_time = time.time()

        if task.executor:
            result = await task.executor(task)
        else:
            result = f"Executed: {task.name}"

        task.result = result
        task.state = TaskState.COMPLETED
        task.metrics.completed_at = datetime.now()
        task.metrics.cpu_time_ms = (time.time() - start_time) * 1000

        if task.on_complete:
            task.on_complete(result)

        self.metrics.record_task_completion(task.metrics.execution_time_ms, success=True)

        logger.info(f"Task {task.id} completed successfully")

    async def _schedule_retry(self, task: OrchestratedTask):
        task.metrics.retry_count += 1
        task.state = TaskState.PENDING
        self.metrics.record_retry()

        await self.task_queue.put((task.priority.value, task.id))
        logger.info(f"Task {task.id} scheduled for retry #{task.metrics.retry_count}")

    async def _update_resource_allocation(self):
        active_count = len(self.running_tasks)

        load_estimate = min(active_count / max(self.max_workers, 1), 1.0)

        self.adaptive_parallelism.update_load(
            cpu_percent=load_estimate * 100, memory_percent=50.0, active_tasks=active_count
        )

    async def _cleanup_completed_tasks(self):
        completed_ids = []
        for task_id, task_handle in list(self.running_tasks.items()):
            if task_handle.done():
                completed_ids.append(task_id)

        for task_id in completed_ids:
            del self.running_tasks[task_id]

    def get_metrics_report(self) -> Dict[str, Any]:
        return {
            "orchestrator": self.metrics.get_summary(),
            "active_tasks": len(self.running_tasks),
            "queued_tasks": self.task_queue.qsize(),
            "adaptive_workers": self.adaptive_parallelism.get_optimal_workers(),
            "task_breakdown": self._get_task_breakdown(),
        }

    def _get_task_breakdown(self) -> Dict[str, int]:
        breakdown = {state.name: 0 for state in TaskState}
        for task in self.tasks.values():
            breakdown[task.state.name] += 1
        return breakdown


__all__ = [
    "AdvancedOrchestrator",
    "OrchestratedTask",
    "TaskPriority",
    "TaskState",
    "TaskMetrics",
    "ResourceAllocation",
    "AdaptiveParallelism",
    "OrchestratorMetrics",
]
