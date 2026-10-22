"""Which tab someone means."""

from __future__ import annotations

import pytest

from ira_mac.tabs import TabError, clean_url, match_tab


def tab(id, title, url, active=False, focused=False, last=0):
    return {
        "id": id,
        "title": title,
        "url": url,
        "active": active,
        "focused": focused,
        "lastAccessed": last,
    }


TABS = [
    tab(1, "Inbox - Example Mail", "https://mail.example.com/", focused=True, last=10),
    tab(2, "Upload - Example Drive", "https://drive.example.com/upload", True, True, 30),
    tab(3, "Upload a file - Docs", "https://docs.example.org/upload", last=50),
    tab(4, "Build #812", "https://ci.example.net/builds/812", active=True, last=40),
]


def test_by_id():
    assert match_tab(TABS, tab_id=3)["id"] == 3
    with pytest.raises(TabError, match="no open tab has id 9"):
        match_tab(TABS, tab_id=9)


def test_by_words_preferring_the_active_tab():
    assert match_tab(TABS, match="upload")["id"] == 2  # two match; the one in front wins
    assert match_tab(TABS, match="docs upload")["id"] == 3  # every word
    assert match_tab(TABS, match="ci.example.net")["id"] == 4  # the address counts
    assert match_tab(TABS, match="build kuch")["id"] == 4  # else any word


def test_no_match_lists_the_open_tabs():
    with pytest.raises(TabError, match="no tab matches 'weather'. Open tabs: Inbox"):
        match_tab(TABS, match="weather")
    with pytest.raises(TabError, match="no Chrome tabs"):
        match_tab([], match="x")


def test_neither_means_the_tab_in_front():
    assert match_tab(TABS)["id"] == 2


def test_addresses_lose_their_query_and_fragment():
    assert clean_url("https://x.example.com/a/b?token=1&q=2#frag") == "https://x.example.com/a/b"
    assert clean_url("") == ""
