"""Task orchestration (architecture §5.3): the registry and its claims, the task with its events, the
prompter and the per-instance job. Imports no web framework, no concrete plugin and no configuration."""

from app.core.tasks.orchestrate import launch, run_task, start_task
from app.core.tasks.prompter import TaskPrompter
from app.core.tasks.registry import InstanceBusy, Started, TaskActive, TaskRegistry
from app.core.tasks.runner import DiscoveryResult, JobEnv, JobOutcome, fail_open_runs, run_job
from app.core.tasks.task import (
    Event,
    InvalidAnswer,
    PromptNotOpen,
    Task,
    TaskStatus,
    TaskTuning,
)

__all__ = [
    "DiscoveryResult",
    "Event",
    "InstanceBusy",
    "InvalidAnswer",
    "JobEnv",
    "JobOutcome",
    "PromptNotOpen",
    "Started",
    "Task",
    "TaskActive",
    "TaskPrompter",
    "TaskRegistry",
    "TaskStatus",
    "TaskTuning",
    "fail_open_runs",
    "launch",
    "run_job",
    "run_task",
    "start_task",
]
