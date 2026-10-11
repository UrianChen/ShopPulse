import argparse

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import engine
from app.providers.credentials import rotate


def main():
    parser = argparse.ArgumentParser(description="ShopPulse maintenance")
    commands = parser.add_subparsers(dest="command", required=True)
    rotation = commands.add_parser("rotate-credentials")
    rotation.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    settings().validate_secrets()
    try:
        with Session(engine()) as db, db.begin():
            count = rotate(db, dry_run=args.dry_run)
    except Exception:
        parser.exit(1, "Rotation failed; check key versions and files.\n")
    print(f"Credentials {'requiring rotation' if args.dry_run else 'rotated'}: {count}")


if __name__ == "__main__":
    main()
