import json
import re
from datetime import date
from urllib.parse import parse_qsl, urlencode, urlunsplit
from zoneinfo import ZoneInfo

from .access import credential, domain, met, request, website
from .state import transaction


def positive(value):
    if type(value) is not int or value < 1:
        raise ValueError("Expected a positive integer ID")
    return value


def counter_info(counter_id):
    counter = met("GET", f"/counter/{positive(counter_id)}")["counter"]
    return {
        k: counter[k]
        for k in (
            "id",
            "name",
            "site",
            "site2",
            "mirrors",
            "mirrors2",
            "labels",
            "permission",
            "code",
            "code_status",
            "activity_status",
            "autogoals_enabled",
        )
        if k in counter
    }


def list_counters(offset=1, limit=100):
    if not 1 <= limit <= 1000 or not 1 <= offset <= 100000:
        raise ValueError("limit 1..1000, offset 1..100000")
    data = met("GET", "/counters", params={"offset": offset, "per_page": limit})
    rows = [
        {
            k: r[k]
            for k in ("id", "name", "site", "site2", "permission", "labels")
            if k in r
        }
        for r in data["counters"]
    ]
    more = offset + len(rows)
    return {
        "counters": rows,
        "next_offset": more if len(rows) == limit and more <= 100000 else None,
    }


def counter_domain(row):
    value = (row.get("site2") or {}).get("site") or row.get("site") or ""
    return domain(value if "://" in value else "https://" + value) if value else ""


def ensure_counter(site_url, name, timezone, autogoals):
    site = domain(site_url)
    if website(site_url).path not in ("", "/") or not name.strip():
        raise ValueError("Use the site's home URL and a nonempty counter name")
    ZoneInfo(timezone)
    with transaction():
        matches = []
        offset = 1
        while offset:
            page = list_counters(offset, 1000)
            matches.extend(
                row for row in page["counters"] if counter_domain(row) == site
            )
            offset = page["next_offset"]
        if matches:
            return {"created": False, "existing": matches}
        counter = {
            "name": name.strip(),
            "site2": {"site": site},
            "time_zone_name": timezone,
            "autogoals_enabled": autogoals,
        }
        row = met("POST", "/counters", body={"counter": counter})["counter"]
        return {"created": True, "id": row["id"], "site": site}


def goals(counter_id):
    return met("GET", f"/counter/{positive(counter_id)}/goals")["goals"]


def ensure_goal(counter_id, name, kind, value, match):
    if kind not in ("action", "url", "phone", "email") or match not in (
        "exact",
        "contain",
    ):
        raise ValueError("Unsupported goal or comparison")
    if not name.strip() or not value.strip() or (kind != "url" and match != "exact"):
        raise ValueError("Specify the name, target and an applicable match type")
    if kind == "action" and not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,80}", value):
        raise ValueError(
            "Use letters, digits, underscores or hyphens for the event identifier"
        )
    desired = {
        "name": name,
        "type": kind,
        "conditions": [{"type": match, "url": value}],
    }
    with transaction():
        for row in goals(counter_id):
            conditions = [
                {k: c.get(k) for k in ("type", "url")}
                for c in row.get("conditions") or []
            ]
            if row["type"] == kind and conditions == desired["conditions"]:
                return {"created": False, "goal": row}
            if row["name"] == name:
                raise ValueError(
                    "Another goal uses that name with different conditions"
                )
        return {
            "created": True,
            "goal": met("POST", f"/counter/{counter_id}/goals", body={"goal": desired})[
                "goal"
            ],
        }


def ensure_label(counter_id, name):
    name = name.strip()
    if not name:
        raise ValueError("Label name is required")
    with transaction():
        counter = counter_info(counter_id)
        labels = met("GET", "/labels")["labels"]
        label = next((l for l in labels if l["name"] == name), None)
        if not label:
            label = met("POST", "/labels", body={"label": {"name": name}})["label"]
        attached = any(l["id"] == label["id"] for l in counter.get("labels", []))
        if not attached:
            met("POST", f"/counter/{counter_id}/label/{positive(label['id'])}")
        return {"label": label, "attached": True, "already_attached": attached}


def developer_handoff(counter_id):
    counter = counter_info(counter_id)
    rows = goals(counter_id)
    examples = []
    for row in rows:
        for condition in row.get("conditions") or []:
            if row["type"] == "action" and condition.get("type") == "exact":
                target = json.dumps(condition["url"], ensure_ascii=True).replace(
                    "<", r"\u003c"
                )
                examples.append(
                    {
                        "goal": row["name"],
                        "javascript": f"ym({counter_id}, 'reachGoal', {target});",
                    }
                )
    if not counter.get("code"):
        raise ValueError("Metrica returned no installation code for this counter")
    return {
        "counter_id": counter_id,
        "site": counter_domain(counter),
        "html": counter["code"],
        "events": examples,
        "goals": rows,
        "installation": [
            "Install the returned HTML once per intended page, respecting the site's consent settings.",
            "For a successful lead or payment fire the event only after confirmed success. Deduplicate retries.",
            "In an SPA verify virtual page views on navigation and avoid duplicate initial hits.",
            "Check the tag in the browser, perform one test conversion, then verify goal statistics in Metrica.",
        ],
        "settings": f"https://metrika.yandex.ru/settings?id={counter_id}",
    }


def tagged_link(url, source, medium, campaign, content=None, term=None):
    u = website(url)
    pairs = [
        (k, v)
        for k, v in parse_qsl(u.query, keep_blank_values=True)
        if k.lower()
        not in {"utm_source", "utm_medium", "utm_campaign", "utm_content", "utm_term"}
    ]
    if not all(x.strip() for x in (source, medium, campaign)):
        raise ValueError("Source, medium and campaign are required")
    pairs.extend(
        ("utm_" + k, v)
        for k, v in (
            ("source", source),
            ("medium", medium),
            ("campaign", campaign),
            ("content", content),
            ("term", term),
        )
        if v
    )
    return urlunsplit(u._replace(query=urlencode(pairs)))


def report(counter_id, start, end, dimension, goal_id=None):
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise ValueError("Invalid report period")
    metrics = ["ym:s:visits", "ym:s:users", "ym:s:bounceRate"]
    if goal_id is not None:
        metrics.extend(
            [
                f"ym:s:goal{positive(goal_id)}reaches",
                f"ym:s:goal{goal_id}conversionRate",
            ]
        )
    dims = {
        "sources": "ym:s:lastTrafficSource",
        "utm": "ym:s:lastUTMCampaign",
        "landing": "ym:s:startURLPath",
        "days": "ym:s:date",
    }
    params = {
        "ids": positive(counter_id),
        "metrics": ",".join(metrics),
        "dimensions": dims[dimension],
        "date1": start,
        "date2": end,
        "limit": 100,
    }
    data = request(
        "GET",
        "https://api-metrika.yandex.net/stat/v1/data",
        token=credential("metrica"),
        params=params,
    )
    return {
        k: data[k]
        for k in ("data", "totals", "total_rows", "sampled", "sample_share", "query")
        if k in data
    }
