import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

// Local recorded HTTP JSON and the frozen frontend reader only. No database,
// service, browser, inference, POST, pure-test rerun or source modification.
const directory = path.dirname(fileURLToPath(import.meta.url));
const repository = path.resolve(directory, "../../../../..");
const web = path.join(repository, "pdos-next/web");
const inputPath = path.join(directory, "pg-http-response.json");
const readerPath = path.join(web, "src/lib/pai-sessions.ts");
const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");
const inputBytes = readFileSync(inputPath), readerBytes = readFileSync(readerPath);
const inputHash = sha256(inputBytes), readerHash = sha256(readerBytes);
assert.equal(readerHash, "d2e907edac089970b4a608500554f328afa38d36e91037cc82af62612dce7a36", "Use only the frozen reader candidate");
const require = createRequire(path.join(web, "package.json")), ts = require("typescript");
const compiled = { exports: {} };
runInNewContext(ts.transpileModule(readerBytes.toString("utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { module: compiled, exports: compiled.exports, URLSearchParams });
const bundle = JSON.parse(inputBytes.toString("utf8"));
const cases = [];
for (const kind of ["category", "personal"]) {
  const raw = bundle[kind], scope = {
    principalId: bundle.session.principal_id,
    categoryId: raw.list.scope.category_id,
    proposalId: raw.list.scope.proposal_id,
  };
  const sessionId = raw.runs.session.session_id;
  const root = scope.categoryId === null ? "v1/personal/agent-sessions" : `v1/categories/${scope.categoryId}/agent-sessions`;
  const query = new URLSearchParams({ page_size: "20" });
  if (scope.proposalId) query.set("proposal_id", scope.proposalId);
  const listPath = `${root}?${query}`, runsPath = `${root}/${sessionId}/runs?${query}`;
  const calls = [];
  const api = async (...args) => {
    assert.equal(args.length, 1, "No body: GET-only reader");
    const [resource] = args;
    calls.push(resource);
    if (resource === listPath) return structuredClone(raw.list);
    assert.equal(resource, runsPath, "Read only the explicitly selected Session");
    return structuredClone(raw.runs);
  };
  const list = await compiled.exports.readSessionList(api, scope);
  assert.equal(calls.length, 1, "Listing never deep-reads Run bodies or events");
  const selected = list.items.find(item => item.session_id === sessionId);
  assert.ok(selected, "Detail Session belongs to the real current list");
  const runs = await compiled.exports.readSessionRuns(api, scope, sessionId);
  assert.equal(calls.length, 2);
  assert.deepEqual(JSON.parse(JSON.stringify(list)), raw.list, "Retain exact Run goals, dates and metadata");
  assert.deepEqual(JSON.parse(JSON.stringify(runs)), raw.runs, "Retain exact chronology and persisted links");
  assert.equal(selected.run_count, runs.session.run_count);
  assert.equal(raw.chain.original.session_id, sessionId);
  assert.equal(raw.chain.continued.session_id, sessionId);
  assert.equal(raw.chain.continued.continued_from_id, raw.chain.original.run_id);
  assert.ok(runs.items.some(item => item.run_id === raw.chain.original.run_id));
  assert.ok(runs.items.some(item => item.run_id === raw.chain.continued.run_id));
  cases.push({
    kind, principal_id: list.principal_id, scope: list.scope,
    session_count: list.items.length,
    session_id: sessionId, session_revision: runs.session.revision,
    readable_run_count: runs.session.run_count,
    latest_run: { run_id: selected.latest_run.run_id, status: selected.latest_run.status },
    runs: runs.items.map(item => ({
      run_id: item.run_id, status: item.status, created_at: item.created_at,
      continued_from_id: item.continued_from_id, conversation: item.conversation,
    })),
    list_next_cursor: list.next_cursor, runs_next_cursor: runs.next_cursor,
    calls,
  });
}
const output = { version: "pai-sessions-dto-check/v1", status: "passed", cases };
const outputPath = path.join(directory, "dto-contract-check.json");
writeFileSync(outputPath, JSON.stringify(output, null, 2) + "\n");
const metadata = {
  status: "passed", checked_reads: 4, database_operations: false,
  source_modified: false, pure_tests_rerun: false,
  input: { path: path.relative(repository, inputPath), sha256: inputHash },
  reader: { path: path.relative(repository, readerPath), sha256: readerHash },
  script: { path: path.relative(repository, fileURLToPath(import.meta.url)), sha256: sha256(readFileSync(fileURLToPath(import.meta.url))) },
  output: { path: path.relative(repository, outputPath), sha256: sha256(readFileSync(outputPath)) },
  scope: "Frozen reader comparison against category/personal list+Run metadata in the actual HTTP/PG response bundle; does not claim the separate PG fixture failure passed.",
};
writeFileSync(path.join(directory, "dto-contract-check.metadata.json"), JSON.stringify(metadata, null, 2) + "\n");
process.stdout.write(JSON.stringify({ status: output.status, checked_reads: metadata.checked_reads, input_sha256: inputHash, reader_sha256: readerHash,
  cases: cases.map(item => ({ kind: item.kind, session_count: item.session_count, readable_run_count: item.readable_run_count, latest_status: item.latest_run.status })) }, null, 2) + "\n");
