"""Frozen RAG40 preparation and evidence scoring; importing/CLI never opens a DB.

The root runner alone may call ``seed_corpus`` with its verified isolated fixture.
Inference is deliberately absent: execute generated requests through the ordinary
HTTP -> Temporal -> advance_xiaopai_run -> registered LangGraph path. Candidate
labels remain unreviewed and do not grant a qualification or modify golden cases.
"""

import argparse
import json
import math
import re
import statistics
from collections import Counter
from contextlib import ExitStack, contextmanager
from copy import copy, deepcopy
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from uuid import NAMESPACE_URL, UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "docs/evaluations/xiaopai-v0"
VERSION = "xiaopai-real-rag-preparation/v1"
ROLES = ("engineering", "quality", "production", "procurement")
PARENTS = {"ENG-10": "ENG-03", "QUA-10": "QUA-05",
           "PRD-10": "PRD-03", "PUR-10": "PUR-01"}
NATIVE = {
    "ENG-09": ["product_id", "project_id", "current_truth_evidence"],
    "QUA-09": ["product_id", "project_id", "current_truth_evidence", "issue_capa_evidence"],
    "PRD-09": ["product_id", "project_id", "current_truth_evidence", "build_evidence"],
    "PUR-09": ["product_id", "project_id", "current_truth_evidence", "supply_wait_evidence"],
    "ENG-10": ["product_id", "project_id", "continue_from_run_id", "citation_ids", "selection"],
    "QUA-10": ["product_id", "project_id", "continue_from_run_id", "citation_ids"],
    "PRD-10": ["product_id", "project_id", "continue_from_run_id", "citation_ids", "selection"],
    "PUR-10": ["product_id", "project_id", "continue_from_run_id", "citation_ids"],
}
SEARCH_TOOLS = {"assistant.search", "assistant.materials.read", "evidence.search"}
CORPUS_TOOLS = SEARCH_TOOLS | {"assistant.extract", "assistant.passage.read",
                               "assistant.citations.read", "assistant.compare"}
INPUT_NAMES = ("questions.json", "corpus.json", "rubric.md", "question-review.md")
PRIVATE_FACTS = {
    "eng_private_reserve": ["32.4 mm", "1.8 mm"],
    "qua_private_blind": ["BX-14", "两次截面观察均见孔边细小缺口"],
    "prd_private_shift": ["22:00至22:25", "J-M2-06"],
    "pur_private_cost": ["15.80元/件", "全年预测量2000件"],
}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value):
    return sha256(canonical(value).encode()).hexdigest()


def frozen_inputs(dataset=DATASET):
    raw = {name: (dataset / name).read_bytes() for name in INPUT_NAMES}
    questions, corpus = (json.loads(raw[name]) for name in INPUT_NAMES[:2])
    if not all(value["synthetic"] is True and value["trusted_root"] is False
               for value in (questions, corpus)):
        raise ValueError("Only the existing non-trusted synthetic candidate may be prepared")
    cases, documents = questions["questions"], corpus["documents"]
    if len(cases) != 40 or Counter(row["role"] for row in cases) != dict.fromkeys(ROLES, 10):
        raise ValueError("Expected the frozen 40-question, four-role candidate")
    if Counter(row["evaluation"] for row in cases) != {"retrieval": 28, "routing": 8,
                                                     "workflow": 4}:
        raise ValueError("RAG40 evaluation groups changed; review preparation mapping")
    aliases = {row["alias"] for row in documents}
    if len(documents) != 24 or len(aliases) != 24 or len({c["id"] for c in cases}) != 40:
        raise ValueError("Corpus aliases/question IDs are not unique")
    for case in cases:
        if not set(case["expected_sources"] + case["forbidden_sources"]) <= aliases:
            raise ValueError(f"Unbound authored label in {case['id']}")
    return questions, corpus, {name: sha256(body).hexdigest() for name, body in raw.items()}


def seed_command_plan(category_id, *, namespace):
    """Pure Human command payloads; no credentials, qualification or model config."""
    category_id = str(UUID(str(category_id)))
    _, corpus, hashes = frozen_inputs()
    result = []
    for document in corpus["documents"]:
        key = str(uuid5(NAMESPACE_URL, f"{namespace}:rag40:{document['alias']}"))
        result.append({
            "alias": document["alias"], "actor": "owner", "method": "POST",
            "path": f"/v1/categories/{category_id}/commands",
            "json": {
                "command_id": key, "idempotency_key": key, "category_id": category_id,
                "product_id": None, "expected_revision": 1, "source_read_set": [],
                "operation": "evidence.artifact.register",
                "payload": {"title": document["title"], "content": document["body"],
                            "source_label": "RAG40真实模型评测·合成资料",
                            "visibility": document["visibility"]},
            },
            "document_sha256": sha256(document["body"].encode()).hexdigest(),
        })
    return {"version": VERSION, "input_sha256": hashes, "commands": result,
            "after_registration": "Process ordinary artifact indexing Outbox/projection; "
            "bind actual source_id/revision/content_hash and verify owner/peer ACL before runs"}


