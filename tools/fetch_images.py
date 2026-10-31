"""Fetch free stock photos into stock/<batch>/. Sources: pexels (needs PEXELS_KEY), pixabay (PIXABAY_KEY), openverse (no key, commercial CC only)."""
import os, sys, json, time, io, urllib.request, urllib.parse
from PIL import Image
Image.MAX_IMAGE_PIXELS = None
batch, source, spec = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])  # spec: {"name": "query", ...}
out = f"stock/{batch}"; os.makedirs(out, exist_ok=True)
UA = {"User-Agent": "webminds-videos/1.0 (https://webminds.dz; contact@webminds.dz)"}
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
        elif source == "commons":
            api = "https://commons.wikimedia.org/w/api.php?"
            if q.startswith("Category:"):
                prm = {"generator": "categorymembers", "gcmtitle": q, "gcmtype": "file", "gcmlimit": 30}
            else:
                prm = {"generator": "search", "gsrsearch": q, "gsrnamespace": 6, "gsrlimit": 30}
            prm.update({"action": "query", "prop": "imageinfo", "iiprop": "url|extmetadata|mime", "iiurlwidth": 1280, "iiextmetadatafilter": "LicenseShortName|Artist|ImageDescription|DateTimeOriginal", "format": "json"})
            d = json.loads(get(api + urllib.parse.urlencode(prm)))
            picks = []
            for pg in (d.get("query", {}).get("pages", {}) or {}).values():
                ii = pg["imageinfo"][0]; md = ii.get("extmetadata", {})
                lic = md.get("LicenseShortName", {}).get("value", "")
                if not ii.get("mime", "").startswith("image/") or "svg" in ii.get("mime", ""): continue
                if not any(k in lic.lower() for k in ("public domain", "pd", "cc0", "cc by")): continue
                picks.append((ii.get("thumburl") or ii["url"], f'{pg["title"]} | {lic} | {md.get("Artist",{}).get("value","")[:80]}', ii.get("descriptionurl", "")))
            picks = picks[:12]
        elif source in ("pexels_video", "pixabay_video"):
            if source == "pexels_video":
                d = json.loads(get("https://api.pexels.com/videos/search?" + urllib.parse.urlencode({"query": q, "per_page": 6}), {"Authorization": os.environ["PEXELS_KEY"]}))
                vids = []
                for v in d["videos"]:
                    fs = sorted([f for f in v["video_files"] if f.get("width") and f["width"] <= 1920 and f.get("file_type") == "video/mp4"], key=lambda f: -f["width"])
                    if fs: vids.append((fs[0]["link"], f'{v["user"]["name"]} / Pexels', v["url"]))
            else:
                d = json.loads(get("https://pixabay.com/api/videos/?" + urllib.parse.urlencode({"key": os.environ["PIXABAY_KEY"], "q": q, "per_page": 6, "safesearch": "true"})))
                vids = [(h["videos"]["medium"]["url"] or h["videos"]["large"]["url"], f'{h["user"]} / Pixabay', h["pageURL"]) for h in d["hits"]]
            for i, (u, by, page) in enumerate(vids[:6]):
                try:
                    fn = f"{out}/{name}-{i+1}.mp4"; open(fn, "wb").write(get(u)); credits[fn] = {"by": by, "page": page, "query": q}
                except Exception as e: print(name, i, "skip", e)
            print(name, len(vids)); time.sleep(3); continue
        else:
            d = json.loads(get("https://api.openverse.org/v1/images/?" + urllib.parse.urlencode({"q": q, "license": "cc0,pdm", "page_size": 6, "mature": "false"})))
            picks = [(r["url"], f'{r.get("creator")} / {r.get("license")} {r.get("license_version")}', r["foreign_landing_url"]) for r in d["results"]]
        for i, (u, by, page) in enumerate(picks[:12] if source == "commons" else picks[:4]):
            fn = f"{out}/{name}.jpg" if source == "urls" else f"{out}/{name}-{i+1}.jpg"
            try:
                if source == "files":
                    open(f"{out}/{name}", "wb").write(get(u)); credits[name] = {"by": by}; continue
                if source == "commons": time.sleep(2.5)
                im = Image.open(io.BytesIO(get(u))).convert("RGB"); im.thumbnail((2400, 2400)); im.save(fn, quality=88)
                credits[fn] = {"by": by, "page": page, "query": q}
            except Exception as e: print(name, i, "skip", e)
        print(name, len(picks)); time.sleep(4)
    except Exception as e:
        print(name, "ERROR", e); time.sleep(8)
json.dump(credits, open(f"{out}/credits.json", "w"), indent=1, ensure_ascii=False)
