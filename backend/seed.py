import argparse

from .database import reset_fixture_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset the local CasePilot demo database to its fictional fixtures.")
    parser.add_argument("--reset", action="store_true", required=True, help="Replace all records in the local demo database.")
    parser.parse_args()

    metadata = reset_fixture_database()
    print(f"Loaded {metadata['fixture_version']} at fixed clock {metadata['clock_utc']}.")


if __name__ == "__main__":
    main()
