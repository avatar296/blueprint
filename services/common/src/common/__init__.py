"""Blueprint shared DB layer — connection pooling, models, job helpers."""

from common.companies import (
    get_company_count,
    get_unprobed_companies as get_unprobed_sourced_companies,
    mark_probed,
    upsert_company,
)
from common.db import get_pool
from common.discovery import (
    fetch_active_discoveries,
    fetch_filtered_discoveries,
    insert_discovery,
)
from common.jobs import fetch_jobs_by_status, insert_job, transition_status
from common.models import JobInsert, JobRow, JobStatus
from common.signals import (
    get_companies_to_verify,
    insert_signal,
    insert_signals_batch,
)
from common.sourcing_runs import (
    complete_run,
    create_run,
    fail_run,
    insert_provider_result,
)

__all__ = [
    "get_pool",
    # jobs
    "insert_job",
    "fetch_jobs_by_status",
    "transition_status",
    "JobStatus",
    "JobInsert",
    "JobRow",
    # discovery
    "insert_discovery",
    "fetch_active_discoveries",
    "fetch_filtered_discoveries",
    # companies
    "upsert_company",
    "get_unprobed_sourced_companies",
    "mark_probed",
    "get_company_count",
    # signals
    "get_companies_to_verify",
    "insert_signal",
    "insert_signals_batch",
    # sourcing runs
    "create_run",
    "complete_run",
    "fail_run",
    "insert_provider_result",
]
