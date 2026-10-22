"use strict";
/** Actual saved HTTP JSON through frozen UI contract. No browser, HTTP or write. */
const fs = require("node:fs"), path = require("node:path"), crypto = require("node:crypto");
const root = path.resolve(__dirname, "../.."), reportDir = path.join(root, "docs/reports/evidence/pdos-next-wave19-20261003");
const sha = bytes => crypto.createHash("sha256").update(bytes).digest("hex");
const tag = process.argv[2];
if (!/^v\d+$/.test(tag ?? "")) throw new Error("EXPLICIT_ACTUAL_RESPONSE_TAG_REQUIRED");
const out = path.join(reportDir, `actual-selection-ui-${tag}.json`);
if (fs.existsSync(out)) throw new Error("RETAIN_ORIGINAL_REPORT");
const result = { status: "RUNNING", scope: "Offline frozen contract with actual response JSON; no current qualification claim", checks: [], sources: {}, responses: {} };
function check(name, ok) { result.checks.push({ name, passed: ok === true }); if (ok !== true) throw new Error(name); }
function read(file) { const bytes = fs.readFileSync(file); result.responses[path.relative(root, file)] = sha(bytes); return JSON.parse(bytes); }
const manifest = read(path.join(reportDir, "ui-selection-source-manifest-v2.json"));
const ts = require(path.join(root, "pdos-next/web/node_modules/typescript")), cache = new Map();
function load(name) {
  if (!["ui-contract", "fact-workflow-contract"].includes(name)) throw new Error("MODULE_OUTSIDE_ACTUAL_ADAPTER");
  if (cache.has(name)) return cache.get(name).exports;
  const file = path.join(root, "pdos-next/web/src/components/capa-effectiveness", `${name}.ts`), bytes = fs.readFileSync(file);
  result.sources[name] = sha(bytes);
  const expected = manifest.files.find(row => path.resolve(root, row.path) === file);
  if (expected) check(`frozen_${name}`, expected.sha256 === sha(bytes));
  const js = ts.transpileModule(bytes.toString("utf8"), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
  const mod = { exports: {} }; cache.set(name, mod);
  new Function("require", "module", "exports", js)(request => {
    if (!/^\.\/[-a-z]+$/.test(request)) throw new Error("MODULE_OUTSIDE_ALLOWLIST");
    return load(request.slice(2));
  }, mod, mod.exports);
  return mod.exports;
}
try {
  const c = load("fact-workflow-contract");
  const host = read(path.join(root, `pdos-next/.local/wave19-http-${tag}-unselected.json`));
  const selected = read(path.join(root, `pdos-next/.local/wave19-http-${tag}-selected-0.json`));
  const b = host.binding, choice = host.candidate_options[0].ref;
  check("actual_unselected_host_shape", c.validFactHost(host));
  check("actual_selected_host_shape", c.validFactHost(selected));
  check("no_guessed_default", host.candidate === null && c.factCandidateSelectionMatches(host, b.scope.product_id, b.caller_id, b.issue_id, null));
  check("whole_actual_selected_ref", c.factCandidateSelectionMatches(selected, b.scope.product_id, b.caller_id, b.issue_id, choice));
  check("unselected_cannot_represent_selected_request", !c.factCandidateSelectionMatches(host, b.scope.product_id, b.caller_id, b.issue_id, choice));
  check("candidate_full_sha_drift_rejected", !c.factCandidateSelectionMatches(selected, b.scope.product_id, b.caller_id, b.issue_id, { ...choice, sha256: "0".repeat(64) }));
  check("both_negative_reviews_remain_disabled", !c.factCanPrepare(host, c.reviewOperation) && !c.factCanPrepare(selected, c.reviewOperation));
  check("saved_history_remains_available", host.history.length === 2 && selected.history.length === 2);
  result.status = "PASS_RECORDED_ACTUAL_RESPONSE_ADAPTER";
} catch (error) { result.status = "FAIL"; result.failure = error.message; process.exitCode = 1; }
finally { result.sources.tool = sha(fs.readFileSync(__filename)); fs.writeFileSync(out, JSON.stringify(result, null, 2) + "\n"); console.log(JSON.stringify({status:result.status, checks:result.checks.length, report:out})); }
