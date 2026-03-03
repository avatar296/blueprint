# ADR-002: Run LLM Locally via Ollama for Data Sovereignty

## Status

Accepted

## Context

The Evaluator service needs an LLM to score job descriptions against the Master Profile. Options include:

- Cloud AI APIs (OpenAI, Anthropic, Google) — highest capability, but career data and PII leave the private server
- Self-hosted inference via Ollama with open-weight models (Llama 3) — lower capability ceiling, but all data stays local
- Fine-tuned smaller models — high upfront cost, narrow applicability

The Master Profile contains 20 years of career history, PII, salary expectations, and clearance information. Data sovereignty is a hard requirement.

## Decision

Run Llama 3 locally via Ollama. The Evaluator communicates with Ollama over the internal Docker network using LangChain as the orchestration layer. The Ollama container stores model weights in a named Docker volume (`ollama_models`).

## Consequences

- **Full data sovereignty.** No career data, job descriptions, or PII ever leaves the Hetzner server.
- **No API costs.** Inference is free after the initial hardware investment.
- **Hardware-bound performance.** Scoring speed depends on the server's CPU/GPU. GPU passthrough is pre-configured in `docker-compose.yml` but commented out until needed.
- **Model quality ceiling.** Open-weight models may produce lower-quality scoring than frontier cloud models. Acceptable for the binary "good fit / bad fit" classification this pipeline needs.
- **LangChain abstraction.** If data sovereignty requirements change in the future, swapping to a cloud provider requires only changing the LangChain LLM binding — no Evaluator logic changes.
