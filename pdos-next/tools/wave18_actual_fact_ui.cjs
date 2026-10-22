#!/usr/bin/env node
"use strict";

/** Offline actual-response check only. No HTTP, database, writes or fake host. */
const fs = require("node:fs");
const path = require("node:path");
const crypto = require("node:crypto");
const root = path.resolve(__dirname, "../..");
const uiDir = path.join(root, "pdos-next/web/src/components/capa-effectiveness");
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const report = {
  schema_version: "pdos-wave18-actual-fact-ui-check-v1",
  status: "FAIL",
  scope: "Offline actual JSON consumed by frozen frontend helpers; no HTTP/DB/browser or actual authority attestation",
  checks: [], failure_codes: [], sources: {}, responses: {}, counts: {}, timing: {},
};
let output;
function check(name, ok, failureCode) {
  report.checks.push({ name, passed: ok === true });
  if (ok !== true) {
    report.failure_codes.push(failureCode);
    throw Object.assign(new Error(failureCode), { safeCode: failureCode });
  }
}
function options() {
  const result = {
    host: "pdos-next/.local/wave18-http-context-v1-current-context.json",
    inputs: "pdos-next/.local/wave18-http-prepare-v1-actual-inputs.json",
    preview: "pdos-next/.local/wave18-http-prepare-v1-actual-preview.json",
    demo: "pdos-next/.local/wave18-fact-demo.json",
    manifest: "docs/reports/evidence/pdos-next-wave18-20261003/fact-ui-source-manifest-v1.json",
  };
  const accepted = new Set(["host", "inputs", "preview", "demo", "manifest", "report", "preview-at"]);
  for (let i = 2; i < process.argv.length; i += 2) {
    const flag = process.argv[i];
    if (!flag?.startsWith("--") || !accepted.has(flag.slice(2)) || !process.argv[i + 1])
      throw Object.assign(new Error(), { safeCode: "INVALID_ARGUMENTS" });
    const key = flag.slice(2);
    if (Object.hasOwn(result, `provided-${key}`)) throw Object.assign(new Error(), { safeCode: "DUPLICATE_ARGUMENT" });
    result[key] = process.argv[i + 1]; result[`provided-${key}`] = true;
  }
  return result;
}
function jsonInput(name, relative) {
  const bytes = fs.readFileSync(path.resolve(root, relative));
  report.responses[name] = { sha256: sha(bytes), bytes: bytes.length };
  return JSON.parse(bytes.toString("utf8"));
}
/** All module code and all parsed actual JSON share the current Node realm. */
function modules(manifestPath) {
  const manifest = jsonInput("manifest", manifestPath);
  const expected = new Map([...manifest.files, ...manifest.dependency_readings].map(f => [path.resolve(root, f.path), f.sha256]));
  const allowed = new Set(["ui-contract", "fact-workflow-contract", "fact-workflow-state"]);
  const ts = require(path.join(root, "pdos-next/web/node_modules/typescript"));
  report.typescript_version = ts.version;
  const cache = new Map();
  function load(name) {
    if (!allowed.has(name)) throw Object.assign(new Error(), { safeCode: "MODULE_OUTSIDE_ALLOWLIST" });
    if (cache.has(name)) return cache.get(name).exports;
    const file = path.join(uiDir, `${name}.ts`), bytes = fs.readFileSync(file), digest = sha(bytes);
    report.sources[name] = { sha256: digest };
    check(`frozen_${name}`, expected.get(file) === digest, "FROZEN_MODULE_CHANGED");
    const result = ts.transpileModule(bytes.toString("utf8"), {
      compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, strict: true },
      fileName: file, reportDiagnostics: true,
    });
    check(`transpile_${name}`, !(result.diagnostics ?? []).some(d => d.category === ts.DiagnosticCategory.Error), "TRANSPILE_FAILED");
    const module = { exports: {} }; cache.set(name, module);
    const ownRequire = requested => {
      if (!/^\.\/[-a-z]+$/.test(requested)) throw Object.assign(new Error(), { safeCode: "MODULE_DEPENDENCY_OUTSIDE_ALLOWLIST" });
      return load(requested.slice(2));
    };
    new Function("require", "module", "exports", result.outputText)(ownRequire, module, module.exports);
    return module.exports;
  }
  return { contract: load("fact-workflow-contract"), state: load("fact-workflow-state"), base: load("ui-contract") };
}
function main() {
  const args = options();
  if (args.report) {
    output = path.resolve(root, args.report);
    if (fs.existsSync(output)) throw Object.assign(new Error(), { safeCode: "REPORT_ALREADY_EXISTS" });
  }
  report.sources.tool = { sha256: sha(fs.readFileSync(__filename)) };
  const { contract: c, state: s, base: b } = modules(args.manifest);
  const host = jsonInput("host", args.host), inputs = jsonInput("inputs", args.inputs);
  const preview = jsonInput("preview", args.preview), demo = jsonInput("demo", args.demo);
  const original = demo?.observation_setup?.command;
  check("actual_host_shape", c.validFactHost(host), "HOST_INVALID");
  check("actual_original_command_shape", c.validFactCommand(original) && original.operation === c.observationOperation,
    "ORIGINAL_COMMAND_UI_SHAPE_INVALID");
  check("actual_scope_and_current", b.same(host.binding.scope, demo.scope) && host.binding.caller_id === demo.actor_id &&
    host.binding.scope.product_id === original.product_id && host.binding.issue_id === original.payload.issue_id &&
    host.binding.capa_id === original.payload.capa_id && demo.rule_payload?.issue_id === original.payload.issue_id &&
    demo.rule_payload?.capa_id === original.payload.capa_id && host.product_revision === original.expected_revision &&
    host.binding.current_issue.revision === original.payload.expected_issue_revision,
    "HOST_SCOPE_CURRENT_MISMATCH");
  check("actual_observation_capability", c.factCanPrepare(host, c.observationOperation), "OBSERVATION_CAPABILITY_UNAVAILABLE");
  let returned;
  try { returned = s.factInputsCommand(inputs, original); }
  catch { check("actual_inputs", false, "INPUTS_CONTRACT_REJECTED"); }
  check("actual_inputs", returned !== null, "INPUTS_NOT_ALLOWED");
  check("actual_inputs_thirteen_keys", b.record(inputs.review) && Object.keys(inputs.review).length === 13,
    "INPUTS_REVIEW_NOT_THIRTEEN_KEYS");
  const at = args["preview-at"];
  check("preview_evaluation_clock", !at || c.factInstant(at) !== null, "INVALID_PREVIEW_EVALUATION_CLOCK");
  const now = at ? Date.parse(at) : Date.now();
  report.preview_clock_basis = at ? "explicit_historical_offline_display_only" : "current_offline_check";
  let prepared;
  try { prepared = s.factPrepared(preview, returned, now); }
  catch { check("actual_preview", false, "PREVIEW_CONTRACT_THROW"); }
  check("actual_preview", prepared !== null, "PREVIEW_INVALID_OR_EXPIRED");
  check("actual_preview_thirteen_keys", Object.keys(prepared.review).length === 13, "PREVIEW_REVIEW_NOT_THIRTEEN_KEYS");
  let business;
  try { business = c.readFactBusinessReview(host, prepared.review, prepared.command); }
  catch { check("actual_business_material", false, "BUSINESS_READER_THROW"); }
  check("actual_business_material", business?.complete === true && business.sections.length > 0 && business.effect.trim().length > 0,
    "BUSINESS_MATERIAL_INCOMPLETE");
  check("saved_effect_boundaries", host.effectiveness_enabled === false && host.close_enabled === false, "EFFECT_OR_CLOSE_UNEXPECTED");
  const semantic = c.tokenlessFactPayload(prepared.command.payload);
  const rows = business.sections.flatMap(section => section.rows);
  const selected = semantic.records.map(record => host.records.filter(choice => b.same(choice.record, record)));
  check("whole_original_record_options", selected.every(matches => matches.length === 1), "ORIGINAL_RECORD_OPTION_MISMATCH");
  const timings = selected.map(matches => c.factRecordTiming(matches[0]));
  check("verified_record_clock_defaults", timings.every(t => t !== null), "VERIFIED_RECORD_CLOCK_DEFAULTS_MISSING");
  report.timing = {
    record_clock_defaults: timings.length,
    original_event_clock_rendered_verbatim: rows.some(row => row.value === semantic.at.occurred_at),
    original_timezone_rendered_verbatim: rows.some(row => row.value === semantic.at.original_timezone),
    selected_clock_microseconds_parseable: timings.every(t => c.factInstant(t.at.occurred_at) !== null),
    first_default_event_same_microsecond_instant: c.sameFactInstant(timings[0].at.occurred_at, semantic.at.occurred_at),
    original_record_occurrence_preserved: selected.every(([choice], i) => choice.record.occurred_at === semantic.records[i].occurred_at),
  };
  const actions = prepared.review.stable_anchor?.origin?.issue?.capa?.actions;
  check("original_completions_available", Array.isArray(actions) && actions.every(a => b.record(a.completion) && b.record(a.completion.at)),
    "ORIGINAL_COMPLETION_CLOCKS_MISSING");
  report.timing.completion_clock_count = actions.length;
  report.timing.completion_clocks_rendered_verbatim = actions.every(a => rows.some(row => row.value === a.completion.at.occurred_at));
  check("actual_clock_values_preserved", report.timing.original_event_clock_rendered_verbatim && report.timing.original_timezone_rendered_verbatim &&
    report.timing.original_record_occurrence_preserved && report.timing.completion_clocks_rendered_verbatim,
    "ACTUAL_CLOCK_DISPLAY_PRECISION_LOST");
  report.counts = {
    host_rules: host.rules.length, host_history: host.history.length, host_record_options: host.records.length,
    full_source_reads: returned.source_read_set.length, selected_records: semantic.records.length,
    rendered_sections: business.sections.length, rendered_rows: rows.length, rendered_sources: business.sources.length,
    fixed_failures: prepared.review.stable_anchor.failures.length, actual_completed_actions: actions.length,
  };
  report.sections = business.sections.map(section => ({ rows: section.rows.length }));
  report.business_complete = business.complete; report.effect_nonempty = business.effect.trim().length > 0;
  report.synthetic = business.synthetic;
  report.status = at ? "PASS_RECORDED_PREVIEW_DISPLAY_ONLY" : "PASS_EXACT_ACTUAL_UI_CONTRACT";
}
try { main(); }
catch (error) {
  const code = typeof error?.safeCode === "string" ? error.safeCode : "OFFLINE_INPUT_OR_RUNTIME_FAILURE";
  if (!report.failure_codes.includes(code)) report.failure_codes.push(code);
  report.status = "FAIL";
}
const serialized = `${JSON.stringify(report, null, 2)}\n`;
try {
  if (output && !fs.existsSync(output)) fs.writeFileSync(output, serialized, { flag: "wx", mode: 0o600 });
} catch { report.status = "FAIL"; report.failure_codes.push("REPORT_WRITE_FAILED"); }
process.stdout.write(`${JSON.stringify(report)}\n`);
process.exitCode = report.status.startsWith("PASS_") ? 0 : 1;
