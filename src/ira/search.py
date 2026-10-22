"""Web and news search: two tools a person switches on for themselves.

* ``web_search`` asks the Brave Search API (``GET /res/v1/web/search`` with the
  key in ``X-Subscription-Token``) when ``BRAVE_SEARCH_API_KEY`` is set. At most
  30 searches an hour for the whole server, since they share one key.
* ``news_search`` reads the RSS and Atom feeds listed in ``ira.yaml``, keeps
  them for a few minutes, and searches them here: the query never leaves the
  server.

Results are text written by others, so they reach the model wrapped as data,
and every result carries its site and date, so answers can name their sources.
"""

from __future__ import annotations

import asyncio
import collections
import datetime as dt
import email.utils
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, quote_plus, urlsplit

import httpx

from ira import __version__
from ira.config import SearchConfig
from ira.devices.protocol import clean_line
from ira.tools.personal import PersonalTool
from ira.tools.registry import ToolError

log = logging.getLogger("ira.search")

BRAVE_URL = "https://api.search.brave.com/res/v1/web/search"
YOUTUBE_SEARCH = "https://www.googleapis.com/youtube/v3/search"
VIDEO_CACHE_SECONDS = 600
# News channels whose live stream has a fixed address on YouTube: opening it plays the stream.
# Checked to resolve on 23 Oct 2026.
LIVE_CHANNELS: dict[str, tuple[str, tuple[str, ...]]] = {
    "@aajtak": ("Aaj Tak", ("aaj tak", "aajtak", "आज तक")),
    "@ndtvindia": ("NDTV India", ("ndtv india", "एनडीटीवी इंडिया")),
    "@ABPNEWS": ("ABP News", ("abp news", "abp", "एबीपी")),
    "@zeenews": ("Zee News", ("zee news", "zee", "ज़ी न्यूज़", "जी न्यूज")),
    "@IndiaTV": ("India TV", ("india tv", "इंडिया टीवी")),
    "@DDNews": ("DD News", ("dd news", "doordarshan", "डीडी न्यूज़", "दूरदर्शन")),
    "@News18India": ("News18 India", ("news18 india", "news 18")),
    "@republicbharat": ("Republic Bharat", ("republic bharat", "रिपब्लिक भारत")),
    "@ndtv": ("NDTV", ("ndtv",)),
    "@IndiaToday": ("India Today", ("india today",)),
    "@WION": ("WION", ("wion",)),
    "@TimesNowNews": ("Times Now", ("times now",)),
    "@CNNnews18": ("CNN-News18", ("cnn news18", "cnn-news18", "cnn news 18")),
}
VIDEO_FIND_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "What to play, such as aaj tak live news."},
        "live": {"type": "boolean", "description": "A live stream (live news), not a video."},
    },
    "required": ["query"],
}


def live_channel(query: str) -> dict[str, Any] | None:
    """A news channel named in the request, as its live stream's address."""
    text = f" {' '.join(query.lower().split())} "
    for handle, (name, names) in LIVE_CHANNELS.items():
        if any(f" {n} " in text or (len(n) > 4 and n in text) for n in names):
            return {
                "title": f"{name} LIVE",
                "channel": name,
                "url": f"https://www.youtube.com/{handle}/live",
                "live": True,
            }
    return None


def watch_id(url: str) -> str | None:
    """The video id of a YouTube watch link, else None."""
    parts = urlsplit(url)
    host = parts.netloc.lower().removeprefix("www.").removeprefix("m.")
    if host == "youtube.com" and parts.path == "/watch":
        found = parse_qs(parts.query).get("v", [""])[0]
    elif host == "youtu.be":
        found = parts.path.strip("/")
    else:
        return None
    return found if re.fullmatch(r"[A-Za-z0-9_-]{11}", found) else None


HOUR = 3600.0
MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_SNIPPET = 300
USER_AGENT = f"IRA/{__version__} (+https://github.com/helloupendra/ira)"
FRESHNESS = {"day": "pd", "week": "pw", "month": "pm", "year": "py"}

