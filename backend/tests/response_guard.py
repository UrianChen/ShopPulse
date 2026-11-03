"""Response models must document the API's JSON, never reshape it.

Every response serialized through a ``response_model`` is compared, byte for byte, with what
FastAPI's ``jsonable_encoder`` produces for the same return value (the API's output before the
models were declared). A dropped, renamed, reordered or reformatted field fails the test that
made the request.
"""

import fastapi.routing
import pytest
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

_original = fastapi.routing.serialize_response


@pytest.fixture(autouse=True)
def response_models_keep_json(monkeypatch):
    mismatches = []

    async def compare(**kwargs):
        content = await _original(**kwargs)
        if kwargs.get("field") is not None:
            current = content if isinstance(content, bytes) else JSONResponse(content).body
            encoded = JSONResponse(jsonable_encoder(kwargs["response_content"])).body
            if current != encoded:
                mismatches.append((current, encoded))
        return content

    monkeypatch.setattr(fastapi.routing, "serialize_response", compare)
    yield
    assert not mismatches, "response model changed the JSON:\n" + "\n".join(
        f"model:   {current[:600]!r}\nencoder: {encoded[:600]!r}" for current, encoded in mismatches
    )
