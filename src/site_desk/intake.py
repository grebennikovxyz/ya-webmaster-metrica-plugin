"""Read only public site pages, pinning the validated IP for each hop."""

import http.client
import ipaddress
import json
import re
import socket
import ssl
from urllib.parse import quote, unquote, urljoin, urlsplit, urlunsplit

import certifi
from bs4 import BeautifulSoup

from .access import domain, website

MAX_BYTES = 2_000_000
FIELDS = (
    "name",
    "legalName",
    "description",
    "telephone",
    "email",
    "address",
    "openingHours",
    "openingHoursSpecification",
    "geo",
    "url",
    "sameAs",
    "logo",
    "priceRange",
    "hasMap",
    "contactPoint",
)
CONTACT = re.compile(
    r"контакт|contact|как добраться|о компании|about[- ]?us", re.IGNORECASE
)


def public_page(url, allowed=None):
    for _ in range(6):
        u = website(url)
        host = domain(url)
        if allowed and host not in allowed:
            raise ValueError("Redirect outside the selected website")
        port = 443 if u.scheme == "https" else 80
        records = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [ipaddress.ip_address(r[4][0]) for r in records]
        if not addresses or any(
            not ip.is_global
            or ip.is_multicast
            or getattr(ip, "ipv4_mapped", None)
            or getattr(ip, "sixtofour", None)
            or getattr(ip, "teredo", None)
            for ip in addresses
        ):
            raise ValueError("Only publicly routed website addresses are supported")
        connection = http.client.HTTPConnection(host, port, timeout=10)
        try:
            connection.sock = socket.create_connection((str(addresses[0]), port), 10)
            if u.scheme == "https":
                context = ssl.create_default_context()
                context.load_verify_locations(cafile=certifi.where())
                connection.sock = context.wrap_socket(
                    connection.sock, server_hostname=host
                )
            path = quote(u.path or "/", safe="/%:@!$&'()*+,;=-._~")
            query = quote(u.query, safe="=&%/:+?,@")
            connection.request(
                "GET",
                path + ("?" + query if query else ""),
                headers={"User-Agent": "Ya-Webmaster/0.1", "Accept": "text/html"},
            )
            res = connection.getresponse()
            if res.status in (301, 302, 303, 307, 308) and res.getheader("Location"):
                url = urljoin(url, res.getheader("Location"))
                continue
            if (
                res.status != 200
                or "html" not in res.getheader("Content-Type", "").lower()
            ):
                raise ValueError(f"Expected an HTML page, HTTP {res.status}")
            data = res.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("Page exceeds 2 MB")
            return urlunsplit((u.scheme, u.netloc, u.path or "/", "", "")), data
        finally:
            connection.close()
    raise ValueError("Too many redirects")


def nodes(value):
    if isinstance(value, list):
        for item in value:
            yield from nodes(item)
    elif isinstance(value, dict):
        yield value
        for item in value.values():
            if isinstance(item, (list, dict)):
                yield from nodes(item)


