"""The device label read from a User-Agent: browser and system, nothing more."""

from __future__ import annotations

import pytest

from ira.useragent import device_label

CASES = [
    # Desktop browsers.
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36",
        "Chrome on macOS",
    ),
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "Version/17.6 Safari/605.1.15",
        "Safari on macOS",
    ),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) Firefox/131.0", "Firefox on macOS"),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36 Edg/129.0.0.0",
        "Edge on Windows",
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36 OPR/114.0.0.0",
        "Opera on Windows",
    ),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0", "Firefox on Linux"),
    (
        "Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.0.0 Safari/537.36",
        "Chrome on ChromeOS",
    ),
    # Phones and tablets.
    (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1",
        "Safari on iPhone",
    ),
    (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 "
        "(KHTML, like Gecko) CriOS/129.0.6668.69 Mobile/15E148 Safari/604.1",
        "Chrome on iPhone",
    ),
    (
        "Mozilla/5.0 (iPad; CPU OS 17_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
        "FxiOS/131.0 Mobile/15E148 Safari/605.1.15",
        "Firefox on iPad",
    ),
    (
        "Mozilla/5.0 (Linux; Android 14; Pixel 8) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/129.0.6668.81 Mobile Safari/537.36",
        "Chrome on Android",
    ),
    (
        "Mozilla/5.0 (Linux; Android 14; SM-S921B) AppleWebKit/537.36 (KHTML, like Gecko) "
        "SamsungBrowser/26.0 Chrome/122.0.0.0 Mobile Safari/537.36",
        "Samsung Internet on Android",
    ),
    # Not browsers, or not much to go on.
    ("curl/8.7.1", "curl"),
    ("python-httpx/0.27.2", "Python (httpx)"),
    ("python-requests/2.32.3", "Python (requests)"),
    ("MyKiosk/2.1 (front desk)", "MyKiosk"),
    ("Mozilla/5.0 (Windows NT 10.0) SomethingNew/1.0", "A browser on Windows"),
    ("Mozilla/5.0", None),
    ("", None),
    ("   ", None),
    (None, None),
]


@pytest.mark.parametrize(("user_agent", "label"), CASES)
def test_device_label(user_agent, label):
    assert device_label(user_agent) == label
