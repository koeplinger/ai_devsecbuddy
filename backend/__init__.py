"""AI DevSecBuddy backend (roadmap M2).

A FastAPI service that hosts the AI-application tiles and exposes the DevSecBuddy
run/report API. It is the integration point: it *imports* the ``devsecbuddy``
product library and never reimplements product logic (see docs/architecture.md).
"""
