# py-code-agent-plan-orchestrator

Plan Orchestrator plugin for Py Code Agent - provides advanced task orchestration capabilities.

## Features

- **Dynamic Resource Allocation**: Automatically allocate resources based on task priority
- **Priority-based Scheduling**: Execute tasks based on priority levels (CRITICAL, HIGH, NORMAL, LOW, BACKGROUND)
- **Execution Monitoring**: Track task metrics including execution time, retries, and success rates
- **Adaptive Parallelism**: Dynamically adjust worker count based on system load
- **Advanced Failure Recovery**: Automatic retry with exponential backoff

## Installation

```bash
pip install py-code-agent-plan-orchestrator
```

## Components

| Component | Description |
|-----------|-------------|
| `AdvancedOrchestrator` | Main orchestrator for task scheduling and execution |
| `OrchestratedTask` | Task wrapper with metadata, resources, and callbacks |
| `TaskPriority` | Priority levels: CRITICAL, HIGH, NORMAL, LOW, BACKGROUND |
| `TaskState` | Task states: PENDING, SCHEDULED, RUNNING, COMPLETED, FAILED, CANCELLED, RETRYING |
| `TaskMetrics` | Execution metrics tracking |
| `ResourceAllocation` | Resource limits for tasks |
| `AdaptiveParallelism` | Dynamic worker count adjustment |
| `OrchestratorMetrics` | Overall orchestrator performance metrics |

## Requirements

- Python 3.9+
- Py Code Agent core