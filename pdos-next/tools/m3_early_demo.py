"""Seed and serve only the M3-owned, synthetic early candidate for browser verification."""

import argparse
import importlib.util
import os
import socket

import m3_early_environment as fixture


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


def port():
    with socket.socket() as connection:
        connection.bind(("127.0.0.1", 0))
        return connection.getsockname()[1]


def seed():
    state = fixture.state()
    if "demo" in state:
        print("Existing M3 synthetic demonstration retained")
        return
    common = module("m3_common_fixture", fixture.local.SERVER / "tests/conftest.py")
    cases = module("m3_cases", fixture.local.SERVER / "tests/preproject/test_g0.py")
    engines_generator = common.engines.__wrapped__()
    engines = next(engines_generator)
    setup_generator = common.setup.__wrapped__(engines)
    work = cases.work.__wrapped__(next(setup_generator))
    draft, _ = cases.create(work)
    reviewing, _ = cases.create(work, {**cases.payload(work), "title": "客户充气泵 · 合成 G0 评审"})
    cases.submit(work, reviewing)
    state["demo"] = {
        "category_id": str(work.category),
        "draft_id": draft,
        "review_id": reviewing,
        "owner_token": work.tokens[work.human],
        "reviewer_token": work.tokens[work.peer],
        "reviewer_id": str(work.peer),
        "expert_id": str(work.expert),
        "api_port": port(),
        "owner_web_port": port(),
        "reviewer_web_port": port(),
    }
    fixture.local.save(state)
    setup_generator.close()
    engines_generator.close()
    print("M3 synthetic draft and independent review seeded; private tokens withheld")
    print(
        f"Owner page: http://127.0.0.1:{state['demo']['owner_web_port']}/categories/{work.category}/proposals/{draft}"
    )
    print(
        f"Reviewer page: http://127.0.0.1:{state['demo']['reviewer_web_port']}/categories/{work.category}/proposals/{reviewing}"
    )


def serve(action):
    state = fixture.state()
    demo = state["demo"]
    env = fixture.local.environment(state)
    if action == "api":
        env["PDOS_WORKFLOWS_ENABLED"] = "0"
        os.chdir(fixture.local.SERVER)
        arguments = [
            str(fixture.local.SERVER / ".venv/bin/python"),
            "-m",
            "uvicorn",
            "pdos_next.asgi:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(demo["api_port"]),
        ]
    else:
        env["PDOS_NEXT_API_URL"] = f"http://127.0.0.1:{demo['api_port']}"
        env["PDOS_NEXT_LOCAL_SESSION"] = demo[action + "_token"]
        os.chdir(state["web_candidate"])
        arguments = [
            "node",
            str(fixture.local.ROOT / "web/node_modules/next/dist/bin/next"),
            "start",
            "--hostname",
            "127.0.0.1",
            "--port",
            str(demo[action + "_web_port"]),
        ]
    os.execvpe(arguments[0], arguments, env)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("seed", "api", "owner", "reviewer"))
    args = parser.parse_args()
    seed() if args.action == "seed" else serve(args.action)