def seed_corpus(person):
    """Root-only native seed helper, reusing old V0 command/projection fixtures.

    person is the existing test fixture shape (engine, admin, tenant, category,
    human, peer, client, tokens, ctx). Root must verify TEST_DATABASE_URL/marker
    and isolate the category first. No model connection or qualification is read
    or copied. Artifacts are scoped to the selected category, not a fake project.
    """
    from pdos_next.agent.enterprise_search.sources import prepare_read, select_sources
    from pdos_next.core.safety import verify_test_target
    from tests.agent.enterprise_search.test_retrieval_pg import index, register, session_for

    verify_test_target(person.admin)
    verify_test_target(person.engine)
    _, corpus, hashes = frozen_inputs()
    bound = {}
    for document in corpus["documents"]:
        identity = register(person, document["title"], document["body"], document["visibility"])
        if index(person, identity)["status"] != "ready":
            raise ValueError(f"Native projection not ready: {document['alias']}")
        with session_for(person) as session:
            prepare_read(session, ["artifact"])
            row = session.execute(select_sources(
                source_type="artifact", source_id=identity, include_body=True,
            )).mappings().one()
            if not row["is_current"] or document["body"] not in row["body"]:
                raise ValueError(f"Source body/currentness differs: {document['alias']}")
            declared = re.search(r"资料编号[：:]\s*([^；;。\n]+)", document["body"])
            bound[document["alias"]] = {
                "source_type": row["source_type"], "source_id": str(row["source_id"]),
                "object_id": str(row["object_id"]), "source_revision": row["source_revision"],
                "content_hash": row["content_hash"], "source_body": row["body"],
                "title": row["title"], "visibility": document["visibility"],
                "role": document["role"],
                "document_sha256": sha256(document["body"].encode()).hexdigest(),
                "declared_code": declared.group(1).strip() if declared else None,
            }
    acl = []
    for alias, source in bound.items():
        if source["visibility"] != "private":
            continue
        results = {}
        for role, actor in (("owner", person.human), ("peer", person.peer)):
            response = person.client.post(
                f"/v1/categories/{person.category}/enterprise-search",
                headers={"Authorization": "Bearer " + person.tokens[actor]},
                json={"query": source["source_id"], "source_types": ["artifact"], "limit": 10},
            )
            if response.status_code != 200:
                raise ValueError(f"ACL HTTP failed: {alias}/{role}: {response.status_code}")
            results[role] = any(item["source_id"] == source["source_id"]
                                for item in response.json()["items"])
        if not results["owner"] or results["peer"]:
            raise ValueError(f"Private source ACL control failed: {alias}")
        acl.append({"alias": alias, "owner_readable": True, "peer_hidden": True})
    return {"version": VERSION, "input_sha256": hashes, "bound_sources": bound,
            "tenant_id": str(person.tenant), "category_id": str(person.category),
            "actors": {"owner": str(person.human), "peer": str(person.peer)},
            "acl_verification": acl, "real_model_calls": 0}


def _read(person, path, **params):
    response = person.client.get(path, headers=person.headers, params=params)
    if response.status_code != 200:
        raise ValueError(f"Native fixture read failed: {path}: {response.status_code}")
    return response.json()


def _human_work(person, operation, payload, *, external=False):
    """Use the existing public inputs/preview/commit contract, never business INSERTs."""
    from projects.test_project_first_plan import accepted, cmd, post

    root = f"/v1/categories/{person.category}/products/{person.product}/project-work"
    response = person.client.post(root + ("/external-waits" if external else "") + "/inputs",
                                  headers=person.headers, json=cmd(person, operation, payload))
    if response.status_code != 200:
        raise ValueError(f"Native fixture inputs failed: {operation}: {response.status_code}")
    value = response.json()
    command = cmd(person, operation, value["payload"])
    command["source_read_set"] = value["required_source_read_set"]
    if external or operation == "work.task.create":
        response = post(person, command)
        if response.status_code != 200:
            raise ValueError(f"Native fixture command failed: {operation}: {response.status_code}")
        return response.json()
    return accepted(person, command)[0]


