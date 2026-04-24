from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response

from app.config import MAX_CONCURRENT_TASKS
from app.models.schemas import APIResponse, BatchDownloadRequest, DownloadRequest, ParseRequest
from app.services.task_store import task_store
from app.services.ytdlp_service import ytdlp_service


router = APIRouter(prefix="", tags=["download"])
executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS)


def _run_download(task_id: str, url: str, format_id: str | None) -> None:
    def progress_hook(_task_id: str, progress: float, data: dict) -> None:
        task_store.update(_task_id, status="downloading", progress=progress, title=data.get("filename"))

    try:
        task_store.update(task_id, status="downloading", progress=0)
        file_path = ytdlp_service.download(task_id, url, format_id, progress_hook)
        task_store.update(task_id, status="completed", progress=100, file_path=str(file_path))
    except Exception as exc:
        task_store.update(task_id, status="failed", error=str(exc))


@router.post("/parse", response_model=APIResponse)
def parse_video(payload: ParseRequest) -> APIResponse:
    try:
        data = ytdlp_service.parse(str(payload.url))
        return APIResponse(data=data)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Parse failed: {exc}") from exc


@router.post("/download", response_model=APIResponse)
def create_download(payload: DownloadRequest) -> APIResponse:
    task = task_store.create(str(payload.url), payload.format_id)
    executor.submit(_run_download, task.id, str(payload.url), payload.format_id)
    return APIResponse(message="task created", data=task.to_dict())


@router.post("/download/batch", response_model=APIResponse)
def create_batch_download(payload: BatchDownloadRequest) -> APIResponse:
    tasks = []
    for url in payload.urls:
        task = task_store.create(str(url), payload.format_id)
        executor.submit(_run_download, task.id, str(url), payload.format_id)
        tasks.append(task.to_dict())
    return APIResponse(message="batch tasks created", data=tasks)


@router.get("/tasks", response_model=APIResponse)
def list_tasks() -> APIResponse:
    return APIResponse(data=task_store.list_all())


@router.get("/tasks/{task_id}", response_model=APIResponse)
def get_task(task_id: str) -> APIResponse:
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    return APIResponse(data=task.to_dict())


@router.get("/file/{task_id}")
def get_file(task_id: str) -> FileResponse:
    task = task_store.get(task_id)
    if not task or task.status != "completed" or not task.file_path:
        raise HTTPException(status_code=404, detail="File not ready")
    path = Path(task.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Downloaded file missing")
    return FileResponse(path=path, filename=path.name, media_type="application/octet-stream")


@router.get("/thumbnail")
def get_thumbnail(url: str = Query(..., description="Original remote thumbnail URL")) -> Response:
    if not (url.startswith("http://") or url.startswith("https://")):
        raise HTTPException(status_code=400, detail="Invalid thumbnail url")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
    }
    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers) as client:
            resp = client.get(url)
            resp.raise_for_status()
            content_type = resp.headers.get("content-type", "image/jpeg")
            return Response(content=resp.content, media_type=content_type)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Thumbnail fetch failed: {exc}") from exc
