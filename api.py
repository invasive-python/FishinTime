import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import stripe
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from billing.router import router as billing_router
from routers.forecast_router import (
    router as forecast_router,
)
from routers.location_router import router as location_router
from services.secrets_manager import SecretsManagerError, get_secret

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    try:
        app.state.openai_api_key = get_secret("FishinSecret_OpenAI")
        app.state.openai_agent_id = get_secret("FishinSecret_Agent_Id")
        app.state.stripe_api_key = get_secret("FishinSecret_Stripe_API_Key")
        stripe.api_key = app.state.stripe_api_key
        app.state.evaluation_jobs = {}
    except SecretsManagerError as exc:
        logger.exception("Failed to load application credentials during startup.")
        raise RuntimeError(
            "Unable to load application credentials from AWS Secrets Manager."
        ) from exc
    yield

app = FastAPI(title="FishinTime Forecast API", lifespan=lifespan)

app.include_router(forecast_router)
app.include_router(location_router)
app.include_router(billing_router)

@app.get("/health", include_in_schema=False)
def health():
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(
        Path(__file__).with_name("static") / "index.html"
    )


@app.get("/static/config.js", include_in_schema=False)
def public_config() -> FileResponse:
    return FileResponse(
        Path(__file__).with_name("static") / "config.js"
    )


@app.get("/billing/subscribe", include_in_schema=False)
def subscribe_page() -> FileResponse:
    return FileResponse(
        Path(__file__).with_name("billing") / "subscribe.html"
    )


@app.get("/billing/client.js", include_in_schema=False)
def billing_client() -> FileResponse:
    return FileResponse(Path(__file__).with_name("billing") / "client.js")


@app.get("/billing/success", include_in_schema=False)
def billing_success_page() -> FileResponse:
    return FileResponse(Path(__file__).with_name("billing") / "success.html")


@app.get("/billing/cancel", include_in_schema=False)
def billing_cancel_page() -> FileResponse:
    return FileResponse(Path(__file__).with_name("billing") / "cancel.html")


app.mount(
    "/static",
    StaticFiles(directory=Path(__file__).with_name("static")),
    name="static",
)