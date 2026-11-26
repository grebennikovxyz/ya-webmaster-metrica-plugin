import asyncio
import os
import socket
import sys
import xml.etree.ElementTree as ET
from unittest.mock import Mock

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from site_desk import access, analytics, intake, maps, search, server, watch

HOME = "https://example.org/"
HTML = b"""<title>Studio</title><meta property="og:site_name" content="Site Studio">
<script type="application/ld+json">{"@graph":[{"@type":"LocalBusiness","name":"Studio","address":"123 Main","telephone":"555"}]}</script>
<a href="/contact">Contacts</a><form></form><a href="tel:+12345">Call</a><script>ym(12345,'init',{})</script>"""
ENT = maps.Place(name="Entrance", lat=55.75, lon=37.62)
STOP = maps.Place(name="Metro & Bus", lat=55.76, lon=37.61)


@pytest.fixture(autouse=True)
def private_state(tmp_path, monkeypatch):
    monkeypatch.setenv("SITE_DESK_STATE_DIR", str(tmp_path))


def test_card_and_triggers(monkeypatch):
    monkeypatch.setattr(intake, "public_page", lambda url, allowed: (url, HTML))
    draft = server.organization_draft(HOME)
    assert {"value": "Studio", "source": HOME} in draft["fields"]["name"]
    assert "entrance" in draft["needs_confirmation"]
    assert draft["evidence"]["pages"][0]["counter_ids"] == ["12345"]
    goals = server.metrica_goal_plan(HOME)["suggestions"]
    assert {g["type"] for g in goals} == {"phone", "action"}


def test_markup_cannot_close_script():
    data = server.organization_markup("</script>", HOME, "street")
    assert (
        data["html"].count("</script>") == 1 and data["fields"]["name"] == "</script>"
    )


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc",
        "https://me:pass@example.org",
        "http://x:8000",
        "https://local\\test",
    ],
)
def test_bad_site(url):
    with pytest.raises(ValueError):
        access.website(url)


@pytest.mark.parametrize(
    "ip", ["127.0.0.1", "169.254.169.254", "192.168.1.2", "224.0.0.1", "::1"]
)
def test_nonpublic_destinations(monkeypatch, ip):
    monkeypatch.setattr(
        socket, "getaddrinfo", lambda *a, **kw: [(None, None, None, "", (ip, 80))]
    )
    with pytest.raises(ValueError, match="public"):
        intake.public_page("http://example.org/")


def test_utm_replaces_tags_retains_fragment():
    url = analytics.tagged_link(
        HOME + "?a=1&utm_source=old#door", "maps", "referral", "nov"
    )
    assert url.count("utm_source") == 1 and "a=1" in url and url.endswith("#door")


def test_routes_and_export(monkeypatch):
    args = {}

    def request(method, url, params):
        args.update(params)
        return {
            "route": {
                "legs": [
                    {
                        "status": "OK",
                        "steps": [
                            {
                                "length": 40,
                                "duration": 33,
                                "polyline": {
                                    "points": [[STOP.lat, STOP.lon], [ENT.lat, ENT.lon]]
                                },
                            }
                        ],
                    }
                ]
            }
        }

    monkeypatch.setattr(maps, "credential", lambda k: "test")
    monkeypatch.setattr(maps, "request", request)
    data = maps.directions(ENT, [STOP], True, True)
    assert args["waypoints"] == "55.76,37.61|55.75,37.62" and args["mode"] == "walking"
    assert data["routes"][0]["walking_metres"] == 40
    ns = {"g": "http://www.topografix.com/GPX/1/1"}
    gpx = ET.fromstring(data["gpx"])
    assert [p.text for p in gpx.findall("g:wpt/g:name", ns)] == [
        "Entrance",
        "Metro & Bus",
    ]
    assert len(gpx.findall(".//g:trkpt", ns)) == 2
    assert maps.directions(ENT, [STOP], True, False)["track_count"] == 0
    monkeypatch.setattr(maps, "route", Mock(side_effect=ValueError("No path")))
    fallback = maps.directions(ENT, [STOP], True, True)
    assert (
        "rtt=pd" in fallback["routes"][0]["open_route"] and fallback["track_count"] == 0
    )


