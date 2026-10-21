"""Agent collaboration tracing: TraceRecorder accumulates in memory -> flushes to agent_trace at task end (persistent shared memory outside graph state)."""
import threading
from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from app.models.agent import AgentTrace


class TraceRecorder:
    """Thread-safe: clause-reviewer sub-agents record their own tool-call steps when running concurrently."""

    def __init__(self, task_type: str, ref_id: int):
        self.task_type = task_type
        self.ref_id = ref_id
        self._steps: list[AgentTrace] = []
        self._lock = threading.Lock()

    def step(
        self,
        agent_name: str,
        role: str,
        action: str,
        payload: dict | None = None,
        tokens: int = 0,
        latency_ms: int = 0,
        error: str | None = None,
    ) -> None:
        with self._lock:
            self._steps.append(
                AgentTrace(
                    task_type=self.task_type,
                    ref_id=self.ref_id,
                    agent_name=agent_name,
                    role=role,
                    step_idx=len(self._steps),
                    action=action,
                    payload=payload or {},
                    tokens=tokens,
                    latency_ms=latency_ms,
                    error=error[:500] if error else None,
                    created_at=datetime.now(),
                )
            )

    def total_tokens(self) -> int:
        with self._lock:
            return sum(s.tokens for s in self._steps)

    def flush(self, db: Session) -> int:
        """Batch flush to DB (run by the caller's main thread); failures only warn and do not affect the main flow."""
        with self._lock:
            steps, self._steps = self._steps, []
        if not steps:
            return 0
        try:
            for s in steps:
                db.add(s)
            db.commit()
            return len(steps)
        except Exception as e:  # noqa: BLE001
            db.rollback()
            logger.warning(f"agent trace flush failed: {e}")
            return 0