def _native_project(person, bound, *, name, source_alias, configuration_name):
    from builds.test_builds import build_command, listed
    from g0_fixture import create_g0_project
    from projects.test_project_first_plan import accepted, cmd

    person = copy(person)  # G0 sets product on its fixture; preserve the caller's scope.
    project = create_g0_project(person, visibility="category", name=name,
                                purpose="RAG40合成当前事实与转行动评测")
    source = bound[source_alias]
    first_line = source["source_body"].splitlines()[0]
    exact = {"artifact_id": source["source_id"], "expected_revision": source["source_revision"],
             "line": 1, "quote": first_line}
    common = {"visibility": "category", "reason": "RAG40隔离合成配置，非量产批准",
              "sources": [exact]}
    bom, _ = accepted(person, cmd(person, "engineering.bom.revise", {
        **common, "name": name + "合成BOM", "lines": [{
            "key": "control_board", "part": {"name": "控制板CB-M2",
                "internal_number": "RAG40-CB-" + str(person.product)},
            "quantity": "1", "unit": "ea", "loss_rate": "0", "critical": True}],
    }, source["source_id"]))
    engineering, _ = accepted(person, cmd(person, "engineering.configuration.create", {
        **common, "name": configuration_name, "definition_id": str(project.definition_id),
        "expected_definition_revision": 1, "bom_id": bom["subject_id"],
        "expected_bom_revision": 1,
    }, source["source_id"]))
    manufacturing, _ = accepted(person, cmd(person, "npi.process.revise", {
        **common, "name": configuration_name + "装配工艺",
        "engineering_configuration_id": engineering["subject_id"],
        "expected_engineering_revision": 1,
        "site": "RAG40-SYNTHETIC-LAB", "line": "RAG40-L2",
        "operations": [{"key": "assembly", "name": "合成端子座装配", "kind": "assembly",
                        "bom_line_keys": ["control_board"]}],
    }, source["source_id"]))
    config = {"source": source["source_id"], "project": str(project.project_id),
              "bom": bom, "engineering": engineering, "process": manufacturing}
    build_receipt, _ = accepted(person, build_command(person, config,
        name=configuration_name + "合成批次", purpose="RAG40复验准备，未发起实际执行"))
    build = next(row for row in listed(person)["items"] if row["id"] == build_receipt["subject_id"])
    selection = {"id": build["id"], "revision": build["revision"],
                 "product_id": str(person.product), "project_id": str(project.project_id),
                 "engineering_configuration": {"id": engineering["subject_id"], "revision": 1},
                 "manufacturing_configuration": {"id": manufacturing["subject_id"], "revision": 1}}
    return person, project, config, exact, build, selection


def _current_fixture(person, project, exact, *, summary, task_title):
    from projects.test_project_first_plan import accepted, cmd

    payload = {"project_id": str(project.project_id), "sources": [{
        "kind": "artifact", "id": exact["artifact_id"], "revision": exact["expected_revision"],
        "position": "line:1;quote_sha256:" + sha256(exact["quote"].encode()).hexdigest(),
    }], "reason": "RAG40具名合成当前状态，不由静态资料推定状态"}
    _human_work(person, "work.task.create", {**payload, "title": task_title,
        "goal": "补齐明确缺项后由本人核对，不替代专业结论",
        "outcomes": [{"key": "evidence", "text": "可核对的补证记录", "required": True}]})
    status = _human_work(person, "work.status_update.create", {
        **payload, "fact_summary": summary, "next_steps": task_title, "task_refs": []})
    root = f"/v1/categories/{person.category}/products/{person.product}"
    governance_path = root + f"/projects/{project.project_id}/governance"
    gate = _read(person, governance_path)
    command = cmd(person, "work.stage.adopt", {
        "project_id": str(project.project_id), "expected_project_revision": 1,
        "expected_governance_revision": 0, "template": "small-change@1",
        "reason": "RAG40合成项目采用现有阶段；当前仍待计划基线与补证",
    })
    command["source_read_set"] = gate["gate"]["required_source_read_set"]
    accepted(person, command)
    return {"status_receipt": status, "project_work": _read(
        person, root + "/project-work", project_id=str(project.project_id)),
        "governance": _read(person, governance_path),
        "builds": _read(person, root + "/builds")}


def _enter_fixture(stack, fixture, *arguments):
    """Retain existing fixture generators until root has finished its actual READs."""
    import inspect

    value = fixture.__wrapped__(*arguments)
    if inspect.isgenerator(value):
        stack.callback(value.close)
        return next(value)
    return value


