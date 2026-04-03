"""LangGraph-based KYB discovery cascade.

Reimplements the 4-layer careers/contact discovery pipeline using LangGraph's
StateGraph for orchestration, LangChain Ollama for LLM calls, and ChromaDB
for entity matching.  Toggle via VERIFIER_USE_LANGGRAPH=true.
"""
