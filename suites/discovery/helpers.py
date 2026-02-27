"""Discovery writer utility for recording edge cases found during test runs.

Self-contained module with no dependency on mrrc_testbed.state. Writes JSON
arrays to results/discoveries/ for later import by scripts/import_run.py.
"""

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


class DiscoveryWriter:
    """Accumulates discoveries during a test run and writes them to disk.

    Mirrors the Rust DiscoveryWriter in crates/mrrc_testbed/src/discovery.rs.
    Test suites create a DiscoveryWriter, call record_error() for each problem
    found, then call finalize() to persist results as a JSON file.
    """

    def __init__(self, test_suite: str, results_dir: Path) -> None:
        self.test_suite = test_suite
        self.results_dir = results_dir
        self.discoveries: list[dict] = []
        self.seen_hashes: set[str] = set()
        self.duplicates_skipped: int = 0

    def record_error(
        self,
        test_name: str,
        source_path: Path,
        record_offset: int,
        raw_bytes: bytes,
        error_message: str,
        category: str = "unknown",
    ) -> None:
        """Record a discovery for a problematic MARC record.

        Deduplicates by SHA-256 hash of the raw bytes -- if the same record
        has already been seen in this run, the call increments
        duplicates_skipped and returns without creating a new discovery.
        """
        sha256_hex = hashlib.sha256(raw_bytes).hexdigest()

        if sha256_hex in self.seen_hashes:
            self.duplicates_skipped += 1
            return
        self.seen_hashes.add(sha256_hex)

        now = datetime.now(timezone.utc)
        seq = len(self.discoveries) + 1
        discovery_id = f"disc-{now.strftime('%Y-%m-%d')}-{seq:03d}"

        # Derive control number from raw bytes if possible.
        control_number = _extract_control_number(raw_bytes)

        # Derive dataset name from source path.
        source_dataset = source_path.parent.name or source_path.stem

        discovery = {
            "discovery_id": discovery_id,
            "discovered_at": now.isoformat(),
            "test_suite": self.test_suite,
            "test_name": test_name,
            "source_dataset": source_dataset,
            "record": {
                "sha256": sha256_hex,
                "control_number": control_number,
                "offset_bytes": record_offset,
            },
            "error": {
                "category": _categorize_error(error_message, category),
                "message": error_message,
            },
            "context": {},
        }

        self.discoveries.append(discovery)

    def finalize(self) -> Path:
        """Write all accumulated discoveries to a JSON file.

        Returns the path to the written JSON file.
        """
        self.results_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        filename = f"{self.test_suite}_{timestamp}.json"
        output_path = self.results_dir / filename

        with open(output_path, "w") as f:
            json.dump(self.discoveries, f, indent=2)

        total = len(self.discoveries)
        print(f"Discovery run complete ({self.test_suite}):")
        print(f"  Errors found: {total}")
        print(f"  Duplicates skipped: {self.duplicates_skipped}")
        print(f"  Output: {output_path}")

        return output_path


def _extract_control_number(raw_bytes: bytes) -> str:
    """Try to extract the MARC control number (field 001) from raw bytes.

    MARC records have a 24-byte leader. The directory starts at byte 24 and
    consists of 12-byte entries (3-byte tag + 4-byte field length + 5-byte
    starting position) terminated by a field terminator (0x1E).
    """
    if len(raw_bytes) < 37:
        return "unknown"

    try:
        base_address = int(raw_bytes[12:17].decode("ascii").strip())
    except (UnicodeDecodeError, ValueError):
        return "unknown"

    pos = 24
    while pos + 12 <= len(raw_bytes):
        if raw_bytes[pos] == 0x1E:
            break

        try:
            tag = raw_bytes[pos : pos + 3].decode("ascii")
            field_len = int(raw_bytes[pos + 3 : pos + 7].decode("ascii").strip())
            field_start = int(raw_bytes[pos + 7 : pos + 12].decode("ascii").strip())
        except (UnicodeDecodeError, ValueError):
            pos += 12
            continue

        if tag == "001":
            data_start = base_address + field_start
            data_end = data_start + field_len
            if data_end > len(raw_bytes):
                return "unknown"

            field_data = raw_bytes[data_start:data_end]
            # Strip field terminator (0x1E) and record terminator (0x1D).
            trimmed = bytes(
                b for b in field_data if b != 0x1E and b != 0x1D
            )
            try:
                return trimmed.decode("ascii").strip()
            except UnicodeDecodeError:
                return "unknown"

        pos += 12

    return "unknown"


def _categorize_error(message: str, default: str = "unknown") -> str:
    """Attempt to categorize an error based on its message text."""
    msg = message.lower()
    if "malform" in msg or "invalid record" in msg or "leader" in msg:
        return "malformed_record"
    if "encod" in msg or "utf" in msg or "charset" in msg:
        return "encoding_error"
    if "parse" in msg or "unexpected" in msg:
        return "parse_error"
    return default
