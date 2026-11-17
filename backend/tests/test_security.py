"""Public-site hardening: request size, list caps, API docs, browser headers and the per-visitor
tutor quota."""
import base64
import hashlib
import json
import re

import pytest

from app import tutor
from app.main import FRONTEND_DIR, MAX_BODY_BYTES
from tests.test_rows import canon

needs_frontend = pytest.mark.skipif(not FRONTEND_DIR.is_dir(), reason="frontend/ not present")
NEXT = "/api/puzzle/next"


# ---------------------------------------------------------------- request size and list caps

def test_body_over_the_limit_is_rejected_before_parsing(client):
    body = json.dumps({"topic": "loops", "exclude_ids": ["x" * 60] * 2000})
    assert len(body) > MAX_BODY_BYTES
    r = client.post(NEXT, content=body, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_streamed_body_over_the_limit_is_cut_off(client):
    def chunks():
        for _ in range(MAX_BODY_BYTES // 1000 + 5):
            yield b" " * 1000                     # whitespace: would be valid JSON padding
        yield b'{"topic": "loops"}'

    r = client.post(NEXT, content=chunks(), headers={"content-type": "application/json"})
    assert r.status_code in (400, 413)


def test_normal_requests_still_work(client):
    body = {"topic": "loops", "tier": 1, "level": "beginner", "kind": "rescue",
            "exclude_ids": [f"loops_range_fill__{i:03d}" for i in range(500)], "exclude_templates": []}
    assert client.post(NEXT, json=body).status_code == 200


@pytest.mark.parametrize("field,value", [
    ("exclude_ids", ["a"] * 1001),
    ("exclude_templates", ["a"] * 51),
    ("template_id", "x" * 81),
])
def test_oversized_lists_and_ids_are_422(client, field, value):
    assert client.post(NEXT, json={"topic": "loops", field: value}).status_code == 422


def test_oversized_board_is_422(client):
    rows = [{"row": i, "tokens": []} for i in range(31)]
    assert client.post("/api/rows/levels/r3/run", json={"rows": rows}).status_code == 422


# ---------------------------------------------------------------- docs and headers

@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_api_docs_are_off(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/api/health", "/css/base.css", "/og-image.png"])
def test_security_headers_on_every_response(client, path):
    if not path.startswith("/api") and not FRONTEND_DIR.is_dir():
        pytest.skip("frontend/ not present")
    h = client.get(path).headers
    assert h["x-content-type-options"] == "nosniff"
    assert h["x-frame-options"] == "DENY"
    assert h["referrer-policy"] == "strict-origin-when-cross-origin"
    assert h["strict-transport-security"].startswith("max-age=")
    assert "camera=()" in h["permissions-policy"]


@needs_frontend
def test_page_csp_allows_only_own_scripts_and_the_exact_import_map(client):
    r = client.get("/")
    csp = r.headers["content-security-policy"]
    importmap = re.search(r'<script type="importmap">(.*?)</script>', r.text, re.S).group(1)
    digest = base64.b64encode(hashlib.sha256(importmap.encode()).digest()).decode()
    script_src = next(d for d in csp.split("; ") if d.startswith("script-src"))
    assert script_src == f"script-src 'self' https://static.cloudflareinsights.com 'sha256-{digest}'"
    assert "connect-src 'self' https://cloudflareinsights.com" in csp
    assert "'unsafe-inline'" not in script_src and "'unsafe-eval'" not in script_src
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp
    assert "https://fonts.gstatic.com" in csp


# ---------------------------------------------------------------- per-visitor tutor quota

def _configure(monkeypatch, client_limit):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test/hook")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_CLIENT_LIMIT", str(client_limit))
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_DAILY_LIMIT", raising=False)
    calls = []
    monkeypatch.setattr(tutor, "request_tutor",
                        lambda url, payload, *, timeout: calls.append(payload) or {"text": f"AI {len(calls)}"})
    return calls


def test_one_visitor_cannot_use_up_the_quota_for_everyone(monkeypatch):
    calls = _configure(monkeypatch, client_limit=2)
    a = [tutor.feedback("teach_back", {"n": i}, "canned", client="203.0.113.7")["source"] for i in range(4)]
    assert a == ["ai", "ai", "canned", "canned"]
    assert tutor.feedback("teach_back", {"n": 99}, "canned", client="198.51.100.2")["source"] == "ai"
    assert len(calls) == 3
    assert tutor.stats()["calls_today"] == 3


def test_cached_replies_do_not_count_against_the_visitor(monkeypatch):
    calls = _configure(monkeypatch, client_limit=1)
    first = tutor.feedback("coach", {"same": 1}, "canned", client="203.0.113.7")
    again = tutor.feedback("coach", {"same": 1}, "canned", client="203.0.113.7")
    assert first["source"] == again["source"] == "ai" and len(calls) == 1


def test_client_ip_is_never_kept_in_clear(monkeypatch):
    _configure(monkeypatch, client_limit=5)
    tutor.feedback("coach", {"x": 1}, "canned", client="203.0.113.7")
    assert "203.0.113.7" not in json.dumps(tutor._per_client)


def test_endpoint_uses_the_cloudflare_visitor_ip(client, monkeypatch):
    _configure(monkeypatch, client_limit=1)
    url = "/api/rows/levels/r4/teach-back"
    ask = lambda text, ip: client.post(url, json={"rows": canon("r4"), "reflection": text},
                                       headers={"CF-Connecting-IP": ip}).json()["source"]
    assert ask("lần một", "203.0.113.7") == "ai"
    assert ask("lần hai", "203.0.113.7") == "canned"      # same visitor, new text: over quota
    assert ask("lần ba", "198.51.100.2") == "ai"          # a different visitor is unaffected
