"""LangGraph state definitions for the KYB discovery cascade.

The DiscoveryState flows through the graph, accumulating data at each node.
Each node returns a partial dict — LangGraph merges it into the full state.
"""

from __future__ import annotations

from typing import Any, TypedDict


class DiscoveryState(TypedDict, total=False):
    """Typed state flowing through the discovery cascade graph.

    Fields marked as inputs are set at graph entry.  Cascade fields are
    populated by whichever scoring layer succeeds first.
    """

    # ── Inputs (set at graph entry) ──────────────────────────────
    company_id: str
    company_name: str
    url: str
    is_parked: bool
    city: str | None
    state_code: str | None  # "state" is a LangGraph reserved concept

    # ── After homepage navigation ────────────────────────────────
    base_url: str
    base_domain: str
    nav_failed: bool  # True if homepage unreachable

    # ── Extracted page data (shared across nodes) ────────────────
    elements: list[dict[str, Any]]
    page_data: dict[str, Any]  # {hrefs, mailto, tel, jsonld, text}

    # ── Cascade picks ────────────────────────────────────────────
    best_careers_el: dict[str, Any] | None
    best_contact_el: dict[str, Any] | None
    careers_source: str  # "dom" | "llm" | "vision" | "probe" | "none"

    # ── Output signals (same schema as existing discovery.py) ────
    careers: dict[str, Any]  # {careers_url, ats_platform, ats_url}
    contact: dict[str, Any]  # {contact_email, contact_phone, contact_page_url}

    # ── Vector store ─────────────────────────────────────────────
    similar_companies: list[dict[str, Any]]


def empty_careers() -> dict[str, Any]:
    return {"careers_url": None, "ats_platform": None, "ats_url": None}


def empty_contact() -> dict[str, Any]:
    return {"contact_email": None, "contact_phone": None, "contact_page_url": None}


def initial_state(
    company_id: str,
    company_name: str,
    url: str,
    *,
    is_parked: bool = False,
    city: str | None = None,
    state_code: str | None = None,
) -> DiscoveryState:
    """Build the initial state dict to invoke the graph with."""
    return DiscoveryState(
        company_id=company_id,
        company_name=company_name,
        url=url,
        is_parked=is_parked,
        city=city,
        state_code=state_code,
        base_url="",
        base_domain="",
        nav_failed=False,
        elements=[],
        page_data={},
        best_careers_el=None,
        best_contact_el=None,
        careers_source="none",
        careers=empty_careers(),
        contact=empty_contact(),
        similar_companies=[],
    )
