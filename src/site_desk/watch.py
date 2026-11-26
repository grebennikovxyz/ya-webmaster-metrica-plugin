import json

from . import analytics, intake, search
from .access import domain, website
from .state import transaction


def audit(site_url, host_id=None, counter_id=None):
    inspected = intake.inspect_site(site_url)
    pages = inspected["pages"]
    hostname = domain(pages[0]["source"])
    snapshot = {
        "pages": {
            p["source"]: {
                k: p[k]
                for k in (
                    "title",
                    "description",
                    "site_name",
                    "organizations",
                    "addresses",
                    "phones",
                    "emails",
                    "contact_evidence",
                    "counter_ids",
                    "signals",
                )
            }
            for p in pages
        }
    }
    found = sorted({v for p in pages for v in p["counter_ids"]})
    result = {
        "snapshot": snapshot,
        "incomplete_pages": inspected["incomplete_pages"],
        "installed_counter_ids": found,
    }
    if host_id:
        detail = search.wm("GET", search.host_path(host_id))
        if domain(detail["host_url"]).removeprefix("www.") != hostname.removeprefix(
            "www."
        ):
            raise ValueError("Webmaster host belongs to another site")
        snapshot["webmaster"] = {
            "verified": detail.get("verified"),
            "diagnostics": search.site_read(host_id, "diagnostics").get("problems", {}),
        }
    if counter_id:
        counter = analytics.counter_info(counter_id)
        primary = analytics.counter_domain(counter)
        mirrors = [
            v.get("site", "") if isinstance(v, dict) else v
            for v in (counter.get("mirrors2") or counter.get("mirrors") or [])
        ]
        hosts = {
            domain(v if "://" in v else "https://" + v).removeprefix("www.")
            for v in [primary, *mirrors]
            if v
        }
        if hostname.removeprefix("www.") not in hosts:
            raise ValueError("Metrica counter belongs to another site")
        rows = analytics.goals(counter_id)
        snapshot["metrica"] = {
            "id": counter_id,
            "found_in_html": str(counter_id) in found,
            "goals": {
                str(g["id"]): {
                    k: g[k] for k in ("name", "type", "conditions") if k in g
                }
                for g in rows
            },
            "labels": sorted(l["name"] for l in counter.get("labels", [])),
        }
        result["linking"] = {
            "counter_settings": f"https://metrika.yandex.ru/settings?id={counter_id}",
            "webmaster": "https://webmaster.yandex.ru/sites/",
            "guide": "https://yandex.ru/support/webmaster/ru/indexing-options/link-metrica",
            "status": "Confirm the association in the two cabinets.",
        }
    return result


def changes(old, new, path=""):
    if isinstance(old, dict) and isinstance(new, dict):
        result = []
        for k in sorted(old.keys() | new.keys()):
            p = f"{path}/{k}"
            if k not in old or k not in new:
                result.append({"field": p, "before": old.get(k), "after": new.get(k)})
            else:
                result.extend(changes(old[k], new[k], p))
        return result
    return [] if old == new else [{"field": path, "before": old, "after": new}]


def check(site_url, host_id=None, counter_id=None):
    u = website(site_url)
    if u.query or u.fragment:
        raise ValueError("Monitor a canonical page URL without a query or fragment")
    key = json.dumps([u.geturl().rstrip("/"), host_id, counter_id])
    # Take the writer lock before reading remote state to avoid out-of-order baselines.
    with transaction() as db:
        data = audit(site_url, host_id, counter_id)
        if data["incomplete_pages"]:
            return {
                "state": "incomplete",
                "pages": data["incomplete_pages"],
                "baseline_updated": False,
            }
        snap = data["snapshot"]
        row = db.execute(
            "SELECT snapshot FROM watches WHERE target=?", (key,)
        ).fetchone()
        delta = changes(json.loads(row[0]), snap) if row else []
        db.execute(
            "INSERT OR REPLACE INTO watches VALUES (?,?)",
            (key, json.dumps(snap, ensure_ascii=False)),
        )
    return {
        "state": ("changed" if delta else "unchanged") if row else "baseline_created",
        "changes": delta,
        "baseline_updated": True,
    }