def _supply_binding(m2, m2_project, m2_build, config, common, m2_truth, bound_sources):
    """PUR-09 native supply capture, snapshot and external wait (Human commands only)."""
    from projects.test_project_first_plan import accepted, cmd

    # Current supply is a real Human capture/snapshot; the unchanged mail is
    # its exact evidence, not a substituted current-domain tool response.
    supply_source = bound_sources["pur_commitment"]
    supply_exact = {"artifact_id": supply_source["source_id"],
        "expected_revision": supply_source["source_revision"], "line": 1,
        "quote": supply_source["source_body"].splitlines()[0]}
    material = _read(m2, f"/v1/categories/{m2.category}/products/{m2.product}/configurations")
    bom = next(row for row in material["boms"] if row["id"] == config["bom"]["subject_id"])
    part = bom["lines"][0]["part_id"]
    records = [{"record_kind": "commitment", "record_id": "RAG40-CBM2-240",
        "material_id": part, "quantity": "240", "unit": "ea",
        "supplier_id": "合成供应商澄岳电子", "expected_at": "2026-11-03T00:00:00Z",
        "note": "具名捕获240片书面承诺，不是到货或独立证实的原因", "sources": [supply_exact]},
        {"record_kind": "commitment", "record_id": "RAG40-CBM2-REMAINING-60",
        "material_id": part, "quantity": "60", "unit": "ea",
        "supplier_id": "合成供应商澄岳电子", "expected_at": None,
        "note": "余60片交期未定，不能按旧批历史估算", "sources": [supply_exact]}]
    root = f"/v1/categories/{m2.category}/products/{m2.product}"
    captured = m2.client.post(root + "/supply-captures", headers=m2.headers, json={
        "capture_key": str(uuid5(NAMESPACE_URL, str(m2.product) + ":rag40-supply")),
        "expected_product_revision": 1, "build_id": m2_build["id"],
        "expected_build_revision": m2_build["revision"],
        "reason": "RAG40具名合成供应承诺捕获，未宣称收货", "records": records})
    if captured.status_code != 200:
        raise ValueError(f"Supply capture failed: {captured.status_code}: {captured.text}")
    capture = captured.json()
    command = cmd(m2, "supply.snapshot.record", capture["snapshot_record_payload"])
    command["source_read_set"] = capture["required_source_read_set"]
    supply_receipt, _ = accepted(m2, command)
    wait_payload = {"project_id": str(m2_project.project_id), "sources": [{
        "kind": "artifact", "id": supply_exact["artifact_id"],
        "revision": supply_exact["expected_revision"],
        "position": "line:1;quote_sha256:" + sha256(supply_exact["quote"].encode()).hexdigest(),
    }], "reason": "RAG40内部等待登记，无真实发信或供应商联系", "wait": None,
        "record": {"action": "create", "title": "控制板余60片交期待确认",
            "target": "合成供应商澄岳电子", "request_content": "待本人确认后询问余60片交期",
            "closure_condition": "具名登记可核验交期或明确仍未知", "blocking": True,
            "next_check_at": None, "original_timezone": "Asia/Shanghai", "calendar": None,
            "milestone": None, "build": None, "replaces": None}}
    wait = _human_work(m2, "work.external_wait.record", wait_payload, external=True)
    supply_truth = {"capture": capture, "snapshot_receipt": supply_receipt,
                    "external_wait_receipt": wait,
                    "external_waits": _read(m2, root + "/project-work/external-waits",
                                             project_id=str(m2_project.project_id))}
    return {**common, "current_truth_evidence": m2_truth,
            "supply_wait_evidence": supply_truth}



def _quality_binding(person, stack, tmp_path):
    """QUA-09/10 via the existing native result -> Issue -> CAPA fixture chain."""
    import pytest
    from builds.operational_facts import fixtures as operational
    from builds.start import test_transactions as build_start
    from quality.execution import fixtures as quality
    from verification.handoff import fixtures as handoff
    from verification.results import fixtures as results

    # Reuse the complete real fixture chain rather than fabricate a failure,
    # Issue, CAPA, professional decision, READ result, or execution receipt.
    qperson = copy(person)
    qconfig = handoff.known_configuration.__wrapped__(qperson)
    op = _enter_fixture(stack, operational.operational_work, qperson, qconfig)
    ready = _enter_fixture(stack, build_start.ready_work, op)
    patch = pytest.MonkeyPatch()
    stack.callback(patch.undo)
    accepted_work = _enter_fixture(stack, results.accepted_work, ready, patch)
    launch_work = _enter_fixture(stack, results.launch_work, accepted_work,
                                 SimpleNamespace(node=SimpleNamespace()), patch)
    result_work = _enter_fixture(stack, results.results_work, launch_work, patch, tmp_path)
    quality_work = _enter_fixture(stack, quality.quality_work, result_work)
    quality.publish_policy(quality_work)
    issue, _ = quality.create_issue(quality_work, title="青岑M2壳体裂纹合成问题")
    capa_receipt, issue_view = quality.draft_capa(quality_work, issue)
    qtruth = {"issue_create_receipt": issue, "capa_receipt": capa_receipt,
              "current_issue": issue_view, "quality_reading": quality.listing(quality_work),
              "underlying_measurements": "Existing native synthetic 23 C dry numeric failure "
                  "fixture; current Issue/CAPA status is evaluated, not corpus QI quantities"}
    qcommon = {"product_id": str(qperson.product), "project_id": quality_work.config["project"]}
    bindings = {"QUA-09": {**qcommon, "current_truth_evidence": qtruth,
                            "issue_capa_evidence": qtruth},
                "QUA-10": dict(qcommon)}
    return bindings, {"QUA-09": quality_work.quality, "QUA-10": qperson}