def test_nearby_transit(monkeypatch):
    monkeypatch.setattr(
        maps,
        "request",
        lambda *a, **kw: {
            "elements": [
                {"lat": 0, "lon": 0, "tags": {"name": "Far"}},
                {"lat": 55.751, "lon": 37.62, "tags": {"name": "Near"}},
            ]
        },
    )
    result = maps.nearby(ENT, "openstreetmap", 1000)
    assert [p["place"]["name"] for p in result["candidates"]] == ["Near"]
    assert "OpenStreetMap" in result["attribution"]


def test_duplicate_counter_on_later_page(monkeypatch):
    monkeypatch.setattr(
        analytics,
        "list_counters",
        lambda offset, limit: (
            {"next_offset": 1001, "counters": []}
            if offset == 1
            else {
                "next_offset": None,
                "counters": [{"id": 7, "site2": {"site": "example.org"}}],
            }
        ),
    )
    monkeypatch.setattr(
        analytics, "met", Mock(side_effect=AssertionError("unexpected write"))
    )
    assert not analytics.ensure_counter(HOME, "Studio", "UTC", False)["created"]


def test_goal_conflicts_and_handoff(monkeypatch):
    row = {
        "id": 7,
        "type": "action",
        "name": "Lead",
        "conditions": [{"type": "exact", "url": "lead_success"}],
    }
    monkeypatch.setattr(analytics, "goals", lambda _: [row])
    assert not analytics.ensure_goal(11, "Lead", "action", "lead_success", "exact")[
        "created"
    ]
    with pytest.raises(ValueError, match="different"):
        analytics.ensure_goal(11, "Lead", "action", "other", "exact")
    monkeypatch.setattr(
        analytics,
        "counter_info",
        lambda _: {"code": "<script>test</script>", "site": "example.org"},
    )
    data = analytics.developer_handoff(11)
    assert "lead_success" in data["events"][0]["javascript"] and data[
        "html"
    ].startswith("<script>")


def test_labels_resume_partial_write(monkeypatch):
    items = []

    def met(method, path, body=None):
        if path == "/labels" and method == "GET":
            return {"labels": items}
        if path == "/labels":
            items.append({"id": 3, "name": "Studio"})
            return {"label": items[-1]}
        assert path == "/counter/11/label/3"
        return {}

    monkeypatch.setattr(analytics, "met", met)
    monkeypatch.setattr(analytics, "counter_info", lambda _: {"labels": []})
    assert analytics.ensure_label(11, "Studio")["attached"]
    assert analytics.ensure_label(11, "Studio")["attached"] and len(items) == 1


def test_webmaster_and_indexnow_host_guard(monkeypatch):
    remote = Mock(return_value={"task_id": "one"})
    monkeypatch.setattr(search, "wm", remote)
    search.submit_url("https:example.org:443", HOME + "p", "recrawl")
    remote.assert_called_once_with(
        "POST", "/https:example.org:443/recrawl/queue", body={"url": HOME + "p"}
    )
    with pytest.raises(ValueError):
        search.submit_url("https:example.org:443", "https://other.org/", "sitemap")
    with pytest.raises(ValueError):
        search.index_pages([HOME, "https://other.org/"])


def test_checked_baseline_survives_partial_scan(monkeypatch):
    current = {"snapshot": {"a": "one"}, "incomplete_pages": []}
    monkeypatch.setattr(watch, "audit", lambda *_: current)
    assert watch.check(HOME)["state"] == "baseline_created"
    assert watch.check(HOME)["state"] == "unchanged"
    current.update(snapshot={"a": "two"}, incomplete_pages=["contact"])
    assert not watch.check(HOME)["baseline_updated"]
    current["incomplete_pages"] = []
    assert watch.check(HOME)["changes"] == [
        {"field": "/a", "before": "one", "after": "two"}
    ]


def test_stdio():
    async def run():
        proc = StdioServerParameters(
            command=sys.executable,
            args=["-m", "site_desk.cli", "serve"],
            env={"SITE_DESK_STATE_DIR": os.environ["SITE_DESK_STATE_DIR"]},
        )
        async with (
            stdio_client(proc) as (reader, writer),
            ClientSession(reader, writer) as client,
        ):
            await client.initialize()
            names = {t.name for t in (await client.list_tools()).tools}
            assert {
                "organization_draft",
                "entrance_map",
                "watch_check",
                "metrica_ensure_goal",
            } <= names
            result = await client.call_tool(
                "entrance_map",
                {"entrance": ENT.model_dump(), "stops": [STOP.model_dump()]},
            )
            assert not result.isError and "rtt=pd" in str(result.content)

    asyncio.run(run())
