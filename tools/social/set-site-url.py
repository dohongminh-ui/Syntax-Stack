#!/usr/bin/env python3
"""Rewrite the site's absolute base URL in frontend/index.html, robots.txt and sitemap.xml.

Usage: python tools/social/set-site-url.py https://your-domain.tld

The current base is read from <link rel="canonical"> in index.html, so the script works for
any previous domain and is idempotent (running it twice with the same URL changes nothing).
Stdlib only.
"""
import re
import sys
from pathlib import Path

FRONTEND = Path(__file__).resolve().parents[2] / "frontend"
FILES = ["index.html", "robots.txt", "sitemap.xml"]


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__)
        return 2
    new = sys.argv[1].strip().rstrip("/")
    if not re.fullmatch(r"https?://[A-Za-z0-9.-]+(:\d+)?", new):
        print("Give a base URL like https://example.com (no path).", file=sys.stderr)
        return 2
    html = (FRONTEND / "index.html").read_text(encoding="utf-8")
    m = re.search(r'<link rel="canonical" href="(https?://[^"/]+)/?"', html)
    if not m:
        print("Could not find the canonical link in index.html.", file=sys.stderr)
        return 1
    old = m.group(1)
    for name in FILES:
        p = FRONTEND / name
        text = p.read_text(encoding="utf-8")
        out = text.replace(old, new)
        if out != text:
            p.write_text(out, encoding="utf-8", newline="")
        print(f"{name}: {text.count(old)} replaced ({old} -> {new})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
