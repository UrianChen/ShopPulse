"""Generate local credentials once. Never print or overwrite their contents."""

import os
import secrets
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    folder = ROOT / "secrets"
    folder.mkdir(mode=0o700, exist_ok=True)
    for name in ("database_password", "credential_master_key"):
        path = folder / name
        try:
            # Private 0700 parent protects host access; readable secret mounts let
            # the non-root container user read them (Compose file secrets are bind mounts).
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            print(f"Kept existing secret: {name}")
            continue
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(secrets.token_urlsafe(48) + "\n")
        print(f"Created secret: {name}")
    print("Secrets are local files. Keep them private and back them up separately.")


if __name__ == "__main__":
    main()
