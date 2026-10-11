"""Serve the explicit B8 browser fixture without reading .env or touching main state."""

import argparse
import subprocess

import s0_b8_environment as checkpoint


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("surface", choices=("api", "web"))
    args = parser.parse_args()
    current = checkpoint.state()
    if args.surface == "api":
        import uvicorn
        from pdos_next.api import create_app
        from pdos_next.database import engine_for

        app = create_app(
            engine_for(current["app_url"]),
            engine_for(current["auth_url"]),
            workflow_enabled=False,
        )
        uvicorn.run(app, host="127.0.0.1", port=8899)
    else:
        env = checkpoint.local.environment(current)
        env.update(
            PDOS_NEXT_API_URL="http://127.0.0.1:8899",
            PDOS_NEXT_LOCAL_SESSION=current["preview_token"],
        )
        subprocess.run(
            ["pnpm", "start", "--hostname", "127.0.0.1", "--port", "3120"],
            cwd=checkpoint.local.ROOT / "web",
            env=env,
            check=True,
        )


if __name__ == "__main__":
    main()
