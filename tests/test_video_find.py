"""video_find: a link that plays. Official APIs only; never YouTube's own pages."""

from __future__ import annotations

import httpx
import pytest

from ira.config import SearchConfig
from ira.search import Search, live_channel, watch_id

pytestmark = pytest.mark.anyio

# The shape of YouTube Data API v3's search.list answer (fictional videos).
YOUTUBE = {
    "items": [
        {
            "id": {"kind": "youtube#video", "videoId": "AbCdEfGhIj0"},
            "snippet": {
                "title": "Aaj ki taaza khabar | Example News",
                "channelTitle": "Example News",
                "liveBroadcastContent": "live",
            },
        },
        {"id": {"kind": "youtube#channel", "channelId": "UCx"}, "snippet": {"title": "a channel"}},
        {
            "id": {"kind": "youtube#video", "videoId": "ZyXwVuTsRq9"},
            "snippet": {
                "title": "Monsoon report",
                "channelTitle": "Example",
                "liveBroadcastContent": "none",
            },
        },
    ]
}
BRAVE = {
    "web": {
        "results": [
            {
                "title": "Python 3.13 in 10 minutes",
                "url": "https://www.youtube.com/watch?v=Py313aBcDeF",
            },
            {"title": "A channel", "url": "https://www.youtube.com/@example"},
            {"title": "Short link", "url": "https://youtu.be/ShOrTlInK12"},
        ]
    }
}


def search(handler) -> Search:
    return Search(SearchConfig(), client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))


def test_news_channels_and_watch_links():
    assert live_channel("aaj tak live chalao")["url"] == "https://www.youtube.com/@aajtak/live"
    assert live_channel("आज तक लाइव दिखाओ")["channel"] == "Aaj Tak"
    assert live_channel("NDTV India live")["url"].endswith("/@ndtvindia/live")
    assert live_channel("ndtv news")["url"].endswith("/@ndtv/live")
    assert live_channel("abp news chala do")["channel"] == "ABP News"
    assert live_channel("kuch acha gaana") is None
    assert watch_id("https://www.youtube.com/watch?v=AbCdEfGhIj0&t=3") == "AbCdEfGhIj0"
    assert watch_id("https://youtu.be/ShOrTlInK12") == "ShOrTlInK12"
    assert watch_id("https://www.youtube.com/@aajtak") is None
    assert watch_id("https://evil.example/watch?v=AbCdEfGhIj0") is None


async def test_youtube_api_with_a_key_and_a_short_cache(monkeypatch):
    seen: list[httpx.Request] = []

    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=YOUTUBE)

    monkeypatch.setenv("YOUTUBE_API_KEY", "yt-key")
    found = await search(handle).video("hindi news", live=True)
    assert [v["url"] for v in found["videos"]] == [
        "https://www.youtube.com/watch?v=AbCdEfGhIj0",
        "https://www.youtube.com/watch?v=ZyXwVuTsRq9",
    ]
    assert found["videos"][0]["live"] is True and found["videos"][1]["live"] is False
    params = seen[0].url.params
    assert seen[0].url.host == "www.googleapis.com" and params["eventType"] == "live"
    assert params["type"] == "video" and params["key"] == "yt-key"

    finder = search(handle)
    await finder.video("monsoon")
    await finder.video("monsoon")
    assert len(seen) == 2  # the second is from the cache


async def test_a_named_channel_needs_no_search(monkeypatch):
    def handle(request: httpx.Request) -> httpx.Response:
        raise AssertionError("no request for a known channel's live stream")

    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    found = await search(handle).video("Aaj Tak live news")
    assert found["videos"] == [
        {
            "title": "Aaj Tak LIVE",
            "channel": "Aaj Tak",
            "url": "https://www.youtube.com/@aajtak/live",
            "live": True,
        }
    ]


async def test_brave_without_a_youtube_key_and_nothing_without_either(monkeypatch):
    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "api.search.brave.com"
        assert "site:youtube.com" in request.url.params["q"]
        return httpx.Response(200, json=BRAVE)

    monkeypatch.delenv("YOUTUBE_API_KEY", raising=False)
    monkeypatch.setenv("BRAVE_SEARCH_API_KEY", "brave-key")
    found = await search(handle).video("python 3.13 video")
    assert [v["url"] for v in found["videos"]] == [
        "https://www.youtube.com/watch?v=Py313aBcDeF",
        "https://www.youtube.com/watch?v=ShOrTlInK12",
    ]

    monkeypatch.delenv("BRAVE_SEARCH_API_KEY")
    found = await search(handle).video("python 3.13 video")
    assert found["videos"] == []
    assert found["search_page"] == "https://www.youtube.com/results?search_query=python+3.13+video"


def test_it_is_offered_with_web_search_and_is_web_content():
    tools = {tool.name: tool for tool in Search(SearchConfig()).tools()}
    video = tools["video_find"]
    assert (video.tier, video.source, video.skill) == (0, "web", "web")
    assert "url_open" in video.description
