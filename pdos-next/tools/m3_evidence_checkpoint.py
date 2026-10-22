"""Exact evidence schema roundtrip in the separately marked M3 fixture."""

import argparse

import m3_environment as fixture
from m3_material_checkpoint import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    parser.add_argument("--from-revision", default="s0_0732")
    parser.add_argument("--to-revision", default="s0_0733")
    parser.add_argument(
        "--section",
        choices=["evidence-sharing", "derivation", "read-proof", "category-dialogue", "project-g0"],
        default="evidence-sharing",
    )
    args = parser.parse_args()
    if not args.evidence.endswith(".json") or "/" in args.evidence:
        parser.error("A plain JSON evidence filename is required")
    run(
        args.from_revision,
        args.to_revision,
        args.evidence,
        report=fixture.REPORT.parent / args.section,
    )
