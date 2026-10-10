"""Validate static public-page metadata and local links without launching the app."""

from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET


WEB = Path(__file__).resolve().parents[1] / "web"
ORIGIN = "https://app.svaultai.com"
APP_LINKS = {"/signup", "/help-and-faq-public"}
SITEMAP_PATHS = {
    "/", "/privacy/", "/help-and-faq-public", "/features/",
    "/features/password-manager/", "/features/encrypted-file-storage/",
    "/features/private-memory-vault/", "/features/digital-inheritance/",
    "/features/zero-knowledge-security/", "/guides/",
    "/guides/private-encrypted-vault/",
    "/guides/password-manager-vs-digital-vault/",
    "/guides/encrypted-file-storage-checklist/",
    "/guides/digital-inheritance-checklist/",
}


class PublicPage(HTMLParser):
    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.titles: list[str] = []
        self.descriptions: list[str] = []
        self.canonicals: list[str] = []
        self.links: list[str] = []
        self.ids: set[str] = set()
        self.structured: list[str] = []
        self.h1_count = 0
        self.language: str | None = None
        self._capture: str | None = None
        self._buffer: list[str] = []
        self.feed(source)
        self.close()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.add(values["id"])
        if tag == "html":
            self.language = values.get("lang")
        if tag == "h1":
            self.h1_count += 1
        if tag == "title" or (
            tag == "script" and values.get("type") == "application/ld+json"
        ):
            self._capture = tag
            self._buffer = []
        if tag == "meta" and values.get("name") == "description":
            self.descriptions.append(values.get("content") or "")
        if tag == "link" and values.get("rel") == "canonical":
            self.canonicals.append(values.get("href") or "")
        if tag == "a" and values.get("href"):
            self.links.append(values["href"])

    def handle_data(self, data: str) -> None:
        if self._capture:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._capture == tag:
            text = "".join(self._buffer).strip()
            (self.titles if tag == "title" else self.structured).append(text)
            self._capture = None
            self._buffer = []


def page_path(path: str) -> Path:
    relative = path.lstrip("/")
    if not relative or path.endswith("/"):
        return WEB / relative / "index.html"
    return WEB / relative


def main() -> None:
    paths = [WEB / "index.html", WEB / "privacy" / "index.html"]
    paths += sorted((WEB / "features").rglob("index.html"))
    paths += sorted((WEB / "guides").rglob("index.html"))
    pages = {path: PublicPage(path.read_text(encoding="utf-8")) for path in paths}
    titles: set[str] = set()
    descriptions: set[str] = set()
    metadata = []
    for path, page in pages.items():
        relative = path.relative_to(WEB).as_posix()
        route = "/" if relative == "index.html" else "/" + relative.removesuffix("index.html")
        assert page.language == "en", relative
        assert page.h1_count == 1, relative
        assert len(page.titles) == len(page.descriptions) == len(page.canonicals) == 1, relative
        title, description = page.titles[0], page.descriptions[0]
        assert title and description and title not in titles and description not in descriptions, relative
        assert page.canonicals[0] == ORIGIN + route, relative
        titles.add(title)
        descriptions.add(description)
        for payload in page.structured:
            assert isinstance(json.loads(payload), dict), relative
        for link in page.links:
            url = urlsplit(link)
            if url.scheme or url.netloc:
                continue
            assert not url.query, (relative, link)
            target = path if not url.path else page_path(url.path)
            if url.path in APP_LINKS:
                continue
            assert target.exists(), (relative, link)
            if url.fragment:
                assert target in pages and url.fragment in pages[target].ids, (relative, link)
        metadata.append({"path": route, "title_characters": len(title), "description_characters": len(description)})
    sitemap = ET.fromstring((WEB / "sitemap.xml").read_text(encoding="utf-8"))
    urls = [node.text for node in sitemap.findall("{*}url/{*}loc")]
    assert len(urls) == len(set(urls)) == len(SITEMAP_PATHS)
    assert set(urls) == {ORIGIN + route for route in SITEMAP_PATHS}
    json.loads((WEB / "manifest.json").read_text(encoding="utf-8"))
    print(json.dumps({"status": "passed", "public_pages": len(pages), "sitemap_urls": len(urls), "metadata": metadata}, indent=2))


if __name__ == "__main__":
    main()
