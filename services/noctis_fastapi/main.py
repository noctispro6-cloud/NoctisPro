from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .routers import ai, dicom

settings = get_settings()

app = FastAPI(
    title="Noctis Pro FastAPI Gateway",
    version="0.1.0",
    description=(
        "Unified control plane that bridges the Rust DICOM receiver and "
        "AI analysis workflows while keeping the Django dashboard intact."
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://noctis-pro.com",
        "https://www.noctis-pro.com",
        "https://api.noctis-pro.com",
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(dicom.router)
app.include_router(ai.router)


@app.get('/healthz')
async def healthcheck() -> dict:
    return {
        'status': 'ok',
        'timestamp': datetime.utcnow(),
        'storage_root': str(settings.storage_root),
    }
