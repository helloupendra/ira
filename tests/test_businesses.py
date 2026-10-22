"""Business profiles: kept per person, in the prompt, filled in on the page or told to Ira."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from ira.businesses import MAX_PROMPT_CHARS, BusinessError, Businesses
from ira.channels.http import create_app

from .conftest import make_runtime

pytestmark = pytest.mark.anyio

PASSWORD = "correct-horse-battery"  # pragma: allowlist secret


def login(client, email):
    body = {"email": email, "password": PASSWORD, "use_cookie": False}
    token = client.post("/v1/auth/login", json=body).json()["session_token"]
    return {"Authorization": f"Bearer {token}"}


def test_profiles_are_kept_per_person_and_named_once(store):
    businesses = Businesses(store)
    sunrise = businesses.add(
        1,
        "Sunrise Dental Clinic",
        about="a small clinic; I keep its books.",
        people="Dr. Mehta, owner;  Priya, front desk",
        terms="monthly invoice, net 15",
        may_do="read its appointments; never message patients",
    )
    assert sunrise.line() == (
        "Sunrise Dental Clinic: a small clinic; I keep its books. People: Dr. Mehta, owner; "
        "Priya, front desk. Terms: monthly invoice, net 15. Ira may: read its appointments; "
        "never message patients"
    )
    with pytest.raises(BusinessError, match="already have"):
        businesses.add(1, "sunrise dental clinic")
    assert businesses.add(2, "Sunrise Dental Clinic").line() == "Sunrise Dental Clinic"
    changed = businesses.change(1, sunrise.id, terms="net 30", about=None)
    assert changed.terms == "net 30" and changed.about == "a small clinic; I keep its books."
    with pytest.raises(KeyError):
        businesses.change(2, sunrise.id, terms="mine now")  # not theirs
    assert not businesses.remove(2, sunrise.id) and businesses.get(1, sunrise.id) is not None
    for n in range(10):
        businesses.add(1, f"Shop {n}", about="x" * 590)
    lines = businesses.lines(1)
    assert sum(map(len, lines)) <= MAX_PROMPT_CHARS and lines[0].startswith("Shop 9")
    assert businesses.lines(None) == []


async def test_ira_keeps_them_in_mind_and_remembers_what_it_is_told():
    runtime = make_runtime()
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    runtime.businesses.add(owner.id, "Sunrise Dental Clinic", may_do="never message patients")
    prompt = runtime.assistant.system_prompt(owner.id)
    assert "The businesses this person works with" in prompt
    assert "  - Sunrise Dental Clinic: Ira may: never message patients\n" in prompt
    assert "businesses this person" not in runtime.assistant.system_prompt(None)

    tool = next(t for t in runtime.personal_tools(owner.id) if t.name == "remember_business")
    assert tool.tier == 1
    told = await tool.run({"name": "sunrise dental clinic", "terms": "pays net 30"})
    assert told["summary"].endswith("Terms: pays net 30. Ira may: never message patients")
    await tool.run({"name": "Lotus Bakery", "about": "my sister's bakery"})
    assert [b.name for b in runtime.businesses.list(owner.id)][0] == "Lotus Bakery"
    with pytest.raises(Exception, match="what to remember"):
        await tool.run({"name": "Lotus Bakery"})


def test_the_page_changes_them_and_a_device_only_reads():
    runtime = make_runtime()
    owner = runtime.accounts.create_first_owner("owner@example.com", PASSWORD)
    runtime.accounts.create_user("staff@example.com", PASSWORD, "staff")
    devices = runtime.hub.devices
    code, _ = devices.start_pairing(owner.id, "android", None, [])
    phone = {"Authorization": f"Bearer {devices.redeem(code)[0]}"}
    with TestClient(create_app(runtime, start_channels=False)) as client:
        mine, theirs = login(client, "owner@example.com"), login(client, "staff@example.com")
        body = {"name": "Sunrise Dental Clinic", "about": "a clinic", "terms": "net 15"}
        made = client.post("/v1/me/businesses", json=body, headers=mine)
        assert made.status_code == 200
        business = made.json()
        assert client.post("/v1/me/businesses", json=body, headers=mine).status_code == 409
        assert client.post("/v1/me/businesses", json=body, headers=phone).status_code == 403
        assert [b["name"] for b in client.get("/v1/me/businesses", headers=phone).json()] == [
            "Sunrise Dental Clinic"
        ]
        assert client.get("/v1/me/businesses", headers=theirs).json() == []
        path = f"/v1/me/businesses/{business['id']}"
        assert client.patch(path, json={"terms": "net 30"}, headers=theirs).status_code == 404
        changed = client.patch(path, json={"terms": "net 30"}, headers=mine).json()
        assert changed["terms"] == "net 30" and changed["about"] == "a clinic"
        exported = client.get("/v1/me/export", headers=mine).json()
        assert [b["name"] for b in exported["businesses"]] == ["Sunrise Dental Clinic"]
        assert client.delete(path, headers=theirs).status_code == 404
        assert client.delete(path, headers=mine).json() == {"ok": True}
        client.post("/v1/me/businesses", json=body, headers=mine)
        gone = client.post("/v1/me/data/delete", json={"password": PASSWORD}, headers=mine)
        assert gone.status_code == 200
    assert runtime.businesses.list(owner.id) == []
