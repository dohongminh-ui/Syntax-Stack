"""English next to Vietnamese: content coverage, rendering, endpoints and PvP.

The language is a display choice only. These tests check that every Vietnamese text of the content has an English twin,
that a puzzle in both languages differs in text and nothing else (code, options, answers, verdicts, selection), that the
HTTP header ``X-Lang`` and the WebSocket parameter ``lang`` pick the language, and that Vietnamese without the header is
unchanged. Contract: ``app/i18n.py``.
"""
import glob
import json
import random
import re
import sqlite3
from pathlib import Path

import pytest
import yaml

from app import bank, custom, hints, i18n, pvp, pvp_bot, pvp_coach, ranked, rooms, rows, tutor
from app import validator as V

from .ranked_bot import answer_body
from .test_misaki import go, start_bot
from .test_pvp_match import Client, dev, nick, post, prime_lock, queue, solve, tc  # noqa: F401 (fixtures)

BACKEND = Path(__file__).resolve().parents[1]
CONTENT = BACKEND / "content"
EN = {"X-Lang": "en"}
VI_LETTERS = re.compile(
    "[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]", re.I)
PLACEHOLDER = re.compile(r"\{([^{}]+)\}")


def vi_words(text) -> set:
    return {w for w in re.findall(r"\w+", str(text)) if VI_LETTERS.search(w)}


def placeholders(text) -> set:
    return set(PLACEHOLDER.findall(text))


def load(path):
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def assert_english(text, allowed=frozenset(), where=""):
    """Non-empty, and no Vietnamese word except those that are code / output of the same puzzle."""
    assert isinstance(text, str) and text.strip(), where
    extra = vi_words(text) - set(allowed)
    assert not extra, f"{where}: Vietnamese words in the English text: {sorted(extra)} in {text!r}"


# --------------------------------------------------------------------------- (a) content coverage


def template_files():
    return sorted(glob.glob(str(CONTENT / "templates" / "*.yaml")))


def test_every_template_text_has_an_english_twin_with_the_same_placeholders():
    files = template_files()
    assert len(files) == 16
    for f in files:
        tpl, name = load(f), Path(f).name
        assert len(tpl["hints_en"]) == len(tpl["hints"]) == 3, name
        for vi, en in zip(tpl["hints"], tpl["hints_en"]):
            assert placeholders(vi) == placeholders(en), (name, vi, en)
            assert_english(en, where=name)
        assert placeholders(tpl["explanation"]) == placeholders(tpl["explanation_en"]), name
        assert_english(tpl["explanation_en"], where=name)
        for tier, blocks in tpl["tiers"].items():
            for block in blocks:
                assert placeholders(block["prompt"]) == placeholders(block["prompt_en"]), (name, tier)
                assert_english(block["prompt_en"], where=name)
                if "explanation" in block:
                    assert placeholders(block["explanation"]) == placeholders(block["explanation_en"]), (name, tier)
                    assert_english(block["explanation_en"], where=name)
                else:
                    assert "explanation_en" not in block, (name, tier)


def test_no_vietnamese_text_field_is_left_without_a_sibling():
    """Any text key holding Vietnamese letters, anywhere in the templates and levels, has its ``_en`` sibling."""
    text_keys = {"prompt", "explanation", "hints", "goal", "title", "group_hints"}

    def walk(node, where):
        if isinstance(node, dict):
            for key, value in node.items():
                if key in text_keys and VI_LETTERS.search(json.dumps(value, ensure_ascii=False)):
                    assert key + "_en" in node, f"{where}: {key} has no {key}_en"
                walk(value, where)
        elif isinstance(node, list):
            for item in node:
                walk(item, where)

    for f in template_files() + sorted(glob.glob(str(CONTENT / "levels" / "*.yaml"))):
        walk(load(f), Path(f).name)


def test_every_syntax_rows_level_has_english_text():
    for f in sorted(glob.glob(str(CONTENT / "levels" / "*.yaml"))):
        lv, name = load(f), Path(f).name
        # words that are code or program output (a token, the expected output ...) may stay Vietnamese: "Đậu"
        code_words = set()
        for t in lv["tokens"]:
            code_words |= vi_words(t["text"])
        code_words |= vi_words(lv["expected_output"]) | vi_words(lv.get("twist_output") or "")
        for field in ("title", "goal"):
            assert_english(lv[field + "_en"], code_words, f"{name}:{field}")
        assert len(lv["hints_en"]) == len(lv["hints"]) == 3, name
        for text in lv["hints_en"]:
            assert_english(text, code_words, name)
        assert set(lv["group_hints_en"]) == set(lv["group_hints"]), name
        for group, texts in lv["group_hints_en"].items():
            assert len(texts) == len(lv["group_hints"][group]) == 3, (name, group)
            for text in texts:
                assert_english(text, code_words, f"{name}:{group}")


def test_mistake_notes_and_dashboard_labels_have_english_twins():
    notes, labels = load(CONTENT / "mistakes.yaml"), load(CONTENT / "mistake_labels.yaml")
    for table, limit in ((notes, 200), (labels, 34)):
        vi, en = i18n.split_en(table)
        assert vi and set(vi) == set(en), sorted(set(vi) ^ set(en))
        for key, text in en.items():
            assert_english(text, where=key)
            assert len(text) <= limit, (key, text)
            assert placeholders(text) == placeholders(vi[key]), key
    # every named mistake in the templates has an English label and note (when it has a Vietnamese one)
    vi_labels, en_labels = i18n.split_en(labels)
    names = set()
    for f in template_files():
        for blocks in load(f)["tiers"].values():
            for block in blocks:
                names |= {d["name"] for d in block.get("distractors", []) if isinstance(d, dict)}
    assert not [n for n in names if not en_labels.get(n)]


