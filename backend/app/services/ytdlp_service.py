from pathlib import Path
from typing import Callable, Any
import re
import os
import time
import uuid

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

    def _extract_vqq_vid(self, url: str) -> str | None:
        match = re.search(r"/([a-zA-Z0-9]+)\.html", url)
        return match.group(1) if match else None

    def _build_vqq_stub(self, url: str) -> dict[str, Any]:
        vid = self._extract_vqq_vid(url) or "unknown"
        return {
            "title": f"Tencent Video ({vid})",
            "duration": None,
            "thumbnail": None,
            "uploader": "Tencent Video",
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

    def _is_geo_restriction_error(self, exc: Exception) -> bool:
        msg = str(exc).lower()
        return "geo restriction" in msg or "not available from your location" in msg

    def _extract_douyin_video_id(self, url: str) -> str | None:
        match = re.search(r"douyin\.com/video/(\d+)", url)
        if match:
            return match.group(1)
        match = re.search(r"modal_id=(\d+)", url)
        if match:
            return match.group(1)
        return None

    def _build_douyin_guest_cookie_header(self, url: str) -> str:
        """
        Try obtaining temporary guest cookies from Douyin pages.
        This does NOT require user login and only uses server-side ephemeral session data.
        """
        video_id = self._extract_douyin_video_id(url)
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.douyin.com/",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        }
        proxy = self._get_proxy()
        with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers, proxy=proxy) as client:
            # Warm up anti-bot/session cookies from homepage + target page.
            client.get("https://www.douyin.com/")
            if video_id:
                client.get(f"https://www.douyin.com/video/{video_id}")

            # Build cookie header from current cookie jar.
            cookie_pairs: list[str] = []
            for cookie in client.cookies.jar:
                if cookie.name and cookie.value:
                    cookie_pairs.append(f"{cookie.name}={cookie.value}")

        # Ensure s_v_web_id exists for yt-dlp check path.
        if not any(pair.startswith("s_v_web_id=") for pair in cookie_pairs):
            cookie_pairs.append(f"s_v_web_id=verify_{uuid.uuid4().hex}")
        return "; ".join(cookie_pairs)

    def _decode_unicode_slash(self, value: str) -> str:
        return value.replace("\\u002F", "/").replace("\\/", "/")

    def _resolve_douyin_url(self, url: str) -> str:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            ),
            "Referer": "https://www.iesdouyin.com/",
        }
        proxy = self._get_proxy()
        with httpx.Client(timeout=12.0, follow_redirects=True, headers=headers, proxy=proxy) as client:
            resp = client.get(url)
            return str(resp.url)

    def _extract_douyin_share_payload(self, url: str) -> dict[str, Any]:
        # Prefer extracting from input URL first (jingxuan modal_id works here),
        # then fallback to the fully resolved URL.
        video_id = self._extract_douyin_video_id(url)
        resolved_url = self._resolve_douyin_url(url)
        if not video_id:
            video_id = self._extract_douyin_video_id(resolved_url)
        if not video_id:
            raise DownloadError("Unable to extract Douyin video id from share URL")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            ),
            "Referer": "https://www.iesdouyin.com/",
        }
        proxy = self._get_proxy()
        with httpx.Client(timeout=20.0, follow_redirects=True, headers=headers, proxy=proxy) as client:
            html = client.get(f"https://www.iesdouyin.com/share/video/{video_id}/").text

        uri_match = re.search(r'"play_addr":\{"uri":"([^"]+)"', html)
        playwm_match = re.search(r'"url_list":\["(https:\\u002F\\u002Faweme\\.snssdk\\.com\\u002Faweme\\u002Fv1\\u002Fplaywm[^"]+)"\]', html)
        title_match = re.search(r'"desc":"([^"]*)"', html)
        cover_match = re.search(r'"cover":\{"uri":"[^"]+","url_list":\["([^"]+)"', html)

        if not uri_match and not playwm_match:
            raise DownloadError("Douyin share page parsing failed: play address not found")

        playwm_url = self._decode_unicode_slash(playwm_match.group(1)) if playwm_match else ""
        if playwm_url:
            play_url = playwm_url.replace("/playwm/", "/play/")
        else:
            uri = uri_match.group(1)
            play_url = (
                "https://aweme.snssdk.com/aweme/v1/play/"
                f"?video_id={uri}&line=0&ratio=720p&is_play_url=1&source=PackSourceEnum_DOUYIN_REFLOW"
            )

        title = "Douyin Video"
        if title_match:
            title = self._decode_unicode_slash(title_match.group(1))

        thumbnail = self._decode_unicode_slash(cover_match.group(1)) if cover_match else None

        return {
            "title": title.strip() or f"Douyin Video ({video_id})",
            "duration": None,
            "thumbnail": thumbnail,
            "uploader": "Douyin",
            "webpage_url": resolved_url,
            "video_id": video_id,
            "play_url": play_url,
            "formats": [
                {
                    "format_id": "douyin-no-watermark",
                    "ext": "mp4",
                    "resolution": "best",
                    "filesize": None,
                    "vcodec": "h264",
                    "acodec": "aac",
                }
            ],
        }

    def _download_douyin_via_share(
        self,
        task_id: str,
        url: str,
        on_progress: Callable[[str, float, dict[str, Any]], None],
        should_cancel: Callable[[], bool] | None = None,
    ) -> Path:
        info = self._extract_douyin_share_payload(url)
        play_url = info["play_url"]
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
            ),
            "Referer": "https://www.iesdouyin.com/",
        }
        proxy = self._get_proxy()
        safe_title = _sanitize_name(info["title"])
        # Keep filename short enough for container/filesystem path limits.
        output = DOWNLOAD_DIR / f"{safe_title[:48]}-{task_id}.mp4"
        with httpx.Client(timeout=30.0, follow_redirects=True, headers=headers, proxy=proxy) as client:
            with client.stream("GET", play_url) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("content-length") or 0)
                downloaded = 0
                with output.open("wb") as fp:
                    for chunk in resp.iter_bytes(chunk_size=1024 * 256):
                        if should_cancel and should_cancel():
                            raise DownloadError("Task cancelled by user.")
                        if not chunk:
                            continue
                        fp.write(chunk)
                        downloaded += len(chunk)
                        if total > 0:
                            on_progress(task_id, min(99.0, downloaded * 100 / total), {"status": "downloading"})
        on_progress(task_id, 100.0, {"status": "finished"})
        return output

    def resolve_browser_download(self, url: str, format_id: str | None = None) -> dict[str, Any]:
        """
        Resolve a direct media URL for browser-native download flow.
        Current stable path is optimized for Douyin dedicated parser.
        """
        normalized = self._normalize_url(url)
        lower_url = normalized.lower()
        if "douyin.com/" in lower_url or "iesdouyin.com/" in lower_url or "v.douyin.com/" in lower_url:
            last_exc: Exception | None = None
            info: dict[str, Any] | None = None
            for attempt in range(3):
                try:
                    info = self._extract_douyin_share_payload(normalized)
                    break
                except Exception as exc:
                    last_exc = exc
                    time.sleep(0.7 + 0.6 * attempt)
            if info is None:
                raise DownloadError(f"Douyin direct resolve failed after retries: {last_exc}")
            return {
                "media_url": info["play_url"],
                "title": info.get("title") or "douyin-video",
                "ext": "mp4",
                "headers": {
                    "User-Agent": (
                        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) "
                        "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
                    ),
                    "Referer": "https://www.iesdouyin.com/",
                },
            }

        raise DownloadError(
            "Direct browser download is currently enabled for Douyin links only. "
            "For other platforms, please use background task download flow."
        )

    def _parse_douyin_with_guest_challenge(self, url: str) -> dict[str, Any]:
        guest_cookie = self._build_douyin_guest_cookie_header(url)
        challenge_options = self._base_options()
        challenge_options["skip_download"] = True
        challenge_options["http_headers"] = {
            **challenge_options.get("http_headers", {}),
            "Referer": "https://www.douyin.com/",
            "Cookie": guest_cookie,
        }
        with yt_dlp.YoutubeDL(challenge_options) as ydl:
            return ydl.extract_info(url, download=False)

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
        should_cancel: Callable[[], bool] | None = None,
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
                                if should_cancel and should_cancel():
                                    raise DownloadError("Task cancelled by user.")
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
        if "douyin.com/" in url.lower() or "iesdouyin.com/" in url.lower() or "v.douyin.com/" in url.lower():
            try:
                return self._extract_douyin_share_payload(url)
            except Exception:
                # Keep existing yt-dlp fallback chain as backup path.
                pass
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
                # Retry once with server-side temporary guest challenge cookies.
                try:
                    time.sleep(1.0)
                    info = self._parse_douyin_with_guest_challenge(url)
                except Exception as guest_exc:
                    raise DownloadError(
                        "Douyin anti-bot challenge detected. Backend has auto-started guest verification "
                        "(temporary server cookie, no user login required). Please retry this link in 3-8 seconds."
                    ) from guest_exc
            elif "v.qq.com/" in url.lower() and self._is_geo_restriction_error(exc):
                # Allow frontend workflow to continue with visible metadata, instead of hard parse failure.
                info = self._build_vqq_stub(url)
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
        should_cancel: Callable[[], bool] | None = None,
    ) -> Path:
        url = self._normalize_url(url)
        if "douyin.com/" in url.lower() or "iesdouyin.com/" in url.lower() or "v.douyin.com/" in url.lower():
            last_exc: Exception | None = None
            for attempt in range(3):
                try:
                    return self._download_douyin_via_share(task_id, url, on_progress, should_cancel)
                except Exception as exc:
                    last_exc = exc
                    time.sleep(0.8 + attempt * 0.7)
            raise DownloadError(
                "Douyin dedicated downloader failed after retries. "
                f"Last error: {last_exc}"
            )
        def hook(data: dict[str, Any]) -> None:
            if should_cancel and should_cancel():
                raise DownloadError("Task cancelled by user.")
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
            recovered = False
            if "v.qq.com/" in url.lower() and self._is_geo_restriction_error(exc):
                tencent_proxy = os.getenv("YTDLP_VQQ_PROXY", "").strip()
                if tencent_proxy:
                    retry_options = {**options, "proxy": tencent_proxy, "geo_verification_proxy": tencent_proxy}
                    with yt_dlp.YoutubeDL(retry_options) as ydl:
                        info = ydl.extract_info(url, download=True)
                        file_path = ydl.prepare_filename(info)
                    recovered = True
                else:
                    raise DownloadError(
                        "Tencent Video is geo-restricted in current network route. "
                        "Please set a Mainland-China route in YTDLP_VQQ_PROXY (or YTDLP_PROXY) and retry."
                    ) from exc
            if "bilibili.com/video" in url.lower():
                try:
                    return self._download_bilibili_via_api(task_id, url, on_progress, should_cancel)
                except Exception as api_exc:
                    raise DownloadError(
                        "Bilibili download via yt-dlp failed, and backend proxy fallback also failed. "
                        f"Fallback error: {api_exc}. "
                        "This usually means either (1) Bilibili requires logged-in cookies, or "
                        "(2) current server network cannot reach Bilibili HTTPS endpoint."
                    ) from exc
            if not recovered:
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
