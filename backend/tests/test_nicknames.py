"""Generated nicknames, the free-name blocklist and GET /api/nickname."""
import random
import unicodedata

import pytest

from app import nicknames, ranked


@pytest.fixture(autouse=True)
def _reset():
    ranked.reset_rate_limits()
    yield
    ranked.reset_rate_limits()


def test_generator_output_is_always_generated_format_and_short():
    rng = random.Random(7)
    for _ in range(5000):
        name = nicknames.generate(rng)
        assert nicknames.is_generated(name), name
        assert len(name) <= 20
    assert nicknames.is_generated(nicknames.generate())   # the default (system) generator too


def test_generator_numbers_and_shape():
    rng = random.Random(1)
    for _ in range(300):
        prefix, _, num = nicknames.generate(rng).rpartition(" ")
        assert nicknames.NUM_MIN <= int(num) <= nicknames.NUM_MAX
        assert prefix in nicknames._PREFIXES


@pytest.mark.parametrize("name", [
    "Mèo Xanh 42", "Cánh Cụt Vui 17",
    "Mèo Xanh 4", "Mèo Xanh 042", "Mèo Xanh 100", "Mèo Xanh", "mèo xanh 42", "Mèo Xanh 42 ", " Mèo Xanh 42",
    "Chó Xanh 42", "Mèo Xấu 42", "Fuck 42", "Chuột Túi Thông Minh 99", "", "42", "Mèo  Xanh 42", "Mèo Xanh ٤٢",
])
def test_is_generated_is_exact(name):
    assert nicknames.is_generated(name) is (name in ("Mèo Xanh 42", "Cánh Cụt Vui 17"))


def test_is_generated_normalises_unicode_to_nfc():
    assert nicknames.is_generated(unicodedata.normalize("NFD", "Mèo Xanh 42"))
    assert not nicknames.is_generated(None) and not nicknames.is_generated(42)


@pytest.mark.parametrize("name", [
    "Fuuuck", "FUCK", "f.u.c.k", "đ1t", "D.M", "d m", "v c l", "vcl", "V.C.L", "Vkl", "Đ.m", "dit me",
    "ditmeeee", "Con Cac", "sh1t", "b1tch", "$hit", "p0rn", "Hitler", "N@zi", "ass", "Assss", "Cl", "c l m",
    "Mèo Lớn",      # "lon" is a blocked whole word, so by the rules this name is refused
    "Thằng Ngu", "Bạn Cho", "Mèo Điên",
])
def test_blocklist_catches_lookalikes_diacritics_and_repeats(name):
    assert nicknames.is_allowed_free(name) is False, name


@pytest.mark.parametrize("name", [
    "Nguyễn An", "Clara", "Adam", "Class", "Lớp 10A", "Cassandra", "Hà Vy", "Bích Ngọc", "Vân Anh",
    "Dương", "Lonely", "Nam", "Mèo Xanh", "An",
])
def test_innocent_names_pass(name):
    assert nicknames.is_allowed_free(name) is True, name


def test_nickname_endpoint(client):
    got = {client.get("/api/nickname").json()["nickname"] for _ in range(10)}
    assert len(got) > 1 and all(nicknames.is_generated(n) for n in got)
    assert set(client.get("/api/nickname").json()) == {"nickname"}


def test_nickname_endpoint_is_rate_limited_per_client(client):
    for _ in range(60):
        assert client.get("/api/nickname").status_code == 200
    assert client.get("/api/nickname").status_code == 429
    assert client.get("/api/nickname", headers={"CF-Connecting-IP": "8.8.8.8"}).status_code == 200


def test_runs_and_races_reject_free_names(client):
    dev = "ab" * 16
    msg = "Hãy dùng tên được tạo ngẫu nhiên."
    for name in ("An", "Fuck", "Mèo Xanh", "Mèo Xanh 5"):
        r = client.post("/api/runs", json={"kind": "ranked", "level": "beginner", "nickname": name, "device_id": dev})
        assert r.status_code == 422 and r.json()["detail"] == msg, name
        r = client.post("/api/races", json={"level": "beginner", "nickname": name, "device_id": dev})
        assert r.status_code == 422 and r.json()["detail"] == msg, name
    nick = client.get("/api/nickname").json()["nickname"]
    assert client.post("/api/runs", json={"kind": "ranked", "level": "beginner", "nickname": nick,
                                          "device_id": dev}).status_code == 200
    assert client.post("/api/races", json={"level": "beginner", "nickname": nick,
                                           "device_id": dev}).status_code == 200
