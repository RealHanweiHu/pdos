"""No network/database/filesystem business operations: actual pure protocol helpers."""

from contextlib import ExitStack
from copy import deepcopy
from datetime import UTC, datetime
from unittest import TestCase, main
from unittest.mock import patch
from uuid import UUID

import wave22_shared_build as build

_NO_IO = None


def setUpModule():
    global _NO_IO
    import httpx
    from sqlalchemy.engine import Engine

    def forbidden(*args, **kwargs):
        raise AssertionError("No DB/HTTP/target operation is allowed by these pure checks")

    _NO_IO = ExitStack()
    for target, method in (
        (Engine, "connect"),
        (Engine, "raw_connection"),
        (httpx.Client, "request"),
        (build.SharedBuild, "target"),
    ):
        _NO_IO.enter_context(patch.object(target, method, forbidden))


def tearDownModule():
    _NO_IO.close()


def identity(n):
    return str(UUID(int=n))


def source(n=1, revision=1):
    return {
        "artifact_id": identity(n),
        "expected_revision": revision,
        "line": 1,
        "quote": "Explicit new local synthetic fact",
    }


def foundation():
    roles = {
        role: {"id": identity(i + 10), "login_token": "x" * 32}
        for i, role in enumerate(("maker", "observer", "independent_reviewer"))
    }
    families = {
        "project": "project",
        "definition": "definition_revision",
        "bom": "bom_revision",
        "engineering": "engineering_configuration",
        "manufacturing": "process_revision",
        "native-source": "artifact",
    }
    receipts = {
        label: {"subject_id": identity(i + 20), "subject_revision": 1, "subject_type": family}
        for i, (label, family) in enumerate(families.items())
    }
    ref = source(25)
    return {
        "schema_version": build.FOUNDATION_SCHEMA,
        "marker": identity(100),
        "case_id": identity(101),
        "tenant_id": identity(102),
        "product_id": identity(103),
        "project_id": receipts["project"]["subject_id"],
        "purpose": "新共享内部合成两件A调查",
        "visibility": "product",
        "actors": roles,
        "phase": "foundation_saved_not_build_started",
        "receipts": receipts,
        "scope": {
            "tenant_id": identity(102),
            "product_id": identity(103),
            "project_id": receipts["project"]["subject_id"],
        },
        "configuration": {
            key + suffix: receipts[key]["subject_id" if suffix == "_id" else "subject_revision"]
            for key in ("bom", "engineering", "manufacturing")
            for suffix in ("_id", "_revision")
        },
        "sources": {
            "foundation": {"reference": ref, "required_source_read_set": build.ref_reads([ref])}
        },
        "readback": {
            role: {"shared_objects": 6, "professional_qualification": None} for role in roles
        },
    }


