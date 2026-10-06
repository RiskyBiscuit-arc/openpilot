#!/usr/bin/env python3
"""Capture two independent CCP reads for A220 analysis; never writes EPS flash."""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import sys

ROM_SIZE = 0x80000


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def inspect_dump(data):
    result = {"size": len(data), "sha256": sha256(data)}
    if len(data) != ROM_SIZE:
        raise ValueError(f"Expected {ROM_SIZE} bytes, got {len(data)}")
    app = data[0x4000:0x70000]
    result["application_sha256"] = sha256(app)
    result["application_range_assumption"] = "A040 layout: 0x4000..0x70000; A220 unverified"
    checks = []
    for offset, sign in ((0x6BF80, 1), (0x6BFFE, -1)):
        calculated = (sign * sum(x[0] for x in struct.iter_unpack(">H", app[:offset]))) & 0xFFFF
        stored = int.from_bytes(app[offset:offset + 2], "big")
        checks.append({"application_offset": offset, "stored": stored,
                       "calculated": calculated, "matches": stored == calculated})
    result["a040_layout_checksum_checks"] = checks
    result["nonuniform_application"] = len(set(app)) > 1
    return result


def compare_dumps(first, second):
    return {
        "purpose": "Analysis only. DO NOT FLASH raw CCP captures.",
        "reported_part_number": "39990-TLA-A220 (operator supplied, not ECU authenticated)",
        "captures": [inspect_dump(first), inspect_dump(second)],
        "identical": first == second,
        "differing_byte_count": sum(a != b for a, b in zip(first, second)),
        "limitations": "Matching reads do not exclude repeatable CCP artifacts or establish patch compatibility. "
                       "A040 checksum geometry is a hypothesis for A220. No EEPROM backup is captured.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, required=True, help="New directory; existing paths refused")
    parser.add_argument("--bus", type=int, choices=(0, 1, 2), help="Otherwise discover on buses 0, 1, 2")
    parser.add_argument("--safety", choices=("elm327", "alloutput"), default="elm327")
    parser.add_argument("--routing", choices=("obd", "normal"), default="obd")
    parser.add_argument("--compare", type=Path, nargs=2, metavar=("FIRST", "SECOND"),
                        help="Offline comparison only; no Panda or vehicle access")
    args = parser.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=False)
    paths = []
    if args.compare:
        paths = args.compare
    else:
        print("PARKED, ignition ON, engine OFF; openpilot must be stopped. Two 512 KiB reads.", flush=True)
        for index in (1, 2):
            partial = args.out_dir / f"read-{index}.partial"
            command = [sys.executable, str(Path(__file__).with_name("ccp_honda_eps.py")),
                       "--dump", str(partial), "--len", hex(ROM_SIZE), "--cro", "0x727",
                       "--safety", args.safety, "--routing", args.routing]
            if args.bus is not None:
                command += ["--bus", str(args.bus)]
            subprocess.run(command, check=True)
            data = partial.read_bytes()
            inspect_dump(data)
            target = args.out_dir / f"read-{index}-{sha256(data)}-DO_NOT_FLASH.bin"
            partial.rename(target)
            paths.append(target)
    report = compare_dumps(*(path.read_bytes() for path in paths))
    report["requested_transport"] = None if args.compare else {
        "safety": args.safety, "routing": args.routing, "bus": args.bus,
    }
    report["tool_sha256"] = {
        name: sha256(Path(__file__).with_name(name).read_bytes())
        for name in ("dump_crv_a220.py", "ccp_honda_eps.py")
    }
    encoded = (json.dumps(report, indent=2) + "\n").encode()
    report_path = args.out_dir / f"capture-report-{sha256(encoded)}.json"
    report_path.write_bytes(encoded)
    print(json.dumps(report, indent=2))
    print(f"Report: {report_path}")
    ok = report["identical"] and all(
        item["nonuniform_application"] and all(c["matches"] for c in item["a040_layout_checksum_checks"])
        for item in report["captures"]
    )
    if not ok:
        print("REVIEW REQUIRED: send both unchanged captures and report; do not repair bytes from A040.")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())
