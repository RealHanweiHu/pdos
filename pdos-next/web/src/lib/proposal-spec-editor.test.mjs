import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import Module from 'node:module';
import ts from 'typescript';
const compiled = new Module(import.meta.url);
compiled._compile(ts.transpileModule(readFileSync(new URL('./proposal-spec-editor.ts', import.meta.url), 'utf8'), { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, 'proposal-spec-editor.ts');
const { newSpecPatches, editedSpecContent, specUsesBounds } = compiled.exports;
test('batch selection retains dictionary versions and never duplicates or migrates an existing reference', () => {
 const parameter = { parameter_id:'pressure', version:3, key:'pressure', name:'压力', value_type:'number', unit:'kPa', standard_condition:'23 C' };
 const old = { kind:'spec', content:{parameter_id:'pressure',parameter_version:1} };
 assert.deepEqual(newSpecPatches([parameter], [old]), []);
 const ops = newSpecPatches([parameter, parameter], []);
 assert.equal(ops.length,1);assert.equal(ops[0].content.parameter_version,3);assert.equal(ops[0].content.availability,'unknown');assert.equal(ops[0].content.value,null);assert.deepEqual(ops[0].source_refs,[]);
});
test('condition-only edits preserve number lower/upper bounds, precision and not-applicable semantics', () => {
 for(const shape of [{value:'0.12345678901234567890',lower:null,upper:null},{value:null,lower:'5',upper:null},{value:null,lower:null,upper:'10'},{value:null,lower:'1',upper:'2'}]) {
  const content={value_type:'number',...shape,text_value:null,availability:'known',condition_note:'old'};
  const result=editedSpecContent(content,String(content.value??content.lower??''),String(content.upper??''),'new');
  assert.deepEqual(result,{...content,condition_note:'new'});
 }
 const na={value_type:'number',value:null,lower:null,upper:null,availability:'not_applicable'};
 assert.equal(editedSpecContent(na,'','','new').availability,'not_applicable');
});
test('editing a numeric bound retains its bound shape and empty confirmed targets become unknown', () => {
 const bounded={value_type:'number',value:null,lower:null,upper:'10',availability:'known',item_status:'confirmed'};
 assert.equal(specUsesBounds(bounded),true);
 assert.deepEqual(editedSpecContent(bounded,'','12',''),{...bounded,upper:'12',text_value:null,condition_note:null});
 const cleared=editedSpecContent(bounded,'','','');assert.equal(cleared.availability,'unknown');assert.equal(cleared.item_status,'unknown');assert.equal(cleared.value,null);
});
