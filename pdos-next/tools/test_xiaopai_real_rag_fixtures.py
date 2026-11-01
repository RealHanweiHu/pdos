"""Pure regression controls; no DB, HTTP server, model, or qualification writes."""

import unittest
from copy import deepcopy
from hashlib import sha256
from uuid import NAMESPACE_URL, uuid5

import xiaopai_real_rag_fixtures as rag


class RagPreparationTests(unittest.TestCase):
    def setUp(self):
        self.questions, self.corpus, self.hashes = rag.frozen_inputs()
        self.bound = {doc["alias"]: {
            "source_type": "artifact", "source_id": str(uuid5(NAMESPACE_URL, doc["alias"])),
            "source_revision": 1, "content_hash": sha256(doc["body"].encode()).hexdigest(),
            "source_body": doc["body"],
        } for doc in self.corpus["documents"]}
        self.category = str(uuid5(NAMESPACE_URL, "pure-category"))

    def test_specs_preserve_original_prompts_and_expectations_without_explicit_pins(self):
        specs = rag.build_run_specs(self.category, namespace="test")["cases"]
        for case, spec in zip(self.questions["questions"], specs, strict=True):
            self.assertEqual(spec["request"]["json"]["goal"], case["prompt"])
            self.assertEqual(spec["case_sha256"], rag.digest(case))
            self.assertEqual(spec["expected_behavior"], case["expected_behavior"])
            self.assertNotIn("sources", spec["request"]["json"])
        self.assertEqual(sum(spec["status"] == "ready" for spec in specs), 32)
        self.assertEqual({spec["case_id"] for spec in specs if spec["status"] == "blocked"},
                         set(rag.NATIVE))

    def test_current_truth_cannot_be_replaced_by_project_id_alone(self):
        bindings = {"QUA-09": {"product_id": self.category, "project_id": self.category}}
        specs = rag.build_run_specs(self.category, namespace="test", native_bindings=bindings)
        case = next(case for case in specs["cases"] if case["case_id"] == "QUA-09")
        self.assertEqual(case["status"], "blocked")
        self.assertEqual(case["missing_native_bindings"],
                         ["current_truth_evidence", "issue_capa_evidence"])

    def test_action_request_uses_actual_parent_and_never_confirms_or_assigns(self):
        binding = {key: self.category for key in ("product_id", "project_id",
                                                  "continue_from_run_id")}
        binding["citation_ids"] = [self.category]
        specs = rag.build_run_specs(self.category, namespace="test",
                                    native_bindings={"QUA-10": binding})
        spec = next(row for row in specs["cases"] if row["case_id"] == "QUA-10")
        self.assertEqual(spec["status"], "ready")
        payload = spec["request"]["json"]
        self.assertEqual(payload["continue_from_run_id"], self.category)
        self.assertEqual(payload["work_followup_action"], {
            "project_id": self.category, "citation_ids": [self.category]})
        self.assertNotIn("confirmation_token", str(payload))

    def test_seed_plan_preserves_private_scope_and_does_not_touch_model_policy(self):
        plan = rag.seed_command_plan(self.category, namespace="test")
        self.assertEqual(len(plan["commands"]), 24)
        for doc, command in zip(self.corpus["documents"], plan["commands"], strict=True):
            self.assertEqual(command["json"]["payload"]["content"], doc["body"])
            self.assertEqual(command["json"]["payload"]["visibility"], doc["visibility"])
            self.assertEqual(command["json"]["operation"], "evidence.artifact.register")
        self.assertEqual(len({row["json"]["idempotency_key"] for row in plan["commands"]}), 24)

    def score(self, observation):
        result = rag.score_observations(self.bound, [observation])
        return result, next(row for row in result["cases"]
                            if row["case_id"] == observation["case_id"])

    def test_missing_evidence_is_not_a_pass_or_a_quality_score(self):
        result, case = self.score({"case_id": "ENG-01", "status": "completed"})
        self.assertIsNone(result["quality_passed"])
        self.assertEqual(result["status_counts"]["not_run"], 39)
        self.assertEqual(case["checks"]["normal_execution_path"]["status"], "not_run")
        self.assertEqual(case["semantic_quality"], "requires_independent_review")

    def test_peer_leak_in_model_request_fails_even_when_answer_hides_it(self):
        source = self.bound["eng_private_reserve"]
        _, case = self.score({"case_id": "ENG-07", "status": "completed", "tool_calls": [],
            "output": {"summary": "当前可读资料不足"},
            "model_requests": [{"untrusted_tool_content": source["source_body"]}],
            "model_requests_complete": True})
        self.assertTrue(case["hard_failure_observed"])
        self.assertEqual(case["checks"]["forbidden_source_exclusion"]["status"], "failed")
        _, fragment = self.score({"case_id": "ENG-07", "status": "completed", "tool_calls": [],
            "output": {"summary": "孔距为32.4 mm"}, "model_requests_complete": True})
        self.assertTrue(fragment["hard_failure_observed"])

    def test_valid_quote_requires_actual_passage_and_matching_native_revision(self):
        source = self.bound["eng_thermal_report"]
        cid = str(uuid5(NAMESPACE_URL, "actual-citation"))
        item = {**source, "citation_id": cid}
        quote = "84.6℃"
        row = {"case_id": "ENG-03", "status": "completed", "tool_calls": [
            {"tool": "assistant.search", "state": "completed", "result": {"items": [item]}}],
            "output": {"result": {"assistant": {"sources": [{**item, "quote": quote}]}}}}
        _, case = self.score(row)
        self.assertEqual(case["checks"]["native_quote_binding"]["status"], "failed")

        row["tool_calls"].append({"tool": "assistant.passage.read", "state": "completed",
                                   "result": {"citation_id": cid, "text": source["source_body"]}})
        _, case = self.score(row)
        self.assertEqual(case["checks"]["native_quote_binding"]["status"], "passed")
        stale = deepcopy(row)
        stale["output"]["result"]["assistant"]["sources"][0]["source_revision"] = 2
        _, case = self.score(stale)
        self.assertEqual(case["checks"]["native_quote_binding"]["status"], "failed")

    def test_unbound_native_source_is_missing_evidence_not_a_fabrication_failure(self):
        _, case = self.score({"case_id": "QUA-09", "status": "completed", "output": {"result": {
            "assistant": {"sources": [{"source_type": "issue", "source_id": self.category,
                                       "quote": "措施尚待验证"}]}}}})
        check = case["checks"]["native_quote_binding"]
        self.assertEqual(check["status"], "not_run")
        self.assertEqual(check["evidence"]["missing_source_binding"], 1)

    def test_model_ledger_entry_is_not_misclassified_as_enterprise_routing(self):
        _, case = self.score({"case_id": "ENG-08", "status": "completed", "tool_calls": [
            {"tool": "model.call", "execution_binding": {"kind": "model"}}]})
        self.assertEqual(case["checks"]["routing"]["status"], "passed")
        _, case = self.score({"case_id": "ENG-08", "status": "completed", "tool_calls": [
            {"tool": "skill.load", "execution_binding": {"kind": "read"}}]})
        self.assertEqual(case["checks"]["routing"]["status"], "failed")

    def test_action_binding_rejects_invented_or_cross_project_parent_evidence(self):
        bindings = {"ENG-10": {"product_id": self.category, "project_id": self.category}}
        parent = {"run_id": self.category, "product_id": self.category,
                  "project_id": self.category, "status": "completed", "output": {"result": {
                    "assistant": {"citation_ids": [self.category], "sources": []}}}}
        with self.assertRaisesRegex(ValueError, "required citations"):
            rag.bind_action_parents(bindings, {"ENG-03": parent}, self.bound)
        parent["output"]["result"]["assistant"]["sources"] = [
            {"source_id": self.bound["eng_thermal_report"]["source_id"]}]
        result = rag.bind_action_parents(bindings, {"ENG-03": parent}, self.bound)
        self.assertEqual(result["ENG-10"]["continue_from_run_id"], self.category)
        parent["project_id"] = str(uuid5(NAMESPACE_URL, "different-project"))
        with self.assertRaisesRegex(ValueError, "Parent project differs"):
            rag.bind_action_parents(bindings, {"ENG-03": parent}, self.bound)


if __name__ == "__main__":
    unittest.main()
