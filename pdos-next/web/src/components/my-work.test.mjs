import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Isolated component state harness. */
const reactShim = { ...React, useState(initial) {
  if (!hooks) return React.useState(initial);
  const own = hooks, index = own.index++;
  if (!(index in own.values)) own.values[index] = typeof initial === "function" ? initial() : initial;
  return [own.values[index], next => { own.values[index] = typeof next === "function" ? next(own.values[index]) : next; }];
}, useRef(initial) { if (!hooks) return React.useRef(initial); const index = hooks.index++; return hooks.values[index] ??= { current: initial }; }, useCallback(callback, dependencies) {
  if (!hooks) return React.useCallback(callback, dependencies);
  const index = hooks.index++;
  if (!same(hooks.values[index]?.dependencies, dependencies)) hooks.values[index] = { callback, dependencies };
  return hooks.values[index].callback;
}, useEffect(callback, dependencies) {
  if (!hooks) return React.useEffect(callback, dependencies);
  const own = hooks, index = own.index++;
  if (!same(own.values[index]?.dependencies, dependencies)) { const previous = own.values[index]; const entry = { dependencies, cleanup: previous?.cleanup }; own.values[index] = entry; own.effects.push(() => { entry.cleanup?.(); entry.cleanup = callback(); }); }
} };
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const cache = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? reactShim
    : specifier === "next/link" ? props => React.createElement("a", { href: props.href }, props.children)
    : specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { MyWork, taskPeriod } = load(path.join(directory, "my-work.tsx"));
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
const markup = tree => renderToStaticMarkup(tree);
const tick = () => new Promise(resolve => setImmediate(resolve));
function driver(props) {
  const state = { index: 0, values: [], effects: [] };
  return { render() { hooks = state; state.index = 0; state.effects = []; try { return MyWork(props); } finally { hooks = null; } }, mount() { state.effects.forEach(effect => effect()); }, setProps(next) { props = { ...props, ...next }; } };
}
const today = new Date(), localDay = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const day = offset => { const date = new Date(today); date.setDate(date.getDate() + offset); return localDay(date); };
const task = (id, due_date, owner_id = "me", status = "open") => ({ id, kind: "task", title: `任务${id}`, owner_id, due_date, status });
const entry = { category: { id: "cat", name: "合成品类" }, product: { id: "product", name: "合成型号" }, project: { id: "project", name: "合成项目" }, openItems: [task("今日", day(0)), task("逾期", day(-1)), task("稍后", day(9)), task("未定", null), task("他人", day(0), "other"), task("已完", day(0), "me", "done"), { ...task("风险", day(2)), kind: "risk", title: "合成风险" }], openItemsError: "" };
const waiting = { run_id: "waiting", goal: "需要答复的合成工作", status: "waiting_input", categoryId: "cat", categoryName: "合成品类", scope: "category", product_id: null, created_at: "2026-10-17T08:00:00Z" };
const completed = { ...waiting, run_id: "complete", goal: "已完成的合成工作", status: "completed" };
const g0Item = { proposal_id: "proposal", title: "合成G0提案", proposal_revision: 3, status: "in_review", category: { id: "cat", name: "合成品类" }, owner: { id: "owner", name: "合成负责人" }, reviewer_id: "me", submission: { id: "submission", revision: 2, submitted_at: "2026-10-17T09:00:00Z", document_digest: "fixed-digest" } };
const promiseItem = { id: "promise-record", recorded_at: "2026-10-17T09:00:00Z", category: { id: "cat", name: "合成品类" }, product: { id: "product", name: "合成型号" }, project: { id: "project", name: "合成项目" }, build: { id: "build", name: "合成承诺Build" }, request: { id: "request" }, run: { id: "test-run", revision: 2, status: "planned" }, promise: { occurred_at: "2026-10-17T00:00:00.160086Z", original_timezone: "Asia/Shanghai", effective_at: null }, actual_start: null, recipient: null, recipient_status: "not_recorded", timing: "awaiting_start", coverage: { sample_count: 2, item_count: 3, pair_count: 6 } };
function apiFixture({ fail = () => false, unavailable = 0, g0Fail = () => false, g0Items = [], promisesFail = () => false, promiseItems = [] } = {}) {
  const calls = [];
  return { calls, api: async (url, body) => { calls.push({ url, body }); if (fail()) throw new Error("合成读取失败"); if (url.startsWith("v1/personal/g0-reviews")) { if (g0Fail()) throw new Error("合成G0读取失败"); return { version: "personal-g0-reviews/v1", principal_id: "me", as_of: "2026-10-17T09:00:00Z", total_pending: g0Items.length, items: g0Items, next_cursor: null }; } if (url.startsWith("v1/personal/test-start-promises")) { if (promisesFail()) throw new Error("合成开测承诺读取失败"); return { version: "personal-test-start-promises/v1", principal_id: "me", as_of: "2026-10-17T09:00:00Z", total_records: promiseItems.length, items: promiseItems, next_cursor: null }; } return url.startsWith("v1/personal/projects") ? { items: [entry], next_cursor: null, unavailable_count: unavailable, as_of: "2026-10-17T09:00:00Z" } : { items: url.includes("waiting=true") ? [waiting] : [waiting, completed], next_cursor: null }; } };
}
const defaultProps = api => ({ api, session: { name: "合成人员", principal_id: "me" }, onOpenRun() {}, onOpenProject() {}, onOpenPai() {} });
const section = (tree, label) => elements(tree, element => element.props?.["aria-label"] === label)[0];

