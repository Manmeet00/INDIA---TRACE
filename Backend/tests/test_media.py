"""The source's own pictures and videos in the evidence desk (app/media.py)."""
from urllib.error import URLError

import pytest

import app.media as media
from conftest import SEARCH



@pytest.mark.parametrize("url, kind, embed", [
    ("https://www.youtube.com/watch?v=bh1TVzezZWs", "youtube", "https://www.youtube-nocookie.com/embed/bh1TVzezZWs"),
    ("https://youtu.be/bh1TVzezZWs", "youtube", "https://www.youtube-nocookie.com/embed/bh1TVzezZWs"),
    ("https://www.youtube.com/shorts/bh1TVzezZWs", "youtube", "https://www.youtube-nocookie.com/embed/bh1TVzezZWs"),
    ("https://www.instagram.com/reel/DPx1Ab2Cd3E", "instagram", "https://www.instagram.com/reel/DPx1Ab2Cd3E/embed/"),
    ("https://www.instagram.com/p/DPx1Ab2Cd3E/", "instagram", "https://www.instagram.com/p/DPx1Ab2Cd3E/embed/"),
    ("https://www.instagram.com/somebody/reel/DPx1Ab2Cd3E", "instagram", "https://www.instagram.com/reel/DPx1Ab2Cd3E/embed/"),
    ("https://www.facebook.com/NortheastToday/posts/12345",
     "facebook", "https://www.facebook.com/plugins/post.php?href=https%3A%2F%2Fwww.facebook.com%2FNortheastToday%2Fposts%2F12345&show_text=true&width=500"),
    ("https://m.facebook.com/page/videos/98765",
     "facebook", "https://www.facebook.com/plugins/video.php?href=https%3A%2F%2Fwww.facebook.com%2Fpage%2Fvideos%2F98765&show_text=false&width=500"),
])
def test_embeds_from_source_urls(url, kind, embed):
    expected = {"kind": kind, "embed_url": embed, "site": {"youtube": "YouTube", "instagram": "Instagram", "facebook": "Facebook"}[kind]}
    if kind == "facebook":  # a Facebook video plays in a video-shaped frame, without the post text
        expected["format"] = "video" if "video.php" in embed else "post"
    assert media.embed_for(url) == expected


@pytest.mark.parametrize("url", ["https://www.youtube.com/", "https://www.instagram.com/", "https://www.facebook.com/page",
                                 "https://www.youtube.com/watch?v=<script>", "https://example.org/story", None])
def test_no_embed_without_a_specific_post_or_video(url):
    assert media.embed_for(url) is None


class Page:
    def __init__(self, body, content_type="text/html; charset=utf-8"):
        self.body, self.headers = body.encode(), _Headers(content_type)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self, limit):
        return self.body[:limit]


class _Headers:
    def __init__(self, content_type):
        self.content_type = content_type

    def get(self, name, default=None):
        return self.content_type if name == "Content-Type" else default

    def get_content_charset(self):
        return self.content_type.split("charset=")[1] if "charset=" in self.content_type else "utf-8"


@pytest.fixture
def pages(monkeypatch):
    """Real preview_image with fake pages and DNS: maps URL to HTML (or an exception)."""
    answers = {}
    monkeypatch.setattr(media, "_public_host", lambda host: host not in ("localhost", "10.0.0.5"))

    class Opener:
        def open(self, request, timeout):
            if request.full_url not in answers and request.headers.get("Range"):
                return Page("", "image/jpeg")  # pictures load unless a test says otherwise
            answer = answers[request.full_url]
            if isinstance(answer, BaseException):
                raise answer
            return answer if isinstance(answer, Page) else Page(answer)
    monkeypatch.setattr(media, "build_opener", lambda *handlers: Opener())
    monkeypatch.setattr(media, "preview_image", ORIGINAL_PREVIEW_IMAGE)
    return answers


ORIGINAL_PREVIEW_IMAGE = media.preview_image  # captured at import, before the autouse fixture replaces it


