"""CLI entry point for the production deployment preflight."""

from __future__ import annotations

import argparse
from pathlib import Path

from app.deployment.preflight import (
    UnsafeProductionConfigurationError,
    validate_production_environment_file,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate PDOS production configuration")
    parser.add_argument("environment_file", type=Path)
    arguments = parser.parse_args()
    environment_file = Path(arguments.environment_file)
    try:
        validate_production_environment_file(environment_file)
    except UnsafeProductionConfigurationError as error:
        parser.exit(1, f"Production preflight refused: {error}\n")
    print("Production environment preflight passed without exposing configuration values")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