test("task periods keep overdue visible, use calendar weeks, and never invent a due date", () => {
  for (const date of ["2026-10-16", "2026-10-17"]) assert.equal(taskPeriod(date, "2026-10-17"), "today");
  assert.equal(taskPeriod("2026-10-18", "2026-10-17"), "week");
  assert.equal(taskPeriod("2026-10-19", "2026-10-17"), "later");
  assert.equal(taskPeriod("2026-10-19", "2026-10-18"), "later");
  assert.equal(taskPeriod("2026-10-25", "2026-10-19"), "week");
  assert.equal(taskPeriod(null, "2026-10-17"), "later");
});


const list = tree => elements(tree, item=>item.type?.name === "MyWorkList")[0];
const rows = tree => list(tree).props.rows;
test("one responsibility list combines real tasks, risks and paused conversations with exact navigation", async () => {
  const fixture=apiFixture(),opened=[],component=driver({...defaultProps(fixture.api),onOpenProject:(...args)=>opened.push(args),onOpenRun:(...args)=>opened.push(args)});
  component.render();component.mount();await tick();const tree=component.render(),items=rows(tree);
  assert.ok(items.some(item=>item.title==="合成风险"));assert.ok(items.some(item=>item.title==="任务今日"));
  assert.equal(items.some(item=>/任务他人|任务已完/.test(item.title)),false);
  const run=items.find(item=>item.kind==="pai");assert.equal(run.title,"需要答复的合成工作");
  list(tree).props.onOpenRun(run.target.runId,run.target.categoryId);
  const task=items.find(item=>item.title==="任务今日");list(tree).props.onOpenProject(task.target.categoryId,task.target.projectId);
  assert.deepEqual(opened,[["waiting","cat"],["cat","project"]]);
  assert.equal(elements(tree,item=>item.type?.name==="PersonalAttention" || item.type?.name==="PersonalProjectWorkQueue").length,0);
  assert.ok(fixture.calls.every(item=>item.body===undefined));assert.equal(fixture.calls.some(item=>item.url.startsWith("v1/personal/g0-reviews")),false);
});
test("recent project history remains private and is filtered against current authorized reads",async()=>{
 const previous=globalThis.localStorage,values=new Map([["pdos-next:my-work:recent-projects:me",JSON.stringify(["revoked","project"])],["pdos-next:my-work:recent-projects:other",'["other-project"]']]);
 globalThis.localStorage={getItem:key=>values.get(key)??null,setItem:(key,value)=>values.set(key,value)};
 try{const fixture=apiFixture(),opened=[],component=driver({...defaultProps(fixture.api),onOpenProject:(...args)=>opened.push(args)});component.render();component.mount();await tick();const recents=section(component.render(),"继续项目");assert.match(markup(recents),/合成项目/);assert.doesNotMatch(markup(recents),/revoked|other-project/);elements(recents,item=>item.type==="button")[0].props.onClick();assert.deepEqual(opened,[["cat","project"]]);assert.equal(values.get("pdos-next:my-work:recent-projects:other"),'["other-project"]');}finally{globalThis.localStorage=previous}
});
test("failed and partial reads expose uncertainty without erasing independently available work",async()=>{
 let fail=true;const fixture=apiFixture({fail:()=>fail}),component=driver(defaultProps(fixture.api));component.render();component.mount();await tick();let tree=component.render();assert.ok(list(tree).props.readings.some(item=>item.error.includes("合成读取失败")));
 fail=false;elements(tree,item=>item.props?.["aria-label"]==="刷新我的工作")[0].props.onClick();component.render();component.mount();await tick();assert.ok(rows(component.render()).some(item=>item.title==="任务今日"));
 const partial=driver(defaultProps(apiFixture({unavailable:1}).api));partial.render();partial.mount();await tick();assert.ok(list(partial.render()).props.readings.some(item=>item.error.includes("不可读")));
});
test("principal changes synchronously hide every previous private row before effects run",async()=>{
 const fixture=apiFixture({promiseItems:[promiseItem]}),component=driver(defaultProps(fixture.api));component.render();component.mount();await tick();assert.ok(rows(component.render()).length>0);
 component.setProps({session:{name:"另一人",principal_id:"other"}});const next=component.render();assert.deepEqual(rows(next),[]);assert.ok(list(next).props.readings.every(item=>item.loading));assert.doesNotMatch(markup(next),/合成项目|任务今日/);
});
test("commitments share one list while test-start recipient gaps and original times stay visible",async()=>{
 const fixture=apiFixture({promiseItems:[promiseItem]}),component=driver(defaultProps(fixture.api));component.render();component.mount();await tick();const active=component.render();assert.equal(rows(active).some(item=>item.kind==="test"),false);
 elements(section(active,"我的工作视图"),item=>item.type==="button"&&item.props.children==="承诺")[0].props.onClick();const tree=component.render(),items=rows(tree);assert.equal(items.length,1);assert.equal(items[0].kind,"test");assert.match(JSON.stringify(items[0].facts),/Asia\/Shanghai|Asia\\\/Shanghai/);assert.match(JSON.stringify(items[0].facts),/尚未记录|配对 6/);assert.match(items[0].target.href,/project=project/);
});
test("a test-start read failure does not erase tasks or paused conversations",async()=>{
 const component=driver(defaultProps(apiFixture({promisesFail:()=>true}).api));component.render();component.mount();await tick();const active=component.render();assert.ok(rows(active).some(item=>item.kind==="pai"));assert.ok(rows(active).some(item=>item.kind==="task"));
 elements(section(active,"我的工作视图"),item=>item.type==="button"&&item.props.children==="承诺")[0].props.onClick();assert.ok(list(component.render()).props.readings.some(item=>item.error.includes("合成开测承诺读取失败")));
});
const workItems=load(path.join(webRoot,"src/lib/my-work-items.ts"));
test("task attention deduplicates the same task, never its independent commitment or a similarly named task",()=>{
 const task={id:"task",task:{id:"task",title:"同名工作",state:"assigned",revision:2},category:{id:"cat",name:"品类"},project:{id:"project",name:"项目"},assignee:null,recipient:null,commitment:{id:"promise",promised_at:"2026-10-25T01:00:00Z",original_timezone:"America/Los_Angeles",outcome_keys:["proof"]},timing:"pending"};
 const attention={id:"task:task",kind:"task",queue:"receive",source:{id:"task"},details:{},category:task.category,project:task.project,title:task.task.title,state:"assigned",reason:"本人承接",responsible:{name:"本人"},due_at:null,valid_until:null,target:"project"};
 const combined=workItems.responsibilityRows([attention],[task,{...task,id:"other",task:{...task.task,id:"other"}}],[],[]);assert.equal(combined.length,2);assert.equal(combined.filter(item=>item.kind==="receive").length,1);
 const promises=workItems.commitmentRows([task],[]);assert.equal(promises.length,1);assert.equal(promises[0].due,"2026-10-24");assert.match(JSON.stringify(promises[0].facts),/不代替承诺履行结论/);
 assert.equal(workItems.workDate(null),null);assert.equal(workItems.workDate("2026-10-25","America/Los_Angeles"),"2026-10-25");
});
const {MyWorkList}=load(path.join(directory,"my-work-list.tsx"));
test("list filters only local records, preserves scope navigation and offers all outstanding pages",async()=>{
 const row={id:"one",title:"压力验证",project:"项目甲",kind:"task",state:"进行中",due:day(9),dateKind:"期限",facts:[],target:{categoryId:"cat",projectId:"project"}},opened=[],pages=[];
 const props={rows:[row,{...row,id:"two",title:"噪声",kind:"risk",due:day(-1)}],readings:[{name:"任务",more:true,loading:false,error:"",retry(){},loadMore:async()=>pages.push("tasks")},{name:"风险",more:true,loading:false,error:"",retry(){},loadMore:async()=>pages.push("risk")}],onOpenProject:(...args)=>opened.push(args),onOpenRun(){}};
 const state={index:0,values:[],effects:[]};const render=()=>{hooks=state;state.index=0;try{return MyWorkList(props)}finally{hooks=null}};let tree=render();
 elements(tree,item=>item.props?.["aria-label"]==="工作期限")[0].props.onChange({target:{value:"later"}});tree=render();assert.match(markup(tree),/压力验证/);assert.doesNotMatch(markup(tree),/>噪声</);
 elements(tree,item=>item.props?.children==="进入项目办理")[0].props.onClick();assert.deepEqual(opened,[["cat","project"]]);
 elements(tree,item=>item.props?.children==="加载更多工作")[0].props.onClick();await tick();assert.deepEqual(pages,["tasks","risk"]);
 elements(tree,item=>item.props?.["aria-label"]==="搜索我的工作")[0].props.onChange({target:{value:"未匹配"}});assert.match(markup(render()),/部分资料尚未取得/);
});