@pytest.mark.parametrize("html, expected", [
    ('<head><meta property="og:image" content="https://cdn.example.org/slide.jpg"></head><body>', "https://cdn.example.org/slide.jpg"),
    ('<meta content="/img/slide.jpg" property="og:image"><body>', "https://news.example.org/img/slide.jpg"),   # relative
    ('<meta name="twitter:image" content="https://cdn.example.org/tw.jpg"><body>', "https://cdn.example.org/tw.jpg"),
    ('<meta property="og:image" content="https://cdn.example.org/site-logo.png"><body>', None),                 # generic picture
    ('<meta property="og:image" content="javascript:alert(1)"><body>', None),
    ('<head><title>No image</title></head><body><meta property="og:image" content="https://late.jpg">', None),  # only the head counts
])
def test_preview_image_comes_from_the_page_head(pages, html, expected):
    pages["https://news.example.org/story"] = html
    assert media.preview_image("https://news.example.org/story") == expected


def test_a_picture_the_publisher_refuses_to_show_elsewhere_is_left_out(pages):
    pages["https://news.example.org/story"] = '<meta property="og:image" content="https://img.example.org/blocked.jpg"><body>'
    pages["https://img.example.org/blocked.jpg"] = URLError("HTTP Error 403: Forbidden")
    assert media.preview_image("https://news.example.org/story") is None
    pages["https://img.example.org/blocked.jpg"] = Page("<html>Access denied</html>")  # an error page, not a picture
    assert media.preview_image("https://news.example.org/story") is None


def test_preview_image_never_reads_private_addresses_social_sites_or_non_html(pages):
    pages["https://news.example.org/file.pdf"] = Page("%PDF", "application/pdf")
    pages["https://news.example.org/down"] = URLError("timed out")
    assert media.preview_image("http://localhost/admin") is None
    assert media.preview_image("http://10.0.0.5/") is None
    assert media.preview_image("https://www.facebook.com/page/posts/1") is None  # embeds cover social sites
    assert media.preview_image("https://news.example.org/file.pdf") is None
    assert media.preview_image("https://news.example.org/down") is None


def test_redirects_to_private_addresses_are_refused(monkeypatch):
    monkeypatch.setattr(media, "_public_host", lambda host: host != "10.0.0.5")
    with pytest.raises(URLError, match="non-public address"):
        media._SafeRedirects().redirect_request(None, None, 302, "Found", {}, "http://10.0.0.5/secret")


def test_reports_carry_their_media_and_collection_reads_preview_images(client, tinyfish_network, pages):
    tinyfish_network[SEARCH] = {"results": [
        {"url": "https://news.example.org/nh6", "title": "NH-6 landslide", "snippet": "Landslide blocks NH-6."},
        {"url": "https://www.youtube.com/watch?v=bh1TVzezZWs", "title": "NH-6 video", "snippet": "Video of the NH-6 landslide."},
    ]}
    pages["https://news.example.org/nh6"] = '<meta property="og:image" content="https://cdn.example.org/nh6.jpg"><body>'
    client.post("/api/collection/run", json={"road": "NH-6"})
    items = {item["source_url"]: item for item in client.get("/api/incidents").json()}
    assert items["https://news.example.org/nh6"]["media"] == {"kind": "image", "url": "https://cdn.example.org/nh6.jpg", "site": "news.example.org"}
    assert items["https://www.youtube.com/watch?v=bh1TVzezZWs"]["media"]["kind"] == "youtube"
    assert client.post("/api/media/collect").json() == {"checked": 0, "found": 0}  # each page is read once


def test_a_page_with_an_unknown_charset_or_a_local_port_has_no_picture(pages):
    pages["https://news.example.org/odd"] = Page('<meta property="og:image" content="https://news.example.org/a.jpg">', "text/html; charset=bogus")
    assert media.preview_image("https://news.example.org/odd") is None  # LookupError, not a crashed run
    assert media.preview_image("http://news.example.org:8000/admin") is None  # only the usual web ports are read


def test_one_failing_page_does_not_stop_the_others(client, add_incident, monkeypatch):
    add_incident("bad", source_url="https://news.example.org/bad")
    add_incident("good", source_url="https://news.example.org/good")
    def preview(url):
        if url.endswith("bad"):
            raise RuntimeError("parser exploded")
        return "https://news.example.org/good.jpg"
    monkeypatch.setattr(media, "preview_image", preview)
    from app.database import get_connection
    with get_connection() as connection:
        media.collect_preview_images(connection)
        rows = dict(connection.execute("SELECT id, page_image FROM incidents").fetchall())
    assert rows == {"bad": None, "good": "https://news.example.org/good.jpg"}
