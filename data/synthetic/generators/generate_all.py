"""Generate all synthetic MARC test data.

Entry point for `just generate-synthetic`.
"""

from __future__ import annotations

from generate_encoding import generate_all as generate_encoding
from generate_malformed import generate_all as generate_malformed


def main() -> None:
    print("Generating malformed records...")
    generate_malformed()
    print()
    print("Generating encoding records...")
    generate_encoding()
    print()
    print("Done.")


if __name__ == "__main__":
    main()