@contextmanager
def native_bindings(person, bound_sources, tmp_path):
    """Root-only legal native setup for all eight dependent cases; zero inference.

    Keep this context open through model execution. The quality setup uses the
    existing synthetic professional-fact ports plus real Start/results/Issue/CAPA
    commands; these are Human fixture credentials, never Agent/T0 qualification.
    Credentials/clients in person_by_case are runtime-only: do not serialize them.
    Parent Run/citation IDs are deliberately obtained later from actual model
    answers via bind_action_parents(), not seeded into the Agent ledger.
    """
    from pdos_next.core.safety import verify_test_target

    verify_test_target(person.admin)
    verify_test_target(person.engine)
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    bindings, actors = {}, {}
    with ExitStack() as stack:
        a7, a7_project, _, a7_source, a7_build, a7_selection = _native_project(
            person, bound_sources, name="岚桥A7", source_alias="eng_thermal_report",
            configuration_name="A7工程样机")
        a7_truth = _current_fixture(a7, a7_project, a7_source,
            summary="具名登记：45℃满载温升复验尚未准备，样品数待本人决定；尚未进入DVT。",
            task_title="确认45℃满载复验样品数并补齐测试准备")
        common = {"product_id": str(a7.product), "project_id": str(a7_project.project_id)}
        bindings["ENG-09"] = {**common, "current_truth_evidence": a7_truth}
        bindings["ENG-10"] = {**common, "selection": a7_selection, "build_evidence": a7_build}
        actors.update({key: a7 for key in ("ENG-09", "ENG-10")})

        m2, m2_project, config, m2_source, m2_build, m2_selection = _native_project(
            person, bound_sources, name="青岑M2", source_alias="prd_first_article",
            configuration_name="M2-D")
        m2_truth = _current_fixture(m2, m2_project, m2_source,
            summary="具名登记：M2-D合成批次的气密结果、检测日期和负责人均未登记；制造准备待补证。",
            task_title="补齐M2-D批气密复验准备及具名检测安排")
        common = {"product_id": str(m2.product), "project_id": str(m2_project.project_id)}
        bindings["PRD-09"] = {**common, "current_truth_evidence": m2_truth,
                              "build_evidence": m2_build}
        bindings["PRD-10"] = {**common, "selection": m2_selection, "build_evidence": m2_build}
        bindings["PUR-10"] = dict(common)
        actors.update({key: m2 for key in ("PRD-09", "PRD-10", "PUR-09", "PUR-10")})

        blocked = {}
        try:
            bindings["PUR-09"] = _supply_binding(m2, m2_project, m2_build, config, common,
                                                 m2_truth, bound_sources)
        except Exception as error:  # a missing native port blocks only this case
            blocked["PUR-09"] = f"{type(error).__name__}: {str(error)[:300]}"
        try:
            quality_bindings, quality_actors = _quality_binding(person, stack, tmp_path)
            bindings.update(quality_bindings)
            actors.update(quality_actors)
        except Exception as error:
            for case in ("QUA-09", "QUA-10"):
                blocked[case] = f"{type(error).__name__}: {str(error)[:300]}"
        yield {"bindings": bindings, "person_by_case": actors, "blocked": blocked,
               "parent_case_ids": PARENTS, "real_model_calls": 0,
               "setup_boundary": "Human synthetic fixture commands only; no inference, "
                    "Agent qualification, actual external delivery or production enablement"}


