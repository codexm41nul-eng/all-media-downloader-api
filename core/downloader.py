# ============================================
# CORE MODULE - DOWNLOADER
# Primary media extraction engine using yt-dlp
# yt-dlp only - no third-party scraper fallback
# ============================================

import os
import tempfile
import yt_dlp
import requests
import re
import json
import base64
from urllib.parse import urlparse, parse_qs, unquote

from core.utils import format_size, format_duration, clean_caption
from config import PREFERRED_QUALITY


class DownloaderError(Exception):
    pass


def _get_size_via_head(video_url: str):
    try:
        resp = requests.head(video_url, timeout=8, allow_redirects=True)
        content_length = resp.headers.get("Content-Length")
        if content_length:
            return int(content_length)
    except Exception:
        pass
    return None


def _get_duration_from_url(video_url: str):
    try:
        parsed = urlparse(video_url)
        params = parse_qs(parsed.query)
        efg_values = params.get("efg")
        if not efg_values:
            return None

        efg_raw = unquote(efg_values[0])
        padded = efg_raw + "=" * (-len(efg_raw) % 4)
        decoded = base64.b64decode(padded)
        efg_data = json.loads(decoded)

        duration = efg_data.get("duration_s")
        if duration:
            return float(duration)
    except Exception:
        pass
    return None


def _format_string_for(platform: str) -> str:
    if platform == "tiktok":
        return "best[ext=mp4][vcodec!=none][acodec!=none]/best[ext=mp4]/best"
    if platform == "facebook":
        return (
            "best[ext=mp4][vcodec!=none][acodec!=none][height>=720]/"
            "best[ext=mp4][vcodec!=none][acodec!=none][height>=480]/"
            "best[ext=mp4][vcodec!=none][acodec!=none]/"
            "best[ext=mp4]/best"
        )
    if platform == "instagram":
        return "best[ext=mp4][vcodec!=none][acodec!=none]/best[ext=mp4]/best"
    return "best[ext=mp4][vcodec!=none][acodec!=none]/best[ext=mp4]/best"


def _build_result(info: dict, platform: str, video_url: str = None) -> dict:
    video_url = video_url or info.get("url")

    formats = info.get("formats") or []
    best_format = formats[-1] if formats else None
    if not video_url and best_format:
        video_url = best_format.get("url")

    caption_source = info.get("description") or info.get("title") or ""

    size_bytes = info.get("filesize") or info.get("filesize_approx")
    if not size_bytes and best_format:
        size_bytes = best_format.get("filesize") or best_format.get("filesize_approx")
    if not size_bytes and formats:
        for fmt in reversed(formats):
            candidate = fmt.get("filesize") or fmt.get("filesize_approx")
            if candidate:
                size_bytes = candidate
                break
    if not size_bytes and video_url:
        size_bytes = _get_size_via_head(video_url)

    duration_seconds = info.get("duration")
    if not duration_seconds and best_format:
        duration_seconds = best_format.get("duration")
    if not duration_seconds:
        requested = info.get("requested_downloads")
        if requested and isinstance(requested, list):
            duration_seconds = requested[0].get("duration")
    if not duration_seconds and video_url:
        duration_seconds = _get_duration_from_url(video_url)

    return {
        "platform": platform,
        "caption": clean_caption(caption_source),
        "format": info.get("ext", "mp4"),
        "size": format_size(size_bytes),
        "duration": format_duration(duration_seconds),
        "video_url": video_url,
        "thumbnail_url": info.get("thumbnail"),
        "quality": info.get("format_note") or PREFERRED_QUALITY,
    }


def extract_with_ytdlp(url: str, platform: str) -> dict:
    ydl_options = {
        "quiet": True,
        "no_warnings": True,
        "format": _format_string_for(platform),
        "noplaylist": True,
        "playlist_items": "1",
        "extract_flat": False,
        "skip_download": True,
        "socket_timeout": 30,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as error:
        raise DownloaderError(str(error))

    if not info:
        raise DownloaderError("No data returned from extractor")

    result = _build_result(info, platform)
    if not result["video_url"]:
        raise DownloaderError("Could not resolve direct video url")

    return result


def download_with_ytdlp(url: str, platform: str) -> tuple:
    """
    Resolves metadata AND downloads the media file to a local temp path in
    a single yt-dlp pass, instead of just resolving a CDN url.

    This mirrors how the project's Node.js bot handles TikTok (yt-dlp
    resolves AND downloads in the same process) — that approach works
    reliably, while handing the resolved signed CDN url to a *different*
    process/server (as this API's proxy-video endpoint originally did)
    gets rejected by TikTok's CDN. Downloading here, on the same server
    that resolved the url, sidesteps that entirely.

    Returns (file_path, result_dict). Caller is responsible for deleting
    file_path once it's done streaming it.
    """
    tmp_dir = tempfile.mkdtemp(prefix="amd_")
    output_template = os.path.join(tmp_dir, "%(id)s.%(ext)s")

    ydl_options = {
        "quiet": True,
        "no_warnings": True,
        "format": _format_string_for(platform),
        "noplaylist": True,
        "playlist_items": "1",
        "outtmpl": output_template,
        "socket_timeout": 30,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_options) as ydl:
            info = ydl.extract_info(url, download=True)
            file_path = ydl.prepare_filename(info)
    except Exception as error:
        raise DownloaderError(str(error))

    if not info or not file_path or not os.path.exists(file_path):
        raise DownloaderError("yt-dlp did not produce a downloaded file")

    # The actual local file is the source of truth for size — more accurate
    # than any filesize/filesize_approx metadata yt-dlp may have guessed.
    result = _build_result(info, platform, video_url=info.get("webpage_url") or url)
    result["size"] = format_size(os.path.getsize(file_path))

    return file_path, result
