"""Standard response wrappers."""
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class OkResponse(BaseModel, Generic[T]):
    ok: bool = True
    data: Optional[T] = None


class ErrorResponse(BaseModel):
    ok: bool = False
    error: str
    details: Optional[dict] = None


class HealthResponse(BaseModel):
    healthy: bool
    version: str
    supabase: str
    brain: str
    watcher: str
    machine_id: str


class PaginatedResponse(BaseModel, Generic[T]):
    items: list[T]
    total: int
    limit: int
    offset: int


class SettingChangeResponse(BaseModel):
    namespace: str
    key: str
    old_value: Any
    new_value: Any