class FoundationProtocol(TestCase):
    def test_actual_b_foundation_shape_keeps_new_scope_and_three_people(self):
        value = foundation()
        material = build.foundation_material(value, identity(100))
        self.assertEqual(material["scope"], value["scope"])
        self.assertEqual(len(set(material["actors"].values())), 3)
        self.assertNotIn("login_token", build.canonical(material))

    def test_cannot_consume_old_demo_schema(self):
        value = foundation()
        value["schema_version"] = "wave15-seed"
        with self.assertRaisesRegex(build.Stop, "NEW_SHARED_FOUNDATION"):
            build.foundation_material(value, identity(100))

    def test_wrong_marker_or_private_or_unfinished_foundation_rejected(self):
        for key, val in (
            ("marker", identity(99)),
            ("visibility", "private"),
            ("phase", "allocated"),
        ):
            with self.subTest(key=key):
                value = foundation()
                value[key] = val
                with self.assertRaises(build.Stop):
                    build.foundation_material(value, identity(100))

    def test_duplicate_actor_cannot_be_independent_reviewer(self):
        value = foundation()
        value["actors"]["independent_reviewer"]["id"] = value["actors"]["maker"]["id"]
        with self.assertRaisesRegex(build.Stop, "THREE_EXACT_ACTORS"):
            build.foundation_material(value, identity(100))

    def test_configuration_receipt_revision_not_guessed(self):
        value = foundation()
        value["configuration"]["manufacturing_revision"] = 2
        with self.assertRaises(build.Stop):
            build.foundation_material(value, identity(100))

    def test_product_scope_not_taken_from_other_checkpoint(self):
        value = foundation()
        value["scope"]["product_id"] = identity(999)
        with self.assertRaisesRegex(build.Stop, "EXACT_FOUNDATION_SCOPE"):
            build.foundation_material(value, identity(100))

    def test_missing_actor_readback_does_not_make_shared_case_available(self):
        value = foundation()
        del value["readback"]["observer"]
        with self.assertRaisesRegex(build.Stop, "THREE_ACTOR_FOUNDATION_READBACK"):
            build.foundation_material(value, identity(100))

    def test_long_purpose_is_not_truncated_for_manufacturing_scope(self):
        value = foundation()
        value["purpose"] = "新" * 161
        with self.assertRaises(build.Stop):
            build.foundation_material(value, identity(100))

    def test_real_project_nested_definition_source_and_fixed_chain_are_consumed(self):
        material, workspace, projects, configs = view_fixture()
        self.assertNotIn("source_status", projects["items"][0])
        product, selected = build.foundation_views(material, workspace, projects, configs)
        self.assertEqual(product["id"], material["scope"]["product_id"])
        self.assertEqual(len(selected), 3)

    def test_withdrawn_nested_definition_or_other_fixed_bom_does_not_create_build(self):
        for field in ("definition_state", "bom"):
            material, workspace, projects, configs = view_fixture()
            if field == "definition_state":
                projects["items"][0]["definition"]["source_status"] = "needs_recheck"
            else:
                configs["engineering"][0]["bom_id"] = identity(99)
            with self.subTest(field=field), self.assertRaises(build.Stop):
                build.foundation_views(material, workspace, projects, configs)

    def test_shared_project_owned_by_peer_is_not_maker_build_write_permission(self):
        material, workspace, projects, configs = view_fixture()
        projects["items"][0]["owner_id"] = material["actors"]["observer"]
        with self.assertRaisesRegex(build.Stop, "MAKER_PROJECT_OWNER_REQUIRED"):
            build.foundation_views(material, workspace, projects, configs)


def view_fixture():
    material = build.foundation_material(foundation(), identity(100))
    config = material["configuration"]
    required = material["foundation_source"]["required_source_read_set"]
    workspace = {
        "product": {
            "id": material["scope"]["product_id"],
            "purpose": material["purpose"],
            "revision": 1,
        }
    }
    projects = {
        "items": [
            {
                "id": material["scope"]["project_id"],
                "revision": 1,
                "owner_id": material["actors"]["maker"],
                "purpose": material["purpose"],
                "visibility": "product",
                "required_source_read_set": required,
                "definition": {
                    "id": material["definition_id"],
                    "revision": material["definition_revision"],
                    "source_status": "current",
                },
            }
        ]
    }
    configs = {
        "engineering": [
            {
                "id": config["engineering_id"],
                "revision": config["engineering_revision"],
                "visibility": "product",
                "source_status": "current",
                "required_source_read_set": required,
                "definition_id": material["definition_id"],
                "definition_revision": material["definition_revision"],
                "bom_id": config["bom_id"],
                "bom_revision": config["bom_revision"],
            }
        ],
        "processes": [
            {
                "id": config["manufacturing_id"],
                "revision": config["manufacturing_revision"],
                "visibility": "product",
                "source_status": "current",
                "required_source_read_set": required,
                "engineering_configuration_id": config["engineering_id"],
                "engineering_revision": config["engineering_revision"],
            }
        ],
    }
    return material, workspace, projects, configs


