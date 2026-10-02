"""Offline product capability replay; never reads credentials or opens network/DB."""

import argparse
import json
from hashlib import sha256
from pathlib import Path

from app.ai.product_evaluation import (
    MAX_SUITE_BYTES,
    OfflineProductReplay,
    ProductEvaluationBinding,
    canonical,
    load_product_suite,
    run_product_evaluation,
    strict_object,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Replay one product capability; does not qualify or enable a model."
    )
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--suite-sha256", required=True)
    parser.add_argument(
        "--responses",
        type=Path,
        required=True,
        help="JSON object: case id -> ordered response strings",
    )
    args = parser.parse_args()
    try:
        suite = load_product_suite(args.suite, expected_sha256=args.suite_sha256)
        with args.responses.open("rb") as source:
            document = source.read(MAX_SUITE_BYTES + 1)
        if len(document) > MAX_SUITE_BYTES:
            raise ValueError("responses_too_large")
        outputs = json.loads(document, object_pairs_hook=strict_object)
        if (
            not isinstance(outputs, dict)
            or len(outputs) > 100
            or any(
                not isinstance(key, str)
                or not isinstance(values, list)
                or len(values) > 3
                or any(not isinstance(value, str) for value in values)
                for key, values in outputs.items()
            )
        ):
            raise ValueError("invalid_response_map")
        report = run_product_evaluation(
            suite,
            binding=ProductEvaluationBinding(
                provider="offline",
                model="fixed-response-replay",
                protocol="offline_replay",
                configuration_sha256=sha256(document).hexdigest(),
            ),
            executor=OfflineProductReplay(outputs),
        )
    except (OSError, ValueError, KeyError, TypeError):
        print('{"error":"invalid_evaluation_input","qualification_granted":false}')
        return 2
    print(canonical(report))
    return 0 if report["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
