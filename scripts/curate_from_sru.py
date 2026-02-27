"""Curate fixture records from LOC's SRU service.

Queries the Library of Congress catalog via SRU for targeted record types,
converts MARCXML responses to ISO 2709 binary, and writes fixture files
with manifest.json provenance.

This avoids downloading the full ~15GB LOC Books All dataset for initial
fixture curation. The SRU service returns MARCXML records that mrrc
converts to standard MARC binary.

Usage:
    uv run python scripts/curate_from_sru.py \
        --output data/fixtures/bibliographic/
    uv run python scripts/curate_from_sru.py \
        --output data/fixtures/authority/ --authority
"""

import argparse
import json
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

import mrrc

# LOC SRU endpoint for the Online Catalog
LOC_CATALOG_SRU = "http://lx2.loc.gov:210/LCDB"
LOC_NAF_SRU = "http://lx2.loc.gov:210/NAF"
LOC_SAF_SRU = "http://lx2.loc.gov:210/SAF"

# MARCXML namespace
MARC_NS = "http://www.loc.gov/MARC21/slim"
SRU_NS = "http://www.loc.gov/zing/srw/"

# Queries for targeted bibliographic record selection.
# Each tuple: (description, CQL query, max records to fetch)
# Use only indexes confirmed to work with LOC's SRU: bath.title, bath.author,
# bath.lccn, bath.isbn, dc.date.  Keep queries small and polite.
BIBLIOGRAPHIC_QUERIES = [
    # Targeted by subject matter (using title keywords)
    ("history_pre1900", 'bath.title="history" and dc.date<1900', 30),
    ("modern_books", 'bath.title="novel" and dc.date>2010', 30),
    ("atlas_maps", 'bath.title="atlas"', 20),
    ("music_scores", 'bath.title="sonata"', 20),
    ("photographs", 'bath.title="photographs"', 15),
    # Foreign language / non-Latin scripts
    ("french_titles", 'bath.title="bibliothèque"', 25),
    ("cjk_content", 'bath.title="中国"', 20),
    ("cyrillic_content", 'bath.title="Москва"', 20),
    ("arabic_content", 'bath.title="القاهرة"', 15),
    # Broad random-ish samples via common title words
    ("general_sample_a", 'bath.title="science"', 40),
    ("general_sample_b", 'bath.title="education"', 40),
    ("general_sample_c", 'bath.title="poetry"', 40),
    ("general_sample_d", 'bath.title="engineering"', 40),
    ("general_sample_e", 'bath.title="medicine"', 40),
    ("general_sample_f", 'bath.title="economics"', 40),
    ("general_sample_g", 'bath.title="geography"', 40),
    ("general_sample_h", 'bath.title="religion"', 35),
]

# Authority queries — use name and subject indexes
AUTHORITY_QUERIES = [
    ("personal_names_a", 'bath.personalName="smith"', 30),
    ("personal_names_b", 'bath.personalName="johnson"', 30),
    ("corporate_names", 'bath.corporateName="university"', 30),
    ("geographic_names", 'bath.name="new york"', 20),
    ("personal_names_c", 'bath.personalName="garcia"', 20),
    ("personal_names_d", 'bath.personalName="müller"', 20),
]

# Delay between SRU requests (seconds) — be polite to LOC's servers
REQUEST_DELAY = 2.0


def sru_search(base_url: str, query: str, max_records: int = 10,
               start_record: int = 1) -> str:
    """Execute an SRU search and return the raw XML response."""
    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "recordSchema": "marcxml",
        "maximumRecords": str(max_records),
        "startRecord": str(start_record),
        "query": query,
    }
    url = f"{base_url}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "mrrc-testbed/0.1"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def extract_marcxml_records(sru_xml: str) -> list[str]:
    """Extract individual MARCXML <record> elements from SRU response."""
    root = ET.fromstring(sru_xml)
    records = []
    for sru_record in root.findall(f".//{{{SRU_NS}}}recordData"):
        marc_record = sru_record.find(f"{{{MARC_NS}}}record")
        if marc_record is not None:
            records.append(ET.tostring(marc_record, encoding="unicode"))
    return records


def marcxml_to_binary(marcxml_str: str) -> tuple[bytes | None, str | None]:
    """Convert a single MARCXML record to ISO 2709 binary bytes.

    Returns (binary_bytes, control_number) or (None, None) on failure.
    """
    try:
        # Wrap in collection for xml_to_records
        wrapped = (
            f'<collection xmlns="{MARC_NS}">'
            f"{marcxml_str}"
            f"</collection>"
        )
        records = mrrc.xml_to_records(wrapped)
        if not records:
            return None, None
        record = records[0]

        # Get control number
        cn = record.control_field("001")
        cn_str = cn if cn else None

        # Write to binary
        import io
        buf = io.BytesIO()
        writer = mrrc.MARCWriter(buf)
        writer.write(record)
        writer.close()
        binary = buf.getvalue()
        return binary, cn_str
    except Exception as e:
        print(f"    Warning: conversion failed: {e}", file=sys.stderr)
        return None, None