class ExactSourcesAndTimes(TestCase):
    def test_complete_reads_coalesce_same_revision_without_dropping_source(self):
        self.assertEqual(
            build.reads(build.ref_reads([source(1), source(2)]), build.ref_reads([source(1)])),
            build.ref_reads([source(1), source(2)]),
        )

    def test_conflicting_revision_rejected(self):
        with self.assertRaisesRegex(build.Stop, "SOURCE_VERSION_CONFLICT"):
            build.reads(build.ref_reads([source(1)]), build.ref_reads([source(1, 2)]))

    def test_21_sources_rejected_instead_of_sliced(self):
        with self.assertRaisesRegex(build.Stop, "SOURCE_CLOSURE_EXCEEDS_20"):
            build.ref_reads([source(i) for i in range(1, 22)])

    def test_bool_source_revision_is_not_int_revision(self):
        with self.assertRaises(build.Stop):
            build.ref_reads([source(1, True)])

    def test_actual_clock_preserves_offset_and_six_digits_in_original_source(self):
        text = "2026-10-03T06:25:03.160086+00:00"
        event = {"build_id": identity(1), "occurred_at": text}
        line = build.occurred_json(
            event,
            kind="start",
            material={"build_id": identity(1)},
            at=datetime(2026, 10, 4, tzinfo=UTC),
        )
        self.assertIn(text, line)
        self.assertEqual(build.aware(text).microsecond, 160086)

    def test_future_or_naive_event_cannot_be_native_registered(self):
        for text in ("2026-10-05T00:00:00+00:00", "2026-10-03T00:00:00"):
            with self.subTest(text=text), self.assertRaises(build.Stop):
                build.occurred_json(
                    {"build_id": identity(1), "occurred_at": text},
                    kind="start",
                    material={"build_id": identity(1)},
                    at=datetime(2026, 10, 4, tzinfo=UTC),
                )

    def test_wrong_config_or_extra_event_field_rejected(self):
        for value in (
            {"build_id": identity(2), "occurred_at": "2026-10-03T00:00:00Z"},
            {"build_id": identity(1), "occurred_at": "2026-10-03T00:00:00Z", "ready": True},
        ):
            with self.assertRaises(build.Stop):
                build.occurred_json(
                    value,
                    kind="start",
                    material={"build_id": identity(1)},
                    at=datetime(2026, 10, 4, tzinfo=UTC),
                )

    def test_preview_preserves_entire_command_except_server_token_and_typed_clock(self):
        original = build.base_command(
            operation="build.start",
            product_id=identity(1),
            revision=1,
            payload={"occurred_at": "2026-10-03T06:25:03.160086+00:00", "source": source()},
            source_reads=build.ref_reads([source()]),
        )
        prepared = deepcopy(original)
        prepared["payload"]["occurred_at"] = "2026-10-03T06:25:03.160086Z"
        prepared["payload"]["confirmation_token"] = "x" * 32

        def typed(payload):
            result = deepcopy(payload)
            result["occurred_at"] = build.aware(result["occurred_at"]).astimezone(UTC).isoformat()
            return result

        self.assertTrue(build.prepared_equal(original, prepared, typed))
        prepared["payload"]["occurred_at"] = "2026-10-03T06:25:03.160085Z"
        self.assertFalse(build.prepared_equal(original, prepared, typed))

    def test_changed_key_source_or_quantity_not_normalized_away(self):
        original = build.base_command(
            operation="build.create",
            product_id=identity(1),
            revision=1,
            payload={"quantity": "2", "source": source()},
            source_reads=build.ref_reads([source()]),
        )
        for mutate in (
            lambda p: p.update(idempotency_key=identity(9)),
            lambda p: p["payload"].update(quantity="3"),
            lambda p: p["payload"]["source"].update(quote="other source"),
        ):
            prepared = deepcopy(original)
            mutate(prepared)
            with self.subTest(prepared=prepared):
                self.assertFalse(build.prepared_equal(original, prepared, lambda v: v))


def memory_work(stage="execute_unknown"):
    work = object.__new__(build.SharedBuild)
    work.pid, work.actor = identity(1), identity(2)
    original = build.base_command(
        operation="build.start",
        product_id=work.pid,
        revision=1,
        payload={"material": "fixed"},
        source_reads=[],
    )
    prepared = deepcopy(original)
    prepared["payload"]["confirmation_token"] = "x" * 32
    work.data = {
        "requests": {
            "start": {
                "actor": work.actor,
                "original": original,
                "body": prepared,
                "stage": stage,
                "review_digest": "d" * 64,
            }
        },
        "receipts": {},
    }
    work.confirm = work.review_digest = work.recover = None
    work.confirm_used = work.recover_used = False
    snapshots, sent = [], []
    work.save = lambda: snapshots.append(deepcopy(work.data))
    result = {
        "id": identity(3),
        "operation": "build.start",
        "subject_type": "build_start",
        "subject_id": identity(4),
        "subject_revision": 1,
        "writer_id": work.actor,
        "requester_id": work.actor,
        "created_at": "2026-10-03T00:00:00Z",
    }

    def http(method, path, *, body):
        sent.append(deepcopy(body))
        return deepcopy(result)

    work.http = http
    return work, snapshots, sent, result


