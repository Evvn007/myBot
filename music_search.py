"""
bot/music_search.py
-------------------
yt-dlp se YouTube search karo aur guaranteed .mp3 file download karo.
ffmpeg se audio extract + convert hota hai.
"""

import asyncio
import glob
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import List, Optional

import yt_dlp

from config import (
    DOWNLOAD_DIR,
    MAX_DURATION_SEC,
    SEARCH_RESULTS_COUNT,
    YDL_OUTPUT_TEMPLATE,
)
from queue_manager import Track
logger = logging.getLogger(__name__)

# Blocking calls ke liye thread pool (asyncio loop block na ho)
_executor = ThreadPoolExecutor(max_workers=3)


# ──────────────────────────────────────────────
#  yt-dlp Options
# ──────────────────────────────────────────────

def _search_opts(n: int) -> dict:
    """Sirf metadata fetch karo, download nahi."""
    return {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,       # download mat karo, sirf info lo
        "skip_download": True,
        "noplaylist": True,
    }


def _download_opts(video_id: str) -> dict:
    """
    MP3 download options.
    outtmpl me video_id use karein taaki file easily milti rahe.
    """
    output = str(DOWNLOAD_DIR / f"{video_id}.%(ext)s")
    return {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
        # Bestaudio format - ffmpeg mp3 me convert karega
        "format": "bestaudio/best",
        "outtmpl": output,
        "postprocessors": [
            {
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": "192",  # 192 kbps — achi quality
            }
        ],
        # Agar file pehle se download hai to skip karo
        "nooverwrites": True,
        # Bohot bade / restricted videos skip karo
        "match_filter": yt_dlp.utils.match_filter_func(
            f"duration <= {MAX_DURATION_SEC}"
        ),
        # Progress quiet rakho
        "progress_hooks": [],
    }


# ──────────────────────────────────────────────
#  Synchronous functions (thread pool me chalenge)
# ──────────────────────────────────────────────

def _sync_search(query: str, n: int) -> List[dict]:
    """
    YouTube pe search karo aur top N results ke metadata do.
    Yeh blocking hai isliye executor me chalega.
    """
    logger.debug("Searching: '%s' (n=%d)", query, n)
    with yt_dlp.YoutubeDL(_search_opts(n)) as ydl:
        try:
            # ytsearch5:query → YouTube pe 5 results
            result = ydl.extract_info(f"ytsearch{n}:{query}", download=False)
            entries = result.get("entries", []) if result else []
            # None entries filter karo
            return [e for e in entries if e and e.get("id")]
        except Exception as exc:
            logger.error("yt-dlp search error: %s", exc)
            return []


def _sync_download_mp3(url: str, video_id: str) -> Optional[str]:
    """
    Ek song download karo aur MP3 path return karo.

    Steps:
      1. yt-dlp se bestaudio download karo
      2. ffmpeg se .mp3 me convert karo
      3. Final .mp3 file ka path return karo
    """
    # Pehle check karo — already downloaded hai?
    cached = DOWNLOAD_DIR / f"{video_id}.mp3"
    if cached.exists() and cached.stat().st_size > 1000:
        logger.info("Cache hit: %s", cached)
        return str(cached)

    opts = _download_opts(video_id)
    logger.info("Downloading: %s (id=%s)", url, video_id)

    with yt_dlp.YoutubeDL(opts) as ydl:
        try:
            ydl.download([url])
        except yt_dlp.utils.DownloadError as exc:
            logger.warning("Download failed: %s", exc)
            return None
        except Exception as exc:
            logger.error("Unexpected download error: %s", exc)
            return None

    # ── MP3 file dhundo ──────────────────────────────────────────
    # Option 1: seedha expected path
    mp3_path = DOWNLOAD_DIR / f"{video_id}.mp3"
    if mp3_path.exists() and mp3_path.stat().st_size > 1000:
        logger.info("MP3 ready: %s (%.1f MB)", mp3_path, mp3_path.stat().st_size / 1e6)
        return str(mp3_path)

    # Option 2: glob se video_id wali koi bhi file dhundo
    pattern = str(DOWNLOAD_DIR / f"{video_id}.*")
    matches = glob.glob(pattern)
    for f in matches:
        if os.path.getsize(f) > 1000:
            logger.info("Found via glob: %s", f)
            return f

    # Option 3: downloads folder me latest file
    all_files = sorted(
        DOWNLOAD_DIR.glob("*.mp3"),
        key=lambda x: x.stat().st_mtime,
        reverse=True,
    )
    if all_files:
        latest = all_files[0]
        # Sirf last 60 seconds me bani file lo
        import time
        if time.time() - latest.stat().st_mtime < 60:
            logger.info("Using latest file: %s", latest)
            return str(latest)

    logger.warning("MP3 file nahi mili for id=%s", video_id)
    return None


