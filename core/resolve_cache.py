# ============================================
# CORE MODULE - RESOLVE CACHE
# Short-lived in-memory cache mapping a token -> (video_url, headers)
#
# Why this exists: yt-dlp resolves not just a video_url for TikTok but also
# the exact request headers (session/signature specific) that TikTok's CDN
# expects for that url. Those headers can't be reconstructed generically,
# and there's no way to hand them back through a single "video_url" string
# to a separate caller (the Telegram bot). So instead of returning the raw
# video_url + headers, we cache them here under a short opaque token and
# return the token; the proxy-video endpoint then looks the token up to get
# the exact url+headers yt-dlp resolved, right when it's needed.
#
# In-memory and single-process only — fine for a single Render free-tier
# instance. Entries expire quickly since TikTok's signed urls are
# short-lived anyway.
# ============================================

import time
import uuid
import threading

_TTL_SECONDS = 5 * 60  # tokens are useless well before this anyway
_lock = threading.Lock()
_store = {}


def put(video_url: str, headers: dict) -> str:
    token = uuid.uuid4().hex
    with _lock:
        _store[token] = {
            "video_url": video_url,
            "headers": headers or {},
            "expires_at": time.time() + _TTL_SECONDS,
        }
        _prune_locked()
    return token


def get(token: str):
    with _lock:
        entry = _store.get(token)
        if not entry:
            return None
        if entry["expires_at"] < time.time():
            _store.pop(token, None)
            return None
        return entry["video_url"], entry["headers"]


def _prune_locked():
    now = time.time()
    expired = [key for key, value in _store.items() if value["expires_at"] < now]
    for key in expired:
        _store.pop(key, None)
