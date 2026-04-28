"""Load and render agent prompts from YAML with Jinja2."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Template

_PROMPTS_DIR = Path(__file__).resolve().parent / "prompts"
_DEFAULT_PROMPTS_FILE = "prompts.yaml"


@lru_cache(maxsize=128)
def _load_prompts(prompts_file: str) -> dict[str, dict[str, str]]:
    """Load a prompts YAML file and cache."""
    path = _PROMPTS_DIR / prompts_file
    if not path.exists():
        raise FileNotFoundError(f"Prompts file not found: {path}")
    with path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{prompts_file} must be a mapping")
    return data


def get_prompt(
    category: str,
    role: str = "user",
    prompts_file: str = _DEFAULT_PROMPTS_FILE,
    **kwargs: Any,
) -> str:
    """Load a prompt template from YAML and render with Jinja2.

    Args:
        category: Top-level key in the YAML file (e.g. ``text_to_sql``).
        role: ``system`` or ``user``.
        prompts_file: YAML filename in prompts/ folder (default: ``prompts.yaml``).
        **kwargs: Variables for the Jinja2 template.

    Returns:
        Rendered prompt string.
    """
    data = _load_prompts(prompts_file)
    if category not in data:
        raise KeyError(f"Unknown prompt category: {category!r} in {prompts_file}")
    if role not in data[category]:
        raise KeyError(f"Missing {role!r} prompt for category {category!r} in {prompts_file}")

    template_str = data[category][role]
    template = Template(template_str)
    return template.render(**kwargs)


def clear_prompt_cache() -> None:
    """Invalidate all cached prompt files (e.g. after hot-reload in dev)."""
    _load_prompts.cache_clear()
