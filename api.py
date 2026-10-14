from fastapi import FastAPI

from routers.forecast_router import router as forecast_router


app = FastAPI(title="FishinTime Forecast API")
app.include_router(forecast_router)
