"""CLI entry point for the production deployment preflight."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from app.deployment.preflight import (
    UnsafeProductionConfigurationError,
    validate_production_environment,
    validate_production_environment_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PDOS production configuration")
    parser.add_argument("environment_file", nargs="?", type=Path)
    parser.add_argument(
        "--from-environment",
        action="store_true",
        help="validate variables already injected into an isolated deployment container",
    )
    arguments = parser.parse_args()
    if arguments.from_environment == (arguments.environment_file is not None):
        parser.error("provide exactly one environment file or --from-environment")
    try:
        if arguments.from_environment:
            validate_production_environment(os.environ)
        else:
            validate_production_environment_file(Path(arguments.environment_file))
    except UnsafeProductionConfigurationError as error:
        parser.exit(1, f"Production preflight refused: {error}\n")
    print("Production environment preflight passed without exposing configuration values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
