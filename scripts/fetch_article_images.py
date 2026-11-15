#!/usr/bin/env python3
"""Fetch and verify per-article images for render_daily_news.py's --images map.

daily-news/STYLE.md section 3.5.1 is strict about images: only the
article's own og:image/twitter:image (or RSS enclosure), never a
placeholder, logo, AI-generated image, or another article's picture — and
if nothing real is found, the card just has no image. This script is the
mechanical half of that rule:

1. Fetch each article's page (or, for Hacker News Front Page items, the
   `external_link` — the HN item's own `link` has already been redirected
   to the discussion thread, which has no article og:image).
2. Pull og:image / og:image:url / twitter:image.
3. HEAD-check the image URL actually returns 200 with an image/* content
   type.
4. Drop any image URL that comes back for more than one article — that's
   the signature of a shared/generic placeholder (a site-wide default
   social card, a Google News interstitial image, etc.), not real
   per-article art, and STYLE.md forbids using those as filler.

What this script deliberately does NOT do: guess an image from the URL,
fall back to a site logo, or keep an image just because *something* was
found. No image is always an acceptable outcome; a wrong image is not.

Usage:
    python3 scripts/fetch_article_images.py payload.json --output images.json

payload.json is the same shape render_email.py / render_daily_news.py take
(a {"domains": [{"items": [{"link": ..., "external_link": ...?}, ...]}]}
 object) — pass the digest payload you're about to render, not raw feed
data. Only items with a `link` are considered; `external_link` (set by
prepare_domain_payloads.py's HN redirect, if present) is preferred as the
fetch target over `link`.
"""

import argparse
import json
import re
import subprocess
import sys
from urllib.parse import urljoin

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

OG_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](?:og:image(?::url)?|twitter:image)["\'][^>]+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
OG_RE_REVERSED = re.compile(
    r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+(?:property|name)=["\'](?:og:image(?::url)?|twitter:image)["\']',
    re.IGNORECASE,
)


def fetch_page(url, timeout):
    try:
        r = subprocess.run(
            ["curl", "-sS", "-L", "--max-time", str(timeout), "-A", UA, "-o", "-", url],
            capture_output=True, timeout=timeout + 5,
        )
        return r.stdout.decode("utf-8", errors="replace")
    except Exception:
        return ""


def verify_image_url(candidate, base_url, timeout):
    if not candidate:
        return None
    img_url = urljoin(base_url, candidate)
    if not img_url.startswith("https://"):
        return None
    try:
        r = subprocess.run(
            ["curl", "-sS", "-I", "-L", "--max-time", str(timeout), "-A", UA, img_url],
            capture_output=True, timeout=timeout + 5,
        )
        head = r.stdout.decode("utf-8", errors="replace")
        status_lines = [l for l in head.split("\r\n") if l.startswith("HTTP/")]
        last_status = status_lines[-1] if status_lines else ""
        ctype_lines = [l for l in head.split("\r\n") if l.lower().startswith("content-type:")]
        ctype = ctype_lines[-1].split(":", 1)[1].strip() if ctype_lines else ""
        if "200" in last_status and ctype.lower().startswith("image/"):
            return img_url
    except Exception:
        pass
    return None


def collect_items(payload):
    for dom in payload.get("domains", []):
        for it in dom.get("items", []):
            yield it
        bonus = dom.get("bonus_reading") or {}
        for it in bonus.get("items", []):
            yield it


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("payload", help="Digest payload JSON (render_email.py/render_daily_news.py shape)")
    parser.add_argument("--output", "-o", help="Write the link->image-url JSON map here instead of stdout")
    parser.add_argument("--timeout", type=int, default=15, help="Per-request curl timeout in seconds (default 15)")
    args = parser.parse_args()

    with open(args.payload, encoding="utf-8") as f:
        payload = json.load(f)

    items = list(collect_items(payload))
    print(f"{len(items)} items to check", file=sys.stderr)

    raw = {}
    for it in items:
        link = it.get("link")
        if not link:
            continue
        fetch_url = it.get("external_link") or link
        html = fetch_page(fetch_url, args.timeout)
        if not html:
            print(f"  fetch failed: {fetch_url}", file=sys.stderr)
            continue
        m = OG_RE.search(html) or OG_RE_REVERSED.search(html)
        if not m:
            print(f"  no og:image: {fetch_url}", file=sys.stderr)
            continue
        verified = verify_image_url(m.group(1), fetch_url, args.timeout)
        if verified:
            raw[link] = verified
            print(f"  OK {link} -> {verified}", file=sys.stderr)
        else:
            print(f"  image check failed: {fetch_url} ({m.group(1)})", file=sys.stderr)

    # Any image URL shared by more than one article is a generic/placeholder
    # asset (site-wide social card, redirect-service interstitial, etc.) —
    # never real per-article art. Drop all of them.
    from collections import Counter
    counts = Counter(raw.values())
    shared = {url for url, n in counts.items() if n > 1}
    if shared:
        print(f"dropping {len(shared)} shared/placeholder image URL(s):", file=sys.stderr)
        for u in shared:
            print(f"  {u} (used by {counts[u]} articles)", file=sys.stderr)
    clean = {k: v for k, v in raw.items() if v not in shared}

    print(f"kept {len(clean)}/{len(items)} verified, non-shared images", file=sys.stderr)

    out = json.dumps(clean, ensure_ascii=False, indent=2)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(out)
    else:
        print(out)


if __name__ == "__main__":
    main()
