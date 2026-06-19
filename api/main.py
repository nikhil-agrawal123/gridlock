from contextlib import asynccontextmanager

from fastapi import FastAPI

from api import scheduler
from api.routes import corridor, event


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.start()
    yield
    scheduler.scheduler.shutdown(wait=False)


app = FastAPI(title="TrafficSense API", lifespan=lifespan)
app.include_router(event.router)
app.include_router(corridor.router)


@app.get("/health")
def health():
    return {"status": "ok"}