class OriginalRequestRecovery(TestCase):
    def test_confirmation_resume_reports_saved_start_without_claiming_current_qualification(self):
        work, _, _, _ = memory_work("awaiting_confirmation")
        work.confirm, work.review_digest = "start", "d" * 64
        work.resume("start", "build.start", "build_start")
        self.assertEqual(
            build.saved_phase(work.data),
            "internal_synthetic_start_saved_current_qualification_not_asserted",
        )

    def test_unknown_never_repreviews_or_sends_without_explicit_original_recovery(self):
        work, _, sent, _ = memory_work()
        with self.assertRaises(build.Pending):
            work.resume("start", "build.start", "build_start")
        self.assertEqual(sent, [])

    def test_explicit_unknown_recovery_sends_exact_prepared_key_payload_once(self):
        work, snapshots, sent, result = memory_work()
        before = deepcopy(work.data["requests"]["start"]["body"])
        work.recover = "start"
        self.assertEqual(work.resume("start", "build.start", "build_start"), result)
        self.assertEqual(sent, [before])
        self.assertEqual(snapshots[0]["requests"]["start"]["stage"], "execute_sending")
        self.assertEqual(snapshots[-1]["receipts"]["start"], result)

    def test_timeout_preserves_original_prepared_body_and_unknown_lock(self):
        work, _, sent, _ = memory_work()
        original = deepcopy(work.data["requests"]["start"]["body"])
        work.recover = "start"

        def fail(*args, **kwargs):
            sent.append(deepcopy(kwargs["body"]))
            raise TimeoutError

        work.http = fail
        with self.assertRaises(TimeoutError):
            work.resume("start", "build.start", "build_start")
        self.assertEqual(sent, [original])
        self.assertEqual(work.data["requests"]["start"]["stage"], "execute_unknown")
        self.assertEqual(work.data["requests"]["start"]["body"], original)

    def test_saved_receipt_wins_and_later_failure_does_not_send_again(self):
        work, _, sent, result = memory_work()
        work.data["receipts"]["start"] = result
        work.http = lambda *a, **k: (_ for _ in ()).throw(
            AssertionError("Must not HTTP replay saved receipt")
        )
        self.assertEqual(work.resume("start", "build.start", "build_start"), result)
        self.assertEqual(sent, [])

    def test_one_confirmation_requires_exact_review_digest(self):
        work, _, sent, result = memory_work("awaiting_confirmation")
        work.confirm, work.review_digest = "start", "e" * 64
        with self.assertRaises(build.Pending):
            work.resume("start", "build.start", "build_start")
        self.assertEqual(sent, [])
        work.review_digest = "d" * 64
        self.assertEqual(work.resume("start", "build.start", "build_start"), result)
        self.assertEqual(len(sent), 1)

    def test_scope_or_family_change_not_replayed(self):
        work, _, sent, result = memory_work()
        work.data["receipts"]["start"] = result
        with self.assertRaises(build.Stop):
            work.resume("start", "build.start", "actual_configuration")
        with self.assertRaises(build.Stop):
            work.resume("start", "build.output.record", "build_lot")
        self.assertEqual(sent, [])

    def test_preview_uncertainty_cannot_issue_replacement_token(self):
        work, _, sent, _ = memory_work("preview_unknown")
        work.recover, work.confirm, work.review_digest = "start", "start", "d" * 64
        with self.assertRaises(build.Pending):
            work.resume("start", "build.start", "build_start")
        self.assertEqual(sent, [])

    def test_bool_subject_revision_cannot_be_success(self):
        work, _, _, result = memory_work()
        result["subject_revision"] = True
        with self.assertRaises(build.Stop):
            build.receipt(result, operation="build.start", family="build_start", actor=work.actor)

    def test_source_retry_cannot_change_original_registered_bytes(self):
        work, _, _, _ = memory_work()
        work.data["requests"]["source-event"] = {"original": {"payload": {"content": "original"}}}
        with self.assertRaisesRegex(build.Stop, "ORIGINAL_NATIVE_SOURCE_CONTENT_CHANGED"):
            work.artifact("event", ["changed"])


