"""Cache-Control policy: pages and code always revalidate, images cache for a day, API never caches."""
import pytest
from fastapi.testclient import TestClient

from app.main import FRONTEND_DIR, app

client = TestClient(app)
needs_frontend = pytest.mark.skipif(not FRONTEND_DIR.is_dir(), reason="frontend/ not present")


def test_api_is_not_cached():
    assert client.get("/api/health").headers["cache-control"] == "no-store"


@needs_frontend
@pytest.mark.parametrize("path", ["/", "/index.html", "/css/base.css", "/js/main.js", "/manifest.json"])
def test_pages_and_code_revalidate(path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


@needs_frontend
def test_revalidation_returns_304_when_unchanged():
    first = client.get("/css/base.css")
    again = client.get("/css/base.css", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304


@needs_frontend
def test_index_stamps_every_asset_with_the_build():
    import json
    import re

    from app.main import BUILD_ID
    html = client.get("/").text
    assert client.get("/").headers["x-build"] == BUILD_ID
    for css in ("base", "game", "rows", "modal"):
        assert f'href="css/{css}.css?v={BUILD_ID}"' in html
    assert f'src="js/main.js?v={BUILD_ID}"' in html
    # the import map must come before the module script and cover every module
    assert html.index('type="importmap"') < html.index('<script type="module"')
    imports = json.loads(re.search(r'<script type="importmap">(.*?)</script>', html, re.S).group(1))["imports"]
    modules = {f"/js/{p.name}" for p in (FRONTEND_DIR / "js").glob("*.js")}
    assert set(imports) == modules
    assert all(v == f"{k}?v={BUILD_ID}" for k, v in imports.items())


@needs_frontend
def test_versioned_assets_cache_for_a_year():
    r = client.get("/css/base.css?v=abc")
    assert r.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert client.get("/js/nope.js?v=abc").headers.get("cache-control") != "public, max-age=31536000, immutable"


def test_build_id_env_override(monkeypatch):
    from app.main import build_id
    monkeypatch.setenv("SYNTAX_STACK_BUILD", "81a3ca2f00d$bad")
    assert build_id() == "81a3ca2f00db"


@needs_frontend
@pytest.mark.parametrize("path", ["/og-image.png", "/favicon.svg"])
def test_images_cache_for_a_day(path):
    r = client.get(path)
    assert r.status_code == 200
    assert r.headers["cache-control"] == "public, max-age=86400"
