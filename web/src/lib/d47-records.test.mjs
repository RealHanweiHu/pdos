import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { createHash } from "node:crypto";

const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(path.join(directory, "../../package.json")), ts = dependency("typescript");
const filename = path.join(directory, "d47-records.ts"), loaded = new Module(filename);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const { exactSource, isoFromLocal, splitLines, scopeNames, trialParameters, trialCavities } = loaded.exports;

test("an exact source names the line and the digest of its text", async () => {
  const ref = await exactSource({ id: "a1", revision: 2, content: "first\nSynthetic signed sheet\nlast" }, 2);
  assert.equal(ref.kind, "artifact");
  assert.equal(ref.position, `line:2;quote_sha256:${createHash("sha256").update("Synthetic signed sheet").digest("hex")}`);
  await assert.rejects(exactSource({ id: "a1", revision: 1, content: "only" }, 3));
});

test("dates, lists and the five acceptance scopes", () => {
  assert.equal(isoFromLocal(""), null);
  assert.throws(() => isoFromLocal("not a date"));
  assert.deepEqual(splitLines(" a \n\n b"), ["a", "b"]);
  assert.deepEqual(Object.keys(scopeNames), ["appearance", "dimensions", "performance", "packaging_labeling", "certification_docs"]);
});

test("tool-trial parameters and cavities parse or refuse clearly", () => {
  assert.deepEqual(trialParameters("保压 = 60 MPa\n\n模温=80"), [{ name: "保压", value: "60", unit: "MPa" }, { name: "模温", value: "80", unit: null }]);
  assert.throws(() => trialParameters("没有等号"));
  assert.throws(() => trialParameters("= 60"));
  assert.deepEqual(trialCavities("1, 2，3 4"), [1, 2, 3, 4]);
  assert.deepEqual(trialCavities(""), []);
  assert.throws(() => trialCavities("1, 0"));
  assert.throws(() => trialCavities("A"));
});