class ActualTypedCompatibility(TestCase):
    """Actual domain parsers only; no Session/Engine/client or old Demo construction."""

    def test_real_build_and_readiness_modes_accept_two_unit_shared_scope(self):
        # Match actual tool/API entry order: shared contracts owns schema registration.
        # Direct first-import of the child schema has the existing circular bootstrap.
        from pdos_next.contracts import PAYLOADS

        BuildCreatePayload = PAYLOADS["build.create"]
        BuildReadinessPayload = PAYLOADS["build.readiness.compute"]

        payload = BuildCreatePayload.model_validate(
            {
                "project_id": identity(1),
                "expected_project_revision": 1,
                "engineering_configuration_id": identity(2),
                "manufacturing_configuration_id": identity(3),
                "name": "新共享两件A",
                "type": "prototype",
                "purpose": "新内部合成调查",
                "planned_quantity": "2",
                "unit": "ea",
                "planned_start": None,
                "planned_end": None,
                "verification_objectives": "明确两件A身份供分开的原失败与复验",
                "disposition_plan": "内部保留、不对外放行",
                "previous_build_id": None,
            }
        )
        self.assertEqual(str(payload.planned_quantity), "2")
        first = BuildReadinessPayload.model_validate(
            {"build_id": identity(4), "expected_build_revision": 1}
        )
        self.assertNotIn("execution_scope", first.model_dump(mode="json"))
        execution = BuildReadinessPayload.model_validate(
            {
                "build_id": identity(4),
                "expected_build_revision": 1,
                "previous_assessment_id": None,
                "expected_previous_revision": 0,
                "reason": "当前范围核对",
                "execution_scope": {
                    "purpose": "新内部合成调查",
                    "quantity": "2",
                    "unit": "ea",
                    "site": "新合成场地",
                    "window_start": "2026-10-03T06:25:03.160086+00:00",
                    "window_end": "2026-10-04T06:25:03.160086+00:00",
                    "window_timezone": "UTC",
                },
            }
        )
        self.assertEqual(execution.execution_scope.window_start.microsecond, 160086)

    def test_real_start_preview_clock_canonicalization_retains_exact_microseconds(self):
        from pdos_next.domain.build_start.schemas import BuildStartPayload

        payload = {
            "assessment_id": identity(1),
            "expected_assessment_revision": 1,
            "expected_assessment_sha256": "a" * 64,
            "engineering_authorization_id": identity(2),
            "expected_engineering_authorization_revision": 1,
            "manufacturing_authorization_id": identity(3),
            "expected_manufacturing_authorization_revision": 1,
            "occurred_at": "2026-10-03T06:25:03.160086+00:00",
            "occurred_timezone": "UTC",
            "event_source": source(),
            "reason": "已发生合成开工记录",
        }

        def normalize(val):
            return BuildStartPayload.model_validate(val).model_dump(mode="json", exclude_none=True)

        original = build.base_command(
            operation="build.start",
            product_id=identity(10),
            revision=1,
            payload=normalize(payload),
            source_reads=build.ref_reads([source()]),
        )
        prepared = deepcopy(original)
        prepared["payload"]["confirmation_token"] = "x" * 32
        self.assertTrue(build.prepared_equal(original, prepared, normalize))
        prepared["payload"]["occurred_at"] = "2026-10-03T06:25:03.160085Z"
        self.assertFalse(build.prepared_equal(original, prepared, normalize))

    def test_real_t2_role_rules_and_controls_are_exact_closed_contract(self):
        from pdos_next.domain.build_start.rules import CONTROLS, PROFESSIONAL_RULES
        from pdos_next.domain.build_start.schemas import BuildAuthorizationPayload

        self.assertEqual(set(build.CONTROLS), CONTROLS)
        self.assertEqual(build.PROFESSIONAL_RULES, PROFESSIONAL_RULES)
        raw = {
            "assessment_id": identity(1),
            "expected_assessment_revision": 1,
            "expected_assessment_sha256": "a" * 64,
            "action": "approve",
            "valid_until": "2026-10-04T06:25:03.160086+00:00",
            "accepted_controls": list(build.CONTROLS),
            "sources": [source()],
            "reason": "具名合成用途审批",
            "professional_assessments": [
                {
                    "rule_id": rule,
                    "status": "applicable",
                    "sources": [source()],
                    "valid_until": "2026-10-04T06:25:03.160086+00:00",
                    "reason": "具名限定适用",
                }
                for rule in build.PROFESSIONAL_RULES["engineering"]
            ],
        }
        parsed = BuildAuthorizationPayload.model_validate(raw)
        self.assertEqual(parsed.valid_until.microsecond, 160086)
        self.assertEqual(len(parsed.professional_assessments), 2)


