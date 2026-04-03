"""Conditional edge routing functions for the KYB discovery cascade.

Each router inspects the current DiscoveryState and returns the name of
the next node.  LangGraph uses these as conditional_edges on the graph.
"""

from __future__ import annotations

from typing import Literal

from verifier.graph.state import DiscoveryState


def route_after_navigate(
    state: DiscoveryState,
) -> Literal["facebook_fallback", "entity_match", "__end__"]:
    """After homepage navigation: parked → FB, failed → end, else → cascade."""
    if state.get("is_parked"):
        return "facebook_fallback"
    if state.get("nav_failed"):
        return "__end__"
    return "entity_match"


def route_after_dom(
    state: DiscoveryState,
) -> Literal["navigate_careers", "llm_classify", "probe_fallback"]:
    """After DOM scoring: found → navigate, else → LLM (or probe if no LLM)."""
    if state.get("best_careers_el"):
        return "navigate_careers"
    # If no Ollama configured, the llm_classify node will be a no-op
    # and route_after_llm will push to vision or probe.
    return "llm_classify"


def route_after_llm(
    state: DiscoveryState,
) -> Literal["navigate_careers", "vision_analyze", "probe_fallback"]:
    """After LLM classification: found → navigate, else → vision or probe."""
    if state.get("best_careers_el"):
        return "navigate_careers"
    return "vision_analyze"


def route_after_vision(
    state: DiscoveryState,
) -> Literal["navigate_careers", "probe_fallback"]:
    """After vision analysis: found → navigate, else → probe."""
    if state.get("best_careers_el"):
        return "navigate_careers"
    return "probe_fallback"
