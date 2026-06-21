import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api import scheduler
from api.routes import admin, corridor, event, incident, insights
from modules import model_registry as mr
from fastapi.middleware.cors import CORSMiddleware

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
    allow_origins=["https://gridlock-7ukmkh6fmg6csfwjbqnbvj.streamlit.app/", "http://localhost:8501"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)   



@app.get("/health")
def health():
    return {"status": "ok"}
