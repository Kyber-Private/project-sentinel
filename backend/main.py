"""Project Sentinel API.

Run from the backend folder:
    uvicorn main:app --reload --port 8000
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import health, investigations
from config import settings
from database.models import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

@asynccontextmanager
async def lifespan(_app: FastAPI):
    init_db()
    if not settings.ai_enabled:
        logging.getLogger("sentinel").warning(
            "AI provider is not configured. Agents are disabled; deterministic forecasting still runs."
        )
    yield


app = FastAPI(title="Project Sentinel API", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(health.router)
app.include_router(investigations.router)


init_db()
