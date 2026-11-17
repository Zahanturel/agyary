"""Distances from each fire temple to the nearest Parsi funeral place (dokhma / aramgah / prayer hall).

Inputs: temples_geo.json (from geocode.py) and the SITES list below.
Outputs: prints the tables used in docs/phase2-doongerwadi-research.md, and writes distances.json.
"""
import json, math, sys, time, urllib.parse, urllib.request
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
HERE = Path(__file__).parent

# Hand corrections where the town lookup landed in the wrong place (approximate town centres).
FIX = {"Bordi, Maharashtra, India": (20.105, 72.740), "Thane, Maharashtra, India": (19.197, 72.972),
       "Valsad, Gujarat, India": (20.610, 72.930)}

# Mumbai temples placed by neighbourhood (approximate). None = neighbourhood not certain, city centre kept.
MUMBAI = {"Fanaswadi": (18.951, 72.826), "Dhobi Talao": (18.946, 72.829), "Charni Road": (18.952, 72.819),
          "Andheri West": (19.136, 72.830), "Hill Road Bandra W": (19.056, 72.831), "Turner Rd. Bandra": (19.062, 72.834),
          "Byculla": (18.979, 72.833), "Afghan Church": (18.906, 72.815), "Cusrow Baug": (18.915, 72.829),
          "Dadar Parsi Colony": (19.017, 72.848), "Dadar Rly Station": (19.018, 72.843), "Marine Lines Station": (18.945, 72.824),
          "Dookar Gali D.Talao": (18.946, 72.829), "Gola Street Fort": (18.934, 72.836), "Cawasji Patel street": (18.934, 72.834),
          "Bora Bajar Fort": (18.935, 72.836), "D N Rd. Fort": (18.936, 72.834), "Fountain Fort": (18.932, 72.832),
          "Banaji St. Fort": (18.934, 72.835), "Gdorej Baug": (18.958, 72.805), "Gowalia Tank": (18.962, 72.810),
          "Sleater Rd Grant Rd": (18.962, 72.817), "Lamington Road": (18.960, 72.820), "Corner of Grant Rd": (18.963, 72.816),
          "Malcolm Baug": (19.137, 72.846), "Lal Baug": (18.994, 72.834), "Mazagoan": (18.967, 72.844),
          "Tardeo": (18.969, 72.814), "Churchgate": (18.932, 72.826), "Warden Road": (18.968, 72.806),
          "Karelwadi Marine": (18.952, 72.822), "Hughes Road": (18.960, 72.809), "Balaram St Grant Rd": (18.962, 72.820),
          "Khetwadi Dadi St": (18.959, 72.822), "Walkeshwar": (18.947, 72.795), "Doongerwadi": (18.957, 72.806),
          "Cama Baug": None, "Contractor Baug": None}

# Villages outside the city named in the address; looked up separately.
VILLAGES = {"Kudiana Olpad Taluka": "Kudiyana, Olpad, Surat, Gujarat, India", "Post Mahuva": "Mahuva, Surat, Gujarat, India",
            "Parsi Vad, Olpad": "Olpad, Surat, Gujarat, India", "Post Suvali Taluka Choryasi": "Suvali, Surat, Gujarat, India",
            "Post Elav": "Elav, Hansot, Bharuch, Gujarat, India"}

# Funeral places. kind: dokhma / aramgah / prayer hall (cremation). status: what the sources say.
# Coordinates are approximate (neighbourhood or town level), good to a few km.
SITES = [
    ("Mumbai, Doongerwadi (Malabar Hill)", 18.957, 72.806, "dokhma", "in use (BPP site)"),
    ("Mumbai, Worli Prayer Hall (cremation)", 19.006, 72.817, "prayer hall", "in use since 2015"),
    ("Surat (Surat Parsi Panchayat)", 21.195, 72.825, "dokhma", "in use 2022 (Supreme Court case); exact place to confirm"),
    ("Navsari", 20.952, 72.932, "dokhma", "to confirm"),
    ("Bilimora", 20.767, 72.969, "dokhma", "listed as in use by one weak source; to confirm"),
    ("Udvada", 20.470, 72.910, "dokhma", "exists; use to confirm"),
    ("Bharuch", 21.708, 72.996, "dokhma", "exists (old); use to confirm"),
    ("Pune", 18.521, 73.855, "dokhma", "exists; place and use to confirm"),
    ("Secunderabad, Bhoiguda", 17.418, 78.497, "dokhma", "consecrated 1839; in use per 2017 reports"),
    ("Hyderabad, Zamistanpur", 17.407, 78.507, "dokhma", "Parsi Zoroastrian Anjuman; in use per reports"),
    ("Kolkata, Beleghata", 22.561, 88.392, "dokhma", "exists; under strain, use to confirm"),
    ("Bengaluru, Bellary Road", 13.020, 77.585, "dokhma", "opened 1940; Anjuman runs it; rarely used"),
    ("Chennai, Royapuram Bagh", 13.110, 80.293, "aramgah", "Anjuman burial ground"),
    ("New Delhi, Prithviraj Road", 28.600, 77.218, "aramgah", "Delhi Parsi Anjuman burial ground"),
    ("Karachi, Mehmoodabad", 24.840, 67.080, "dokhma", "in use per 2024 report"),
]


