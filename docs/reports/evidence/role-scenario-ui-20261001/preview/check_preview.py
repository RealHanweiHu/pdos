"""One authenticated reachability check of this synthetic preview, not repo tests."""
import json
from http.cookiejar import CookieJar
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener

preview = Path(__file__).resolve().parent
metadata = json.loads((preview / "metadata.json").read_text())
base = metadata["frontend_url"]
if base != "http://127.0.0.1:3024" or metadata["database"]["port"] != 57441:
    raise SystemExit("Refusing a preview target outside this task.")
checks = []
for username in metadata["credentials"]["usernames"]:
    opener = build_opener(HTTPCookieProcessor(CookieJar()))
    payload = json.dumps({"tenant_slug": "role-preview", "username": username,
                          "password": metadata["credentials"]["password"]}).encode()
    login = Request(base+"/api/session/login", data=payload, headers={"Content-Type": "application/json"})
    try:
        with opener.open(login, timeout=60) as response:
            assert response.status == 200
            assert json.load(response)["authenticated"] is True
        with opener.open(base+"/api/session/me", timeout=60) as response:
            identity = json.load(response)
            assert identity["user"]["username"] == username
            assert identity["tenant"]["slug"] == "role-preview"
        with opener.open(base+"/api/me/work", timeout=60) as response:
            work = json.load(response)
            assert work["counts"]["tasks"] == 1
            assert work["tasks"][0]["project"]["id"] == metadata["records"]["project"]
        checks.append({"username": username, "authenticated": True, "counts": work["counts"],
                       "task_title": work["tasks"][0]["title"], "identity_role": identity["user"]["role"]})
    except HTTPError as error:
        checks.append({"username": username, "status": error.code, "error": error.read().decode()[:1500]})
        (preview / "http-checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2)+"\n")
        raise
with build_opener().open(base+"/login", timeout=60) as response:
    assert response.status == 200
    checks.append({"page": "/login", "status": response.status})
(preview / "http-checks.json").write_text(json.dumps(checks, ensure_ascii=False, indent=2)+"\n")
print(json.dumps(checks, ensure_ascii=False))
