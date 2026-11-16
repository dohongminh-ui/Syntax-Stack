"""Draft a review packet via n8n and verify its code against the puzzle-bank rules."""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys

import httpx
import yaml
from pydantic import BaseModel, Field

import generate_bank as gen
from app import bank, tutor


class Mistake(BaseModel):
    code: str = Field(min_length=1, max_length=400)
    why: str = Field(min_length=1, max_length=350)


class Followup(BaseModel):
    prompt: str = Field(min_length=1, max_length=350)
    code: str = Field(min_length=1, max_length=400)
    expected_output: str = Field(min_length=1, max_length=210)


class Draft(BaseModel):
    hints: list[str] = Field(min_length=3, max_length=3)
    mistakes: list[Mistake] = Field(min_length=3, max_length=3)
    followup: Followup


def review_packet(raw: dict, template: dict, sample: dict) -> dict:
    draft = Draft.model_validate(raw)
    hints = [hint.strip() for hint in draft.hints]
    if any(not hint or len(hint) > 240 for hint in hints) or len(set(hints)) != 3:
        raise ValueError("Expected three distinct, short hints.")
    followup = draft.followup
    actual = gen.run_expected(followup.code)
    if actual != gen.V.normalize_output(followup.expected_output):
        raise ValueError("The follow-up output disagrees with the validator.")
    if followup.code.strip() == sample["solution_code"].strip():
        raise ValueError("The follow-up repeats the reference program.")
    topic_node = {"variables": ast.Assign, "conditions": ast.If, "loops": ast.For,
                  "functions": ast.FunctionDef}[template["topic"]]
    if not any(isinstance(node, topic_node) for node in ast.walk(ast.parse(followup.code))):
        raise ValueError("The follow-up omits the template's Python concept.")
    seen = {followup.code.strip()}
    checked_mistakes = []
    for mistake in draft.mistakes:
        code = mistake.code.strip("\n")
        if not mistake.why.strip() or code.strip() in seen:
            raise ValueError("Expected distinct mistakes with explanations.")
        seen.add(code.strip())
        gen.check_program(code)
        diagnosis = gen.V.diagnose(code, actual)
        if diagnosis.passed or diagnosis.run.error_kind in {"unsafe", "limit"}:
            raise ValueError("A proposed mistake passes or uses unsupported code.")
        checked_mistakes.append({**mistake.model_dump(), "actual_output": diagnosis.actual_output,
                                 "error_group": diagnosis.error_group})
    return {
        "status": "needs_editor_review", "template_id": template["id"], "topic": template["topic"],
        "type": template["type"], "reference_puzzle_id": sample["id"], "tier": sample["tier"],
        "hints": hints, "followup": {**followup.model_dump(), "expected_output": actual},
        "mistakes": checked_mistakes,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("template", choices=[path.stem for path in sorted(gen.TEMPLATE_DIR.glob("*.yaml"))])
    parser.add_argument("--tier", type=int, choices=(1, 2, 3), default=1)
    args = parser.parse_args()
    template = yaml.safe_load((gen.TEMPLATE_DIR / f"{args.template}.yaml").read_text(encoding="utf-8"))
    sample = bank.select_puzzle(kind="rescue", topic=template["topic"], tier=args.tier, level="intermediate",
                                template_id=template["id"], exclude_ids=[], exclude_templates=[])
    context = {
        "template": {key: template[key] for key in ("id", "topic", "type", "hints", "explanation")},
        "reference": {key: sample[key] for key in ("prompt", "solution_code", "expected_output")},
    }
    try:
        payload = json.dumps({"task": "content_review", "context": context}, ensure_ascii=False)
        response = tutor.request_tutor(os.environ["SYNTAX_STACK_TUTOR_URL"], payload, timeout=80)
        if not response.get("text"):
            raise ValueError(f"No draft returned ({response.get('error_category') or response.get('status')}).")
        packet = review_packet(json.loads(response["text"]), template, sample)
    except (KeyError, ValueError, httpx.HTTPError, gen.Drop) as error:
        print(f"Draft rejected: {error}", file=sys.stderr)
        return 1
    print(json.dumps(packet, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
