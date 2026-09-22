from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from app.llm.schemas import EXPLANATION_JSON_SCHEMA

PROMPT_ROOT = Path(__file__).resolve().parents[2] / "prompts"


def render_explanation_prompt(package: dict[str, Any], locale: str) -> str:
    environment = Environment(
        loader=FileSystemLoader(PROMPT_ROOT),
        undefined=StrictUndefined,
        autoescape=select_autoescape(default=False),
    )
    template = environment.get_template("v1/explain.j2")
    return template.render(
        locale=locale,
        evidence_json=json.dumps(package, ensure_ascii=True, sort_keys=True),
        output_schema=json.dumps(EXPLANATION_JSON_SCHEMA, ensure_ascii=True, sort_keys=True),
    )
