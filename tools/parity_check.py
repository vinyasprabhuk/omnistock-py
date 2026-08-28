"""
Diffs tests/golden/*.json (captured from the live Next.js app) against
tests/parity_out/*.json (produced by tools/parity_dump.py running the Python
port), field by field, with a relative tolerance for floats.

Usage: python3 tools/parity_dump.py && python3 tools/parity_check.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

GOLDEN_DIR = Path(__file__).resolve().parent.parent / "tests" / "golden"
OUT_DIR = Path(__file__).resolve().parent.parent / "tests" / "parity_out"

REL_TOL = 1e-9
ABS_TOL = 1e-9  # for values very close to zero, where relative tolerance is meaningless

# Files intentionally excluded from strict parity (none currently -- kept for
# future use, e.g. if a deliberate behavior change needs an annotated
# expected-divergence rather than a straight diff).
SKIP_FILES: set[str] = set()

mismatches: list[str] = []


def numbers_close(a: float, b: float) -> bool:
    if a == b:
        return True
    diff = abs(a - b)
    if diff <= ABS_TOL:
        return True
    return diff <= REL_TOL * max(abs(a), abs(b))


def compare(path: str, golden, actual) -> None:
    if isinstance(golden, bool) or isinstance(actual, bool):
        if golden != actual:
            mismatches.append(f"{path}: golden={golden!r} actual={actual!r}")
        return
    if isinstance(golden, (int, float)) and isinstance(actual, (int, float)):
        if not numbers_close(float(golden), float(actual)):
            mismatches.append(f"{path}: golden={golden!r} actual={actual!r} (diff={abs(golden - actual)!r})")
        return
    if golden is None or actual is None:
        if golden != actual:
            mismatches.append(f"{path}: golden={golden!r} actual={actual!r}")
        return
    if isinstance(golden, dict) and isinstance(actual, dict):
        golden_keys = set(golden.keys())
        actual_keys = set(actual.keys())
        if golden_keys != actual_keys:
            missing = golden_keys - actual_keys
            extra = actual_keys - golden_keys
            if missing:
                mismatches.append(f"{path}: missing keys in actual: {sorted(missing)}")
            if extra:
                mismatches.append(f"{path}: unexpected extra keys in actual: {sorted(extra)}")
        for k in golden_keys & actual_keys:
            compare(f"{path}.{k}", golden[k], actual[k])
        return
    if isinstance(golden, list) and isinstance(actual, list):
        if len(golden) != len(actual):
            mismatches.append(f"{path}: length mismatch golden={len(golden)} actual={len(actual)}")
            return
        for i, (g_item, a_item) in enumerate(zip(golden, actual)):
            compare(f"{path}[{i}]", g_item, a_item)
        return
    if golden != actual:
        mismatches.append(f"{path}: golden={golden!r} actual={actual!r}")


def main() -> int:
    golden_files = sorted(p.stem for p in GOLDEN_DIR.glob("*.json") if p.stem != "_meta")
    if not golden_files:
        print(f"No golden files found in {GOLDEN_DIR}")
        return 1

    for name in golden_files:
        if name in SKIP_FILES:
            print(f"SKIP {name} (in SKIP_FILES)")
            continue
        golden_path = GOLDEN_DIR / f"{name}.json"
        actual_path = OUT_DIR / f"{name}.json"
        if not actual_path.exists():
            mismatches.append(f"{name}: no parity_out file found at {actual_path} -- has this scenario been ported yet?")
            continue
        golden = json.loads(golden_path.read_text())
        actual = json.loads(actual_path.read_text())
        before = len(mismatches)
        compare(name, golden, actual)
        after = len(mismatches)
        status = "OK" if after == before else f"{after - before} mismatch(es)"
        print(f"{name}: {status}")

    print()
    if mismatches:
        print(f"FAILED: {len(mismatches)} mismatch(es)\n")
        for m in mismatches[:200]:
            print(f"  - {m}")
        if len(mismatches) > 200:
            print(f"  ... and {len(mismatches) - 200} more")
        return 1

    print("PASSED: every golden scenario matches within tolerance.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
