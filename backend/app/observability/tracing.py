"""Optional OpenTelemetry tracing for agent runs.

Spans are exported only when ``OTEL_EXPORTER_OTLP_ENDPOINT`` (or the traces-specific variable) is
set, e.g. to a self-hosted Langfuse or Arize Phoenix OTLP endpoint. Without it the API tracer is a
no-op; runs still record a local trace id and timed steps in ``agent_runs``.
Span attributes carry sizes, counts, codes and ids only, never prompts, keys or data values.
"""

import contextlib
import os
import uuid

from opentelemetry import trace
from opentelemetry.propagate import extract, inject

_provider = None


def init(service_name):
    """Configure the OTLP exporter once per process. Returns True when exporting."""
    global _provider
    if _provider is not None:
        return True
    if not (
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT")
    ):
        return False
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError:
        return False
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(provider)
    _provider = provider
    return True


def flush():
    if _provider is not None:
        _provider.force_flush(timeout_millis=3000)


def _clean(attributes):
    return {
        k: v
        for k, v in (attributes or {}).items()
        if isinstance(v, (str, bool, int, float)) and v is not None
    }


@contextlib.contextmanager
def span(name, attributes=None, traceparent=None):
    context = extract({"traceparent": traceparent}) if traceparent else None
    tracer = trace.get_tracer("shoppulse.agent", "2.0.0")
    with tracer.start_as_current_span(name, context=context, attributes=_clean(attributes)) as item:
        yield item


def annotate(item, attributes):
    for key, value in _clean(attributes).items():
        item.set_attribute(key, value)


def traceparent():
    carrier = {}
    inject(carrier)
    return carrier.get("traceparent")


def trace_id(item=None):
    """Hex trace id of the active span, or a fresh local id when tracing is not exporting."""
    context = (item or trace.get_current_span()).get_span_context()
    if context.is_valid:
        return format(context.trace_id, "032x")
    return uuid.uuid4().hex
