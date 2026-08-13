"""Read-only CLI for the S5-1 real-application gate."""

from __future__ import annotations

import argparse

from app.db.engine import get_engine
from app.integrations.dingtalk_readiness import assess_dingtalk_readiness
from app.settings import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(description="Check DingTalk connector readiness")
    parser.add_argument("--tenant-slug", required=True)
    parser.add_argument(
        "--require-delivery-enabled",
        action="store_true",
        help="require the outbound delivery switch for the live-delivery gate",
    )
    arguments = parser.parse_args()
    engine = get_engine()
    try:
        report = assess_dingtalk_readiness(
            engine=engine,
            settings=get_settings(),
            tenant_slug=arguments.tenant_slug,
            require_delivery_enabled=arguments.require_delivery_enabled,
        )
    finally:
        engine.dispose()
    for check in report.checks:
        print(f"{'PASS' if check.passed else 'FAIL'} {check.name}: {check.detail}")
    if not report.ready:
        print("DingTalk readiness failed; no state was changed")
        return 1
    print("DingTalk readiness passed; no state was changed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