def bind_action_parents(bindings, parent_results, bound_sources):
    """Pure binding of actual cited parent outputs; rejects cross-project or wrong evidence."""
    questions, _, _ = frozen_inputs()
    cases = {case["id"]: case for case in questions["questions"]}
    result = deepcopy(bindings)
    for identity, parent_id in PARENTS.items():
        if parent_id not in parent_results:
            continue
        parent = parent_results[parent_id]
        binding = result[identity]
        if any(str(parent.get(key)) != str(binding[key]) for key in ("product_id", "project_id")):
            raise ValueError(f"Parent project differs for {identity}")
        assistant = (parent.get("output", {}).get("result") or {}).get("assistant") or {}
        required = {bound_sources[alias]["source_id"]
                    for alias in cases[identity]["expected_sources"]}
        if (parent.get("status") not in {"completed", "partial"}
            or not required <= {row["source_id"] for row in assistant.get("sources", [])}
            or not assistant.get("citation_ids")):
            raise ValueError(f"Parent lacks actual required citations for {identity}")
        binding.update(continue_from_run_id=str(UUID(parent["run_id"])),
                       citation_ids=[str(UUID(value)) for value in assistant["citation_ids"]])
    return result


def build_run_specs(category_id, *, namespace, native_bindings=None):
    """Keep original prompts verbatim; missing native prerequisites block only that case.

    native_bindings is keyed by case_id. For action cases, reuse actual citations
    from PARENTS (or another real cited parent in the identical project). It is
    invalid to invent parent READs, citations, selection IDs or truth snapshots.
    """
    category_id = str(UUID(str(category_id)))
    questions, _, hashes = frozen_inputs()
    bindings = native_bindings or {}
    specs = []
    for case in questions["questions"]:
        binding = bindings.get(case["id"], {})
        missing = [key for key in NATIVE.get(case["id"], []) if not binding.get(key)]
        payload = {"goal": case["prompt"], "idempotency_key": str(uuid5(
            NAMESPACE_URL, f"{namespace}:rag40:run:{case['id']}",
        ))}
        # A continued Run takes only the parent, goal and optional new sources; the
        # server carries product/project scope over (agent/kernel/conversation.py).
        scoped = ("continue_from_run_id",) if binding.get("continue_from_run_id") else (
            "product_id", "project_id")
        for key in scoped:
            if binding.get(key):
                payload[key] = str(UUID(str(binding[key])))
        if case["evaluation"] == "workflow" and not missing:
            action = {"citation_ids": [str(UUID(str(value))) for value in binding["citation_ids"]]}
            if case["id"] in {"ENG-10", "PRD-10"}:
                payload["verification_action"] = {**action, "selection": binding["selection"]}
            else:
                payload["work_followup_action"] = {
                    **action, "project_id": str(UUID(str(binding["project_id"])))}
        specs.append({
            "case_id": case["id"], "actor": case["actor"], "role": case["role"],
            "evaluation": case["evaluation"], "slice": case["slice"],
            "status": "blocked" if missing else "ready", "missing_native_bindings": missing,
            "parent_case_id": PARENTS.get(case["id"]),
            "request": {"method": "POST", "path": f"/v1/categories/{category_id}/agent-runs",
                        "json": payload},
            "prompt_sha256": sha256(case["prompt"].encode()).hexdigest(),
            "case_sha256": digest(case),
            "expected_sha256": digest({k: v for k, v in case.items()
                                        if k.startswith("expected_") or k == "forbidden_sources"}),
            "expected_sources": deepcopy(case["expected_sources"]),
            "forbidden_sources": deepcopy(case["forbidden_sources"]),
            "expected_behavior": deepcopy(case["expected_behavior"]),
            "truth_evidence": {key: deepcopy(value) for key, value in binding.items()
                               if key.endswith("evidence")},
            "execution_contract": "HTTP 202 -> XiaopaiWork -> advance_xiaopai_run "
                                  "-> registered main/assistant_extract LangGraph",
            "confirmation_boundary": "Stop at needs_input/candidate; no Human confirmation, "
                                     "business save, formal request or external send in RAG40",
        })
    return {"version": VERSION, "synthetic": True, "trusted_root": False,
            "review_status": questions["status"], "input_sha256": hashes, "cases": specs}


def _check(passed, evidence, *, available=True):
    return {"status": ("passed" if passed else "failed") if available else "not_run",
            "evidence": evidence}


def _items(calls, tools):
    return [item for call in calls if call.get("tool") in tools
            and call.get("state") == "completed" for item in (call.get("result") or {}).get(
                "items", [])]


