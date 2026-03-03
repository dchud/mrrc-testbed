from typing import Any

LEADER_LENGTH = 24


def _compare_leader(leader_a, leader_b) -> dict | None:
    """Compare two leaders position by position."""
    diffs = {}
    for i in range(LEADER_LENGTH):
        char_a = leader_a[i]
        char_b = leader_b[i]
        if char_a != char_b:
            diffs[i] = {"a": char_a, "b": char_b}
    return diffs if diffs else None


def _compare_subfields(subs_a: list, subs_b: list) -> list[dict]:
    """Compare two subfield lists pairwise by position."""
    diffs = []
    min_len = min(len(subs_a), len(subs_b))
    for i in range(min_len):
        sa, sb = subs_a[i], subs_b[i]
        if sa.code != sb.code or sa.value != sb.value:
            diffs.append({
                "index": i,
                "type": "changed",
                "a": {"code": sa.code, "value": sa.value},
                "b": {"code": sb.code, "value": sb.value},
            })
    for i in range(min_len, len(subs_a)):
        sa = subs_a[i]
        diffs.append({
            "index": i,
            "type": "only_in_a",
            "code": sa.code,
            "value": sa.value,
        })
    for i in range(min_len, len(subs_b)):
        sb = subs_b[i]
        diffs.append({
            "index": i,
            "type": "only_in_b",
            "code": sb.code,
            "value": sb.value,
        })
    return diffs


def compare_records(record_a: Any, record_b: Any) -> dict:
    """Compare two mrrc.Record objects and return a structured diff.

    Returns a dict with keys:
        "equal": bool
        "leader": dict or None — position-keyed leader diffs
        "control_fields": list — control field diffs
        "fields": list — data field diffs
    """
    leader_diff = _compare_leader(record_a.leader(), record_b.leader())

    # Control fields: list of (tag, value) tuples
    cf_a = record_a.control_fields()
    cf_b = record_b.control_fields()
    control_diffs = []
    min_cf = min(len(cf_a), len(cf_b))
    for i in range(min_cf):
        tag_a, val_a = cf_a[i]
        tag_b, val_b = cf_b[i]
        if tag_a != tag_b or val_a != val_b:
            control_diffs.append({
                "index": i,
                "type": "changed",
                "a": {"tag": tag_a, "value": val_a},
                "b": {"tag": tag_b, "value": val_b},
            })
    for i in range(min_cf, len(cf_a)):
        tag, val = cf_a[i]
        control_diffs.append({
            "index": i,
            "type": "only_in_a",
            "tag": tag,
            "value": val,
        })
    for i in range(min_cf, len(cf_b)):
        tag, val = cf_b[i]
        control_diffs.append({
            "index": i,
            "type": "only_in_b",
            "tag": tag,
            "value": val,
        })

    # Data fields
    fields_a = record_a.fields()
    fields_b = record_b.fields()
    field_diffs = []
    min_f = min(len(fields_a), len(fields_b))
    for i in range(min_f):
        fa, fb = fields_a[i], fields_b[i]
        ind_diff = {}
        if fa.indicator1 != fb.indicator1:
            ind_diff["indicator1"] = {"a": fa.indicator1, "b": fb.indicator1}
        if fa.indicator2 != fb.indicator2:
            ind_diff["indicator2"] = {"a": fa.indicator2, "b": fb.indicator2}
        sub_diffs = _compare_subfields(fa.subfields(), fb.subfields())
        tag_changed = fa.tag != fb.tag
        if tag_changed or ind_diff or sub_diffs:
            diff = {"index": i, "type": "changed", "tag_a": fa.tag, "tag_b": fb.tag}
            if ind_diff:
                diff["indicators"] = ind_diff
            if sub_diffs:
                diff["subfields"] = sub_diffs
            field_diffs.append(diff)
    for i in range(min_f, len(fields_a)):
        fa = fields_a[i]
        field_diffs.append({
            "index": i,
            "type": "only_in_a",
            "tag": fa.tag,
        })
    for i in range(min_f, len(fields_b)):
        fb = fields_b[i]
        field_diffs.append({
            "index": i,
            "type": "only_in_b",
            "tag": fb.tag,
        })

    equal = leader_diff is None and not control_diffs and not field_diffs
    return {
        "equal": equal,
        "leader": leader_diff,
        "control_fields": control_diffs,
        "fields": field_diffs,
    }


def diff_summary(comparison: dict) -> str:
    """Return a human-readable summary of a comparison dict."""
    if comparison["equal"]:
        return "Records are identical"

    lines = ["Records differ:"]

    if comparison["leader"]:
        for pos, diff in sorted(comparison["leader"].items()):
            lines.append(
                f"  Leader: position {pos}: {diff['a']!r} vs {diff['b']!r}"
            )

    for cd in comparison["control_fields"]:
        if cd["type"] == "changed":
            a, b = cd["a"], cd["b"]
            if a["tag"] == b["tag"]:
                lines.append(
                    f"  Control field {a['tag']}: {a['value']!r} vs {b['value']!r}"
                )
            else:
                lines.append(
                    f"  Control field index {cd['index']}: "
                    f"{a['tag']}={a['value']!r} vs {b['tag']}={b['value']!r}"
                )
        elif cd["type"] == "only_in_a":
            lines.append(
                f"  Control field {cd['tag']}: only in record A"
            )
        elif cd["type"] == "only_in_b":
            lines.append(
                f"  Control field {cd['tag']}: only in record B"
            )

    for fd in comparison["fields"]:
        if fd["type"] == "only_in_a":
            lines.append(f"  Field {fd['index']} ({fd['tag']}): only in record A")
        elif fd["type"] == "only_in_b":
            lines.append(f"  Field {fd['index']} ({fd['tag']}): only in record B")
        elif fd["type"] == "changed":
            if fd["tag_a"] == fd["tag_b"]:
                tag = fd["tag_a"]
            else:
                tag = f"{fd['tag_a']}/{fd['tag_b']}"
            for ind_name, ind_diff in fd.get("indicators", {}).items():
                lines.append(
                    f"  Field {fd['index']} ({tag}): "
                    f"{ind_name} {ind_diff['a']!r} vs {ind_diff['b']!r}"
                )
            for sd in fd.get("subfields", []):
                if sd["type"] == "changed":
                    a, b = sd["a"], sd["b"]
                    if a["code"] == b["code"]:
                        lines.append(
                            f"  Field {fd['index']} ({tag}): "
                            f"subfield ${a['code']}: {a['value']!r} vs {b['value']!r}"
                        )
                    else:
                        lines.append(
                            f"  Field {fd['index']} ({tag}): "
                            f"subfield {sd['index']}: "
                            f"${a['code']}={a['value']!r} "
                            f"vs ${b['code']}={b['value']!r}"
                        )
                elif sd["type"] == "only_in_a":
                    lines.append(
                        f"  Field {fd['index']} ({tag}): "
                        f"subfield ${sd['code']}: only in record A"
                    )
                elif sd["type"] == "only_in_b":
                    lines.append(
                        f"  Field {fd['index']} ({tag}): "
                        f"subfield ${sd['code']}: only in record B"
                    )

    return "\n".join(lines)
