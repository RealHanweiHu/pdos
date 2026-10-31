import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import Module from 'node:module';
import ts from 'typescript';
const cache = new Map();
function load(name) {
 if(cache.has(name)) return cache.get(name).exports;
 const loaded = new Module(name); cache.set(name,loaded);
 loaded.require = value => load(value.replace('./',''));
 loaded._compile(ts.transpileModule(readFileSync(new URL(`./${name}.ts`, import.meta.url), 'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,name);
 return loaded.exports;
}
const {candidateRows,reviseCandidateRows,candidateHumanEdits}=load('proposal-candidate-editor');
const {proposalDraftPatches}=load('proposal-spec-editor');
const command={operation:'proposal.create',payload:{title:'Original',brief:'Original brief',groups:{items:[{kind:'spec',content:{parameter:'Pressure',value_type:'number',value:'0.12345678901234567890',availability:'known',item_status:'ai_draft'},source_refs:[{id:'source',version:2}]}],questions:[{question:'Original question',owner_id:'owner',due_date:'2030-01-01',status:'open'}]}}};
test('candidate revisions retain sealed original, source versions, numeric precision and question grouping',()=>{
 const original=structuredClone(command),rows=candidateRows(command);
 const drafts={[rows[0].item_id]:{item:rows[0],values:{condition:'23 C'}},[rows[1].item_id]:{item:rows[1],values:{question:'Human question',owner_id:'peer'}}};
 const result=candidateHumanEdits(command,rows,drafts,'Human title','Human brief');
 assert.deepEqual(command,original);assert.equal(result.title,'Human title');assert.equal(result.groups.items[0].content.value,'0.12345678901234567890');
 assert.equal(result.groups.items[0].item_id,undefined);assert.equal(result.groups.questions[0].owner_id,'peer');assert.equal(result.groups.questions[0].question,'Human question');assert.deepEqual(result.groups.items[0].source_refs,original.payload.groups.items[0].source_refs);
});
test('patch candidates keep domain versions and existing removals, and newly added rows do not leak local ids',()=>{
 const c={operation:'proposal.item.patch',payload:{proposal_id:'proposal',ops:[{op:'upsert',item_id:'old',base_version:4,kind:'section',content:{key:'summary',text:'old'},source_refs:[]},{op:'remove',item_id:'gone',base_version:1,kind:'spec',content:{},source_refs:[]}]}};
 let rows=candidateRows(c);
 rows=reviseCandidateRows(rows,[{op:'upsert',kind:'spec',content:{parameter:'Power'},source_refs:[]}]);
 const result=candidateHumanEdits(c,rows,{},'','');
 assert.equal(result.ops[0].base_version,4);assert.equal(result.ops[1].item_id,undefined);assert.equal(result.ops[2].item_id,'gone');
 rows=reviseCandidateRows(rows,[{op:'remove',item_id:'old',base_version:4,kind:'section',content:{},source_refs:[]}]);
 assert.equal(candidateHumanEdits(c,rows,{},'','').ops.find(row=>row.item_id==='old').op,'remove');
 assert.throws(()=>reviseCandidateRows(rows,[{op:'remove',item_id:'old',base_version:4}]),/变化/);
});
test('bulk document edits are one version-bound batch and refuse protected responsibility changes',()=>{
 const spec={item_id:'spec',version:3,kind:'spec',content:{parameter:'P',value_type:'number',value:'1',availability:'known'},source_refs:[]};
 const question={item_id:'q',version:2,kind:'question',content:{question:'Question',owner_id:'owner',due_date:'2030-01-01',status:'open'},source_refs:[]};
 const result=proposalDraftPatches({spec:{item:spec,values:{first:'2'}},q:{item:question,values:{status:'answered',answer:'Yes'}}},[spec,question]);
 assert.equal(result.length,2);assert.equal(result[0].base_version,3);assert.equal(result[1].content.answer,'Yes');
 assert.throws(()=>proposalDraftPatches({q:{item:question,values:{owner_id:'peer'}}},[question]),/责任安排/);
 assert.throws(()=>proposalDraftPatches({spec:{item:spec,values:{first:'2'}}},[{...spec,version:4}]),/更新/);
});
