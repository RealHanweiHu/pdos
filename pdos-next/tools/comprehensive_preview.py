"""Serve the marked preview clone; model execution requires an explicit local config."""

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "server"), str(ROOT.parent / "packages/pdos-agent-runtime/src")]
import local_environment as environment  # noqa: E402


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("api", "web", "worker"))
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument("--model-runtime", type=Path)
    args = parser.parse_args()
    environment.STATE = args.runtime.resolve()
    state = environment.verified(environment.read_state())
    if state.get("purpose") != "comprehensive-preview-20261022":
        raise RuntimeError("Use the dedicated synthetic comprehensive preview clone")
    catalog = json.loads(args.catalog.read_text())
    enabled = args.model_runtime is not None
    if enabled:
        from pdos_next.model_configuration.host import TenantRuntime

        runtime_path = args.model_runtime.resolve()
        configuration = TenantRuntime(runtime_path).configuration()
        role = next(row for row in catalog["roles"] if row["id"] == catalog["workspace"]["roleId"])
        if {str(row.tenant_id) for row in configuration.models} != {role["tenantId"]}:
            raise RuntimeError("Model configuration must match the fixed preview tenant")
        shared = json.loads((ROOT.parent / ".local/agent-runtime/environment.json").read_text())
        os.environ.update(
            PDOS_TENANT_RUNTIME_CONFIG=str(runtime_path),
            PDOS_STATE_DB_PORT=str(state["port"]),
            PDOS_STATE_DB_MARKER=state["marker"],
            PDOS_CHECKPOINT_DATABASE_URL=state["m3_checkpoint_url"].replace(
                "postgresql://", "postgresql+psycopg://", 1
            ),
            PDOS_TEMPORAL_ADDRESS=f"127.0.0.1:{shared['temporal_port']}",
            PDOS_TEMPORAL_NAMESPACE="pdos-next-comprehensive-20261023",
            PDOS_OBJECT_ROOT=str(ROOT / ".local/comprehensive-objects"),
            PDOS_WORKFLOWS_ENABLED="1",
            PDOS_WORKFLOW_TENANTS=role["tenantId"],
            PDOS_FILE_SECURITY_PROFILE="local-synthetic-v1",
            PDOS_OBJECT_LIFECYCLE_PROFILE="local-synthetic-v1",
        )
    if args.action == "worker":
        if not enabled:
            raise RuntimeError("Worker requires an explicit model runtime configuration")
        import asyncio

        from pdos_next.workflows.worker import main as run_worker

        asyncio.run(run_worker())
        return
    if args.action == "api":
        if not enabled:
            os.environ.pop("PDOS_TENANT_RUNTIME_CONFIG", None)
        import uvicorn
        from pdos_next.api import create_app
        from pdos_next.database import engine_for
        from starlette.responses import JSONResponse

        app = create_app(
            engine=engine_for(state["app_url"]),
            auth_engine=engine_for(state["auth_url"]),
            workflow_enabled=enabled,
            professional_synthetic_profiles=list(
                {
                    (row["tenant_id"], row["product_id"], row.get("project_id")): row
                    for row in catalog["professional_profiles"]
                }.values()
            ),
        )

        @app.middleware("http")
        async def preview_model_boundary(request, call_next):
            if (
                not enabled and request.method == "POST"
                and request.url.path.endswith("/agent-runs")
            ):
                return JSONResponse(
                    {
                        "code": "MODEL_UNAVAILABLE",
                        "message": "综合预览可回看小Pai历史；新模型执行尚未开启。",
                        "detail": {"reason": "PREVIEW_MODEL_DISABLED"},
                    },
                    status_code=503,
                )
            return await call_next(request)

        uvicorn.run(app, host="127.0.0.1", port=catalog["api_port"], access_log=False)
    else:
        env = {
            k: v
            for k, v in os.environ.items()
            if "DATABASE_URL" not in k and "API_KEY" not in k and not k.endswith("_TOKEN")
        }
        env.update(
            PDOS_NEXT_API_URL=f"http://127.0.0.1:{catalog['api_port']}",
            PDOS_NEXT_PREVIEW_CONFIG=str(args.catalog.resolve()),
            NEXT_TELEMETRY_DISABLED="1",
        )
        os.chdir(ROOT / "web")
        os.execvpe(
            "node",
            [
                "node",
                "node_modules/next/dist/bin/next",
                "dev",
                "--hostname",
                "127.0.0.1",
                "--port",
                str(catalog["web_port"]),
            ],
            env,
        )


if __name__ == "__main__":
    main()
