from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.router import router
from app.engine.market import MarketEngine


@asynccontextmanager
async def lifespan(app: FastAPI):
    engine = MarketEngine()
    app.state.engine = engine
    print(f"Starting {settings.app_name} on {settings.host}:{settings.port}")
    yield
    engine.stop()
    print(f"Shutting down {settings.app_name}")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1")


@app.get("/health")
async def health():
    return {"status": "ok", "app": settings.app_name}