WEB_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {"type": "string", "description": "What to search the web for."},
        "freshness": {
            "type": "string",
            "enum": list(FRESHNESS),
            "description": "Only pages from the last day, week, month or year.",
        },
    },
    "required": ["query"],
}
NEWS_SEARCH_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "Words to look for in headlines; empty for the latest news.",
        },
        "days": {
            "type": "integer",
            "minimum": 1,
            "maximum": 30,
            "description": "How many days back (default 2).",
        },
    },
}


def site_of(url: str) -> str:
    host = urlsplit(url).hostname or ""
    return host.removeprefix("www.")


class RateLimit:
    """At most ``limit`` calls in any hour."""

    def __init__(self, limit: int, clock: Callable[[], float] = time.monotonic) -> None:
        self.limit = limit
        self.clock = clock
        self._calls: collections.deque[float] = collections.deque()

    def take(self) -> float | None:
        """Use one call; None if allowed, else the seconds until one is free."""
        now = self.clock()
        while self._calls and now - self._calls[0] >= HOUR:
            self._calls.popleft()
        if len(self._calls) >= self.limit:
            return HOUR - (now - self._calls[0])
        self._calls.append(now)
        return None


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    published: float | None
    summary: str

    def public(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "url": self.url,
            "site": site_of(self.url) or self.source,
            "source": self.source,
            "date": _iso(self.published),
            "summary": self.summary,
        }


def _iso(moment: float | None) -> str | None:
    if moment is None:
        return None
    return dt.datetime.fromtimestamp(moment, dt.UTC).strftime("%Y-%m-%d %H:%M UTC")


def _when(text: str | None) -> float | None:
    """RSS dates (RFC 822) and Atom dates (ISO 8601)."""
    if not text:
        return None
    text = text.strip()
    try:
        return email.utils.parsedate_to_datetime(text).timestamp()
    except (TypeError, ValueError, IndexError):
        pass
    try:
        parsed = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.UTC)
    return parsed.timestamp()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _child(element: ET.Element, name: str) -> ET.Element | None:
    for child in element:
        if _local(child.tag) == name:
            return child
    return None


def _text(element: ET.Element, *names: str) -> str:
    for name in names:
        child = _child(element, name)
        if child is not None and (child.text or "").strip():
            return child.text or ""
    return ""


def parse_feed(data: bytes, source: str) -> list[NewsItem]:
    """Items of an RSS 2.0 or Atom feed. A document type or entity is refused."""
    head = data[:4096].lower()
    if b"<!doctype" in head or b"<!entity" in data.lower():
        raise ValueError("feeds with a document type are not read")
    root = ET.fromstring(data)
    entries = [e for e in root.iter() if _local(e.tag) in ("item", "entry")]
    items = []
    for entry in entries:
        title = clean_line(_text(entry, "title"), 300)
        link = _text(entry, "link").strip()
        if not link:
            for child in entry:
                rel = child.get("rel", "alternate")
                if _local(child.tag) == "link" and child.get("href") and rel == "alternate":
                    link = child.get("href", "")
                    break
        summary = clean_line(_text(entry, "description", "summary", "content"), MAX_SNIPPET)
        published = _when(_text(entry, "pubDate", "published", "updated", "date"))
        if title:
            items.append(NewsItem(title, link, source, published, summary))
    return items