def km(a, b):
    (la1, lo1), (la2, lo2) = a, b
    p1, p2 = math.radians(la1), math.radians(la2)
    dp, dl = p2 - p1, math.radians(lo2 - lo1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(h))


def village(q, cache):
    if q in cache:
        return cache[q]
    url = "https://nominatim.openstreetmap.org/search?" + urllib.parse.urlencode({"q": q, "format": "json", "limit": 1})
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "research-script/1.0"}), timeout=40) as r:
        res = json.load(r)
    time.sleep(1.1)
    cache[q] = {"lat": float(res[0]["lat"]), "lon": float(res[0]["lon"]), "name": res[0]["display_name"]} if res else None
    (HERE / "geocache.json").write_text(json.dumps(cache, indent=1, ensure_ascii=False), encoding="utf-8")
    return cache[q]


def main():
    temples = json.loads((HERE / "temples_geo.json"  ).read_text(encoding="utf-8"))
    cache = json.loads((HERE / "geocache.json").read_text(encoding="utf-8"))
    rows = []
    for t in temples:
        pos, how = (t["geo"]["lat"], t["geo"]["lon"]), "town"
        if t["query"] in FIX:
            pos, how = FIX[t["query"]], "town (hand-corrected)"
        if t["city"] == "Mumbai":
            m = MUMBAI.get(t["address"])
            if m:
                pos, how = m, "neighbourhood"
            else:
                how = "city centre (neighbourhood unsure)"
        if t["address"] in VILLAGES:
            g = village(VILLAGES[t["address"]], cache)
            if g:
                pos, how = (g["lat"], g["lon"]), "village"
                print("village", t["address"], "->", g["name"][:70])
        ds = sorted(((km(pos, (s[1], s[2])), s) for s in SITES), key=lambda x: x[0])
        dok = [x for x in ds if x[1][3] == "dokhma"]
        rows.append({"name": t["name"], "type": t["type"], "city": t["city"], "address": t["address"], "placed_by": how,
                     "nearest": ds[0][1][0], "nearest_km": round(ds[0][0], 1),
                     "nearest_dokhma": dok[0][1][0], "nearest_dokhma_km": round(dok[0][0], 1),
                     "second_km": round(ds[1][0], 1), "second": ds[1][1][0]})
    (HERE / "distances.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")

    india = [r for r in rows if not r["city"] in ("Tehran", "Kerman", "Shiraz", "Yazd", "Kooche Sichan", "New S.Wales",
                                                 "Toranto", "Burnaby BC", "Hong Kong", "Colombo", "Hampstead")]
    print(f"\n{len(rows)} temples; {len(india)} in India and Pakistan\n")

    print("== Per funeral place: temples whose nearest place it is (India+Pakistan) ==")
    by = defaultdict(list)
    for r in india:
        by[r["nearest"]].append(r["nearest_km"])
    for s in SITES:
        v = sorted(by.get(s[0], []))
        if v:
            print(f"{s[0]:42} {len(v):3} temples  median {v[len(v)//2]:6.1f} km  max {v[-1]:6.1f} km")

    print("\n== How far is each temple from its nearest funeral place ==")
    bands = [5, 10, 15, 20, 25, 30, 40, 50, 75, 100, 200, 10_000]
    prev = 0
    for b in bands:
        n = sum(1 for r in india if prev <= r["nearest_km"] < b)
        cum = sum(1 for r in india if r["nearest_km"] < b)
        print(f"  {prev:>4}-{b if b < 10_000 else '...':>4} km: {n:3}   (cumulative {cum:3} = {100*cum/len(india):5.1f}%)")
        prev = b

    print("\n== Radius test: temples within R of at least one place, and within R of two or more ==")
    for R in [10, 15, 20, 25, 30, 40, 50]:
        within = sum(1 for r in india if r["nearest_km"] <= R)
        two = sum(1 for r in india if r["second_km"] <= R)
        print(f"  R={R:3} km: {within:3} covered ({100*within/len(india):5.1f}%), {two:3} near two or more places")

    print("\n== Distances between neighbouring Gujarat / Mumbai funeral places ==")
    names = ["Mumbai, Doongerwadi (Malabar Hill)", "Mumbai, Worli Prayer Hall (cremation)", "Surat (Surat Parsi Panchayat)",
             "Navsari", "Bilimora", "Udvada", "Bharuch", "Pune", "Secunderabad, Bhoiguda", "Hyderabad, Zamistanpur"]
    S = {s[0]: (s[1], s[2]) for s in SITES}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            d = km(S[a], S[b])
            if d < 120:
                print(f"  {a:40} <-> {b:40} {d:6.1f} km")

    print("\n== Temples far (> 50 km) from any place ==")
    for r in sorted(india, key=lambda r: -r["nearest_km"]):
        if r["nearest_km"] > 50:
            print(f"  {r['city']:14} {r['name'][:40]:40} {r['type']:13} -> {r['nearest']} {r['nearest_km']} km")


if __name__ == "__main__":
    main()
