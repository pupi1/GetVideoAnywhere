from pathlib import Path
from typing import Callable, Any
import re
import os

import httpx
import yt_dlp
from yt_dlp.utils import DownloadError

from app.config import DOWNLOAD_DIR


def _sanitize_name(name: str) -> str:
    cleaned = re.sub(r"[^\w\-. ]+", "_", name).strip()
    return cleaned[:120] or "video"


class YtDlpService:
    def _normalize_url(self, url: str) -> str:
        # Douyin "jingxuan?modal_id=xxx" is not a direct video URL for yt-dlp.
        if "douyin.com/jingxuan" in url and "modal_id=" in url:
            match = re.search(r"modal_id=(\d+)", url)
            if match:
                return f"https://www.douyin.com/video/{match.group(1)}"
        return url

    def _get_proxy(self) -> str | None:
        return (
            os.getenv("YTDLP_PROXY")
            or os.getenv("HTTPS_PROXY")
            or os.getenv("HTTP_PROXY")
            or None
        )

    def _extract_bvid(self, url: str) -> str | None:
        match = re.search(r"(BV[0-9A-Za-z]+)", url)
        return match.group(1) if match else None

    def _parse_bilibili_via_api(self, url: str) -> dict[str, Any] | None:
        bvid = self._extract_bvid(url)
        if not bvid:
            return None
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://www.bilibili.com/video/{bvid}",
        }
        api_url = f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}"
        proxy = self._get_proxy()
        with httpx.Client(timeout=15.0, headers=headers, proxy=proxy) as client:
            response = client.get(api_url)
            response.raise_for_status()
            payload = response.json()
        data = payload.get("data") or {}
        if not data:
            return None
        return {
            "title": data.get("title"),
            "duration": data.get("duration"),
            "thumbnail": data.get("pic"),
            "uploader": (data.get("owner") or {}).get("name"),
            "webpage_url": f"https://www.bilibili.com/video/{bvid}",
            # fallback format to keep frontend flow available
            "formats": [
                {
                    "format_id": "best",
                    "ext": "mp4",
                    "resolution": "best",
                    "filesize": None,
                    "vcodec": "unknown",
                    "acodec": "unknown",
                }
            ],
        }

    def _download_bilibili_via_api(
        self,
        task_id: str,
        url: str,
        on_progress: Callable[[str, float, dict[str, Any]], None],
    ) -> Path:
        bvid = self._extract_bvid(url)
        if not bvid:
            raise DownloadError("Bilibili fallback failed: invalid BV id")

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": f"https://www.bilibili.com/video/{bvid}",
            "Origin": "https://www.bilibili.com",
        }

        proxy = self._get_proxy()
        with httpx.Client(timeout=25.0, follow_redirects=True, headers=headers, proxy=proxy) as client:
            view_resp = client.get(f"https://api.bilibili.com/x/web-interface/view?bvid={bvid}")
            view_resp.raise_for_status()
            view_data = view_resp.json().get("data") or {}
            cid = (view_data.get("pages") or [{}])[0].get("cid")
            if not cid:
                raise DownloadError("Bilibili fallback failed: cid not found")

            playurl = client.get(
                "https://api.bilibili.com/x/player/playurl",
                params={
                    "bvid": bvid,
                    "cid": cid,
                    "qn": 64,
                    "fnval": 0,
                    "fnver": 0,
                    "fourk": 0,
                },
            )
            playurl.raise_for_status()
            payload = playurl.json().get("data") or {}
            durls = payload.get("durl") or []
            if not durls:
                raise DownloadError("Bilibili fallback failed: no direct durl")

            media_url = durls[0].get("url")
            if not media_url:
                raise DownloadError("Bilibili fallback failed: empty media url")

            title = _sanitize_name(view_data.get("title", f"bilibili-{bvid}"))
            output = DOWNLOAD_DIR / f"{title}-{task_id}.mp4"
            max_resume_attempts = 6
            downloaded = 0
            total = 0
            output.parent.mkdir(parents=True, exist_ok=True)
            with output.open("wb") as fp:
                for _ in range(max_resume_attempts):
                    req_headers = {}
                    if downloaded > 0:
                        req_headers["Range"] = f"bytes={downloaded}-"
                    before_attempt = downloaded
                    try:
                        with client.stream("GET", media_url, headers=req_headers) as stream:
                            stream.raise_for_status()
                            content_length = int(stream.headers.get("content-length") or 0)
                            if total == 0:
                                content_range = stream.headers.get("content-range")
                                if content_range and "/" in content_range:
                                    total = int(content_range.split("/")[-1] or 0)
                                else:
                                    total = downloaded + content_length

                            for chunk in stream.iter_bytes(chunk_size=1024 * 256):
                                if not chunk:
                                    continue
                                fp.write(chunk)
                                downloaded += len(chunk)
                                if total > 0:
                                    on_progress(
                                        task_id,
                                        min(99.0, downloaded * 100 / total),
                                        {"status": "downloading"},
                                    )
                    except Exception:
                        # Connection can be closed by upstream; continue with Range resume.
                        if downloaded == before_attempt:
                            # If no bytes were received in this attempt, let next attempt retry.
                            continue

                    if total > 0 and downloaded >= total:
                        break

                if total > 0 and downloaded < total:
                    raise DownloadError(
                        f"Bilibili fallback interrupted before completion ({downloaded}/{total} bytes)"
                    )

            on_progress(task_id, 100.0, {"status": "finished"})
            return output

    def _base_options(self) -> dict[str, Any]:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.bilibili.com/",
            "Origin": "https://www.bilibili.com",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        cookie_header = os.getenv("YTDLP_COOKIE_HEADER", "").strip()
        if cookie_header:
            headers["Cookie"] = cookie_header

        options: dict[str, Any] = {
            "quiet": True,
            "noplaylist": True,
            "retries": 3,
            "extractor_retries": 3,
            "fragment_retries": 3,
            "socket_timeout": 20,
            "geo_bypass": True,
            "http_headers": headers,
        }
        cookie_file = os.getenv("YTDLP_COOKIES_FILE", "").strip()
        if cookie_file:
            options["cookiefile"] = cookie_file
        proxy = self._get_proxy()
        if proxy:
            options["proxy"] = proxy
        return options

    def _build_bilibili_stub(self, url: str) -> dict[str, Any]:
        bvid = self._extract_bvid(url) or "unknown"
        return {
            "title": f"Bilibili Video ({bvid})",
            "duration": None,
            "thumbnail": None,
            "uploader": "Unknown",
            "webpage_url": url,
            "formats": [
                {
                    "format_id": "best",
                    "ext": "mp4",
                    "resolution": "best",
                    "filesize": None,
                    "vcodec": "unknown",
                    "acodec": "unknown",
                }
            ],
        }

    def parse(self, url: str) -> dict[str, Any]:
        url = self._normalize_url(url)
        options = self._base_options()
        options["skip_download"] = True
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=False)
        except Exception as exc:
            # For Bilibili, anti-bot/network/TLS failures are common in server environments.
            # Always apply robust fallback chain to avoid hard parse failures.
            if "bilibili.com/video" in url.lower():
                fallback = dict(options)
                fallback["impersonate"] = "chrome"
                try:
                    with yt_dlp.YoutubeDL(fallback) as ydl:
                        info = ydl.extract_info(url, download=False)
                except Exception:
                    try:
                        api_fallback = self._parse_bilibili_via_api(url)
                    except Exception:
                        api_fallback = None
                    info = api_fallback or self._build_bilibili_stub(url)
            elif "douyin.com/" in url.lower() and "Fresh cookies" in str(exc):
                raise DownloadError(
                    "Douyin blocked anonymous metadata extraction for this link type. "
                    "Try a direct video URL format like https://www.douyin.com/video/{id} or app share short-link."
                ) from exc
            else:
                raise
        formats = []
        for fmt in info.get("formats", []):
            if not fmt.get("format_id"):
                continue
            formats.append(
                {
                    "format_id": fmt.get("format_id"),
                    "ext": fmt.get("ext"),
                    "resolution": fmt.get("resolution") or f"{fmt.get('height', 'audio')}p",
                    "filesize": fmt.get("filesize"),
                    "vcodec": fmt.get("vcodec"),
                    "acodec": fmt.get("acodec"),
                }
            )
        return {
            "title": info.get("title"),
            "duration": info.get("duration"),
            "thumbnail": info.get("thumbnail"),
            "uploader": info.get("uploader"),
            "webpage_url": info.get("webpage_url"),
            "formats": formats[:80],
        }

    def download(
        self,
        task_id: str,
        url: str,
        format_id: str | None,
        on_progress: Callable[[str, float, dict[str, Any]], None],
    ) -> Path:
        url = self._normalize_url(url)
        def hook(data: dict[str, Any]) -> None:
            status = data.get("status")
            if status == "downloading":
                downloaded = data.get("downloaded_bytes", 0) or 0
                total = data.get("total_bytes") or data.get("total_bytes_estimate") or 1
                progress = min(99.0, (downloaded / total) * 100)
                on_progress(task_id, progress, data)
            elif status == "finished":
                on_progress(task_id, 100.0, data)

        DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)
        outtmpl = str(DOWNLOAD_DIR / f"%(title).120s-{task_id}.%(ext)s")
        options: dict[str, Any] = self._base_options()
        options.update(
            {
                "outtmpl": outtmpl,
                "progress_hooks": [hook],
                "merge_output_format": "mp4",
            }
        )
        if format_id:
            options["format"] = format_id
        try:
            with yt_dlp.YoutubeDL(options) as ydl:
                info = ydl.extract_info(url, download=True)
                file_path = ydl.prepare_filename(info)
        except DownloadError as exc:
            if "bilibili.com/video" in url.lower():
                try:
                    return self._download_bilibili_via_api(task_id, url, on_progress)
                except Exception as api_exc:
                    raise DownloadError(
                        "Bilibili download via yt-dlp failed, and backend proxy fallback also failed. "
                        f"Fallback error: {api_exc}. "
                        "This usually means either (1) Bilibili requires logged-in cookies, or "
                        "(2) current server network cannot reach Bilibili HTTPS endpoint."
                    ) from exc
            raise
        final_path = Path(file_path)
        if final_path.exists():
            return final_path
        title = _sanitize_name(info.get("title", "video"))
        possible = list(DOWNLOAD_DIR.glob(f"{title}-{task_id}.*"))
        if possible:
            return possible[0]
        raise FileNotFoundError("Download succeeded but file path not found.")


ytdlp_service = YtDlpService()
