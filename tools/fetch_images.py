"""Fetch free stock photos into stock/<batch>/. Sources: pexels (needs PEXELS_KEY), pixabay (PIXABAY_KEY), openverse (no key, commercial CC only)."""
import os, sys, json, time, io, urllib.request, urllib.parse
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
batch, source, spec = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])  # spec: {"name": "query", ...}
out = f"stock/{batch}"; os.makedirs(out, exist_ok=True)
UA = {"User-Agent": "webminds-videos/1.0"}
def get(url, headers=None):
    req = urllib.request.Request(url, headers={**UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=30) as r: return r.read()
credits = {}
for name, q in spec.items():
    try:
        if source in ("urls", "files"):
            picks = [(q, "generated", "")]
        elif source == "pexels":
            d = json.loads(get("https://api.pexels.com/v1/search?" + urllib.parse.urlencode({"query": q, "orientation": "portrait", "per_page": 3}), {"Authorization": os.environ["PEXELS_KEY"]}))
            ph = d["photos"]; picks = [(p["src"]["large2x"], f'{p["photographer"]} / Pexels', p["url"]) for p in ph]
        elif source == "pixabay":
            d = json.loads(get("https://pixabay.com/api/?" + urllib.parse.urlencode({"key": os.environ["PIXABAY_KEY"], "q": q, "orientation": "vertical", "image_type": "photo", "per_page": 3, "safesearch": "true"})))
            picks = [(h["largeImageURL"], f'{h["user"]} / Pixabay', h["pageURL"]) for h in d["hits"]]
        else:
            d = json.loads(get("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode({"q": q, "license": "cc0,pdm", "page_size": 6, "mature": "false"})))
            picks = [(r["url"], f'{r.get("creator")} / {r.get("license")} {r.get("license_version")}', r["foreign_landing_url"]) for r in d["results"]]
        for i, (u, by, page) in enumerate(picks[:4]):
            fn = f"{out}/{name}.jpg" if source == "urls" else f"{out}/{name}-{i+1}.jpg"
            try:
                if source == "files":
                    open(f"{out}/{name}", "wb").write(get(u)); credits[name] = {"by": by}; continue
                im = Image.open(io.BytesIO(get(u))).convert("RGB"); im.thumbnail((2400, 2400)); im.save(fn, quality=88)
                credits[fn] = {"by": by, "page": page, "query": q}
            except Exception as e: print(name, i, "skip", e)
        print(name, len(picks)); time.sleep(4)
    except Exception as e:
        print(name, "ERROR", e); time.sleep(8)
json.dump(credits, open(f"{out}/credits.json", "w"), indent=1, ensure_ascii=False)
