from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from routers.forecast_router import router as forecast_router
from routers.location_router import router as location_router


app = FastAPI(title="FishinTime Forecast API")
app.include_router(forecast_router)
app.include_router(location_router)


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(Path(__file__).with_name("index.html"))

