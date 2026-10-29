"""Model subprocess. It holds the provider key and talks to the network; tools run in the parent.

Newline-delimited JSON over anonymous pipes:
  parent -> child  first line: the request (never a command argument or temporary file)
  child  -> parent {"type": "event", "step": {...}}            live trajectory step
                   {"type": "tool", "id": n, "name", "args"}   tool request
                   {"type": "final", "output": {...}}          last message
  parent -> child  {"type": "tool_result", "id": n, "ok": bool, "evidence" | "code"}
"""

import json
import sys

from app.observability import tracing
from app.reports.tools import ToolError
from app.reports.workflow import ReportWorkflow

LIMIT = 16 * 1024 * 1024


class Channel:
    def __init__(self, reader, writer):
        self.reader, self.writer, self.sequence = reader, writer, 0

    def send(self, message):
        self.writer.write((json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8"))
        self.writer.flush()

    def tool(self, name, args):
        self.sequence += 1
        self.send({"type": "tool", "id": self.sequence, "name": name, "args": args})
        line = self.reader.readline(LIMIT + 1)
        if not line or len(line) > LIMIT:
            raise ToolError("TOOL_CHANNEL_CLOSED")
        reply = json.loads(line)
        if reply.get("type") != "tool_result" or reply.get("id") != self.sequence:
            raise ToolError("TOOL_CHANNEL")
        if not reply.get("ok"):
            raise ToolError(str(reply.get("code") or "TOOL_FAILED")[:64])
        return reply["evidence"]

    def emit(self, step):
        self.send({"type": "event", "step": step})


def main():
    tracing.init("shoppulse-agent")
    channel = Channel(sys.stdin.buffer, sys.stdout.buffer)
    try:
        line = sys.stdin.buffer.readline(LIMIT + 1)
        if len(line) > LIMIT:
            raise ValueError
        request = json.loads(line)
        output = ReportWorkflow(request, tools=channel.tool, emit=channel.emit).run()
    except Exception:
        output = {
            "analysis": None,
            "raw_analysis": None,
            "error_code": "MODEL_OUTPUT_INVALID",
            "usage": {},
            "steps": [],
        }
    # Steps were streamed as events; the parent keeps its own trusted evidence list.
    output.pop("extra_evidence", None)
    output.pop("steps", None)
    output.pop("analysis", None)  # The parent re-validates raw_analysis against its evidence.
    channel.send({"type": "final", "output": output})
    tracing.flush()


if __name__ == "__main__":
    main()
