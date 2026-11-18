import argparse
import sqlite3

from .database import reset_fixture_database, upgrade_fixture_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Load the local CasePilot demo fixtures.")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--reset", action="store_true", help="Replace all records in the local demo database.")
    action.add_argument("--upgrade", action="store_true", help="Install new fixtures and preserve existing v3 records.")
    args = parser.parse_args()

    try:
        metadata = upgrade_fixture_database() if args.upgrade else reset_fixture_database()
    except (sqlite3.DatabaseError, ValueError) as error:
        parser.error(str(error))
    print(f"Loaded {metadata['fixture_version']} at fixed clock {metadata['clock_utc']}.")


if __name__ == "__main__":
    main()