class KnownDemandDecimalProtocol(TestCase):
    def row(self):
        return {
            "unit": "ea",
            "issues": [],
            "item_id": "unit",
            "ancestry": [],
            "critical": True,
            "material_id": identity(160),
            "required_quantity": "2.00000000",
            "quantity_per_product": "1",
        }

    def test_actual_fixed_scale_demand_is_known_and_original_strings_remain(self):
        values = [self.row()]
        original = deepcopy(values)
        self.assertTrue(build.known_two_unit_demand(values))
        self.assertEqual(values, original)
        self.assertEqual(values[0]["required_quantity"], "2.00000000")

    def test_exact_finite_decimal_equivalents_do_not_imply_tolerance(self):
        for per, required in (("1.00000000", "2"), ("1", "2.00"), ("1e0", "2E+0")):
            row = self.row()
            row.update(quantity_per_product=per, required_quantity=required)
            self.assertTrue(build.known_two_unit_demand([row]))
        for value in ("2.00000001", "1.99999999", "0", "-2", "3"):
            row = self.row()
            row["required_quantity"] = value
            self.assertFalse(build.known_two_unit_demand([row]))

    def test_bool_float_null_nonfinite_and_noncanonical_numeric_input_rejected(self):
        for key in ("quantity_per_product", "required_quantity"):
            for value in (
                True,
                False,
                1,
                2.0,
                None,
                "NaN",
                "sNaN",
                "Infinity",
                "-Infinity",
                "2_0e-1",
                " 2",
                "2 ",
                "two",
                "",
            ):
                row = self.row()
                row[key] = value
                with self.subTest(key=key, value=value):
                    self.assertFalse(build.known_two_unit_demand([row]))

    def test_wrong_per_product_quantity_or_unit_or_issues_not_known(self):
        for key, value in (
            ("quantity_per_product", "2"),
            ("unit", "piece"),
            ("issues", [{"code": "UNKNOWN"}]),
            ("issues", None),
            ("issues", False),
            ("issues", ()),
            ("critical", 1),
        ):
            row = self.row()
            row[key] = value
            self.assertFalse(build.known_two_unit_demand([row]))

    def test_missing_extra_or_multiple_rows_are_not_the_exact_fixed_demand(self):
        row = self.row()
        for values in ([], [row, deepcopy(row)], None, [None], (row,)):
            self.assertFalse(build.known_two_unit_demand(values))
        row["unknown_scope"] = "must not silently ignore extra fields"
        self.assertFalse(build.known_two_unit_demand([row]))
        row = self.row()
        del row["material_id"]
        self.assertFalse(build.known_two_unit_demand([row]))


