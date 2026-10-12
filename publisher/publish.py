"""Webminds publisher — publie les posts programmés sur Facebook (Reels/photos) et Instagram (Reels/photos)
via l'API officielle Meta (Graph API). Gratuit, tourne dans GitHub Actions.

Planning : publisher/posts.json  (liste de posts)
  {
    "id": "web-ep08",                      # identifiant unique
    "when": "2026-10-13T11:00:00+01:00",   # heure d'Alger
    "networks": ["facebook", "instagram"],
    "type": "reel" | "photo",
    "media": "https://..." | "repo:publish/media/xxx.mp4",
    "caption": "texte FB/IG",
    "caption_instagram": "(optionnel) texte IG différent"
  }
État : publisher/state.json  ({"<id>:<network>": {"status": "published"|"error", ...}})

Secrets (GitHub) : META_PAGE_TOKEN, FB_PAGE_ID, IG_USER_ID
"""
import json, os, sys, time, datetime as dt, pathlib, requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
POSTS = ROOT / "publisher" / "posts.json"
STATE = ROOT / "publisher" / "state.json"
V = os.environ.get("GRAPH_VERSION", "v21.0")
G = f"https://graph.facebook.com/{V}"
TOKEN = os.environ.get("META_PAGE_TOKEN", "")
PAGE = os.environ.get("FB_PAGE_ID", "")
IG = os.environ.get("IG_USER_ID", "")
WINDOW_H = float(os.environ.get("CATCHUP_HOURS", "12"))   # ne publie pas un post en retard de plus de 12 h
DRY = os.environ.get("DRY_RUN") == "1"

def log(*a):
    print(*a, flush=True)

def check(r):
    try:
        j = r.json()
    except Exception:
        j = {"raw": r.text[:500]}
    if r.status_code >= 400 or (isinstance(j, dict) and "error" in j):
        raise RuntimeError(f"HTTP {r.status_code}: {json.dumps(j)[:800]}")
    return j

def get_media(m):
    if m.startswith("repo:"):
        return (ROOT / m[5:]).read_bytes()
    r = requests.get(m, timeout=300)
    r.raise_for_status()
    return r.content

# ---------------- Facebook ----------------
def fb_reel(data, caption):
    j = check(requests.post(f"{G}/{PAGE}/video_reels", data={"upload_phase": "start", "access_token": TOKEN}))
    vid = j["video_id"]
    up = j.get("upload_url") or f"https://rupload.facebook.com/video-upload/{V}/{vid}"
    check(requests.post(up, headers={"Authorization": f"OAuth {TOKEN}", "offset": "0", "file_size": str(len(data))}, data=data, timeout=600))
    check(requests.post(f"{G}/{PAGE}/video_reels", data={"upload_phase": "finish", "video_id": vid, "video_state": "PUBLISHED", "description": caption, "access_token": TOKEN}))
    return vid

def fb_photo(data, caption):
    j = check(requests.post(f"{G}/{PAGE}/photos", data={"caption": caption, "access_token": TOKEN}, files={"source": ("image.jpg", data)}))
    return j.get("post_id") or j.get("id")

# ---------------- Instagram ----------------
def ig_wait(cid, limit=600):
    t0 = time.time()
    while time.time() - t0 < limit:
        j = check(requests.get(f"{G}/{cid}", params={"fields": "status_code,status", "access_token": TOKEN}))
        st = j.get("status_code")
        if st == "FINISHED":
            return
        if st in ("ERROR", "EXPIRED"):
            raise RuntimeError(f"IG container {st}: {j}")
        time.sleep(10)
    raise RuntimeError("IG container timeout")

def ig_reel(data, caption, thumb_ms=None):
    p = {"media_type": "REELS", "upload_type": "resumable", "caption": caption, "share_to_feed": "true", "access_token": TOKEN}
    if thumb_ms is not None:
        p["thumb_offset"] = str(int(thumb_ms))
    cid = check(requests.post(f"{G}/{IG}/media", data=p))["id"]
    check(requests.post(f"https://rupload.facebook.com/ig-api-upload/{V}/{cid}",
                        headers={"Authorization": f"OAuth {TOKEN}", "offset": "0", "file_size": str(len(data))}, data=data, timeout=600))
    ig_wait(cid)
    return check(requests.post(f"{G}/{IG}/media_publish", data={"creation_id": cid, "access_token": TOKEN}))["id"]

def ig_photo(url, caption):
    # Instagram exige une URL publique pour les images
    cid = check(requests.post(f"{G}/{IG}/media", data={"image_url": url, "caption": caption, "access_token": TOKEN}))["id"]
    ig_wait(cid, 120)
    return check(requests.post(f"{G}/{IG}/media_publish", data={"creation_id": cid, "access_token": TOKEN}))["id"]

def public_url(m):
    if m.startswith("repo:"):
        return f"https://raw.githubusercontent.com/{os.environ.get('GITHUB_REPOSITORY','picsooo/webminds-videos')}/{os.environ.get('GITHUB_SHA','main')}/{m[5:]}"
    return m

def main():
    posts = json.loads(POSTS.read_text()) if POSTS.exists() else []
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    now = dt.datetime.now(dt.timezone.utc)
    changed = False
    if not DRY and not (TOKEN and PAGE):
        log("::warning::Secrets META_PAGE_TOKEN / FB_PAGE_ID manquants — rien n'est publié.")
        return
    for p in sorted(posts, key=lambda x: x["when"]):
        when = dt.datetime.fromisoformat(p["when"])
        late_h = (now - when).total_seconds() / 3600
        if late_h < 0:
            continue
        for net in p.get("networks", []):
            key = f"{p['id']}:{net}"
            if state.get(key, {}).get("status") == "published":
                continue
            if state.get(key, {}).get("tries", 0) >= 3:
                continue
            if late_h > WINDOW_H:
                if key not in state:
                    state[key] = {"status": "skipped", "reason": f"en retard de {late_h:.1f} h"}; changed = True
                    log(f"::warning::{key} ignoré (en retard de {late_h:.1f} h)")
                continue
            if net == "instagram" and not IG:
                continue
            cap = p.get(f"caption_{net}") or p.get("caption", "")
            log(f"→ {key} ({p.get('type','reel')}) prévu {p['when']}")
            if DRY:
                continue
            try:
                if p.get("type", "reel") == "reel":
                    try:
                        data = get_media(p["media"])
                    except Exception as e:
                        if not p.get("media_fallback"): raise
                        log(f"::warning::média principal indisponible ({e}), fallback {p['media_fallback']}")
                        data = get_media(p["media_fallback"])
                    rid = fb_reel(data, cap) if net == "facebook" else ig_reel(data, cap, p.get("thumb_ms"))
                else:
                    if net == "facebook":
                        rid = fb_photo(get_media(p["media"]), cap)
                    else:
                        rid = ig_photo(public_url(p["media"]), cap)
                state[key] = {"status": "published", "id": rid, "at": now.isoformat()}
                log(f"::notice::{key} publié ({rid})")
            except Exception as e:
                s = state.get(key, {})
                state[key] = {"status": "error", "tries": s.get("tries", 0) + 1, "error": str(e)[:600], "at": now.isoformat()}
                log(f"::error::{key} : {e}")
            changed = True
    if changed:
        STATE.write_text(json.dumps(state, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
