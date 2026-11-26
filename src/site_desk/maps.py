import math
import xml.etree.ElementTree as ET
from typing import Annotated
from urllib.parse import urlencode

from pydantic import BaseModel, Field

from .access import credential, request


class Place(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    lat: Annotated[float, Field(ge=-90, le=90, allow_inf_nan=False)]
    lon: Annotated[float, Field(ge=-180, le=180, allow_inf_nan=False)]


def distance(a, b):
    lat = math.radians(b.lat - a.lat)
    lon = math.radians(b.lon - a.lon)
    half = (
        math.sin(lat / 2) ** 2
        + math.cos(math.radians(a.lat))
        * math.cos(math.radians(b.lat))
        * math.sin(lon / 2) ** 2
    )
    return 6371000 * 2 * math.asin(math.sqrt(min(1, half)))


def geocode(query, metro=False):
    params = {
        "apikey": credential("geocoder"),
        "geocode": query,
        "lang": "ru_RU",
        "format": "json",
        "results": 5,
    }
    if metro:
        params["kind"] = "metro"
    response = request("GET", "https://geocode-maps.yandex.ru/v1/", params=params)
    features = response["response"]["GeoObjectCollection"]["featureMember"]
    result = []
    for feature in features:
        obj = feature["GeoObject"]
        lon, lat = map(float, obj["Point"]["pos"].split())
        metadata = obj["metaDataProperty"]["GeocoderMetaData"]
        if metro and metadata.get("kind") != "metro":
            continue
        result.append(
            {
                "place": Place(name=obj["name"], lat=lat, lon=lon).model_dump(),
                "description": obj.get("description"),
                "precision": metadata.get("precision"),
                "kind": metadata.get("kind"),
            }
        )
    return result


def nearby(entrance, source, radius):
    if not 100 <= radius <= 3000:
        raise ValueError("Choose a radius between 100 and 3000 metres")
    if source == "yandex_metro":
        places = [
            Place(**r["place"])
            for r in geocode(f"{entrance.lon},{entrance.lat}", metro=True)
        ]
        credit = "Яндекс Карты"
    else:
        # A bounded public transit lookup. Only the entrance coordinates leave this process.
        around = f"(around:{radius},{entrance.lat},{entrance.lon})"
        query = (
            f'[out:json][timeout:12];(node["highway"="bus_stop"]{around};'
            f'node["railway"~"^(tram_stop|subway_entrance)$"]{around};'
            f'node["public_transport"="platform"]{around};);out body 300;'
        )
        data = request(
            "GET", "https://overpass-api.de/api/interpreter", params={"data": query}
        )
        if data.get("remark"):
            raise ValueError("Overpass returned an incomplete transit search")
        places = []
        for row in data["elements"]:
            tags = row.get("tags", {})
            name = tags.get("name") or tags.get("ref")
            if name:
                places.append(Place(name=name, lat=row["lat"], lon=row["lon"]))
        credit = (
            "© OpenStreetMap contributors · https://www.openstreetmap.org/copyright"
        )
    rows = sorted(
        ((distance(entrance, p), p) for p in places), key=lambda pair: pair[0]
    )
    return {
        "candidates": [
            {"place": p.model_dump(), "straight_line_metres": round(d)}
            for d, p in rows
            if d <= radius
        ][:12],
        "attribution": credit,
        "ranking": "straight-line distance among returned candidates",
    }


def walking_link(start, entrance):
    params = {
        "rtext": f"{start.lat},{start.lon}~{entrance.lat},{entrance.lon}",
        "rtt": "pd",
    }
    return "https://yandex.ru/maps/?" + urlencode(params)


def route(start, end):
    points = f"{start.lat},{start.lon}|{end.lat},{end.lon}"
    data = request(
        "GET",
        "https://api.routing.yandex.net/v2/route",
        params={"apikey": credential("router"), "waypoints": points, "mode": "walking"},
    )
    legs = (data.get("route") or {}).get("legs") or []
    if not legs or any(leg.get("status") != "OK" for leg in legs):
        raise ValueError("The routing API found no walkable route")
    geometry = []
    metres = seconds = 0
    for leg in legs:
        for step in leg.get("steps", []):
            metres += step["length"]
            seconds += step["duration"]
            for lat, lon in step["polyline"]["points"]:
                if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                    raise ValueError("Invalid route coordinates from provider")
                if not geometry or geometry[-1] != (lat, lon):
                    geometry.append((lat, lon))
    if len(geometry) < 2:
        raise ValueError("Routing response contains no usable walking geometry")
    return geometry, round(metres), round(seconds)


def directions(entrance, stops, use_routing, export_geometry):
    if not 1 <= len(stops) <= 8:
        raise ValueError("Supply between one and eight departure points")
    doc = ET.Element(
        "gpx",
        version="1.1",
        creator="Site Desk",
        xmlns="http://www.topografix.com/GPX/1/1",
    )
    meta = ET.SubElement(doc, "metadata")
    ET.SubElement(
        meta, "desc"
    ).text = "Transit stops may include © OpenStreetMap contributors (openstreetmap.org/copyright). Walking geometry, when supplied, is from Yandex Maps."
    for p in [entrance, *stops]:
        wpt = ET.SubElement(doc, "wpt", lat=str(p.lat), lon=str(p.lon))
        ET.SubElement(wpt, "name").text = p.name
    routes = []
    for p in stops:
        item = {
            "from": p.name,
            "to": entrance.name,
            "open_route": walking_link(p, entrance),
        }
        if use_routing:
            try:
                geometry, metres, seconds = route(p, entrance)
                item.update(walking_metres=metres, walking_seconds=seconds)
                if export_geometry:
                    trk = ET.SubElement(doc, "trk")
                    ET.SubElement(trk, "name").text = p.name + " → " + entrance.name
                    seg = ET.SubElement(trk, "trkseg")
                    for lat, lon in geometry:
                        ET.SubElement(seg, "trkpt", lat=str(lat), lon=str(lon))
            except ValueError as exc:
                item["routing_error"] = str(exc)
        routes.append(item)
    routes.sort(key=lambda item: item.get("walking_metres", float("inf")))
    return {
        "routes": routes,
        "constructor": "https://yandex.ru/map-constructor/",
        "gpx": ET.tostring(doc, encoding="unicode"),
        "track_count": len(doc.findall("trk")),
        "instructions": "Save GPX as directions.gpx. Create a new map, choose Import, select the GPX, review markers and tracks, add arrows, then save.",
    }
