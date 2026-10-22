// Recorded script: executed from pdos-next/web using node --input-type=module.
// Replay from that directory with: node --input-type=module < ../../docs/reports/evidence/pdos-next-ui-20261017/project-builds/dto-contract-check.mjs
// This file was saved after the successful run; saving it did not repeat that run.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { runInNewContext } from 'node:vm';
const require = createRequire(import.meta.url), ts = require('typescript');
const raw = JSON.parse(readFileSync('../../docs/reports/evidence/pdos-next-ui-20261017/project-builds/pg-http-response.json','utf8'));
const compiled = {exports:{}};
runInNewContext(ts.transpileModule(readFileSync('src/lib/project-build-summary.ts','utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{module:compiled,exports:compiled.exports,URLSearchParams});
const scope={categoryId:raw.scope.category_id,productId:raw.scope.product_id,projectId:raw.scope.project_id};
const base=`v1/categories/${scope.categoryId}/products/${scope.productId}`;
const rows=[];
for(const stage of raw.result_stages){
 const calls=[];
 const api=async(path,...body)=>{
  assert.equal(body.length,0);
  calls.push(path);
  if(path===`${base}/builds?project_id=${scope.projectId}`) return structuredClone(raw.builds);
  assert.equal(path,`${base}/verification-results?build_id=${raw.scope.build_id}`);
  return structuredClone(stage.results);
 };
 const list=await compiled.exports.readProjectBuilds(api,scope);
 const selected=list.items.find(item=>item.id===raw.scope.build_id);
 assert.ok(selected);
 assert.ok(list.items.every(item=>item.project_id===scope.projectId));
 assert.equal(calls.length,1);
 const summary=await compiled.exports.readBuildTestSummary(api,scope,selected);
 assert.equal(calls.length,3);
 const run=summary.runs.find(item=>item.runId===raw.scope.run_id);
 assert.ok(run);
 assert.equal(run.requestRevision,run.runSnapshot.request_revision);
 assert.equal(run.request.id,raw.scope.request_id);
 assert.equal(summary.build.id,raw.scope.build_id);
 for(const m of run.runSnapshot.measurements){
  const original=stage.results.runs.find(row=>row.id===run.versionId).run_snapshot.measurements.find(row=>row.id===m.id);
  assert.equal(m.raw_value,original.raw_value);
  assert.equal(m.observed_at,original.observed_at);
 }
 rows.push({stage:stage.stage,projectId:summary.build.project_id,buildId:summary.build.id,buildRevision:summary.build.revision,projectFixedRevision:summary.build.project_revision,plannedQuantity:summary.build.planned_quantity,runRevision:run.revision,fixedRequestRevision:run.requestRevision,currentRequestRevision:run.request.revision,currentProjection:run.currentProjection?{revision:run.currentProjection.revision,runRevision:run.currentProjection.runRevision,result:run.currentProjection.result}:null,coverage:run.coverage,rawValues:run.runSnapshot.measurements.map(m=>m.raw_value),unavailableCount:summary.unavailableCount,hasMore:summary.hasMore,unindexedRunCount:summary.unindexedRunCount});
}
process.stdout.write(JSON.stringify({stages:rows.length,scope,rows},null,2)+'\n');
