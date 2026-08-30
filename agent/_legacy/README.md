# Legacy files — Gemini-era architecture

These files are from a prior version of the agent that used the Google Gemini API
for natural-language understanding and response generation.

They are kept here to:
1. Show that the architecture is LLM-pluggable (the tool schemas are the same format)
2. Provide a migration path if an LLM backend is added in future

The current implementation does NOT use any external LLM API.
See `agent/parser.py`, `agent/planner.py`, `agent/responder.py` for the deterministic replacements.
