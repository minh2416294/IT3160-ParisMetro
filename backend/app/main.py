from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.app.api import auth, network, path, scenarios
from backend.app.config import PROJECT_ROOT
from backend.app.database import init_tables
from backend.app.dependencies.services import get_pathfinder, get_scenario_service

logger = logging.getLogger(__name__)

FRONTEND_DIR = PROJECT_ROOT / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    init_tables()
    # Warm singletons so the first user request isn't slow.
    get_pathfinder()
    get_scenario_service()
    logger.info("Paris Metro Navigator ready.")
    yield


app = FastAPI(title="Paris Metro Navigator", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(path.router)
app.include_router(scenarios.router)
app.include_router(network.router)


if FRONTEND_DIR.is_dir():
    app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")
