# schemas.py
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

AgentName = Literal["research", "data", "writer", "reviewer", "diagram"]

class AgentError(BaseModel):
    message: str
    detail: Optional[str] = None

class AgentResult(BaseModel):
    ok: bool
    agent: AgentName
    job_id: str
    payload: Dict[str, Any] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    error: Optional[AgentError] = None

    @staticmethod
    def success(
        agent: AgentName,
        job_id: str,
        payload: Dict[str, Any] | None = None,
        warnings: List[str] | None = None,
    ) -> "AgentResult":
        return AgentResult(ok=True, agent=agent, job_id=job_id, payload=payload or {}, warnings=warnings or [])

    @staticmethod
    def fail(
        agent: AgentName,
        job_id: str,
        message: str,
        detail: str | None = None,
    ) -> "AgentResult":
        return AgentResult(ok=False, agent=agent, job_id=job_id, error=AgentError(message=message, detail=detail))
