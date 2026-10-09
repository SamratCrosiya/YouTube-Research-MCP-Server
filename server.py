"""YouTube Research MCP Server - Level 1 (transcript + metadata).

Lets an AI assistant "open" a YouTube video by calling these tools:
  - get_video_info(url)
  - get_transcript(url, start_sec, end_sec, languages)
"""

import re
from urllib.parse import parse_qs, urlsplit

import yt_dlp
from mcp.server.fastmcp import FastMCP
from youtube_transcript_api import YouTubeTranscriptApi

mcp = FastMCP("youtube-research")

_VIDEO_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{11}")
_YOUTUBE_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "music.youtube.com",
    "youtu.be",
    "www.youtu.be",
    "youtube-nocookie.com",
    "www.youtube-nocookie.com",
}


def extract_video_id(url_or_id: str) -> str:
    """Accept a full YouTube URL (any common form) or a bare 11-char video ID."""
    url_or_id = url_or_id.strip()
    if _VIDEO_ID_PATTERN.fullmatch(url_or_id):
        return url_or_id

    candidate = url_or_id if "://" in url_or_id else f"https://{url_or_id}"
    parsed = urlsplit(candidate)
    host = (parsed.hostname or "").lower().rstrip(".")
    if host not in _YOUTUBE_HOSTS:
        raise ValueError("Expected a YouTube URL or an 11-character video ID.")

    if host.endswith("youtu.be"):
        parts = parsed.path.strip("/").split("/")
        video_id = parts[0] if parts else ""
    elif parsed.path == "/watch":
        video_id = parse_qs(parsed.query).get("v", [""])[0]
    else:
        parts = parsed.path.strip("/").split("/")
        video_id = parts[1] if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live", "v"} else ""

    if not _VIDEO_ID_PATTERN.fullmatch(video_id):
        raise ValueError(f"Could not find a valid YouTube video ID in: {url_or_id!r}")
    return video_id


def fmt_time(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


@mcp.tool()
def get_video_info(url: str) -> dict:
    """Get metadata for a YouTube video: title, channel, duration, upload date,
    description, tags and chapters (if the creator added them).
    Call this first to learn what a video is about."""
    vid = extract_video_id(url)
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(f"https://www.youtube.com/watch?v={vid}", download=False)

    chapters = [
        {
            "start": fmt_time(c["start_time"]),
            "title": c["title"],
            "link": f"https://youtu.be/{vid}?t={int(c['start_time'])}",
        }
        for c in (info.get("chapters") or [])
    ]
    return {
        "video_id": vid,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "title": info.get("title"),
        "channel": info.get("uploader"),
        "duration": fmt_time(info.get("duration") or 0),
        "upload_date": info.get("upload_date"),
        "view_count": info.get("view_count"),
        "description": info.get("description"),
        "tags": info.get("tags"),
        "chapters": chapters,
    }


@mcp.tool()
def get_transcript(
    url: str,
    start_sec: int = 0,
    end_sec: int | None = None,
    languages: list[str] | None = None,
) -> str:
    """Get the timestamped transcript of a YouTube video.

    Each line looks like "[12:34] spoken text". Use start_sec / end_sec to fetch
    just one part of a long video. When citing a moment, build a link like
    https://youtu.be/<video_id>?t=<seconds>.

    Args:
        url: YouTube URL or video ID.
        start_sec: Only include lines at or after this second.
        end_sec: Only include lines before this second (default: whole video).
        languages: Preferred language codes in order, e.g. ["en", "hi"]. Default ["en"].
    """
    vid = extract_video_id(url)
    langs = languages or ["en"]
    try:
        snippets = YouTubeTranscriptApi().fetch(vid, languages=langs)
    except Exception as exc:  # no captions, disabled, blocked, private, etc.
        return (
            f"Could not fetch a transcript for video {vid}: {type(exc).__name__}: {exc}\n"
            "The video may have no captions, or YouTube may be blocking this network."
        )

    lines = []
    for sn in snippets:
        if sn.start < start_sec:
            continue
        if end_sec is not None and sn.start >= end_sec:
            break
        lines.append(f"[{fmt_time(sn.start)}] {sn.text.replace(chr(10), ' ')}")

    if not lines:
        return f"No transcript lines found between {start_sec}s and {end_sec}s."

    header = f"Transcript for https://www.youtube.com/watch?v={vid} (video_id={vid})\n"
    return header + "\n".join(lines)


if __name__ == "__main__":
    mcp.run()
