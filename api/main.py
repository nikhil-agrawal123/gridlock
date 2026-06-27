import os

os.environ.setdefault("OMP_NUM_THREADS", os.environ.get("CATBOOST_PREDICT_THREADS", "1"))
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")
os.environ.setdefault("NUMEXPR_NUM_THREADS", "1")

from contextlib import asynccontextmanager

from fastapi import FastAPI
from datetime import datetime

from api import scheduler
from api.routes import admin, corridor, event, incident, insights
from modules import model_registry as mr
from fastapi.middleware.cors import CORSMiddleware
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("trafficsense.main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    mr.seed_if_needed()  # first run: archive Day-2 models as v1, write registry
    scheduler.start()
    yield
    scheduler.scheduler.shutdown(wait=False)


app = FastAPI(title="TrafficSense API", lifespan=lifespan)
app.include_router(event.router)
app.include_router(corridor.router)
app.include_router(admin.router)
app.include_router(incident.router)
app.include_router(insights.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://gridlock-7ukmkh6fmg6csfwjbqnbvj.streamlit.app",  # no trailing slash: must match the browser Origin exactly
        "http://localhost:8501",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)   



@app.get("/health")
def health():
    logger.info("Health check requested at %s", datetime.now().isoformat())
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("api.main:app", host="0.0.0.0", port=port)
