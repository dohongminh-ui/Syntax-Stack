#!/usr/bin/env python3
"""Prepare the Live2D model for the "Chat with Misaki" screen (docs/misaki-chat.md section 6).

    python -I tools/setup_live2d.py "<folder that contains the *.model3.json>"

Reads the source model folder (read only, nothing in it is executed) and writes frontend/live2d/misaki/ with
ASCII file names, textures downscaled to 2048 px, expressions and motions registered in misaki.model3.json,
and a small portrait.webp / portrait.png for the low-power fallback. The output folder is gitignored: the model's
terms forbid redistributing the complete files (see the credit line on the chat screen).

Needs Pillow. Run it with -I so Python does not import anything from the working directory.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    sys.exit("Pillow is required: python -m pip install Pillow")

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "frontend" / "live2d" / "misaki"
TEXTURE_SIZE = 2048
PORTRAIT_SIZE = 512

# Expressions the chat uses (docs/misaki-chat.md mood table). Source name (Chinese) -> ASCII name.
EXPRESSIONS = {
    "脸红": "blush",
    "爱心眼": "heart",
    "流泪": "tears",
    "流冷汗": "sweat",
    "圈圈眼": "spiral",
    "＞＜": "xx",
    # The rest of the pack, copied under sensible names. The chat never selects these.
    "体型1": "body_1",
    "体型2": "body_2",
    "默认体型": "body_default",
    "兔牙": "buck_teeth",
    "前倾": "lean_forward",
    "加载": "loading",
    "单片眼镜": "monocle",
    "黑框眼镜": "black_glasses",
    "尾巴开关": "tail_toggle",
    "屑屑眼": "eyes_alt",
    "竖食指开": "index_finger_on",
    "竖食指关": "index_finger_off",
    "胸口衣服": "chest_clothes",
    "脱鞋": "shoes_off",
    "裙子切换": "skirt_switch",
    "钢盆": "steel_bowl",
    "黑脸": "dark_face",
}

# Motion groups the chat uses. group -> (source file stem, ASCII name, loop override or None).
# Every source motion has "Loop": true (made for a streaming app). The "back" clips must end, so the idle loop can
# resume; the "raise" / "finger" clips keep looping, which holds the pose until the chat plays the matching "back".
MOTIONS = {
    "Idle": ("IDLE", "idle", None),
    "Raise": ("默认手切举手", "raise", None),
    "RaiseBack": ("举手切默认手", "raise_back", False),
    "Finger": ("竖手指切出来动画", "finger", None),
    "FingerBack": ("竖手指切回默认", "finger_back", False),
}
# Not copied: 脱捕 (13 s, undresses the model; not used and not suitable for a classroom game).


def inside(base: Path, p: Path) -> Path:
    """Resolve p and refuse anything outside base (the source folder is untrusted data)."""
    rp = p.resolve()
    try:
        rp.relative_to(base.resolve())
    except ValueError:
        sys.exit(f"Refusing a path outside the model folder: {p}")
    return rp


def load_json(p: Path) -> dict:
    with p.open("r", encoding="utf-8-sig") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        sys.exit(f"Not a JSON object: {p}")
    return data


def write_json(p: Path, data: dict, indent: int | None = 2) -> None:
    p.write_text(json.dumps(data, ensure_ascii=True, indent=indent), encoding="utf-8")


def downscale(src: Path, dst: Path, size: int) -> tuple[int, int]:
    """Resize with premultiplied alpha so transparent edges do not pick up dark fringes."""
    with Image.open(src) as im:
        im.load()
        w, h = im.size
        if max(w, h) <= size:
            out = im.convert("RGBA")
        else:
            scale = size / max(w, h)
            new = (max(1, round(w * scale)), max(1, round(h * scale)))
            out = im.convert("RGBa").resize(new, Image.LANCZOS).convert("RGBA")
        out.save(dst, "PNG", optimize=True)
        return out.size


def find_main(src: Path, name: str | None) -> Path:
    files = sorted(src.glob("*.model3.json"))
    if name:
        files = [f for f in files if f.name == name]
    if not files:
        sys.exit(f"No *.model3.json in {src}")
    return files[0]


def main() -> None:
    sys.stdout.reconfigure(errors="backslashreplace")  # source names are Chinese; consoles are not always UTF-8
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("source", type=Path, help="folder that contains the model's .model3.json")
    ap.add_argument("--main", help="model3.json file name when the folder has several")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"output folder (default {DEFAULT_OUT})")
    args = ap.parse_args()

    src = args.source.resolve()
    if not src.is_dir():
        sys.exit(f"Not a folder: {src}")
    main_file = find_main(src, args.main)
    model = load_json(main_file)
    refs = model.get("FileReferences") or {}
    out = args.out.resolve()
    if out.exists():
        shutil.rmtree(out)
    (out / "textures").mkdir(parents=True)
    (out / "expressions").mkdir()
    (out / "motions").mkdir()

    new_refs: dict = {}

    moc = inside(src, src / refs["Moc"])
    shutil.copyfile(moc, out / "misaki.moc3")
    new_refs["Moc"] = "misaki.moc3"
    with moc.open("rb") as f:
        head = f.read(5)
    print(f"moc3: {moc.stat().st_size / 1e6:.1f} MB, version byte {head[4] if len(head) == 5 else '?'}")

    textures = []
    for i, t in enumerate(refs.get("Textures") or []):
        name = f"texture_{i:02d}.png"
        size = downscale(inside(src, src / t), out / "textures" / name, TEXTURE_SIZE)
        print(f"texture {i}: {t} -> textures/{name} {size[0]}x{size[1]}")
        textures.append(f"textures/{name}")
    new_refs["Textures"] = textures

    if refs.get("Physics"):
        shutil.copyfile(inside(src, src / refs["Physics"]), out / "misaki.physics3.json")
        new_refs["Physics"] = "misaki.physics3.json"

    # expressions
    exp_dir = src / "Exp3"
    exps = []
    for f in sorted(exp_dir.glob("*.exp3.json")) if exp_dir.is_dir() else []:
        stem = f.name[: -len(".exp3.json")]
        ascii_name = EXPRESSIONS.get(stem)
        if not ascii_name:
            ascii_name = "exp_" + ("".join(c for c in stem if c.isascii() and c.isalnum()).lower() or str(len(exps)))
            print(f"unmapped expression {stem!r} -> {ascii_name}")
        data = load_json(inside(src, f))
        write_json(out / "expressions" / f"{ascii_name}.exp3.json", data, indent=2)
        exps.append({"Name": ascii_name, "File": f"expressions/{ascii_name}.exp3.json"})
    new_refs["Expressions"] = exps
    missing = [n for n in ("blush", "heart", "tears", "sweat", "spiral", "xx") if n not in {e["Name"] for e in exps}]
    if missing:
        print("WARNING: expressions missing:", ", ".join(missing))

    # motions
    motions: dict = {}
    anim_dir = src / "Animation"
    for group, (stem, ascii_name, loop) in MOTIONS.items():
        f = anim_dir / f"{stem}.motion3.json"
        if not f.is_file():
            print(f"WARNING: motion {stem} not found, group {group} skipped")
            continue
        data = load_json(inside(src, f))
        if loop is not None:
            data.setdefault("Meta", {})["Loop"] = loop
        write_json(out / "motions" / f"{ascii_name}.motion3.json", data, indent=None)
        motions[group] = [{"File": f"motions/{ascii_name}.motion3.json", "FadeInTime": 0.3, "FadeOutTime": 0.3}]
    new_refs["Motions"] = motions

    new_model = {
        "Version": 3,
        "FileReferences": new_refs,
        "Groups": model.get("Groups") or [],
    }
    write_json(out / "misaki.model3.json", new_model)

    # portrait for low-power devices (Save-Data, no WebGL)
    portrait_src = None
    for cand in sorted(src.glob("*.png")):
        portrait_src = cand
        break
    if portrait_src:
        with Image.open(inside(src, portrait_src)) as im:
            im.load()
            im = im.convert("RGBA")
            bbox = im.getbbox()
            if bbox:
                im = im.crop(bbox)
            im.thumbnail((PORTRAIT_SIZE, PORTRAIT_SIZE), Image.LANCZOS)
            im.save(out / "portrait.png", "PNG", optimize=True)
            try:
                im.save(out / "portrait.webp", "WEBP", quality=86, method=6)
            except Exception as e:  # webp not built into this Pillow
                print("webp skipped:", e)
            print(f"portrait: {im.size[0]}x{im.size[1]}")
    else:
        print("WARNING: no png preview found for the portrait")

    total = sum(p.stat().st_size for p in out.rglob("*") if p.is_file())
    print(f"done: {out} ({total / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
