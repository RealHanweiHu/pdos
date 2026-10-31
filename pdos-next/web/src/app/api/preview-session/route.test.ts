import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { runInNewContext } from 'node:vm';
import { ModuleKind, ScriptTarget, transpileModule } from 'typescript';
import type { NextRequest } from 'next/server';
const compile=(p:string)=>transpileModule(readFileSync(p,'utf8'),{compilerOptions:{module:ModuleKind.CommonJS,target:ScriptTarget.ES2022}}).outputText;
const source=compile('src/app/api/preview-session/route.ts'), serverSource=compile('src/lib/local-preview-server.ts'), originSource=compile('src/lib/request-origin.ts');
function harness(options:{identity?:string;enabled?:boolean;expired?:boolean;api?:string;workspace?:boolean;brokenWorkspace?:boolean}={}) {
 const sets:unknown[][]=[],calls:string[]=[];
 const value={version:1,created_at:'2026-01-01T00:00:00Z',expires_at:options.expired?'2000-01-01T00:00:00Z':'2100-01-01T00:00:00Z',api_port:12345,workspace:options.workspace?{roleId:options.brokenWorkspace?'missing':'quality'}:undefined,cases:[{id:'trial',categoryId:'category-a',roleIds:['quality'],entries:[{id:'results',href:'/?area=work'}]}],roles:[{id:'quality',caseId:'trial',principalId:'person-a',tenantId:'tenant-a',token:'private-session-token'}]};
 const server={exports:{}},origin={exports:{}},route={exports:{}};
 runInNewContext(serverSource,{module:server,exports:server.exports,process:{env:{PDOS_NEXT_PREVIEW_CONFIG:options.enabled===false?undefined:'/private/fixture.json'}},require:(name:string)=>name==='server-only'?{}:{readFile:async()=>JSON.stringify(value)},Date,URLSearchParams});
 runInNewContext(originSource,{module:origin,exports:origin.exports,URL});
 runInNewContext(source,{module:route,exports:route.exports,URL,Response,Date,AbortSignal,process:{env:{PDOS_NEXT_API_URL:options.api??'http://127.0.0.1:12345'}},fetch:async(url:string)=>{calls.push(url);return Response.json({principal_id:options.identity??'person-a'});},require:(name:string)=>{
  if(name==='@/lib/local-preview-server')return server.exports;
  if(name==='@/lib/request-origin')return origin.exports;
  if(name==='next/headers')return {cookies:async()=>({set:(...args:unknown[])=>sets.push(args)})};
  throw new Error(name);
 }});
 async function send(body:unknown={caseId:'trial',roleId:'quality',entryId:'results'},host='localhost:3000',originValue=`http://${host}`){
  const request=new Request(`http://${host}/api/preview-session`,{method:'POST',headers:{host,origin:originValue},body:JSON.stringify(body)});
  Object.defineProperty(request,'nextUrl',{value:new URL(request.url)});
  return (route.exports as {POST:(r:NextRequest)=>Promise<Response>}).POST(request as NextRequest);
 }
 return {send,sets,calls,value,server:server.exports as {publicPreview:(v:unknown)=>unknown}};
}
test('allowlisted identity sets httpOnly session; response contains only destination',async()=>{
 const h=harness(),r=await h.send();assert.equal(r.status,200);assert.deepEqual(await r.json(),{href:'/?area=work'});assert.equal(h.sets.length,1);assert.equal(h.sets[0][0],'pdos-next-session');assert.equal((h.sets[0][2] as {httpOnly:boolean}).httpOnly,true);
});
test('cross-origin and non-loopback cannot sign in',async()=>{
 for(const [host,origin] of [['localhost:3000','https://other.invalid'],['example.com','http://example.com']]){const h=harness();assert.equal((await h.send(undefined,host,origin)).status,403);assert.equal(h.calls.length,0);assert.equal(h.sets.length,0);}
});
test('forged role, cross-case role and arbitrary redirect never authenticate',async()=>{
 for(const body of [{caseId:'trial',roleId:'other',entryId:'results'},{caseId:'other',roleId:'quality',entryId:'results'},{caseId:'trial',roleId:'quality',entryId:'https://other.invalid'}]){const h=harness();assert.equal((await h.send(body)).status,400);assert.equal(h.calls.length,0);}
});
test('wrong identity, disabled/expired catalog and external API leave cookies intact',async()=>{
 for(const [options,status] of [[{identity:'other'},409],[{enabled:false},404],[{expired:true},503],[{api:'https://example.com'},503]] as const){const h=harness(options);assert.equal((await h.send()).status,status);assert.equal(h.sets.length,0);}
});
test('page catalog never exposes tokens or private runtime fields',()=>{
 const h=harness(),data=JSON.stringify(h.server.publicPreview(h.value));assert.ok(!data.includes('private-session-token'));assert.ok(!data.includes('api_port'));
});
test('product preview opens the ordinary home with one server-selected identity',async()=>{
 const h=harness({workspace:true}),r=await h.send({mode:'workspace'});
 assert.equal(r.status,200);assert.deepEqual(await r.json(),{href:'/?area=work&category=category-a'});
 assert.equal(h.sets.length,1);assert.equal(h.sets[0][1],'private-session-token');
});
test('product preview cannot switch to a case, identity or caller destination',async()=>{
 for(const input of [{caseId:'trial',roleId:'quality',entryId:'results'},{mode:'workspace',roleId:'other'},{mode:'workspace',href:'/?area=category'},{mode:'other'}]){
  const h=harness({workspace:true}),r=await h.send(input);assert.equal(r.status,400);assert.equal(h.calls.length,0);assert.equal(h.sets.length,0);
 }
});
test('missing fixed persona fails closed instead of falling back to another case',async()=>{
 const h=harness({workspace:true,brokenWorkspace:true}),r=await h.send({mode:'workspace'});assert.equal(r.status,503);assert.equal(h.calls.length,0);assert.equal(h.sets.length,0);
});
