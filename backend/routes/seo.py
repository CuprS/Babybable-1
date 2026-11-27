"""Server-rendered pages for search engines and link previews.

The Expo web app renders in the browser, so crawlers and chat apps see an empty page. These
routes return real HTML (title, description, Open Graph tags, readable text) for public tutor
profiles and blog posts, plus a sitemap. People who land on them are sent on to the app.
"""
from html import escape

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, Response

from core import PUBLIC_WEB_URL, db

router = APIRouter()


# The same script on every share page, so the site's Content-Security-Policy can allow exactly
# this script by its hash (see deploy/Caddyfile and tests_inprocess/test_security.py). It sends
# people (not crawlers) on to the page's canonical app address.
REDIRECT_JS = "if(!/bot|crawl|spider|preview|facebookexternalhit|slack|discord|whatsapp/i.test(navigator.userAgent)){location.replace(document.querySelector('link[rel=canonical]').href)}"


def _abs(path: str) -> str:
    return f"{PUBLIC_WEB_URL}{path}" if PUBLIC_WEB_URL else path


def _image(url: str) -> str:
    if not url:
        return ""
    if url.startswith("http"):
        return url
    return _abs(f"/api/files/{url}")


def _page(title: str, description: str, body_html: str, app_path: str, image: str = "", kind: str = "website") -> HTMLResponse:
    t, d, app_url = escape(title), escape(description[:300]), escape(_abs(app_path))
    img = f'<meta property="og:image" content="{escape(image)}"><meta name="twitter:image" content="{escape(image)}">' if image else ""
    html = f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{t}</title>
<meta name="description" content="{d}">
<link rel="canonical" href="{app_url}">
<meta property="og:type" content="{kind}"><meta property="og:title" content="{t}">
<meta property="og:description" content="{d}"><meta property="og:url" content="{app_url}">
<meta property="og:site_name" content="Babybabel"><meta name="twitter:card" content="summary_large_image">
{img}
<style>body{{font-family:system-ui,Arial,sans-serif;max-width:720px;margin:0 auto;padding:24px 16px;color:#2C2421;background:#FAF8F5;line-height:1.6;font-size:18px}}
a.cta{{display:inline-block;background:#B83A23;color:#fff;padding:14px 22px;border-radius:999px;text-decoration:none;font-weight:700}}
img{{max-width:100%;border-radius:16px}}</style>
<script>{REDIRECT_JS}</script>
</head><body>{body_html}<p><a class="cta" href="{app_url}">Open in Babybabel</a></p></body></html>"""
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=600"})


@router.get("/share/tutor/{tutor_id}", response_class=HTMLResponse)
async def share_tutor(tutor_id: str):
    t = await db.tutors.find_one({"id": tutor_id, "suspended": {"$ne": True}, "verification_status": "verified"}, {"_id": 0})
    if not t:
        raise HTTPException(404, "Tutor not found")
    langs = ", ".join(t.get("languages") or []) or "languages"
    place = t.get("location") or ("Remote" if t.get("allows_remote") else "")
    title = f"{t['name']} — {langs} tutor & childcare{f' in {place}' if place else ''} | Babybabel"
    desc = (t.get("bio") or f"{t['name']} teaches {langs} to children while caring for them.").strip()
    badge = " · ✔ Verified" if t.get("verification_status") == "verified" else ""
    rating = f"★ {t['rating']:.1f} ({t.get('reviews_count', 0)} reviews)" if t.get("rating") else "New tutor"
    body = (
        f"<h1>{escape(t['name'])}</h1>"
        f"<p><strong>{escape(langs)}</strong>{escape(f' · {place}' if place else '')}{escape(badge)}</p>"
        f"<p>{escape(rating)} · ${int(t.get('hourly_rate_cents') or 0) / 100:.0f}/hour</p>"
        f"<p>{escape(desc)}</p>"
    )
    return _page(title, desc, body, f"/tutor/{tutor_id}", _image(t.get("hero_image_url") or t.get("avatar_url") or ""), "profile")


@router.get("/share/blog/{post_id}", response_class=HTMLResponse)
async def share_post(post_id: str):
    p = await db.posts.find_one({"id": post_id, "status": "published"}, {"_id": 0})
    if not p:
        raise HTTPException(404, "Post not found")
    paragraphs = "".join(f"<p>{escape(par)}</p>" for par in (p.get("body") or "").split("\n") if par.strip())
    body = f"<h1>{escape(p['title'])}</h1><p><em>By {escape(p.get('author_name') or 'Babybabel')}</em></p>{paragraphs}"
    return _page(f"{p['title']} | Babybabel", p.get("excerpt") or p["title"], body, f"/blog/{post_id}",
                 _image(p.get("cover_image_url") or ""), "article")


@router.get("/seo/sitemap.xml")
async def sitemap():
    urls = [_abs(path) for path in ("/find-tutor", "/become-tutor", "/blog", "/mission", "/resources", "/languages-near-you", "/support", "/privacy")]
    async for t in db.tutors.find({"suspended": {"$ne": True}, "verification_status": "verified", "bio": {"$nin": [None, ""]}}, {"_id": 0, "id": 1}):
        urls.append(_abs(f"/api/share/tutor/{t['id']}"))
    async for p in db.posts.find({"status": "published"}, {"_id": 0, "id": 1}):
        urls.append(_abs(f"/api/share/blog/{p['id']}"))
    body = "".join(f"<url><loc>{escape(u)}</loc></url>" for u in urls)
    xml = f'<?xml version="1.0" encoding="UTF-8"?><urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">{body}</urlset>'
    return Response(xml, media_type="application/xml", headers={"Cache-Control": "public, max-age=3600"})