class Search:
    def __init__(
        self,
        config: SearchConfig,
        *,
        client: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.config = config
        self.client = client or httpx.AsyncClient(
            headers={"User-Agent": USER_AGENT}, follow_redirects=True
        )
        self.clock = clock
        self.limit = RateLimit(config.calls_per_hour, monotonic)
        self._news: list[NewsItem] = []
        self._news_at: float | None = None
        self._news_lock = asyncio.Lock()
        self._videos: dict[tuple[str, bool], tuple[float, dict[str, Any]]] = {}

    # What is set up.

    @property
    def web_ready(self) -> bool:
        return bool(os.environ.get(self.config.brave_api_key_env))

    @property
    def news_ready(self) -> bool:
        return bool(self.config.news.feeds)

    # Web.

    async def web(self, query: str, freshness: str | None = None) -> dict[str, Any]:
        key = os.environ.get(self.config.brave_api_key_env)
        if not key:
            raise ToolError(
                "web search is not configured on this server: the owner sets "
                f"{self.config.brave_api_key_env} in .env (a Brave Search API key)"
            )
        query = " ".join(query.split())[:400]
        if not query:
            raise ToolError("say what to search for")
        wait = self.limit.take()
        if wait is not None:
            minutes = max(1, round(wait / 60))
            raise ToolError(
                f"web search is limited to {self.config.calls_per_hour} searches an hour; "
                f"try again in {minutes} minute{'s' if minutes != 1 else ''}"
            )
        params: dict[str, Any] = {"q": query, "count": self.config.results}
        if freshness in FRESHNESS:
            params["freshness"] = FRESHNESS[freshness]
        if self.config.country:
            params["country"] = self.config.country
        if self.config.search_lang:
            params["search_lang"] = self.config.search_lang
        started = time.monotonic()
        try:
            response = await self.client.get(
                BRAVE_URL,
                params=params,
                headers={"X-Subscription-Token": key, "Accept": "application/json"},
                timeout=15,
            )
        except httpx.HTTPError as exc:
            raise ToolError(f"web search could not be reached ({type(exc).__name__})") from None
        if response.status_code == 429:
            raise ToolError("the search provider says too many searches; try again later")
        if response.status_code in (401, 403):
            raise ToolError("the search provider refused the key; the owner should check it")
        if response.status_code != 200:
            raise ToolError(f"web search failed (HTTP {response.status_code})")
        try:
            body = response.json()
        except ValueError:
            raise ToolError("web search returned something that is not JSON") from None
        results = []
        for item in ((body.get("web") or {}).get("results") or [])[: self.config.results]:
            url = str(item.get("url") or "")
            meta = item.get("meta_url") or {}
            results.append(
                {
                    "title": clean_line(item.get("title"), 300),
                    "url": url,
                    "site": str(meta.get("hostname") or site_of(url)).removeprefix("www."),
                    "snippet": clean_line(item.get("description"), MAX_SNIPPET),
                    "age": clean_line(item.get("age"), 40) or None,
                    "date": clean_line(item.get("page_age"), 40) or None,
                }
            )
        log.info("web search: %d results in %.2fs", len(results), time.monotonic() - started)
        return {"query": query, "results": results}

    # News.

    async def _feeds(self) -> list[NewsItem]:
        async with self._news_lock:
            fresh = self._news_at is not None and (
                self.clock() - self._news_at < self.config.news.cache_minutes * 60
            )
            if fresh:
                return self._news
            fetched = await asyncio.gather(
                *(self._fetch(feed.name, feed.url) for feed in self.config.news.feeds)
            )
            items = [item for batch in fetched for item in batch]
            if items or self._news_at is None:
                self._news, self._news_at = items, self.clock()
            return self._news

    async def _fetch(self, name: str, url: str) -> list[NewsItem]:
        try:
            response = await self.client.get(url, timeout=10)
            response.raise_for_status()
            if len(response.content) > MAX_FEED_BYTES:
                raise ValueError("the feed is larger than 2 MB")
            return parse_feed(response.content, name)
        except (httpx.HTTPError, ValueError, ET.ParseError) as exc:
            log.warning("news feed %s failed: %s", name, type(exc).__name__)
            return []

    async def news(self, query: str = "", days: int = 2) -> dict[str, Any]:
        if not self.news_ready:
            raise ToolError(
                "no news feeds are set up on this server: the owner lists them under "
                "search.news.feeds in ira.yaml"
            )
        days = max(1, min(int(days or 2), 30))
        since = self.clock() - days * 86400
        words = [w for w in re.findall(r"\w+", query.lower()) if len(w) > 1]
        scored = []
        for item in await self._feeds():
            if item.published is not None and item.published < since:
                continue
            haystack = f"{item.title} {item.summary}".lower()
            score = sum(1 for w in words if w in haystack)
            if words and score == 0:
                continue
            scored.append((score, item.published or 0.0, item))
        scored.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
        found = [item.public() for _, _, item in scored[: self.config.news.results]]
        return {"query": query, "days": days, "items": found}

    # Videos.

    async def video(self, query: str, live: bool = False) -> dict[str, Any]:
        """Videos to play: a news channel's live address when one is named, else YouTube's
        own search (with a YouTube Data API key) or Brave's. Never YouTube's pages scraped."""
        query = " ".join(query.split())[:200]
        if not query:
            raise ToolError("say what to play")
        channel = live_channel(query)
        if channel is not None and (live or "live" in query.lower() or "news" in query.lower()):
            return {"query": query, "videos": [channel]}
        key = (query.lower(), live)
        cached = self._videos.get(key)
        if cached and self.clock() - cached[0] < VIDEO_CACHE_SECONDS:
            return cached[1]
        youtube = os.environ.get(self.config.youtube_api_key_env)
        if youtube:
            found = await self._youtube(query, live, youtube)
        elif self.web_ready:
            found = await self._brave_videos(query)
        else:
            if channel is not None:
                return {"query": query, "videos": [channel]}
            return {
                "query": query,
                "videos": [],
                "search_page": f"https://www.youtube.com/results?search_query={quote_plus(query)}",
                "note": "No video search is set up on this server: open the search page.",
            }
        result = {"query": query, "videos": found}
        self._videos[key] = (self.clock(), result)
        return result

    async def _youtube(self, query: str, live: bool, key: str) -> list[dict[str, Any]]:
        if self.limit.take() is not None:
            raise ToolError("too many searches this hour; try again later")
        params: dict[str, Any] = {
            "part": "snippet",
            "type": "video",
            "maxResults": 5,
            "q": query,
            "key": key,
        }
        if live:
            params["eventType"] = "live"
        try:
            response = await self.client.get(YOUTUBE_SEARCH, params=params, timeout=15)
        except httpx.HTTPError as exc:
            raise ToolError(f"YouTube could not be reached ({type(exc).__name__})") from None
        if response.status_code in (400, 403):
            raise ToolError("YouTube refused the search; the owner should check the API key")
        if response.status_code != 200:
            raise ToolError(f"YouTube search failed (HTTP {response.status_code})")
        videos = []
        for item in response.json().get("items") or []:
            video_id = (item.get("id") or {}).get("videoId")
            snippet = item.get("snippet") or {}
            if not video_id:
                continue
            videos.append(
                {
                    "title": clean_line(snippet.get("title"), 200),
                    "channel": clean_line(snippet.get("channelTitle"), 100),
                    "url": f"https://www.youtube.com/watch?v={video_id}",
                    "live": snippet.get("liveBroadcastContent") == "live",
                }
            )
        return videos

    async def _brave_videos(self, query: str) -> list[dict[str, Any]]:
        found = await self.web(f"{query} site:youtube.com")
        videos = []
        for result in found["results"]:
            video_id = watch_id(result["url"])
            if video_id:
                videos.append(
                    {
                        "title": result["title"],
                        "channel": None,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                        "live": False,
                    }
                )
        return videos

    # The tools, for one person who switched web search on.

    def tools(self) -> list[PersonalTool]:
        async def web(arguments: dict[str, Any]) -> Any:
            return await self.web(str(arguments.get("query", "")), arguments.get("freshness"))

        async def video(arguments: dict[str, Any]) -> Any:
            return await self.video(str(arguments.get("query", "")), arguments.get("live") is True)

        async def news(arguments: dict[str, Any]) -> Any:
            try:
                days = int(arguments.get("days") or 2)
            except (TypeError, ValueError):
                days = 2
            return await self.news(str(arguments.get("query") or ""), days)

        return [
            PersonalTool(
                name="web_search",
                description="Search the web. Returns titles, links, sites, dates and snippets.",
                parameters=WEB_SEARCH_SCHEMA,
                tier=0,
                source="web",
                label="web search",
                run=web,
                skill="web",
            ),
            PersonalTool(
                name="news_search",
                description="Search recent news headlines from the news feeds this server reads.",
                parameters=NEWS_SEARCH_SCHEMA,
                tier=0,
                source="web",
                label="news feeds",
                run=news,
                skill="web",
            ),
            PersonalTool(
                name="video_find",
                description="Find a YouTube video or a news channel's live stream to play. "
                "Returns watch links: to play one, open its url with url_open (Tier 1), then "
                "say what is playing ('Aaj Tak LIVE chala diya'). For live news, set live.",
                parameters=VIDEO_FIND_SCHEMA,
                tier=0,
                source="web",
                label="video search",
                run=video,
                skill="web",
            ),
        ]

    async def aclose(self) -> None:
        await self.client.aclose()
