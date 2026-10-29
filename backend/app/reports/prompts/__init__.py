"""Versioned prompt files. A prompt change ships as a new directory and a PROMPT_VERSION bump."""

from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LANGUAGE_NAMES = {"zh": "Simplified Chinese (简体中文)", "en": "English"}


@lru_cache
def load(version, name):
    return (ROOT / version / f"{name}.md").read_text(encoding="utf-8")


def system_prompt(version, kind, language, strategy, tool_names=()):
    text = load(version, "common").replace("{language_name}", LANGUAGE_NAMES[language])
    text += "\n\n" + load(version, "report" if kind == "report" else "question")
    if strategy == "restricted_json":
        text += (
            "\n\n## Tool requests\n\nTo use tools, reply with JSON only: "
            '{"tools": [{"tool": "<name>", "arguments": {...}}]} with one to three calls. '
            "Available tools and their arguments are listed in `tool_catalog`. "
            "Otherwise reply with the final JSON object."
        )
    elif strategy == "narrative":
        text += "\n\nTools are unavailable in this session; use the evidence you were given."
    return text
