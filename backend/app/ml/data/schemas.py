"""Typed, file-format-neutral dataset records."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class DatasetSplit(str, Enum):
    TRAIN = "train"
    VALIDATION = "validation"
    TEST = "test"


class DatasetRecord(BaseModel):
    model_config = ConfigDict(extra="allow")

    record_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    split: DatasetSplit | None = None
    event_type: str | None = None
    severity: str | None = None
    depth_cm: float | None = None
    spam: bool | None = None
    language: str | None = None
