"""Shared data models aligned with the jobs table schema."""

from datetime import datetime
from enum import StrEnum
from typing import TypedDict
from uuid import UUID


class JobStatus(StrEnum):
    SCRAPED = "scraped"
    SCORING = "scoring"
    SCORED = "scored"
    REVIEWING = "reviewing"
    APPROVED = "approved"
    REJECTED = "rejected"
    GENERATING = "generating"
    APPLYING = "applying"
    APPLIED = "applied"
    ERROR = "error"


class JobInsert(TypedDict, total=False):
    """Fields accepted by insert_job(). source, source_id, title, company are required."""

    source: str
    source_id: str
    url: str | None
    title: str
    company: str
    description: str | None
    location: str | None
    remote: bool
    salary_min: int | None
    salary_max: int | None
    date_posted: datetime | None


class JobRow(TypedDict):
    """A full row returned from the jobs table."""

    id: UUID
    source: str
    source_id: str
    url: str | None
    title: str
    company: str
    description: str | None
    location: str | None
    remote: bool
    salary_min: int | None
    salary_max: int | None
    date_posted: datetime | None
    date_scraped: datetime
    fit_score: int | None
    score_rationale: str | None
    scored_at: datetime | None
    status: str
    applied_at: datetime | None
    resume_path: str | None
    created_at: datetime
    updated_at: datetime
