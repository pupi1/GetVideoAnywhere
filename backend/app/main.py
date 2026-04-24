from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import ALLOWED_ORIGINS
from app.routes.ai import router as ai_router
from app.routes.download import router as download_router


app = FastAPI(
    title="Universal Video Downloader API",
    version="0.1.0",
    description="FastAPI backend for multi-platform video parsing/downloading and AI text utilities.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS if ALLOWED_ORIGINS != ["*"] else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(download_router)
app.include_router(ai_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
