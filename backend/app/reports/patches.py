"""Local repairs: replace only the sentences or fields that failed, then re-validate the whole.

A full rewrite of the final JSON costs as many output tokens as the first answer; a patch costs a
few sentences. Issues whose location is not a single sentence or field fall back to a rewrite.
"""

import copy
import re

from pydantic import ValidationError

from app.reports.schema import PatchReply

INDEX = r"\[(\d{1,2})\]"
# (pattern, kind): kind says which patch field carries the replacement.
TARGETS = [
    (rf"^(summary|answer){INDEX}", "sentence"),
    (rf"^findings{INDEX}\.(observation|supporting{INDEX}|hypotheses{INDEX})", "sentence"),
    (rf"^findings{INDEX}\.title", "text"),
    (rf"^findings{INDEX}\.hypothesis_ids", "ids"),
    (rf"^recommendations{INDEX}\.action", "sentence"),
    (rf"^recommendations{INDEX}\.rationale_finding_ids", "ids"),
    (rf"^recommendations{INDEX}\.verification_metric", "text"),
    (rf"^ruled_out{INDEX}\.sentence", "sentence"),
    (rf"^ruled_out{INDEX}\.hypothesis_id", "text"),
    (r"^clarify", "sentence"),
    (rf"^options{INDEX}", "text"),
]
COMPILED = [(re.compile(pattern), kind) for pattern, kind in TARGETS]


def target(at):
    """Normalized patch location and kind for an issue location, or None."""
    for pattern, kind in COMPILED:
        match = pattern.match(at)
        if match:
            return match.group(0), kind
    return None


def targets(issues):
    """{location: kind} when every issue can be patched locally, else None."""
    found = {}
    for item in issues:
        hit = target(item["at"])
        if hit is None:
            return None
        found[hit[0]] = hit[1]
    return found or None


def steps(at):
    parts = []
    for name, index in re.findall(r"([a-z_]+)(?:\[(\d+)\])?", at):
        parts.append(name)
        if index:
            parts.append(int(index))
    return parts


def apply(raw, reply, allowed):
    """Return a patched copy of ``raw``. Raises ValueError for unusable patches."""
    try:
        parsed = PatchReply.model_validate(reply).model_dump(mode="json")
    except ValidationError:
        raise ValueError("INVALID_PATCH") from None
    result = copy.deepcopy(raw)
    for patch in parsed["patches"]:
        hit = target(patch["at"])
        if hit is None or hit[0] != patch["at"] or patch["at"] not in allowed:
            raise ValueError("INVALID_PATCH")
        kind = hit[1]
        value = patch[kind]
        if value is None:
            raise ValueError("INVALID_PATCH")
        path = steps(patch["at"])
        node = result
        for step in path[:-1]:
            try:
                node = node[step]
            except (KeyError, IndexError, TypeError):
                raise ValueError("INVALID_PATCH") from None
        try:
            node[path[-1]]  # The location must already exist; patches never add items.
        except (KeyError, IndexError, TypeError):
            raise ValueError("INVALID_PATCH") from None
        node[path[-1]] = value
    return result


def request(issues, allowed):
    lines = [
        f"- {i['at']}: {i['code']}" + (f" ({i['hint']})" if i.get("hint") else "") for i in issues
    ]
    fields = {"sentence": "a Sentence", "text": "a string", "ids": "a list of ids"}
    where = [f"- {at}: {fields[kind]}" for at, kind in allowed.items()]
    return (
        "Your last reply failed validation and was not shown to the merchant. Do not rewrite the "
        "whole reply. Return only patches as JSON: "
        '{"patches": [{"at": "<location>", "sentence": Sentence or null, "text": string or null, '
        '"ids": [ids] or null}]}, one patch per location below, filling the one field it needs. '
        "Keep values in bindings; tools are closed.\nProblems:\n"
        + "\n".join(lines)
        + "\nLocations to patch:\n"
        + "\n".join(where)
    )
