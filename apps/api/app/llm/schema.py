"""Convert Pydantic models into JSON Schemas acceptable for strict structured output.

Strict mode (OpenAI-style, also used by Groq) requires: every property listed in `required`,
`additionalProperties: false` on every object, no unsupported keywords (numeric bounds, formats,
defaults, titles). Bounds removed here are still enforced by Pydantic validation afterwards.
"""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel

_DROP_KEYS = {
    "title",
    "default",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "format",
    "minLength",
    "maxLength",
    "pattern",
    "minItems",
    "maxItems",
    "examples",
}


def _inline_refs(node: Any, defs: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        if "$ref" in node:
            ref = node["$ref"].split("/")[-1]
            return _inline_refs(copy.deepcopy(defs[ref]), defs)
        return {k: _inline_refs(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [_inline_refs(v, defs) for v in node]
    return node


def _strictify(node: Any) -> Any:
    if isinstance(node, dict):
        node = {k: _strictify(v) for k, v in node.items() if k not in _DROP_KEYS}
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"].keys())
            node["additionalProperties"] = False
        return node
    if isinstance(node, list):
        return [_strictify(v) for v in node]
    return node


def strict_json_schema(model: type[BaseModel]) -> dict[str, Any]:
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})
    return _strictify(_inline_refs(raw, defs))


def compact_schema_hint(model: type[BaseModel]) -> str:
    """Short human-readable schema used in json_object mode prompts."""
    import json  # noqa: PLC0415

    return json.dumps(strict_json_schema(model), separators=(",", ":"))
