"""Batch cascade runner with training signal capture.

Runs the LangGraph KYB discovery cascade against a list of companies,
capturing full intermediate state (careers_source, picked elements,
element lists) for LoRA training data generation.
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Per-company timeout (matches verifier's _COMPANY_TIMEOUT).
_COMPANY_TIMEOUT = 120


@dataclass
class CapturedResult:
    """One company's cascade output with full training signals."""

    company_id: str
    company_name: str
    url: str
    # Normal cascade output.
    careers: dict[str, Any] = field(default_factory=dict)
    contact: dict[str, Any] = field(default_factory=dict)
    # Training signals.
    careers_source: str = "none"
    best_careers_el: dict | None = None
    best_contact_el: dict | None = None
    elements: list[dict] = field(default_factory=list)
    base_url: str = ""
    nav_failed: bool = False
    error: str | None = None
    timestamp: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        # Drop large fields if empty to keep JSONL manageable.
        if not d.get("elements"):
            d.pop("elements", None)
        return d


def load_company_list(path: Path) -> list[dict]:
    """Load companies from JSON or CSV.

    JSON format: [{"name": "...", "website": "https://..."}, ...]
    CSV format: columns name, website (optional: id, city, state)

    Generates UUIDs for companies without an id field.
    """
    suffix = path.suffix.lower()

    if suffix == ".json":
        with open(path) as f:
            companies = json.load(f)
    elif suffix == ".csv":
        with open(path, newline="") as f:
            reader = csv.DictReader(f)
            companies = list(reader)
    else:
        raise ValueError(f"Unsupported file format: {suffix}. Use .json or .csv")

    # Ensure every company has an id.
    for c in companies:
        if not c.get("id"):
            c["id"] = str(uuid.uuid4())
        if not c.get("website"):
            log.warning("Company %s has no website — will be skipped", c.get("name", "?"))

    log.info("Loaded %d companies from %s", len(companies), path)
    return companies


async def run_capture_batch(
    companies: list[dict],
    *,
    concurrency: int = 3,
    ollama_base_url: str = "http://localhost:11434",
    ollama_model: str = "llama3:8b",
    ollama_timeout: float = 10.0,
    ollama_vision_model: str | None = None,
    ollama_vision_timeout: float = 15.0,
    output_path: Path | None = None,
) -> list[CapturedResult]:
    """Run the cascade against each company, capturing training signals.

    Orchestrates Playwright lifecycle with stealth and semaphore-bound
    concurrency. Results are streamed to *output_path* as JSONL
    incrementally (crash-safe).
    """
    from playwright.async_api import async_playwright
    from playwright_stealth import Stealth

    # Import here to avoid Playwright dep at import time.
    from verifier.graph.build import discover_one_langgraph

    _stealth = Stealth()

    # Filter to companies with websites.
    eligible = [c for c in companies if c.get("website")]
    if len(eligible) < len(companies):
        log.info("Skipping %d companies without websites", len(companies) - len(eligible))

    sem = asyncio.Semaphore(concurrency)
    results: list[CapturedResult] = []
    done_count = 0
    total = len(eligible)

    # Open output file for streaming if requested.
    out_file = None
    if output_path:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        out_file = open(output_path, "a")

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(ignore_https_errors=True)
            await _stealth.apply_stealth_async(context)

            async def _run(company: dict) -> CapturedResult | None:
                nonlocal done_count
                cid = company["id"]
                url = company.get("website", "")
                name = company.get("name", "")

                async with sem:
                    page = await context.new_page()
                    t_start = asyncio.get_event_loop().time()
                    try:
                        result = await asyncio.wait_for(
                            discover_one_langgraph(
                                page,
                                url,
                                company_id=str(cid),
                                company_name=name,
                                city=company.get("city"),
                                state_code=company.get("state"),
                                ollama_base_url=ollama_base_url,
                                ollama_model=ollama_model,
                                ollama_timeout=ollama_timeout,
                                ollama_vision_model=ollama_vision_model,
                                ollama_vision_timeout=ollama_vision_timeout,
                                capture_training_signals=True,
                            ),
                            timeout=_COMPANY_TIMEOUT,
                        )

                        ts = result.get("training_signals", {})
                        captured = CapturedResult(
                            company_id=str(cid),
                            company_name=name,
                            url=url,
                            careers=result.get("careers", {}),
                            contact=result.get("contact", {}),
                            careers_source=ts.get("careers_source", "none"),
                            best_careers_el=ts.get("best_careers_el"),
                            best_contact_el=ts.get("best_contact_el"),
                            elements=ts.get("elements", []),
                            base_url=ts.get("base_url", ""),
                            nav_failed=ts.get("nav_failed", False),
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        )

                        elapsed = asyncio.get_event_loop().time() - t_start
                        ats = result.get("careers", {}).get("ats_platform", "")
                        source = captured.careers_source
                        log.info(
                            "[%d/%d] %s — source=%s ats=%s (%.1fs)",
                            done_count + 1, total, name,
                            source, ats or "none", elapsed,
                        )
                        return captured

                    except asyncio.TimeoutError:
                        log.warning("[%d/%d] %s — TIMEOUT", done_count + 1, total, name)
                        return CapturedResult(
                            company_id=str(cid), company_name=name, url=url,
                            error="timeout",
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        )
                    except Exception as exc:
                        log.warning("[%d/%d] %s — ERROR: %s", done_count + 1, total, name, exc)
                        return CapturedResult(
                            company_id=str(cid), company_name=name, url=url,
                            error=str(exc),
                            timestamp=datetime.now(timezone.utc).isoformat(),
                        )
                    finally:
                        done_count += 1
                        await page.close()

            # Run all companies concurrently (bounded by semaphore).
            tasks = [asyncio.create_task(_run(c)) for c in eligible]
            for coro in asyncio.as_completed(tasks):
                captured = await coro
                if captured:
                    results.append(captured)
                    # Stream to JSONL immediately.
                    if out_file:
                        out_file.write(json.dumps(captured.to_dict()) + "\n")
                        out_file.flush()

            await context.close()
            await browser.close()

    finally:
        if out_file:
            out_file.close()

    log.info(
        "Capture complete: %d total, %d with careers, %d errors",
        len(results),
        sum(1 for r in results if r.careers.get("careers_url")),
        sum(1 for r in results if r.error),
    )
    return results


def load_captured_results(path: Path) -> list[CapturedResult]:
    """Load previously captured results from JSONL."""
    results = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            data = json.loads(line)
            results.append(CapturedResult(
                company_id=data.get("company_id", ""),
                company_name=data.get("company_name", ""),
                url=data.get("url", ""),
                careers=data.get("careers", {}),
                contact=data.get("contact", {}),
                careers_source=data.get("careers_source", "none"),
                best_careers_el=data.get("best_careers_el"),
                best_contact_el=data.get("best_contact_el"),
                elements=data.get("elements", []),
                base_url=data.get("base_url", ""),
                nav_failed=data.get("nav_failed", False),
                error=data.get("error"),
                timestamp=data.get("timestamp", ""),
            ))
    log.info("Loaded %d captured results from %s", len(results), path)
    return results
