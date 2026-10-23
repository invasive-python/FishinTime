import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from routers.forecast_router import (
    SecretsManagerError,
    get_secret,
)
from routers.forecast_router import (
    router as forecast_router,
)
from routers.location_router import router as location_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        app.state.openai_api_key = get_secret("FishinSecret_OpenAI")
        app.state.openai_agent_id = get_secret("FishinSecret_Agent_Id")
        app.state.evaluation_jobs = {}
    except SecretsManagerError as exc:
        logger.exception("Failed to load OpenAI credentials during startup.")
        raise RuntimeError(
            "Unable to load OpenAI credentials from AWS Secrets Manager."
        ) from exc
    yield

# TODO: cleanup print statements
app = FastAPI(title="FishinTime Forecast API", lifespan=lifespan)
app.include_router(forecast_router)
app.include_router(location_router)
app.mount(
    "/res",
    StaticFiles(directory=Path(__file__).with_name("res")),
    name="res",
)

@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(Path(__file__).with_name("index.html"))
