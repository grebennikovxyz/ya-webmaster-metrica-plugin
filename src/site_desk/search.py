import re
from urllib.parse import quote, urlunsplit

from .access import credential, domain, request, website, wm


def host_path(host_id):
    if not re.fullmatch(r"https?:[^/\\?#\s]+:\d{1,5}", host_id):
        raise ValueError("Use host_id from webmaster_sites")
    return "/" + quote(host_id, safe=":")


def site_origin(url):
    u = website(url)
    return urlunsplit((u.scheme, u.netloc, "", "", ""))


def add_site(site_url):
    origin = site_origin(site_url)
    for row in wm("GET").get("hosts", []):
        if site_origin(row["host_url"]) == origin:
            return {"created": False, "host_id": row["host_id"]}
    return {"created": True, **wm("POST", body={"host_url": origin})}


def site_read(host_id, section, limit=30):
    paths = {
        "verification": "/verification",
        "diagnostics": "/diagnostics",
        "summary": "/summary",
        "sitemaps": "/sitemaps",
        "submitted_sitemaps": "/user-added-sitemaps/",
        "recrawls": "/recrawl/queue",
        "quota": "/recrawl/quota",
        "queries": "/search-queries/popular",
    }
    params = None
    if section == "queries":
        params = {
            "order_by": "TOTAL_SHOWS",
            "query_indicator": ["TOTAL_SHOWS", "TOTAL_CLICKS"],
            "limit": min(500, max(1, limit)),
        }
    return wm("GET", host_path(host_id) + paths[section], params=params)


def submit_url(host_id, url, task):
    u = website(url)
    if (
        f"{u.scheme}:{domain(url)}:{u.port or (443 if u.scheme == 'https' else 80)}"
        != host_id
    ):
        raise ValueError("URL must belong to the exact selected Webmaster host")
    path = "/user-added-sitemaps/" if task == "sitemap" else "/recrawl/queue"
    return wm("POST", host_path(host_id) + path, body={"url": url})


def index_pages(urls, key_location=None):
    if not 1 <= len(urls) <= 10000:
        raise ValueError("Submit 1..10000 URLs")
    host = domain(urls[0])
    if any(domain(u) != host for u in urls) or (
        key_location and domain(key_location) != host
    ):
        raise ValueError("Every URL and the key file must have the same host")
    key = credential("indexnow")
    if not re.fullmatch(r"[A-Za-z0-9-]{8,128}", key):
        raise ValueError("Invalid IndexNow key format")
    body = {"host": host, "key": key, "urlList": list(dict.fromkeys(urls))}
    if key_location:
        body["keyLocation"] = key_location
    return request("POST", "https://yandex.com/indexnow", body=body, allow_text=True)
