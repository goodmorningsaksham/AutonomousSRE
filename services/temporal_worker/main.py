"""
Aegis Temporal Worker Service
"""
import asyncio
from workflows.incident_workflow import run_worker

if __name__ == "__main__":
    asyncio.run(run_worker())