# ──────────────────────────────────────────────
#  Public Async API
# ──────────────────────────────────────────────

async def search_tracks(query: str, n: int = SEARCH_RESULTS_COUNT) -> List[Track]:
    """
    YouTube pe query search karo, Track list return karo.
    Download nahi hoga — sirf metadata.
    """
    logger.info("Searching tracks: '%s'", query)
    loop = asyncio.get_event_loop()

    try:
        entries = await loop.run_in_executor(
            _executor, _sync_search, query, n
        )
    except Exception as exc:
        logger.error("Search executor error: %s", exc)
        return []

    tracks: List[Track] = []
    for entry in entries:
        duration = int(entry.get("duration") or 0)

        # Too long? Skip
        if duration and duration > MAX_DURATION_SEC:
            logger.debug("Skipping long video: %s (%ds)", entry.get("title"), duration)
            continue

        # URL build karo — watch URL ya direct
        vid_id = entry.get("id", "")
        url = entry.get("url") or entry.get("webpage_url") or ""
        if not url and vid_id:
            url = f"https://www.youtube.com/watch?v={vid_id}"

        if not url:
            continue

        track = Track(
            title=entry.get("title", "Unknown Song"),
            url=url,
            duration=duration,
            thumbnail=entry.get("thumbnail", ""),
        )
        tracks.append(track)

    logger.info("Found %d tracks for '%s'", len(tracks), query)
    return tracks


async def download_track(track: Track) -> Optional[str]:
    """
    Track download karo aur local .mp3 path return karo.
    Fails hone pe None return karo.
    """
    # YouTube video ID URL se nikalin
    video_id = _extract_video_id(track.url)
    if not video_id:
        logger.error("Video ID nahi mila: %s", track.url)
        return None

    logger.info("Downloading track: '%s' [%s]", track.title, video_id)
    loop = asyncio.get_event_loop()

    try:
        path = await loop.run_in_executor(
            _executor, _sync_download_mp3, track.url, video_id
        )
    except Exception as exc:
        logger.error("Download executor error: %s", exc)
        return None

    if not path:
        logger.warning("Download returned None for '%s'", track.title)
        return None

    size_mb = os.path.getsize(path) / 1e6
    logger.info("Downloaded: '%s' → %s (%.1f MB)", track.title, path, size_mb)
    return path


def cleanup_file(path: str) -> None:
    """Sent hone ke baad temp MP3 file delete karo."""
    if not path:
        return
    try:
        if os.path.exists(path):
            os.remove(path)
            logger.debug("Deleted: %s", path)
    except OSError as exc:
        logger.warning("Delete failed %s: %s", path, exc)


# ──────────────────────────────────────────────
#  Helper
# ──────────────────────────────────────────────

def _extract_video_id(url: str) -> Optional[str]:
    """
    YouTube URL se video ID nikalo.
    Supports:
      https://www.youtube.com/watch?v=XXXXXXXXXXX
      https://youtu.be/XXXXXXXXXXX
      ytsearch result URLs
    """
    import re

    # Standard watch URL
    m = re.search(r"[?&]v=([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)

    # Short URL youtu.be/ID
    m = re.search(r"youtu\.be/([A-Za-z0-9_-]{11})", url)
    if m:
        return m.group(1)

    # Baaki URLs me last segment try karo
    m = re.search(r"/([A-Za-z0-9_-]{11})(?:[?&/]|$)", url)
    if m:
        return m.group(1)

    # Kuch nahi mila — URL hi ID manlo (yt-dlp handle karega)
    # Random safe ID banao taaki file naming kaam kare
    import hashlib
    return hashlib.md5(url.encode()).hexdigest()[:11]




