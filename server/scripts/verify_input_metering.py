"""Read-only verification of an operator-published input metering bundle."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import httpx2
from dotenv import dotenv_values

from app.ai.egress import ProviderEgressPolicy
from app.ai.golden_suite import load_golden_suite
from app.ai.input_metering import MeteringError, load_published_meters
from app.ai.model_catalog import ModelCatalog
from app.ai.qualifications import GoldenQualificationFileError, load_golden_qualifications

SERVER_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document", type=Path, required=True)
    parser.add_argument("--sha256", required=True, help="Externally pinned publication digest")
    parser.add_argument("--env-file", type=Path, default=SERVER_ROOT.parent / ".env")
    parser.add_argument(
        "--golden-qualifications",
        type=Path,
        default=SERVER_ROOT / "golden/model-qualifications.json",
    )
    args = parser.parse_args()
    environment = {
        key: value for key, value in dotenv_values(args.env_file).items() if value is not None
    }
    environment.update(os.environ)
    try:
        catalog = ModelCatalog.from_environment(environment)
        qualifications = load_golden_qualifications(
            args.golden_qualifications,
            trusted_suite=load_golden_suite(SERVER_ROOT / "golden/model-gateway-v1.json"),
        )
        with httpx2.Client(follow_redirects=False, trust_env=False) as client:
            meters = load_published_meters(
                args.document,
                expected_sha256=args.sha256,
                qualifications=qualifications,
                client=client,
                egress_policy=ProviderEgressPolicy.from_catalog(catalog),
            )
        print(
            json.dumps(
                {
                    "verified": len(meters),
                    "publication_sha256": args.sha256,
                    "models": [
                        {
                            "provider": provider.value,
                            "model": model,
                            "meter_version": meter.meter_version,
                            "qualification_ref": meter.qualification_ref,
                        }
                        for (provider, model), meter in meters.items()
                    ],
                },
                indent=2,
            )
        )
    except (MeteringError, GoldenQualificationFileError, ValueError, OSError):
        parser.exit(1, "Input metering verification failed; no qualification was published.\n")


if __name__ == "__main__":
    main()
