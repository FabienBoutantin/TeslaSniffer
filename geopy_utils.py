from geopy import distance
from geopy.geocoders import Nominatim
from random import randint

from pathlib import Path
from json import loads, dumps

from functools import cache as memoize
from threading import Lock

CACHE_PATH = Path("./geo_cache")
CACHE_DATA = {
    "addr": dict(),
    "distance": dict(),
    "coords": dict(),
}
if CACHE_PATH.exists():
    CACHE_DATA.update(loads(CACHE_PATH.read_text("utf-8")))

COMPUTE_LOCK = Lock()
CACHE_LOCK = Lock()


@memoize
def get_addr(coords):
    key = f"{coords}"
    if key not in CACHE_DATA["addr"]:
        COMPUTE_LOCK.acquire()
        try:
            geolocator = Nominatim(user_agent=f"teslaSniffer-{randint(0,256)}")
            location = geolocator.reverse(str(coords)[1:-1])
        finally:
            COMPUTE_LOCK.release()
        address = location.raw['address']
        if 0:
            print(location)
            print(address)
        post_code = int(address.get("postcode", "0"))
        city = address.get("city", address.get("town", address.get("village", "???")))
        municipality = address.get("municipality", "???")
        if city != municipality:
            city += f" [{municipality}]"

        CACHE_DATA["addr"][key] = post_code, city
        CACHE_LOCK.acquire()
        try:
            CACHE_PATH.write_text(dumps(CACHE_DATA, indent=2), "utf-8")
        finally:
            CACHE_LOCK.release()
    return CACHE_DATA["addr"][key]


@memoize
def get_distance(coords, ref_coords):
    key = f"{coords} {ref_coords}"
    if key not in CACHE_DATA["distance"]:
        km = int(distance.distance(coords, ref_coords).km)
        CACHE_DATA["distance"][key] = km
        CACHE_LOCK.acquire()
        try:
            CACHE_PATH.write_text(dumps(CACHE_DATA, indent=2), "utf-8")
        finally:
            CACHE_LOCK.release()
    return CACHE_DATA["distance"][key]


@memoize
def get_coords(country_code, zip_code):
    key = f"{country_code} {zip_code}"
    if key not in CACHE_DATA["coords"]:
        COMPUTE_LOCK.acquire()
        try:
            geolocator = Nominatim(user_agent=f"teslaSniffer-{randint(0,256)}")
            location = geolocator.geocode(zip_code, country_codes=country_code)
            coords = (location.latitude, location.longitude)
        finally:
            COMPUTE_LOCK.release()
        CACHE_DATA["coords"][key] = coords
        CACHE_LOCK.acquire()
        try:
            CACHE_PATH.write_text(dumps(CACHE_DATA, indent=2), "utf-8")
        finally:
            CACHE_LOCK.release()
    return tuple(CACHE_DATA["coords"][key])


if __name__ == "__main__":
    me = (48.6896459, 6.1737197)
    print("My coords:", me, str(me)[1:-1])
    print("My place:", *get_addr(me), get_distance(me, me), "km")
    for item in sorted(Path("car_cards").glob("*.json")):
        print(item.name)
        car_info = loads(item.read_text())

        locations = car_info.get("product", dict()).get("data", dict()).get("ComboVrlData", dict())
        for loc in locations:
            loc_coords = eval(f'({locations[loc]["Geolocation"]})')

            if locations[loc]["IsAtLocation"]:
                print("  ✓ ", loc, "\t", *get_addr(loc_coords), "\t", get_distance(loc_coords, me), "km")
            else:
                print("  ? ", loc, "\t", *get_addr(loc_coords), "\t", get_distance(loc_coords, me), "km")
