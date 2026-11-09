"""Run the existing scan -> parse path (real ClamAV + rebuilt parser containers) for pending uploads."""
import asyncio, os, sys
sys.path.insert(0, os.path.dirname(__file__))
from common import OBJECTS, STATE, env  # noqa: E402
os.environ.update(env())
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402
from pdos_next.core.database import engine_for  # noqa: E402
from pdos_next.core.models import UploadedOriginal  # noqa: E402
from pdos_next.bootstrap.security import local_runtime  # noqa: E402
from pdos_next.originals.access import parse_uploaded  # noqa: E402
from pdos_next.originals.security import configure, queue_uploaded, scan_requested  # noqa: E402
from pdos_next.originals.store import OriginalStore  # noqa: E402
store = OriginalStore(str(OBJECTS))
engine = engine_for(STATE["app_url"]); admin = engine_for(STATE["admin_url"])
async def main():
    from pdos_next.originals.lifecycle.worker import configure_lifecycle
    configure_lifecycle(engine, store, allow_local_profile=True)  # same wiring as the Temporal worker
    runtime = await local_runtime(store)
    assert runtime is not None, "local security runtime unavailable"
    configure(engine, runtime)
    with Session(admin) as s:
        tenant = STATE["dev_accounts"]["d42"]["tenant_id"]
        rows = s.scalars(select(UploadedOriginal).where(UploadedOriginal.status == "uploaded", UploadedOriginal.tenant_id == tenant)).all()
        refs = [{"tenant_id": str(r.tenant_id), "category_id": str(r.category_id), "product_id": str(r.product_id) if r.product_id else None,
                 "actor_id": str(r.owner_id), "requester_id": str(r.owner_id), "subject_id": str(r.id), "filename": r.filename} for r in rows]
    for ref in refs:
        name = ref.pop("filename")
        queued = await asyncio.to_thread(queue_uploaded, engine, ref)
        scanned = await asyncio.to_thread(scan_requested, engine, {**ref, "subject_id": queued["request_id"]})
        parsed = await asyncio.to_thread(parse_uploaded, engine, ref, store) if scanned["status"] == "clean" else scanned
        print(name, "scan:", scanned["status"], "parse:", parsed.get("status"))
    await runtime.scanner.close() if hasattr(runtime.scanner, "close") else None
asyncio.run(main())
