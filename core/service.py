# ============================================
# CORE MODULE - SERVICE
# Orchestrates extraction: yt-dlp only, no scraper fallback
# ============================================

from core.downloader import extract_with_ytdlp, DownloaderError
from core import resolve_cache


class ExtractionFailedError(Exception):
    pass


def resolve_media(url: str, platform: str) -> dict:
    try:
        result = extract_with_ytdlp(url, platform)
    except DownloaderError as error:
        raise ExtractionFailedError(str(error))

    resolved_headers = result.pop("_resolved_headers", None)

    if platform == "tiktok":
        # TikTok's CDN checks the exact headers yt-dlp resolved (not a
        # generic guess), so cache them under a token the proxy endpoint
        # can look up right when it actually fetches the file.
        result["proxy_token"] = resolve_cache.put(result["video_url"], resolved_headers)

    return result