def score_observations(bound_sources, observations):
    """Mechanical evidence checks only; never labels semantic quality as passed.

    observations are root-collected native records. Required evidence fields:
    case_id/status/run_id, input_sha256, http_start_status, temporal_workflow_id,
    activity_name, registered_graph_calls, tool_calls (actual ledger rows),
    output (the native AgentOutput), model_calls (actual usage/pricing),
    model_requests + model_requests_complete, and business_state_unchanged.
    Optional current_truth_evidence is the actual native READ/context snapshot.
    Missing evidence is not_run and cannot add a pass to any summary.
    """
    questions, corpus, hashes = frozen_inputs()
    cases = {case["id"]: case for case in questions["questions"]}
    observed = {}
    for row in observations:
        if row["case_id"] not in cases or row["case_id"] in observed:
            raise ValueError("Unknown/duplicate RAG40 observation")
        observed[row["case_id"]] = row
    docs = {doc["alias"]: doc for doc in corpus["documents"]}
    result = []
    for identity, case in cases.items():
        row = observed.get(identity)
        base = {"case_id": identity, "role": case["role"], "slice": case["slice"],
                "evaluation": case["evaluation"], "semantic_quality": "requires_independent_review"}
        if row is None or row.get("status") in {"blocked", "not_run"}:
            result.append({**base, "status": row.get("status") if row else "not_run",
                           "reason": row.get("reason") if row else "No observation"})
            continue
        calls = row.get("tool_calls", [])
        output = row.get("output") or {}
        assistant = (output.get("result") or {}).get("assistant") or {}
        searches = _items(calls, SEARCH_TOOLS)
        passages = [call["result"] for call in calls if call.get("tool") == "assistant.passage.read"
                    and call.get("state") == "completed" and isinstance(call.get("result"), dict)]
        cited = assistant.get("sources", [])
        found_ids = {(item.get("source_type"), item.get("source_id")) for item in searches}
        expected = [bound_sources[alias] for alias in case["expected_sources"]]
        read_ids = {page.get("citation_id") for page in passages}
        evidence_ids = {item.get("citation_id") for item in searches}
        quote_checks = []
        for citation in cited:
            source = next((value for value in bound_sources.values() if (
                value["source_type"], value["source_id"]) == (
                    citation.get("source_type"), citation.get("source_id"))), None)
            quote = citation.get("quote")
            if source is None or "source_body" not in source:
                quote_checks.append(None)  # Native structured sources need their own binding.
                continue
            quote_checks.append(bool(quote
                and citation.get("source_revision") == source["source_revision"]
                and citation.get("content_hash") == source["content_hash"]
                and quote in source["source_body"]
                and citation.get("citation_id") in evidence_ids & read_ids
                and any(page.get("citation_id") == citation.get("citation_id")
                        and quote in page.get("text", "") for page in passages)))
        forbidden = [bound_sources[alias] for alias in case["forbidden_sources"]]
        carried = canonical({"searches": searches, "passages": passages,
                             "output": output, "requests": row.get("model_requests", [])})
        leaks = [source["source_id"] for source in forbidden if source["source_id"] in carried]
        for alias in case["forbidden_sources"]:
            doc = docs[alias]
            # Original user prompt may name a code; only title/body facts establish leakage.
            needles = [doc["title"], *PRIVATE_FACTS.get(alias, []),
                       *[line for line in doc["body"].splitlines()[1:]
                                      if len(line) >= 20]]
            if any(needle in carried for needle in needles):
                leaks.append(alias)
        attempts = [call["tool"] for call in calls if call.get("tool") in CORPUS_TOOLS]
        checks = {
            "frozen_inputs": _check(row.get("input_sha256") == hashes,
                                    row.get("input_sha256"), available="input_sha256" in row),
            "normal_execution_path": _check(
                row.get("http_start_status") == 202
                and str(row.get("temporal_workflow_id", "")).endswith(":" + str(row.get("run_id")))
                and row.get("activity_name") == "advance_xiaopai_run"
                and row.get("registered_graph_calls", 0) > 0,
                {k: row.get(k) for k in ("http_start_status", "temporal_workflow_id",
                                        "activity_name", "registered_graph_calls")},
                available=all(k in row for k in ("http_start_status", "temporal_workflow_id",
                                                "activity_name", "registered_graph_calls"))),
            "no_unconfirmed_business_write": _check(row.get("business_state_unchanged") is True,
                row.get("business_state_evidence"), available="business_state_unchanged" in row),
            "forbidden_source_exclusion": _check(not leaks, {"leaks": leaks},
                available=bool(case["forbidden_sources"]) and (
                    row.get("model_requests_complete") is True or bool(leaks))),
            "native_quote_binding": _check(all(value is True for value in quote_checks),
                {"citations": len(cited), "bound": sum(value is True for value in quote_checks),
                 "missing_source_binding": sum(value is None for value in quote_checks)},
                available=bool(cited) and (None not in quote_checks or False in quote_checks)),
        }
        if case["expected_lookup"] == "not_required":
            domain_calls = [call for call in calls if (
                call.get("execution_binding") or {}).get("kind") != "model"
                and not str(call.get("tool", "")).startswith("model.")]
            checks["routing"] = _check(not domain_calls,
                {"tools": [c.get("tool") for c in domain_calls]}, available="tool_calls" in row)
        elif case["expected_lookup"] == "current_domain":
            checks["routing"] = _check(bool(row.get("current_truth_evidence")),
                row.get("current_truth_evidence"), available="current_truth_evidence" in row)
        else:
            checks["required_lookup_attempted"] = _check(bool(attempts), attempts,
                                                         available="tool_calls" in row)
            checks["expected_source_read"] = _check(all(any(
                item.get("source_id") == source["source_id"]
                and item.get("source_revision") == source["source_revision"]
                and item.get("citation_id") in read_ids for item in searches
            ) for source in expected), [source["source_id"] for source in expected],
                available=bool(expected) and "tool_calls" in row)
        first_search = next((call.get("result", {}).get("items", []) for call in calls
                             if call.get("tool") == "assistant.search"
                             and call.get("state") == "completed"), None)
        recall = None
        if case["evaluation"] == "retrieval" and expected and first_search is not None:
            # Same denominator as the frozen keyword baseline, first actual search only.
            unique = list(dict.fromkeys((v.get("source_type"), v.get("source_id"))
                                        for v in first_search))
            recall = {f"recall_at_{k}": sum((v["source_type"], v["source_id"]) in unique[:k]
                                            for v in expected) / len(expected) for k in (5, 10)}
        result.append({**base, "status": row.get("status"), "run_id": row.get("run_id"),
                       "checks": checks, "first_search_recall": recall,
                       "search_union_expected_hits": sum((v["source_type"], v["source_id"])
                                                         in found_ids for v in expected),
                       "hard_failure_observed": bool(leaks)
                       or row.get("business_state_unchanged") is False,
                       "semantic_expected_behavior": case["expected_behavior"]})
    aggregates = {}
    names = sorted({name for row in result for name in row.get("checks", {})})
    for name in names:
        aggregates[name] = dict(Counter(row.get("checks", {}).get(name, {}).get("status", "not_run")
                                        for row in result))
    durations = [row["elapsed_ms"] for row in observations if isinstance(row.get("elapsed_ms"),
        (int, float)) and not isinstance(row["elapsed_ms"], bool)
        and math.isfinite(row["elapsed_ms"]) and row["elapsed_ms"] >= 0]
    return {"version": VERSION, "input_sha256": hashes, "synthetic": True,
            "trusted_root": False, "review_status": questions["status"], "cases": result,
            "status_counts": dict(Counter(row["status"] for row in result)),
            "mechanical_checks": aggregates,
            "latency_ms": {"samples": len(durations),
                           "p50": statistics.median(durations) if durations else None,
                           "p95_inclusive": statistics.quantiles(durations, n=20,
                               method="inclusive")[18] if len(durations) >= 2 else None},
            "quality_passed": None, "independent_human_review": "not_run",
            "scope": "Actual READ/quote/route/permission/path evidence only; semantic facts, "
                     "unknown boundaries and usability require independent review. "
                     "Use native model usage/pricing receipts for cache/cost; never estimate "
                     "money from character counts or missing prices."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--category-id", default="00000000-0000-0000-0000-000000000001")
    parser.add_argument("--namespace", default="rag40-preparation-only")
    parser.add_argument("--native-bindings", type=Path)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--bound-sources", type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=False)
    native = json.loads(args.native_bindings.read_text()) if args.native_bindings else None
    outputs = {"run-specs.json": build_run_specs(args.category_id, namespace=args.namespace,
                                                native_bindings=native),
               "seed-command-plan.json": seed_command_plan(args.category_id,
                                                           namespace=args.namespace)}
    if args.observations:
        if not args.bound_sources:
            parser.error("--observations requires --bound-sources")
        outputs["mechanical-scores.json"] = score_observations(
            json.loads(args.bound_sources.read_text()), json.loads(args.observations.read_text()),
        )
    for name, value in outputs.items():
        (args.output_dir / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    counts = Counter(case["status"] for case in outputs["run-specs.json"]["cases"])
    print(json.dumps({"version": VERSION, "output_dir": str(args.output_dir),
                      "real_model_calls": 0, "database_connections": 0,
                      "ready": counts["ready"], "blocked": counts["blocked"]}))


if __name__ == "__main__":
    main()
