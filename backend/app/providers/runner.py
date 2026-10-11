"""Secret IPC uses anonymous pipes, never command arguments or temporary files."""

import json
import sys

from app.providers.adapter import ProviderAdapter, failure
from app.providers.egress import ProviderError


def main():
    try:
        request = json.loads(sys.stdin.buffer.read(16384))
        result = ProviderAdapter(request["config"], request["key"]).probe()
    except Exception:
        result = {
            "usable": False,
            "strategy": "unavailable",
            "stages": {"basic": failure(ProviderError("INVALID_RESPONSE"))},
        }
    sys.stdout.write(json.dumps(result))


if __name__ == "__main__":
    main()