def parse_page(source, data):
    soup = BeautifulSoup(data, "html.parser")
    orgs = []
    for script in soup.find_all(
        "script", type=re.compile(r"application/ld\+json", re.IGNORECASE)
    ):
        try:
            graph = json.loads(script.string or "")
        except (ValueError, RecursionError):
            continue
        for obj in nodes(graph):
            kind = obj.get("@type", "")
            kinds = kind if isinstance(kind, list) else [kind]
            if not (
                obj.get("name")
                and (
                    any(
                        t
                        in (
                            "Organization",
                            "LocalBusiness",
                            "Corporation",
                            "Store",
                            "Restaurant",
                            "MedicalClinic",
                            "ProfessionalService",
                        )
                        for t in kinds
                    )
                    or (
                        "address" in obj
                        and any(k in obj for k in ("telephone", "openingHours", "geo"))
                    )
                )
            ):
                continue
            entry = {k: obj[k] for k in FIELDS if k in obj}
            entry["@type"] = kind
            if (
                len(json.dumps(entry, ensure_ascii=False)) <= 12000
                and entry not in orgs
            ):
                orgs.append(entry)
    phones, emails, contact_links = set(), set(), []
    signals = set()
    for a in soup.select("a[href]"):
        href = a.get("href", "").strip()
        if href.lower().startswith(("tel:", "mailto:")):
            is_phone = href.lower().startswith("tel:")
            (phones if is_phone else emails).add(
                unquote(href.split(":", 1)[1].split("?")[0])[:160]
            )
            signals.add("phone_click" if is_phone else "email_click")
        target = urljoin(source, href)
        if (
            CONTACT.search(a.get_text(" ", strip=True) + " " + href)
            and len(contact_links) < 12
            and urlsplit(target).netloc == urlsplit(source).netloc
            and not urlsplit(target).query
        ):
            contact_links.append(target.split("#")[0])
        if "yandex." in href.lower() and ("maps" in href.lower() or "rtext=" in href):
            signals.add("directions_click")
    if soup.select_one("form"):
        signals.add("form_present")
    raw = str(soup)
    counters = sorted(
        set(
            re.findall(
                r"(?:\bym\s*\(\s*['\"]?|mc\.yandex\.(?:ru|com)/watch/)([1-9]\d{2,11})",
                raw,
            )
        )
    )

    def meta(**attrs):
        found = soup.find("meta", attrs=attrs)
        return found.get("content", "")[:1500] if found else ""

    site_name = meta(property="og:site_name")
    description = meta(name="description") or meta(property="og:description")
    title = soup.title.get_text(" ", strip=True)[:250] if soup.title else ""
    address = [
        n.get_text(" ", strip=True)[:600]
        for n in soup.select("address, [itemprop=streetAddress]")
    ][:8]
    for elem in soup(["script", "style", "nav", "header", "footer", "template"]):
        elem.decompose()
    lines = [
        s.strip()[:350]
        for s in soup.stripped_strings
        if re.search(
            r"улица|улиц[аеы] |(?:ул|пр-т|наб|пер)\.\s|режим работы|часы работы|ежедневно|понедельник|пн[–—-]|вход |street|opening hours",
            s,
            re.IGNORECASE,
        )
    ]
    return {
        "source": source,
        "title": title,
        "site_name": site_name,
        "description": description,
        "organizations": orgs[:12],
        "phones": sorted(phones)[:20],
        "emails": sorted(emails)[:20],
        "addresses": address,
        "contact_evidence": list(dict.fromkeys(lines))[:18],
        "signals": sorted(signals),
        "counter_ids": counters,
    }, list(dict.fromkeys(contact_links))


def inspect_site(url):
    base = domain(url)
    naked = base.removeprefix("www.")
    allowed = {naked, "www." + naked}
    source, data = public_page(url, allowed)
    first, links = parse_page(source, data)
    pages, warnings, visited = [first], [], {source.rstrip("/")}
    for link in links:
        if len(visited) >= 4:
            break
        if link.rstrip("/") in visited:
            continue
        visited.add(link.rstrip("/"))
        try:
            final, data = public_page(link, allowed)
            if not any(page["source"] == final for page in pages):
                pages.append(parse_page(final, data)[0])
        except (OSError, ValueError, http.client.HTTPException) as error:
            warnings.append({"page": link, "error": type(error).__name__})
    return {"pages": pages, "incomplete_pages": warnings}


def business_draft(url):
    evidence = inspect_site(url)
    pages = evidence["pages"]
    candidates = {}

    def add(field, value, source):
        if value:
            entry = {"value": value, "source": source}
            if entry not in candidates.setdefault(field, []):
                candidates[field].append(entry)

    for page in pages:
        for org in page["organizations"]:
            for k in FIELDS:
                add(k, org.get(k), page["source"])
        for k, values in (
            ("telephone", page["phones"]),
            ("email", page["emails"]),
            ("address", page["addresses"]),
        ):
            for v in values:
                add(k, v, page["source"])
        add("description", page["description"], page["source"])
        add("name", page["site_name"], page["source"])
    return {
        "website": pages[0]["source"],
        "fields": candidates,
        "evidence": evidence,
        "needs_confirmation": [
            k
            for k in (
                "name",
                "address",
                "telephone",
                "openingHours",
                "category",
                "entrance",
            )
            if not candidates.get(k)
            and not (
                k == "openingHours" and candidates.get("openingHoursSpecification")
            )
        ],
        "business_cabinet": "https://business.yandex.ru/companies/",
        "webmaster_cabinet": "https://webmaster.yandex.ru/sites/",
    }
