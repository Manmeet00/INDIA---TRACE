"""Pictures and videos from a report's own source, shown in the evidence desk.

Two kinds, both from the source itself and never generated:
- Embeds: YouTube videos, Instagram posts and reels, and Facebook posts and videos, shown with each site's
  official embed player. Worked out from the source URL alone; the dashboard loads them only on request.
- Preview images: the picture a news page publishes for link previews (og:image or twitter:image), read from
  the page's header the way chat apps build link previews. A preview image can be a file or stock photo, so
  the dashboard labels it as the source's picture, not as proof of the incident.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
import ipaddress
import re
import socket
import sqlite3
import ssl
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, HTTPSHandler

import certifi

from .config import get_settings

SOCIAL_HOSTS = {"facebook.com", "instagram.com", "youtube.com", "youtu.be", "x.com", "twitter.com"}
BROWSER_AGENT = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
MAX_HEAD_BYTES = 256 * 1024
TIMEOUT_S = 8
WORKERS = 6
MAX_PER_RUN = 40
# Site-wide pictures that say nothing about a report.
GENERIC_IMAGE = re.compile(r"logo|favicon|placeholder|default[-_.]|sprite|blank\.|/icons?/", re.IGNORECASE)


def _host(url: str) -> str:
    host = (urlsplit(url).hostname or "").lower()
    for prefix in ("www.", "m.", "mobile.", "web."):
        host = host.removeprefix(prefix)
    return host


def embed_for(url: str | None) -> dict[str, str] | None:
    """The official embed player for a YouTube, Instagram or Facebook source URL, or None."""
    if not url:
        return None
    parts = urlsplit(url)
    host = _host(url)
    segments = [segment for segment in parts.path.split("/") if segment]
    if host in ("youtube.com", "youtu.be"):
        video = (segments[0] if host == "youtu.be" and segments else
                 parse_qs(parts.query).get("v", [None])[0] if segments[:1] == ["watch"] else
                 segments[1] if len(segments) > 1 and segments[0] in ("shorts", "embed", "live") else None)
        if video and re.fullmatch(r"[A-Za-z0-9_-]{6,20}", video):
            return {"kind": "youtube", "embed_url": f"https://www.youtube-nocookie.com/embed/{video}", "site": "YouTube"}
    if host == "instagram.com":
        for index, segment in enumerate(segments[:-1]):
            code = segments[index + 1]
            if segment in ("p", "reel", "tv") and re.fullmatch(r"[A-Za-z0-9_-]{5,40}", code):
                return {"kind": "instagram", "embed_url": f"https://www.instagram.com/{segment}/{code}/embed/", "site": "Instagram"}
    if host == "facebook.com" and len(segments) >= 2:
        canonical = f"https://www.facebook.com{parts.path}"
        video = any(segment in ("videos", "reel", "reels", "watch") for segment in segments)
        # A video plays in a video-shaped frame without the post text (the evidence desk shows the text already).
        plugin, text = ("video.php", "false") if video else ("post.php", "true")
        return {"kind": "facebook", "format": "video" if video else "post", "site": "Facebook",
                "embed_url": f"https://www.facebook.com/plugins/{plugin}?href={quote(canonical, safe='')}&show_text={text}&width=500"}
    return None


class _PreviewImage(HTMLParser):
    """Collects og:image / twitter:image from the page head and stops at <body>."""

    def __init__(self) -> None:
        super().__init__()
        self.found: dict[str, str] = {}
        self.done = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "body":
            self.done = True
        if self.done or tag != "meta":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        name = (values.get("property") or values.get("name") or "").lower()
        if name in ("og:image", "og:image:secure_url", "twitter:image", "twitter:image:src") and values.get("content"):
            self.found.setdefault(name, values["content"].strip())


def _public_host(host: str | None) -> bool:
    """Only public internet hosts: never localhost, private, link-local or reserved addresses."""
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return False
    try:
        addresses = {info[4][0] for info in socket.getaddrinfo(host, None)}
    except OSError:
        return False
    return all(ipaddress.ip_address(address.split("%")[0]).is_global for address in addresses)


class _SafeRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802 (urllib's name)
        parts = urlsplit(newurl)
        if parts.scheme not in ("http", "https") or not _public_host(parts.hostname):
            raise URLError(f"redirect to a non-public address refused: {newurl}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def preview_image(url: str) -> str | None:
    """The page's own link-preview picture, from its header only (at most 256 KB read), or None."""
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or _host(url) in SOCIAL_HOSTS or not _public_host(parts.hostname):
        return None
    opener = build_opener(_SafeRedirects(), HTTPSHandler(context=ssl.create_default_context(cafile=certifi.where())))
    request = Request(url, headers={"User-Agent": get_settings().geocoder_user_agent, "Accept": "text/html"})
    try:
        with opener.open(request, timeout=TIMEOUT_S) as response:
            if "html" not in (response.headers.get("Content-Type") or ""):
                return None
            head = response.read(MAX_HEAD_BYTES).decode(response.headers.get_content_charset() or "utf-8", "replace")
    except (HTTPError, URLError, OSError, ValueError):
        return None
    parser = _PreviewImage()
    try:
        parser.feed(head)
    except Exception:  # malformed markup: use whatever was found before it
        pass
    for key in ("og:image:secure_url", "og:image", "twitter:image", "twitter:image:src"):
        image = parser.found.get(key)
        if image:
            image = urljoin(url, image)
            if urlsplit(image).scheme in ("http", "https") and not GENERIC_IMAGE.search(image) and _loads(opener, image):
                return image[:1000]
    return None


def _loads(opener, image: str) -> bool:
    """Whether the picture can actually be shown: some publishers refuse it to other sites (HTTP 403)."""
    if not _public_host(urlsplit(image).hostname):
        return False
    # Asked the way the dashboard's viewers ask (a browser, no referrer), so the answer matches what they will see.
    request = Request(image, headers={"User-Agent": BROWSER_AGENT, "Range": "bytes=0-2047", "Accept": "image/avif,image/webp,image/*"})
    try:
        with opener.open(request, timeout=TIMEOUT_S) as response:
            return (response.headers.get("Content-Type") or "").startswith("image/")
    except (HTTPError, URLError, OSError, ValueError):
        return False


def media_for(item: dict[str, Any]) -> dict[str, str] | None:
    """What the evidence desk can show for a report: an embed player, or the page's preview image."""
    embed = embed_for(item.get("source_url"))
    if embed:
        return embed
    if item.get("page_image"):
        return {"kind": "image", "url": item["page_image"], "site": _host(item["source_url"])}
    return None


def collect_preview_images(connection: sqlite3.Connection, incident_ids: list[str] | None = None) -> dict[str, int]:
    """Read preview images for news and web reports that have not been checked yet (several pages at a time)."""
    query = "SELECT id, source_url FROM incidents WHERE page_image_checked_at IS NULL"
    rows = connection.execute(query).fetchall()
    if incident_ids is not None:
        wanted = set(incident_ids)
        rows = [row for row in rows if row["id"] in wanted]
    rows = [row for row in rows if _host(row["source_url"]) not in SOCIAL_HOSTS][:MAX_PER_RUN]
    connection.commit()  # no write transaction stays open while pages are read
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        images = list(pool.map(lambda row: preview_image(row["source_url"]), rows))
    now = datetime.now(timezone.utc).isoformat()
    for row, image in zip(rows, images):
        connection.execute("UPDATE incidents SET page_image = ?, page_image_checked_at = ? WHERE id = ?", (image, now, row["id"]))
    connection.commit()
    return {"checked": len(rows), "found": sum(image is not None for image in images)}