def curate_bibliographic(output_dir: Path, target_count: int = 500) -> int:
    """Curate bibliographic fixture records from LOC SRU."""
    output_dir.mkdir(parents=True, exist_ok=True)
    mrc_path = output_dir / "sample.mrc"
    manifest_path = output_dir / "manifest.json"

    all_binary = bytearray()
    manifest_records = []
    seen_control_numbers = set()
    total = 0

    for desc, query, max_recs in BIBLIOGRAPHIC_QUERIES:
        if total >= target_count:
            break

        remaining = target_count - total
        fetch_count = min(max_recs, remaining)

        print(f"  Querying: {desc} ({fetch_count} records)...")
        try:
            xml = sru_search(LOC_CATALOG_SRU, query, max_records=fetch_count)
        except Exception as e:
            print(f"    Error querying {desc}: {e}")
            continue

        marcxml_records = extract_marcxml_records(xml)
        print(f"    Got {len(marcxml_records)} MARCXML records")

        for marcxml_str in marcxml_records:
            if total >= target_count:
                break

            binary, cn = marcxml_to_binary(marcxml_str)
            if binary is None:
                continue

            # Skip duplicates
            if cn and cn in seen_control_numbers:
                continue
            if cn:
                seen_control_numbers.add(cn)

            offset = len(all_binary)
            all_binary.extend(binary)

            manifest_records.append({
                "index": total,
                "control_number": cn,
                "source_offset": offset,
                "selection_reason": (
                    f"targeted:{desc}"
                    if "sample" not in desc
                    else "random_sample"
                ),
                "notes": None,
            })
            total += 1

        time.sleep(REQUEST_DELAY)

    # Write files
    mrc_path.write_bytes(bytes(all_binary))
    manifest = {
        "source": "Library of Congress Online Catalog (SRU)",
        "source_url": "https://www.loc.gov/standards/sru/resources/lcServers.html",
        "download_date": time.strftime("%Y-%m-%d"),
        "license": "Public Domain (US Government Work)",
        "records": manifest_records,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"  Wrote {total} records to {mrc_path} ({len(all_binary)} bytes)")
    return total


def curate_authority(output_dir: Path, target_count: int = 150) -> int:
    """Curate authority fixture records from LOC NAF/SAF SRU."""
    output_dir.mkdir(parents=True, exist_ok=True)
    mrc_path = output_dir / "sample.mrc"
    manifest_path = output_dir / "manifest.json"

    all_binary = bytearray()
    manifest_records = []
    seen_control_numbers = set()
    total = 0

    for desc, query, max_recs in AUTHORITY_QUERIES:
        if total >= target_count:
            break

        remaining = target_count - total
        fetch_count = min(max_recs, remaining)

        # Use NAF for name queries, SAF for subject queries
        base_url = LOC_SAF_SRU if "subject" in desc or "genre" in desc else LOC_NAF_SRU

        print(f"  Querying: {desc} ({fetch_count} records)...")
        try:
            xml = sru_search(base_url, query, max_records=fetch_count)
        except Exception as e:
            print(f"    Error querying {desc}: {e}")
            continue

        marcxml_records = extract_marcxml_records(xml)
        print(f"    Got {len(marcxml_records)} MARCXML records")

        for marcxml_str in marcxml_records:
            if total >= target_count:
                break

            binary, cn = marcxml_to_binary(marcxml_str)
            if binary is None:
                continue

            if cn and cn in seen_control_numbers:
                continue
            if cn:
                seen_control_numbers.add(cn)

            offset = len(all_binary)
            all_binary.extend(binary)

            manifest_records.append({
                "index": total,
                "control_number": cn,
                "source_offset": offset,
                "selection_reason": f"targeted:{desc}",
                "notes": None,
            })
            total += 1

        time.sleep(0.5)

    mrc_path.write_bytes(bytes(all_binary))
    manifest = {
        "source": "Library of Congress Authority Files (SRU)",
        "source_url": "https://www.loc.gov/standards/sru/resources/lcServers.html",
        "download_date": time.strftime("%Y-%m-%d"),
        "license": "Public Domain (US Government Work)",
        "records": manifest_records,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(f"  Wrote {total} records to {mrc_path} ({len(all_binary)} bytes)")
    return total


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Curate fixture records from LOC's SRU service."
    )
    parser.add_argument(
        "--output", type=Path, required=True,
        help="Output directory for sample.mrc and manifest.json",
    )
    parser.add_argument(
        "--authority", action="store_true",
        help="Curate authority records instead of bibliographic",
    )
    parser.add_argument(
        "--count", type=int, default=500,
        help="Target number of records (default: 500)",
    )
    args = parser.parse_args()

    if args.authority:
        print("Curating authority records from LOC SRU...")
        total = curate_authority(args.output, args.count)
    else:
        print("Curating bibliographic records from LOC SRU...")
        total = curate_bibliographic(args.output, args.count)

    if total == 0:
        print("ERROR: No records curated.", file=sys.stderr)
        return 1

    print(f"\nDone. Curated {total} records.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
