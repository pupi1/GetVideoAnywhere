from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Lock
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, Response, StreamingResponse

from app.config import MAX_CONCURRENT_TASKS
from app.models.schemas import APIResponse, BatchDownloadRequest, DownloadRequest, ParseRequest
from app.services.task_store import task_store
from app.services.ytdlp_service import ytdlp_service


router = APIRouter(prefix="", tags=["download"])
executor = ThreadPoolExecutor(max_workers=MAX_CONCURRENT_TASKS)
_task_futures: dict[str, object] = {}
_task_futures_lock = Lock()


def _run_download(task_id: str, url: str, format_id: str | None) -> None:
    if task_store.is_cancel_requested(task_id):
        task_store.update(task_id, status="cancelled", error="Task cancelled by user.")
        with _task_futures_lock:
            _task_futures.pop(task_id, None)
        return

    def should_cancel() -> bool:
        return task_store.is_cancel_requested(task_id)

    def progress_hook(_task_id: str, progress: float, data: dict) -> None:
        if should_cancel():
            raise RuntimeError("Task cancelled by user.")
        task_store.update(_task_id, status="downloading", progress=progress, title=data.get("filename"))

    try:
        task_store.update(task_id, status="downloading", progress=0)
        file_path = ytdlp_service.download(task_id, url, format_id, progress_hook, should_cancel)
        if should_cancel():
            task_store.update(task_id, status="cancelled", error="Task cancelled by user.")
            return
        task_store.update(task_id, status="completed", progress=100, file_path=str(file_path))
    except Exception as exc:
        if should_cancel() or "cancelled by user" in str(exc).lower():
            task_store.update(task_id, status="cancelled", error="Task cancelled by user.")
        else:
            task_store.update(task_id, status="failed", error=str(exc))
    finally:
        with _task_futures_lock:
            _task_futures.pop(task_id, None)


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
    future = executor.submit(_run_download, task.id, str(payload.url), payload.format_id)
    with _task_futures_lock:
        _task_futures[task.id] = future
    return APIResponse(message="task created", data=task.to_dict())


@router.post("/download/batch", response_model=APIResponse)
def create_batch_download(payload: BatchDownloadRequest) -> APIResponse:
    tasks = []
    for url in payload.urls:
        task = task_store.create(str(url), payload.format_id)
        future = executor.submit(_run_download, task.id, str(url), payload.format_id)
        with _task_futures_lock:
            _task_futures[task.id] = future
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


@router.post("/tasks/{task_id}/cancel", response_model=APIResponse)
def cancel_task(task_id: str) -> APIResponse:
    task = task_store.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status in {"completed", "failed", "cancelled"}:
        return APIResponse(message=f"task already {task.status}", data=task.to_dict())

    task = task_store.request_cancel(task_id)
    with _task_futures_lock:
        future = _task_futures.get(task_id)
    if future and hasattr(future, "cancel"):
        future.cancel()
    return APIResponse(message="task cancelled", data=task.to_dict() if task else None)


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


@router.get("/browser-download")
def browser_download(
    url: str = Query(..., description="Original video URL"),
    format_id: str | None = Query(None, description="Optional format_id"),
) -> StreamingResponse:
    try:
        resolved = ytdlp_service.resolve_browser_download(url, format_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Browser download resolve failed: {exc}") from exc

    media_url = resolved.get("media_url")
    if not media_url:
        raise HTTPException(status_code=400, detail="Browser download resolve failed: empty media URL")

    headers = resolved.get("headers") or {}
    proxy = ytdlp_service._get_proxy()  # noqa: SLF001 - same service boundary
    filename = f"{Path((resolved.get('title') or 'video')).stem}.{resolved.get('ext') or 'mp4'}"
    safe_filename = quote(filename, safe="")

    def stream_bytes():
        timeout = httpx.Timeout(connect=20.0, read=None, write=60.0, pool=60.0)
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers, proxy=proxy) as client:
            with client.stream("GET", media_url) as upstream:
                upstream.raise_for_status()
                for chunk in upstream.iter_bytes(chunk_size=1024 * 256):
                    if chunk:
                        yield chunk

    response_headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        "Cache-Control": "no-store",
    }
    return StreamingResponse(stream_bytes(), media_type="application/octet-stream", headers=response_headers)


@router.get("/browser-download-direct")
def browser_download_direct(
    media_url: str = Query(..., description="Direct media URL resolved from parse result"),
    title: str = Query("video", description="Suggested filename title"),
    ext: str = Query("mp4", description="File extension"),
) -> StreamingResponse:
    if not media_url.startswith("https://aweme.snssdk.com/aweme/v1/play/"):
        raise HTTPException(status_code=400, detail="Invalid direct media URL")

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
            "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
        ),
        "Referer": "https://www.iesdouyin.com/",
    }
    proxy = ytdlp_service._get_proxy()  # noqa: SLF001 - same service boundary
    filename = f"{Path((title or 'video')).stem}.{ext or 'mp4'}"
    safe_filename = quote(filename, safe="")

    def stream_bytes():
        timeout = httpx.Timeout(connect=20.0, read=None, write=60.0, pool=60.0)
        with httpx.Client(timeout=timeout, follow_redirects=True, headers=headers, proxy=proxy) as client:
            with client.stream("GET", media_url) as upstream:
                upstream.raise_for_status()
                for chunk in upstream.iter_bytes(chunk_size=1024 * 256):
                    if chunk:
                        yield chunk

    response_headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{safe_filename}",
        "Cache-Control": "no-store",
    }
    return StreamingResponse(stream_bytes(), media_type="application/octet-stream", headers=response_headers)