def test_misaki_coach_has_english_lines_with_the_same_shape():
    assert set(pvp_coach.KINDS) <= set(pvp_coach.TEXTS_EN)
    for kind in pvp_coach.KINDS:
        vi, en = pvp_coach.TEXTS[kind], pvp_coach.TEXTS_EN[kind]
        assert len(vi) == len(en) >= 2, kind          # the variant index is shared by both languages
        for a, b in zip(vi, en):
            assert placeholders(a) == placeholders(b), (kind, a, b)
            out = pvp_coach._format(b, 8, "loops", "en")
            assert_english(out, where=kind)
            assert 0 < len(out) <= pvp_coach.MAX_TEXT and "{" not in out, out
    assert set(pvp_coach.TEXTS_EN["suggestion"]) == set(pvp_coach.TEXTS["suggestion"])
    for key in pvp_coach.SUGGESTION_KEYS:
        assert_english(pvp_coach.suggestion_text(key, 4, "en"), where=key)
        assert len(pvp_coach.suggestion_text(key, 4, "en")) <= pvp_coach.MAX_TEXT


def test_python_side_catalogs_are_complete():
    assert set(rooms.GROUP_LABELS_EN) == set(rooms.GROUP_LABELS)
    assert hints.GENERIC_ROWS_HINTS_EN.keys() == hints.GENERIC_ROWS_HINTS.keys()
    for group, texts in hints.GENERIC_ROWS_HINTS_EN.items():
        assert len(texts) == 3
        for text in texts:
            assert_english(text, where=group)
    names = {lvl: pvp_bot.LADDER[lvl]["name_en"] for lvl in pvp_bot.LADDER}
    assert names == {1: "Apprentice", 2: "Skilled", 3: "Expert", 4: "Master"}
    assert pvp_bot.title(3, "en") == "Misaki · Expert" and pvp_bot.title(3) == "Misaki · Giỏi"
    for key, text in rooms.GROUP_LABELS_EN.items():
        assert_english(text, where=key)


# --------------------------------------------------------------------------- the stored bank


def allowed_words(row) -> set:
    """Vietnamese words that are part of the puzzle's code or output (they stay as they are in English)."""
    parts = [row["code"] or "", row["expected_output"], row["solution_code"]]
    data = row["data"]
    parts += [o["text"] for o in data.get("options", [])]
    parts += [l["text"] for l in data.get("lines", [])]
    parts += [d["code"] for d in data.get("distractors", [])]
    return vi_words(" ".join(parts))


def test_every_bank_row_has_english_text_and_no_placeholder_left(all_rows):
    conn = sqlite3.connect(bank.DB_PATH)
    conn.row_factory = sqlite3.Row
    extra = {r["id"]: dict(r) for r in conn.execute("SELECT id, prompt_en, explanation_en, hints_en FROM puzzles")}
    conn.close()
    assert len(all_rows) >= 700
    for row in all_rows:
        en = extra[row["id"]]
        allowed = allowed_words(row)
        assert_english(en["prompt_en"], allowed, row["id"])
        assert_english(en["explanation_en"], allowed, row["id"])
        hints_en = json.loads(en["hints_en"])
        assert len(hints_en) == len(row["hints"]) == 3
        for text in [en["prompt_en"], en["explanation_en"], *hints_en]:
            assert "{" not in text and "}" not in text, (row["id"], text)
        for text in hints_en:
            assert_english(text, allowed, row["id"])
        for opt in row["data"].get("options", []):
            for field in ("message", "note"):
                if opt.get(field):
                    assert_english(opt.get(field + "_en"), allowed, f"{row['id']}:{opt['id']}:{field}")
                else:
                    assert not opt.get(field + "_en")
        for d in row["data"].get("distractors", []):
            assert bool(d.get("note")) == bool(d.get("note_en")), row["id"]