class CompleteStartSourceClosure(TestCase):
    def actual_shape(self):
        bid, aid = identity(200), identity(201)
        assessment = {
            "id": aid,
            "build_id": bid,
            "revision": 1,
            "is_current": True,
            "source_status": "current",
            "snapshot_sha256": "a" * 64,
            "required_source_read_set": build.ref_reads([source(210)]),
        }
        approvals = []
        for role, ident, publication in (("engineering", 202, 211), ("manufacturing", 203, 212)):
            approvals.append(
                {
                    "id": identity(ident),
                    "revision": 1,
                    "build_id": bid,
                    "role": role,
                    "action": "approve",
                    "status": "approved",
                    "is_current": True,
                    "source_status": "current",
                    "assessment_id": aid,
                    "assessment_revision": 1,
                    "assessment_sha256": "a" * 64,
                    "required_source_read_set": build.ref_reads([source(210), source(publication)]),
                }
            )
        state = {
            "assessments": [assessment],
            "authorizations": approvals,
            "current_assessment_by_build": {bid: {"assessment_id": aid, "revision": 1}},
            "current_authorization_by_build": {
                bid: {
                    role: {"decision_id": row["id"], "revision": row["revision"]}
                    for role, row in zip(("engineering", "manufacturing"), approvals, strict=True)
                }
            },
            "capabilities_by_build": {
                bid: {
                    "start": True,
                    "required_source_read_set": build.ref_reads([source(210), source(213)]),
                    "authority": {
                        "start": {"required_source_read_set": build.ref_reads([source(214)])}
                    },
                }
            },
        }
        receipts = [
            {"subject_id": row["id"], "subject_revision": row["revision"]} for row in approvals
        ]
        return state, bid, assessment, *receipts, source(215)

    def test_current_both_saved_approvals_publish_full_sources_not_in_assessment_or_cap(self):
        args = self.actual_shape()
        original = deepcopy(args)
        result = build.start_read_set(*args)
        self.assertEqual(
            {entry["artifact_id"] for entry in result}, {identity(i) for i in range(210, 216)}
        )
        self.assertEqual(args, original)
        self.assertNotIn(
            identity(211), {v["artifact_id"] for v in args[2]["required_source_read_set"]}
        )

    def test_start_method_uses_current_decision_reads_and_preserves_actual_event_clock(self):
        state, bid, assessment, engineering, manufacturing, event = self.actual_shape()
        work = object.__new__(build.SharedBuild)
        work.basis = {
            "purpose": "explicit local synthetic investigation",
            "configuration": {"engineering_id": identity(220), "manufacturing_id": identity(221)},
        }
        work.data = {
            "receipts": {
                "build": {"subject_id": bid},
                "assessment": {"subject_id": assessment["id"]},
                "approve-engineering": engineering,
                "approve-manufacturing": manufacturing,
            }
        }
        work.saved = lambda label: work.data["receipts"][label]
        work.resume = lambda *args: None
        work.get = lambda path: state
        clock = "2026-10-03T06:25:03.160086+00:00"
        work.occurred_source = lambda *args: (event, clock)
        sent = []
        work.submit = lambda *args: sent.append(deepcopy(args))
        work.save = lambda: None
        work.start({"occurred_at": clock})
        self.assertEqual(len(sent), 1)
        self.assertEqual(sent[0][2]["occurred_at"], clock)
        self.assertEqual(sent[0][2]["event_source"], event)
        self.assertEqual(
            {v["artifact_id"] for v in sent[0][3]}, {identity(i) for i in range(210, 216)}
        )

    def test_current_pointer_role_build_assessment_or_visibility_state_drift_rejected(self):
        for field, value in (
            ("role", "manufacturing"),
            ("build_id", identity(230)),
            ("assessment_id", identity(231)),
            ("assessment_sha256", "b" * 64),
            ("assessment_revision", True),
            ("revision", True),
            ("action", "revoke"),
            ("status", "revoked"),
            ("is_current", False),
            ("source_status", "needs_recheck"),
        ):
            args = self.actual_shape()
            args[0]["authorizations"][0][field] = value
            with self.subTest(field=field), self.assertRaises(build.Stop):
                build.start_read_set(*args)
        args = self.actual_shape()
        args[0]["current_authorization_by_build"][args[1]]["engineering"]["revision"] = True
        with self.assertRaises(build.Stop):
            build.start_read_set(*args)

    def test_missing_or_duplicate_saved_current_approval_fail_closed(self):
        for action in ("missing", "duplicate", "wrong_pointer"):
            args = self.actual_shape()
            if action == "missing":
                args[0]["authorizations"].pop(0)
            elif action == "duplicate":
                args[0]["authorizations"].append(deepcopy(args[0]["authorizations"][0]))
            else:
                args[0]["current_authorization_by_build"][args[1]]["engineering"]["decision_id"] = (
                    identity(240)
                )
            with self.subTest(action=action), self.assertRaises(build.Stop):
                build.start_read_set(*args)

    def test_conflicting_source_versions_or_over_twenty_not_silently_trimmed(self):
        args = self.actual_shape()
        args[0]["authorizations"][0]["required_source_read_set"] = build.ref_reads([source(210, 2)])
        with self.assertRaisesRegex(build.Stop, "SOURCE_VERSION_CONFLICT"):
            build.start_read_set(*args)
        args = self.actual_shape()
        args[0]["authorizations"][0]["required_source_read_set"] = build.ref_reads(
            [source(i) for i in range(300, 320)]
        )
        with self.assertRaisesRegex(build.Stop, "SOURCE_CLOSURE_EXCEEDS_20"):
            build.start_read_set(*args)

    def test_existing_preview_unknown_remains_locked_and_original_body_key_untouched(self):
        work, snapshots, sent, _ = memory_work("preview_unknown")
        original = deepcopy(work.data)
        work.get = lambda *args: self.fail("Unknown request must not fetch new source closure")
        with self.assertRaises(build.Pending):
            work.start({"occurred_at": "2026-10-03T06:25:03.160086+00:00"})
        self.assertEqual(work.data, original)
        self.assertEqual(snapshots, [])
        self.assertEqual(sent, [])


if __name__ == "__main__":
    main()
