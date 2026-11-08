import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const dependency = createRequire(path.join(directory, "../../../package.json"));
const ts = dependency("typescript");
const filename = path.join(directory, "lib/export-download.ts");
const loaded = new Module(filename);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const { exportHref, filenameFrom, exportSummary, readExport } = loaded.exports;
const c = "11111111-1111-4111-8111-111111111111", p = "22222222-2222-4222-8222-222222222222", id = "33333333-3333-4333-8333-333333333333";
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";

test("export links name one real scope and stay disabled without it", () => {
  assert.equal(exportHref("project", { categoryId: c, productId: p }, id), `/api/v1/categories/${c}/products/${p}/exports/project?project_id=${id}`);
  assert.equal(exportHref("bom-diff", { categoryId: c, productId: p }, id).endsWith(`/exports/bom-diff?bom_id=${id}`), true);
  assert.equal(exportHref("test-summary", { categoryId: c, productId: p }, id).endsWith(`/exports/test-summary?build_id=${id}`), true);
  assert.equal(exportHref("my-work"), "/api/v1/personal/exports/my-work");
  assert.equal(exportHref("project", { categoryId: c, productId: p }, ""), null);
  assert.equal(exportHref("project", { categoryId: "x", productId: p }, id), null);
});

test("file name comes from the server and summary states AI labels", () => {
  assert.equal(filenameFrom(`attachment; filename*=UTF-8''${encodeURIComponent("项目-P1-20261108.xlsx")}`), "项目-P1-20261108.xlsx");
  assert.equal(filenameFrom(`attachment; filename*=UTF-8''${encodeURIComponent("../../etc/passwd")}`), "导出.xlsx");
  assert.equal(filenameFrom(null), "导出.xlsx");
  assert.equal(exportSummary({ rows: 5, aiRows: 0, aiCells: 0 }), "已导出 5 行，不含 AI 起草内容。");
  assert.equal(exportSummary({ rows: 5, aiRows: 1, aiCells: 3 }), "已导出 5 行，其中 1 行 AI 起草、3 个 AI 起草单元格，文件内已逐条标注。");
});

test("errors keep the server message and never hand a JSON body over as a file", async () => {
  const denied = async () => Response.json({ code: "FORBIDDEN_SCOPE", message: "项目不存在或不在当前受众内。" }, { status: 403 });
  await assert.rejects(readExport(denied, "/x"), /项目不存在或不在当前受众内/);
  await assert.rejects(readExport(async () => { throw new TypeError("offline"); }, "/x"), /暂未连上服务/);
  await assert.rejects(readExport(async () => Response.json({}, { status: 200 }), "/x"), /导出未完成/);
  const ok = await readExport(async () => new Response(new Uint8Array([1]), { headers: { "Content-Type": XLSX, "Content-Disposition": "attachment; filename*=UTF-8''a.xlsx", "X-PDOS-Export-Rows": "2", "X-PDOS-Export-AI-Rows": "1" } }), "/x");
  assert.equal(ok.filename, "a.xlsx");
  assert.deepEqual([ok.rows, ok.aiRows, ok.aiCells], [2, 1, null]);
});