def test_regenerating_the_bank_gives_the_same_vietnamese_and_the_same_english(tmp_path):
    """The English text is rendered with the same parameters and never touches the random generator: a fresh bank is
    identical to the committed one in every column, Vietnamese and English."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("generate_bank", BACKEND / "scripts" / "generate_bank.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    out = tmp_path / "puzzles.sqlite"
    assert mod.main(["--out", str(out)]) == 0
    a, b = sqlite3.connect(bank.DB_PATH), sqlite3.connect(out)
    try:
        assert a.execute("SELECT * FROM puzzles ORDER BY id").fetchall() == \
            b.execute("SELECT * FROM puzzles ORDER BY id").fetchall()
    finally:
        a.close()
        b.close()


def sample(all_rows, step=5):
    picked = all_rows[::step]
    seen = {r["template_id"] for r in picked}
    return picked + [next(r for r in all_rows if r["template_id"] == t) for t in {r["template_id"] for r in all_rows}
                     if t not in seen]


@pytest.mark.parametrize("level", ["beginner", "advanced"])
def test_a_puzzle_in_both_languages_differs_only_in_text(all_rows, level):
    for row in sample(all_rows):
        full = bank.get_puzzle(row["id"])
        vi, en = bank.public_puzzle(full, level, "vi"), bank.public_puzzle(full, level, "en")
        assert vi["prompt"] == full["prompt"] and en["prompt"] == full["prompt_en"]
        assert vi["prompt"] != en["prompt"]
        assert {k: v for k, v in vi.items() if k != "prompt"} == {k: v for k, v in en.items() if k != "prompt"}, row["id"]


def test_answers_have_the_same_verdict_and_output_in_both_languages(all_rows):
    for row in sample(all_rows, 4):
        full = bank.get_puzzle(row["id"])
        bodies = []
        if full["type"] == "parsons":
            bodies = [answer_body(full, True), answer_body(full, False)]
        else:
            bodies = [{"option_id": o["id"]} for o in full["data"]["options"]]
        allowed = allowed_words(full)
        for body in bodies:
            for reveal in (False, True):
                args = {k: v for k, v in body.items() if k in ("option_id", "order", "line_id")}
                vi = bank.check_answer(full, **args, reveal=reveal, lang="vi")
                en = bank.check_answer(full, **args, reveal=reveal, lang="en")
                for key in ("correct", "error_group", "actual_output", "solution_code"):
                    assert vi[key] == en[key], (row["id"], key)
                assert_english(en["message"], allowed, row["id"])
                if en["explanation"]:
                    assert_english(en["explanation"], allowed, row["id"])
                    assert vi["explanation"] and vi["explanation"] != en["explanation"]
                assert vi["message"] != en["message"] or not vi["correct"] and not vi["message"]


def test_the_language_never_changes_which_puzzle_is_picked():
    def picks(lang):
        token = i18n.set_lang(lang)
        try:
            rng = random.Random(4242)
            out = []
            for topic, tier in (("loops", 2), ("variables", 1), ("functions", 3), ("conditions", 2)):
                out.append(bank.select_puzzle(kind="rescue", topic=topic, tier=tier, level="intermediate",
                                              template_id=None, exclude_ids=[], exclude_templates=[], rng=rng)["id"])
            return out
        finally:
            i18n.reset(token)
    assert picks("vi") == picks("en")


def test_validator_messages_come_in_both_languages_with_the_same_verdict():
    cases = [("print(1)", "2"), ("print(x)", "1"), ("print('a' + 1)", "a1"), ("print(1/0)", "1"),
             ("for i in range(3)\n    print(i)", "0"), ("def f():\nprint(1)", "1"), ("import os", "x"), ("", "1")]
    for code, expected in cases:
        d = V.diagnose(code, expected)
        assert d.message and d.message_en and d.message != d.message_en, code
        assert_english(d.message_en, where=code)
        assert d.msg("vi") == d.message and d.msg("en") == d.message_en
    assert V.describe_output("", "en") == "prints nothing" and V.describe_output("") == "không in gì"


# --------------------------------------------------------------------------- Syntax Rows


def test_rows_levels_in_both_languages(client):
    vi = client.get("/api/rows/levels/r2").json()
    en = client.get("/api/rows/levels/r2", headers=EN).json()
    assert vi["title"] == "Đậu hay trượt" and en["title"] == "Pass or fail"
    assert {k: v for k, v in vi.items() if k not in ("title", "goal")} == \
        {k: v for k, v in en.items() if k not in ("title", "goal")}
    assert en["goal"] != vi["goal"] and "Đậu" in en["expected_output"]
    listing_vi, listing_en = client.get("/api/rows/levels").json(), client.get("/api/rows/levels", headers=EN).json()
    assert [l["id"] for l in listing_vi] == [l["id"] for l in listing_en]
    assert [l["title"] for l in listing_en] == ["Your first variable", "Pass or fail", "Count to three", "Adding up",
                                              "The doubling function"]


def test_rows_run_hint_and_errors_in_english(client):
    empty = client.post("/api/rows/levels/r1/run", json={"rows": []}).json()
    en = client.post("/api/rows/levels/r1/run", json={"rows": []}, headers=EN).json()
    assert empty["message"].startswith("Bàn chơi đang trống")
    assert en["message"].startswith("The board is empty")
    assert {k: v for k, v in empty.items() if k != "message"} == {k: v for k, v in en.items() if k != "message"}
    # a real board: same verdict, same output, English message
    lv = rows.get_level("r3")
    board = rows.practice_rows(lv)
    a = client.post("/api/rows/levels/r3/run", json={"rows": board}).json()
    b = client.post("/api/rows/levels/r3/run", json={"rows": board}, headers=EN).json()
    assert a["passed"] == b["passed"] and a["actual_output"] == b["actual_output"] and a["row"] == b["row"]
    assert a["message"] != b["message"]
    assert_english(b["message"])
    # hints
    h_vi = client.get("/api/rows/levels/r2/hint", params={"level": 2, "error_group": "bad_indent"}).json()
    h_en = client.get("/api/rows/levels/r2/hint", params={"level": 2, "error_group": "bad_indent"}, headers=EN).json()
    lv2 = rows.get_level("r2")
    assert h_vi["text"] == lv2["group_hints"]["bad_indent"][1] and h_en["text"] == lv2["group_hints_en"]["bad_indent"][1]
    g_en = client.get("/api/rows/levels/r1/hint", params={"level": 1, "error_group": "syntax"}, headers=EN).json()
    assert g_en["text"] == hints.GENERIC_ROWS_HINTS_EN["syntax"][0]
    # errors
    r_vi, r_en = client.get("/api/rows/levels/nope"), client.get("/api/rows/levels/nope", headers=EN)
    assert r_vi.status_code == r_en.status_code == 404
    assert r_vi.json()["detail"] == "Không tìm thấy màn 'nope'." and r_en.json()["detail"] == "Level 'nope' was not found."
    bad = {"rows": [{"row": 99, "tokens": []}]}
    e_vi, e_en = client.post("/api/rows/levels/r1/run", json=bad), client.post("/api/rows/levels/r1/run", json=bad, headers=EN)
    assert e_vi.status_code == e_en.status_code == 422
    assert "ngoài bàn chơi" in e_vi.json()["detail"] and "outside the board" in e_en.json()["detail"]


# --------------------------------------------------------------------------- Code Rescue endpoints


def pick_row(all_rows, typ="fill_blank"):
    return next(r for r in all_rows if r["type"] == typ and not r["debug_only"] and r["topic"] == "loops")


def test_puzzle_next_hint_answer_and_errors_follow_the_header(client, all_rows):
    body = {"kind": "rescue", "topic": "loops", "tier": 2, "level": "intermediate"}
    en = client.post("/api/puzzle/next", json=body, headers=EN).json()
    full = bank.get_puzzle(en["id"])
    assert en["prompt"] == full["prompt_en"] and en["prompt"] != full["prompt"]
    # Vietnamese without the header: unchanged (the stored Vietnamese prompt)
    vi = client.post("/api/puzzle/next", json=body).json()
    assert vi["prompt"] == bank.get_puzzle(vi["id"])["prompt"]
    assert client.post("/api/puzzle/next", json=body, headers={"X-Lang": "fr"}).json()["prompt"] != ""
    row = pick_row(all_rows)
    # hints
    for lvl in (1, 2, 3):
        assert client.get(f"/api/puzzle/{row['id']}/hint", params={"level": lvl}).json()["text"] == row["hints"][lvl - 1]
        full = bank.get_puzzle(row["id"])
        assert client.get(f"/api/puzzle/{row['id']}/hint", params={"level": lvl}, headers=EN).json()["text"] \
            == full["hints_en"][lvl - 1]
    # answers: same verdict and output, message in the language
    wrong = next(o for o in row["data"]["options"] if not o["correct"])
    a_vi = client.post(f"/api/puzzle/{row['id']}/answer", json={"option_id": wrong["id"], "reveal": True}).json()
    a_en = client.post(f"/api/puzzle/{row['id']}/answer", json={"option_id": wrong["id"], "reveal": True},
                       headers=EN).json()
    assert a_vi["message"] == wrong["message"] and a_en["message"] == wrong["message_en"]
    assert a_vi["explanation"].endswith(row["explanation"]) and a_en["explanation"].endswith(
        bank.get_puzzle(row["id"])["explanation_en"])
    for key in ("correct", "error_group", "actual_output", "solution_code"):
        assert a_vi[key] == a_en[key]
    # an error
    e_vi = client.post(f"/api/puzzle/{row['id']}/answer", json={"option_id": "zz"})
    e_en = client.post(f"/api/puzzle/{row['id']}/answer", json={"option_id": "zz"}, headers=EN)
    assert e_vi.status_code == e_en.status_code == 422
    assert "không thuộc câu đố" in e_vi.json()["detail"] and "does not belong to this puzzle" in e_en.json()["detail"]
    m_vi, m_en = client.get("/api/puzzle/nope__001/hint", params={"level": 1}), \
        client.get("/api/puzzle/nope__001/hint", params={"level": 1}, headers=EN)
    assert m_vi.status_code == m_en.status_code == 404
    assert m_vi.json()["detail"].startswith("Không tìm thấy") and m_en.json()["detail"].endswith("was not found.")
    n_vi = client.post("/api/puzzle/next", json={"kind": "debug"})
    n_en = client.post("/api/puzzle/next", json={"kind": "debug"}, headers=EN)
    assert n_vi.status_code == n_en.status_code == 422
    assert "cần có template_id" in n_vi.json()["detail"] and "needs a template_id" in n_en.json()["detail"]


def test_canned_tutor_fallbacks_follow_the_header(client, all_rows, monkeypatch):
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_URL", raising=False)
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_TOKEN", raising=False)
    row = pick_row(all_rows)
    full = bank.get_puzzle(row["id"])
    wrong = next(o for o in full["data"]["options"] if not o["correct"])
    body = {"option_id": wrong["id"]}
    r_vi = client.post(f"/api/puzzle/{row['id']}/explain", json=body).json()
    r_en = client.post(f"/api/puzzle/{row['id']}/explain", json=body, headers=EN).json()
    assert r_vi["source"] == r_en["source"] == "canned"
    assert r_vi["text"].endswith(full["explanation"]) and r_en["text"].endswith(full["explanation_en"])
    # debrief
    d = {"level": "intermediate", "mode": "rescue", "end_reason": "crash",
         "wrong": [{"puzzle_id": row["id"], "kind": "rescue", "option_id": wrong["id"]}]}
    d_vi = client.post("/api/rescue/debrief", json=d).json()
    d_en = client.post("/api/rescue/debrief", json=d, headers=EN).json()
    assert d_vi["text"].startswith("Ván này bạn sai nhiều nhất ở chủ đề Vòng lặp (1 lần).")
    assert d_en["text"].startswith("In this game you made the most mistakes in Loops (1 time).")
    assert d_en["text"].endswith("Remember that two wrong answers end a Code Rescue game.")
    assert d_vi["focus_topic"] == d_en["focus_topic"] == "loops"
    # rematch
    rm_vi = client.get(f"/api/puzzle/{row['id']}/rematch").json()
    rm_en = client.get(f"/api/puzzle/{row['id']}/rematch", headers=EN).json()
    assert rm_vi["text"] == "Thử áp dụng lại quy tắc vừa gặp vào câu đố mới này."
    assert rm_en["text"] == "Try applying the rule you just met to this new puzzle."
    assert bank.get_puzzle(rm_en["puzzle"]["id"])["prompt_en"] == rm_en["puzzle"]["prompt"]
    # Syntax Rows: teach-back and explain-prediction
    board = {"rows": rows.canonical_rows(rows.get_level("r3"))}
    t_vi = client.post("/api/rows/levels/r3/teach-back", json={**board, "reflection": "Vì range dừng trước 3"}).json()
    t_en = client.post("/api/rows/levels/r3/teach-back", json={**board, "reflection": "range stops before 3"},
                       headers=EN).json()
    assert "mảnh mã" in t_vi["text"] and "/ What would change" in t_vi["text"]     # unchanged Vietnamese fallback
    assert t_en["text"] == "What would change in the output if you swapped one tile?"
    wrong_board = {"rows": rows.practice_rows(rows.get_level("r3")), "prediction": "9"}
    p_vi = client.post("/api/rows/levels/r3/explain-prediction", json=wrong_board).json()
    p_en = client.post("/api/rows/levels/r3/explain-prediction", json=wrong_board, headers=EN).json()
    assert p_vi["text"].startswith("Bạn đoán:") and p_en["text"].startswith("You predicted:")
    e_en = client.post("/api/rows/levels/r3/explain-prediction", json={**board, "prediction": ""}, headers=EN)
    assert e_en.status_code == 422 and e_en.json()["detail"] == "Please enter your prediction."


def test_room_and_classroom_messages_follow_the_header(client, tmp_path, monkeypatch):
    monkeypatch.setattr(rooms, "DB_PATH", tmp_path / "rooms.sqlite")
    monkeypatch.setattr(rooms, "_db_path_cache", None)
    rooms.reset_rate_limits()
    long_title = {"title": "x" * 41}
    vi, en = client.post("/api/rooms", json=long_title), client.post("/api/rooms", json=long_title, headers=EN)
    assert vi.status_code == en.status_code == 422
    assert vi.json()["detail"] == "Tên phòng tối đa 40 ký tự."
    assert en.json()["detail"] == "Room name can be at most 40 characters."
    nf_vi, nf_en = client.get("/api/rooms/ZZZZZ"), client.get("/api/rooms/ZZZZZ", headers=EN)
    assert nf_vi.status_code == nf_en.status_code == 404
    assert nf_vi.json()["detail"] == "Không tìm thấy phòng học này."
    assert nf_en.json()["detail"] == "This classroom was not found."
    made = client.post("/api/rooms", json={"title": "Lớp 10A"}, headers=EN).json()
    s_vi = client.get(f"/api/rooms/{made['code']}/summary", headers={"X-Teacher-Key": "wrong"})
    s_en = client.get(f"/api/rooms/{made['code']}/summary", headers={"X-Teacher-Key": "wrong", **EN})
    assert s_vi.status_code == s_en.status_code == 403
    assert s_vi.json()["detail"] == "Sai mã giáo viên." and s_en.json()["detail"] == "Wrong teacher key."
    # dashboard labels
    assert rooms.mistake_label("off_by_one_high") == "Lệch một đơn vị (thừa)"
    assert rooms.mistake_label("off_by_one_high", "en") == "Off by one (too high)"
    assert rooms.mistake_label("output_mismatch", "en") == "Wrong output"
    assert rooms.mistake_label("never_heard_of_it", "en") == "Other mistake"
    rooms.reset_rate_limits()


# --------------------------------------------------------------------------- custom puzzles

LOOP = "total = 0\nfor i in range(1, 5):\n    total = total + i\nprint(total)"


def test_custom_sets_in_both_languages(tmp_path, monkeypatch, client):
    monkeypatch.setattr(custom, "DB_PATH", tmp_path / "custom.sqlite")
    monkeypatch.setattr(custom, "_db_path_cache", None)
    custom.reset_rate_limits()
    vi = client.post("/api/custom/sets", json={"code": LOOP})
    en = client.post("/api/custom/sets", json={"code": LOOP}, headers=EN)
    assert vi.status_code == en.status_code == 200
    vi, en = vi.json(), en.json()
    assert vi["code"] == en["code"] and vi["expected_output"] == en["expected_output"] and vi["topic"] == en["topic"]
    assert len(vi["puzzles"]) == len(en["puzzles"]) >= 3
    for a, b in zip(vi["puzzles"], en["puzzles"]):
        assert a["prompt"] != b["prompt"]
        assert_english(b["prompt"])
        # (the display order of the options is shuffled by puzzle id, and the two sets have different ids)
        for k in ("options", "lines"):
            for p in (a, b):
                if p[k]:
                    p[k] = sorted(p[k], key=lambda x: x["id"])
        assert {k: v for k, v in a.items() if k not in ("id", "prompt")} == \
            {k: v for k, v in b.items() if k not in ("id", "prompt")}
    assert [s["type"] for s in vi["skipped"]] == [s["type"] for s in en["skipped"]]
    # answers and hints of the English set come in English
    puzzle = next(p for p in en["puzzles"] if p["type"] == "fill_blank")
    stored = custom.get_puzzle(puzzle["id"])
    wrong = next(o for o in stored["data"]["options"] if not o["correct"])
    ans = client.post(f"/api/puzzle/{puzzle['id']}/answer", json={"option_id": wrong["id"], "reveal": True},
                      headers=EN).json()
    assert ans["message"] == wrong["message_en"] and ans["explanation"].endswith(stored["explanation_en"])
    hint = client.get(f"/api/puzzle/{puzzle['id']}/hint", params={"level": 1}, headers=EN).json()
    assert hint["text"] == custom_gen_hints("fill_blank")[0]
    # errors from the pasted program, in the request's language
    short_vi = client.post("/api/custom/sets", json={"code": "x = 1"})
    short_en = client.post("/api/custom/sets", json={"code": "x = 1"}, headers=EN)
    assert short_vi.status_code == short_en.status_code == 422
    assert short_vi.json()["detail"].startswith("Đoạn mã quá ngắn")
    assert short_en.json()["detail"].startswith("The code is too short")
    nothing_vi = client.post("/api/custom/sets", json={"code": "x = 1\ny = 2"})
    nothing_en = client.post("/api/custom/sets", json={"code": "x = 1\ny = 2"}, headers=EN)
    assert "không in ra gì" in nothing_vi.json()["detail"] and "prints nothing" in nothing_en.json()["detail"]
    custom.reset_rate_limits()


def custom_gen_hints(kind):
    from app import custom_gen
    return custom_gen.HINTS_EN[kind]


# --------------------------------------------------------------------------- the tutor (n8n)


@pytest.fixture
def n8n(monkeypatch):
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_URL", "http://n8n.test/hook")
    monkeypatch.setenv("SYNTAX_STACK_TUTOR_TOKEN", "test")
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_CLIENT_LIMIT", raising=False)
    monkeypatch.delenv("SYNTAX_STACK_TUTOR_DAILY_LIMIT", raising=False)
    calls = []

    def ask(url, payload):
        body = json.loads(payload)
        calls.append(body)
        return "Reply in " + body["lang"]

    monkeypatch.setattr(tutor, "_ask", ask)
    return calls


def test_the_tutor_body_carries_the_language_and_the_cache_never_mixes_them(n8n):
    ctx = {"goal": "same context in both languages"}
    en1 = tutor.feedback("coach", ctx, "fallback", lang="en")
    vi1 = tutor.feedback("coach", ctx, "fallback", lang="vi")
    assert [c["lang"] for c in n8n] == ["en", "vi"]                    # two outbound calls: the cache is per language
    assert en1["text"] == "Reply in en" and vi1["text"] == "Reply in vi"
    en2 = tutor.feedback("coach", ctx, "fallback", lang="en")
    vi2 = tutor.feedback("coach", ctx, "fallback", lang="vi")
    assert len(n8n) == 2 and en2["text"] == en1["text"] and vi2["text"] == vi1["text"]    # now both are cached
    assert all(set(c) == {"task", "lang", "context"} for c in n8n)
    tutor.feedback("coach", ctx, "fallback")                           # default: the request's language (vi)
    assert len(n8n) == 2


def test_every_tutor_task_sends_the_language_of_the_request(client, all_rows, n8n):
    row = pick_row(all_rows)
    wrong = next(o for o in row["data"]["options"] if not o["correct"])
    for header, lang in (({}, "vi"), (EN, "en")):
        tutor.reset()
        n8n.clear()
        client.post(f"/api/puzzle/{row['id']}/explain", json={"option_id": wrong["id"]}, headers=header)
        client.get(f"/api/puzzle/{row['id']}/rematch", headers=header)
        client.post("/api/rescue/debrief", headers=header, json={
            "level": "intermediate", "mode": "rescue", "end_reason": "crash",
            "wrong": [{"puzzle_id": row["id"], "kind": "rescue", "option_id": wrong["id"]}]})
        board = rows.canonical_rows(rows.get_level("r3"))
        client.post("/api/rows/levels/r3/teach-back", headers=header, json={"rows": board, "reflection": "because"})
        client.post("/api/rows/levels/r3/explain-prediction", headers=header,
                    json={"rows": rows.practice_rows(rows.get_level("r3")), "prediction": "9"})
        client.post("/api/rows/levels/r3/hint", params={"level": 2}, headers=header,
                    json={"rows": rows.practice_rows(rows.get_level("r3"))})
        assert {c["task"] for c in n8n} == {"explain", "rematch", "debrief", "teach_back", "predict", "coach"}, header
        assert {c["lang"] for c in n8n} == {lang}


# --------------------------------------------------------------------------- the helper module


def test_i18n_helpers():
    assert [i18n.norm(x) for x in ("en", "EN", " en-US ", "vi", "fr", "", None, 5)] == \
        ["en", "en", "en", "vi", "vi", "vi", "vi", "vi"]
    assert i18n.cur() == "vi" and i18n.tr("a", "b") == "a"
    token = i18n.set_lang("en")
    try:
        assert i18n.cur() == "en" and i18n.tr("a", "b") == "b" and i18n.tr("a", "b", "vi") == "a"
        assert i18n.pick({"x": "vi", "x_en": "en"}, "x") == "en"
        assert i18n.pick({"x": "vi"}, "x") == "vi"                      # no English text: the Vietnamese one
        assert i18n.pick({"x": "vi", "x_en": ""}, "x") == "vi"
    finally:
        i18n.reset(token)
    assert i18n.pick({"x": "vi", "x_en": "en"}, "x") == "vi"
    assert i18n.split_en({"a": 1, "a_en": 2, "b": 3}) == ({"a": 1, "b": 3}, {"a": 2})


# --------------------------------------------------------------------------- (d) PvP: per connection


class LangTC:
    """A TestClient whose WebSockets carry ``lang=...`` on the URL (everything else goes to the real client)."""

    def __init__(self, tc, lang):
        self._tc, self._lang = tc, lang

    def websocket_connect(self, url, *args, **kw):
        return self._tc.websocket_connect(f"{url}&lang={self._lang}", *args, **kw)

    def __getattr__(self, name):
        return getattr(self._tc, name)


def formatted(kind, lang, **kw):
    pool = pvp_coach.TEXTS_EN if lang == "en" else pvp_coach.TEXTS
    return {pvp_coach._format(v, kw.get("n"), kw.get("topic"), lang) for v in pool[kind]}


def test_misaki_training_speaks_english_to_a_lang_en_connection(tc, monkeypatch):
    monkeypatch.setattr(pvp, "SPEED", 5.0)
    etc = LangTC(tc, "en")
    c, lobby = go(etc, start_bot(etc, misaki=1, training=True))
    assert lobby["opponent"]["title"] == "Misaki · Apprentice"
    # the suggestion's reason
    c.send(t="suggest")
    sg = c.until("suggestion")
    assert_english(sg["why"])
    assert sg["why"] in {pvp_coach._format(v, sg.get("n", 1), None, "en") for v in pvp_coach.TEXTS_EN["suggestion"].values()} \
        or sg["why"].startswith("Placing it here completes")
    # the coach after a wrong answer (the topic is named in English)
    prime_lock(c, "loops")
    c.act(t="place", i=0, r=7, c=0)
    solve(tc, c, correct=False)
    msg = c.until("coach")
    assert msg["kind"] == "wrong" and msg["text"] in formatted("wrong", "en", topic="loops")
    assert_english(msg["text"])
    c.close()
    # the same match for a Vietnamese connection (no lang at all)
    vc, vlobby = go(tc, start_bot(tc, misaki=1, training=True))
    assert vlobby["opponent"]["title"] == "Misaki · Tập sự"
    prime_lock(vc, "loops")
    vc.act(t="place", i=0, r=7, c=0)
    solve(tc, vc, correct=False)
    vmsg = vc.until("coach")
    assert vmsg["text"] in formatted("wrong", "vi", topic="loops") and vi_words(vmsg["text"])
    vc.close()


def test_two_players_of_one_match_get_their_own_language(tc, monkeypatch):
    monkeypatch.setattr(pvp, "SPEED", 5.0)
    ta = queue(tc, i=1)
    a = Client(LangTC(tc, "en"), ta)
    a.until("lobby")
    tb = queue(tc, i=2)
    b = Client(LangTC(tc, "vi"), tb)
    a.until("lobby")
    b.until("lobby")
    for c in (a, b):
        c.send(t="ready")
    for c in (a, b):
        c.until("start")
        c.until("state")
    a.send(t="suggest")
    b.send(t="suggest")
    ea, eb = a.until("error"), b.until("error")
    assert ea["code"] == eb["code"] == "not_training"
    assert ea["message"] == "Hints are only available in practice mode with Misaki."
    assert eb["message"] == "Gợi ý chỉ có trong chế độ luyện tập cùng Misaki."
    a.send(t="bogus")
    assert a.until("error")["message"] == "That message is not valid."
    b.send(t="bogus")
    assert b.until("error")["message"] == "Tin nhắn không hợp lệ."
    # the two players still play the same match: same seed, same start
    assert a.start["seed"] == b.start["seed"]
    a.close()
    b.close()


def test_a_cancelled_match_tells_each_player_why_in_their_language(tc, monkeypatch):
    monkeypatch.setattr(pvp, "SPEED", 20.0)
    monkeypatch.setattr(pvp, "LOBBY_TIMEOUT_S", 0.4)
    ta = queue(tc, i=3)
    a = Client(LangTC(tc, "en"), ta)
    a.until("lobby")
    tb = queue(tc, i=4)
    b = Client(LangTC(tc, "vi"), tb)
    ea, eb = a.until("error", timeout=8), b.until("error", timeout=8)
    assert ea["code"] == eb["code"] == "lobby_timeout"
    assert ea["message"] == "The two players were not ready in time, so the match was cancelled."
    assert eb["message"] == "Hai người chơi chưa sẵn sàng, trận đấu bị hủy."
    a.close()
    b.close()


def test_bad_ticket_and_http_errors_of_pvp_in_english(tc):
    c = LangTC(tc, "en")
    with c.websocket_connect("/api/pvp/ws?ticket=nope") as ws:
        msg = ws.receive_json()
    assert msg["code"] == "bad_ticket" and msg["message"] == "The ticket is not valid or the match is already over."
    with tc.websocket_connect("/api/pvp/ws?ticket=nope") as ws:
        assert ws.receive_json()["message"] == "Vé không hợp lệ hoặc trận đấu đã kết thúc."
    r_vi = tc.post("/api/pvp/bot", json={"level": "intermediate", "nickname": nick(1), "device_id": dev(),
                                         "misaki": 2})
    r_en = tc.post("/api/pvp/bot", json={"level": "intermediate", "nickname": nick(1), "device_id": dev(),
                                         "misaki": 2}, headers=EN)
    assert r_vi.status_code == r_en.status_code == 403
    assert r_vi.json()["detail"].startswith("Bạn chưa mở khóa")
    assert r_en.json()["detail"].startswith("You have not unlocked this Misaki level")
    assert tc.get("/api/pvp/misaki", params={"device_id": "!"}, headers=EN).json()["detail"] == "That device id is not valid."
    nick_vi, nick_en = tc.get("/api/nickname"), tc.get("/api/nickname", headers=EN)
    assert nick_vi.status_code == nick_en.status_code == 200          # nicknames are identity: generated as before


# --------------------------------------------------------------------------- nicknames follow the language


def test_english_nicknames_are_generated_and_accepted_alongside_vietnamese_ones():
    from app import nicknames
    assert len(nicknames.ANIMALS_EN) == len(nicknames.ANIMALS) and len(nicknames.ADJECTIVES_EN) == len(nicknames.ADJECTIVES)
    assert len(set(nicknames.ANIMALS_EN)) == len(nicknames.ANIMALS) and len(set(nicknames.ADJECTIVES_EN)) == len(nicknames.ADJECTIVES)
    rng = random.Random(7)
    for _ in range(3000):
        name = nicknames.generate(rng, "en")
        adj, animal, num = name.rsplit(" ", 2)
        assert adj in nicknames.ADJECTIVES_EN and animal in nicknames.ANIMALS_EN and not vi_words(name), name
        assert len(name) <= nicknames.MAX_LEN and nicknames.NUM_MIN <= int(num) <= nicknames.NUM_MAX
        assert nicknames.is_generated(name)
    # the Vietnamese generator is untouched: same draws, same names as before
    assert [nicknames.generate(random.Random(s)) for s in range(5)] == [nicknames.generate(random.Random(s), "vi") for s in range(5)]
    assert nicknames.is_generated("Mèo Xanh 42") and nicknames.is_generated("Blue Cat 42") and nicknames.is_generated("Quick Fox 17")
    for bad in ("blue cat 42", "Cat Blue 42", "Blue Cat 042", "Blue Cat 4", "Blue Cat", "Misaki", "Blue Wolf 42"):
        assert not nicknames.is_generated(bad), bad
    token = i18n.set_lang("en")
    try:
        assert nicknames.generate(random.Random(1)) == nicknames.generate(random.Random(1), "en")
    finally:
        i18n.reset(token)


def test_nickname_endpoint_rooms_and_ranked_follow_the_header(client, tmp_path, monkeypatch):
    from app import nicknames
    monkeypatch.setattr(rooms, "DB_PATH", tmp_path / "rooms.sqlite")
    monkeypatch.setattr(rooms, "_db_path_cache", None)
    monkeypatch.setattr(ranked, "DB_PATH", tmp_path / "ranked.sqlite")
    monkeypatch.setattr(ranked, "_db_path_cache", None)
    rooms.reset_rate_limits()
    ranked.reset_rate_limits()
    en = client.get("/api/nickname", headers=EN).json()["nickname"]
    vi = client.get("/api/nickname").json()["nickname"]
    assert not vi_words(en) and en.split(" ")[0] in nicknames.ADJECTIVES_EN
    assert vi.split(" ")[0] in {a.split(" ")[0] for a in nicknames.ANIMALS}
    # a random-name classroom hands out English names to an English joiner, Vietnamese to the other
    code = client.post("/api/rooms", json={"title": "x"}).json()["code"]
    assert nicknames.is_generated(client.post(f"/api/rooms/{code}/join", json={}, headers=EN).json()["nickname"])
    names = [client.post(f"/api/rooms/{code}/join", json={}, headers=h).json()["nickname"] for h in (EN, {}, EN)]
    assert not vi_words(names[0]) and not vi_words(names[2]) and len(set(names)) == 3
    # a ranked run accepts a generated name of either language, whatever the header; other names are refused
    for header in (EN, {}):
        for name in (en, vi):
            r = client.post("/api/runs", json={"kind": "ranked", "level": "beginner", "nickname": name,
                                               "device_id": secrets_hex()}, headers=header)
            assert r.status_code == 200, r.text
    bad = client.post("/api/runs", json={"kind": "ranked", "level": "beginner", "nickname": "Blue Wolf 42",
                                         "device_id": secrets_hex()}, headers=EN)
    assert bad.status_code == 422 and bad.json()["detail"] == "Please use the randomly generated name."
    rooms.reset_rate_limits()
    ranked.reset_rate_limits()


def secrets_hex():
    import secrets
    return secrets.token_hex(16)
