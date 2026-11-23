"""Geocode the fire temples' towns with OpenStreetMap Nominatim (1 request per second).

Only town / village names are sent. Results are cached in geocache.json next to this script.
Usage: python -I geocode.py <path to fire_temples.json>
"""
import json, sys, time, urllib.parse, urllib.request
from pathlib import Path

HERE = Path(__file__).parent
CACHE = HERE / "geocache.json"

# The list's state names were corrected on 23 Nov 2026 (Gujarat, Rajasthan, Telangana,
# Madhya Pradesh, Uttar Pradesh); the old spellings are kept so an older copy still reads.
# Hyderabad and Secunderabad have been in Telangana since 2014, which is what the map knows.
STATE_FIX = {"Gujerat": "Gujarat", "A.P": "Telangana", "Andhra Pradesh": "Telangana", "MP": "Madhya Pradesh",
             "UP": "Uttar Pradesh", "Rajashtan": "Rajasthan", "Bihar": "Jharkhand", "New Delhi": "Delhi"}
CITY_FIX = {"Udwada": "Udvada", "Secundrabad": "Secunderabad", "Hydrabad": "Hyderabad", "Aahmednagar": "Ahmednagar",
            "Baroda": "Vadodara", "Billimora": "Bilimora", "Calcutta": "Kolkata", "Calicut": "Kozhikode",
            "Queta": "Quetta", "Toranto": "Toronto", "Dhanu": "Dahanu", "Sholapur": "Solapur", "Golvad": "Bordi",
            "Rander Surat": "Rander", "Bhuj Kutch": "Bhuj", "Killa Pardi": "Pardi", "Ichhapore": "Ichchhapor"}
# Towns hidden in the address for "Via X" / "Dist X" / Sanjan-area rows
ADDRESS_TOWN = {"Amroli": "Amroli", "Post Bhatha": "Bhatha", "Agiary Street Post Vesu": "Vesu", "Bodhan Via Kim": "Bodhan",
                "Parsi wad Dumas": "Dumas", "Parsi Vad Vyra": "Vyara", "Chikhli": "Chikhli", "Davier": "Dehri",
                "Nani Daman": "Nani Daman", "Nargol": "Nargol", "Saronda": "Sanjan", "Rai Wadi Udhwa road": "Sanjan",
                "Khergam Bazar, Valsad": "Khergam"}
ABROAD = {"Tehran": "Tehran, Iran", "Kerman": "Kerman, Iran", "Shiraz": "Shiraz, Iran", "Yazd": "Yazd, Iran",
          "Kooche Sichan": "Tehran, Iran", "Karachi": "Karachi, Pakistan", "Lahore": "Lahore, Pakistan",
          "Queta": "Quetta, Pakistan", "New S.Wales": "Sydney, Australia", "Toranto": "Toronto, Canada",
          "Burnaby BC": "Burnaby, Canada", "Hong Kong": "Hong Kong", "Colombo": "Colombo, Sri Lanka",
          "Hampstead": "Hampstead, London, United Kingdom"}


def query_for(t):
    city, state, addr = t["city"].strip(), t["state"].strip(), t["address"].strip()
    if city in ABROAD:
        return ABROAD[city]
    town = ADDRESS_TOWN.get(addr)
    if town is None:
        town = CITY_FIX.get(city, city)
    if town == "Dehri":  # Davier, near Sanjan (Umbergaon taluka); not on the map, so Sanjan is used
        return "Sanjan, Gujarat, India"
    if town == "Nani Daman":
        return "Nani Daman, Daman, India"
    if town == "Dahanu" and "Road" in addr:
        return "Dahanu Road, Maharashtra, India"
    return f"{town}, {STATE_FIX.get(state, state)}, India"


def geocode(q, cache):
    if q in cache:
        return cache[q]
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1})
    req = urllib.request.Request(url, headers={"User-Agent": "research-script/1.0"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=40) as r:
                res = json.load(r)
            break
        except Exception as e:
            print("retry", q, e); time.sleep(5)
    else:
        raise SystemExit("gave up on " + q)
    time.sleep(1.1)
    cache[q] = {"lat": float(res[0]["lat"]), "lon": float(res[0]["lon"]), "name": res[0]["display_name"]} if res else None
    CACHE.write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    return cache[q]


def main():
    temples = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    cache = json.loads(CACHE.read_text(encoding="utf-8")) if CACHE.exists() else {}
    out = []
    for t in temples:
        q = query_for(t)
        g = geocode(q, cache)
        out.append({**t, "query": q, "geo": g})
        if not g:
            print("NOT FOUND:", q)
    (HERE / "temples_geo.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    print(len(out), "temples,", len({o["query"] for o in out}), "places,", sum(1 for o in out if not o["geo"]), "not found")


if __name__ == "__main__":
    main()
