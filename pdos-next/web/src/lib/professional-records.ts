import { projectBuildsPath } from "./project-build-scope";

export type ProfessionalTarget = { build?: string; request?: string; run?: string; issue?: string; change?: string; feedback?: string; publication?: string };
export type ProfessionalRecord = { id: string; title: string; kind: string; revision: number; status: string; source: string; historical: boolean; at: string; target: ProfessionalTarget; facts: [string, string][] };
export type ProfessionalReading = { rows: ProfessionalRecord[]; incomplete: boolean; unavailable: number; nextCursor: string | null };
export type ProfessionalApi = <T>(path: string, body?: unknown) => Promise<T>;
type Row = Record<string, unknown>;
const object = (v: unknown): v is Row => !!v && typeof v === "object" && !Array.isArray(v);
const value = (v: unknown) => typeof v === "string" || typeof v === "number" ? String(v) : "";
const nested = (r: Row, key: string): Row => object(r[key]) ? r[key] : {};
const states: Record<string, string> = { observed:"已登记实物", identified:"已登记身份", executing:"执行中", scheduled:"已排期", reported:"结果已返回", applicable:"适用", implementing:"实施中", review:"待专业决定", verifying:"待复验", draft:"草稿", active:"有效", planned:"已固定计划", running:"已开测", results_pending:"待复核", reviewed:"已复核", disposed:"已处置", recorded:"已登记", approved:"已批准", returned:"已退回", withdrawn:"已撤回", accepted:"已接收", offered:"已提出交接", open:"待处理", closed:"已关闭", ready:"条件具备", blocked:"有阻塞", unknown:"待核对", current:"当前有效", READY:"条件具备", READY_WITH_CONDITIONS:"有条件具备", BLOCKED:"有阻塞", UNKNOWN:"待核对", pass:"固定范围通过", fail:"固定范围未通过", indeterminate:"缺项待核对", published:"资料已发布", pending:"尚未形成判定", invalid:"已登记无效", triaged:"已具名分诊", actioning:"措施办理中", awaiting_verification:"待有效性复核", analysis:"影响核对中", rejected:"已拒绝", prepared:"已准备", completed:"已完成登记" };
const fields: Record<string,string> = { description:"记录说明", result:"固定范围结果", purpose:"用途", reason:"办理说明", planned_quantity:"计划数量", observed_unit_count:"实际数量", unit_count:"样件数量", unit:"单位", location:"地点", destination:"去向", custodian_label:"保管人", expected_at:"期望时点", occurred_at:"实际发生", planned_start:"计划开始", planned_end:"计划结束", verification_objectives:"验证目标", disposition_plan:"处置要求", action:"决定", role:"专业", valid_until:"有效至", summary:"摘要", phenomenon:"现场现象", title:"标题" };

export const recordPanels = new Set(["start","execution","supply","cost","verification","professional","handoff","launch","results","quality","followup","changes","field","publication"]);
export const buildRecordPanels = new Set(["start","execution","supply","cost","verification","professional","handoff","launch","results","quality","followup"]);
export async function readProfessionalBuilds(api: ProfessionalApi, productId: string, projectId: string) {
  const data = await api<unknown>(projectBuildsPath(productId,projectId));
  if (!object(data) || !Array.isArray(data.items) || data.items.some(r=>!object(r)||typeof r.id!=="string"||r.project_id!==projectId||typeof r.name!=="string")) throw new Error("项目轮次范围不完整，请重新读取。");
  return { items:data.items as (Row & {id:string;name:string})[], incomplete:data.has_more===true, unavailable:Number(data.unavailable_count)||0 };
}

/** This is a presentation projection of existing authorized reads, never an approval. */
export async function readProfessionalRecords(api: ProfessionalApi, productId:string, projectId:string, panel:string, build="", cursor:string|null=null):Promise<ProfessionalReading> {
  const base=`v1/products/${productId}/`;
  const byBuild=`?build_id=${encodeURIComponent(build)}`, byProject=`?project_id=${encodeURIComponent(projectId)}`;
  const configs:Record<string,[string,[string,string][]]>={
    start:["build-start",[["assessments","开工条件核对"],["authorizations","具名开工决定"],["starts","实际开工"]]],
    execution:["build-execution",[["actual_configurations","实际配置"],["lots","批次"],["samples","样件"]]],
    supply:["supply",[["snapshots","供给快照"],["kits","齐套核对"]]],
    cost:["costs",[["inputs","成本输入"],["estimates","成本估算"]]],
    verification:["verification",[["preparations","验证准备"]]],
    professional:["verification-professional",[["requests","验证请求"]]],
    handoff:[`verification-handoff${byBuild}`,[["requests","验证请求"],["handoffs","交样与接收"]]],
    launch:[`verification-launch${byBuild}`,[["runs","测试运行"]]],
    results:[`verification-results${byBuild}`,[["runs","测试运行"]]],
    quality:[`quality-execution${byBuild}`,[["issues","问题"]]],
    followup:[`quality-execution${byBuild}`,[["issues","问题与后续措施"]]],
    changes:[`change-execution${byProject}`,[["changes","变更"]]],
    field:[`field-feedback${byProject}`,[["feedbacks","现场反馈"]]],
    publication:[`manufacturing-publications${byProject}`,[["versions","制造发布"]]],
  };
  const config=configs[panel];
  if (!config || (buildRecordPanels.has(panel)&&!build)) return {rows:[],incomplete:false,unavailable:0,nextCursor:null};
  const path=base+config[0];
  const raw=await api<unknown>(path+(cursor?`${path.includes("?")?"&":"?"}history_cursor=${encodeURIComponent(cursor)}`:""));
  if (!object(raw)) throw new Error("专业记录读取不完整，请重试。");
  const requests=Array.isArray(raw.requests)?raw.requests.filter(object):[];
  const rows:ProfessionalRecord[]=[];
  for(const [key,kind] of config[1]) {
    if(!Array.isArray(raw[key])) throw new Error("专业记录缺少必要内容，请重试。");
    for(const row of raw[key]) {
      if(!object(row)||typeof row.id!=="string") throw new Error("专业记录身份不完整，请重试。");
      const request=requests.find(r=>r.request_id===row.request_id && r.revision===row.request_revision) ?? requests.find(r=>r.request_id===row.request_id && r.is_current===true) ?? requests.find(r=>r.request_id===row.request_id);
      const body=panel==="changes"?nested(row,"request"):panel==="quality"||panel==="followup"?nested(row,"issue"):row;
      const boundBuild=value(row.build_id)||value(nested(row,"build").id)||value(nested(row,"binding").build_id)||value(request&&nested(request,"build").id);
      const boundProject=value(row.project_id)||value(nested(row,"build").project_id)||value(request?.project_id);
      // Product-wide readers are narrowed to a verified project Build. Scoped readers
      // also retain server scope; a conflicting identity always fails closed.
      if(boundProject&&boundProject!==projectId) continue;
      if(buildRecordPanels.has(panel) && (boundBuild ? boundBuild!==build : !config[0].includes("?build_id="))) continue;
      const title=value(row.title)||value(body.title)||value(row.name)||value(row.lot_label)||value(row.label)||value(request?.title)||value(nested(nested(nested(row,"body"),"baseline_snapshot"),"input").title)||kind;
      const status=value(row.status)||value(nested(row,"result").overall)||value(row.result);
      const target={...(boundBuild||build?{build:boundBuild||build}:{}),...(typeof row.request_id==="string"?{request:row.request_id}:{}),...(typeof row.run_id==="string"?{run:row.run_id}:{}),...(typeof row.issue_id==="string"?{issue:row.issue_id}:{}),...(typeof row.change_id==="string"?{change:row.change_id}:{}),...(panel==="field"?{feedback:row.id}:{}),...(panel==="publication"?{publication:row.id}:{})};
      rows.push({id:row.id,title,kind,revision:Number(row.revision)||0,status:states[status]??(status?"状态需核对":"已登记"),source:row.freshness==="requires_recalculation"?"依据需重算":row.source_status==="current"?"依据当前":row.source_status==="needs_recheck"?"依据需重核":"依据状态待核对",historical:row.is_current===false||row.current===false||row.freshness==="historical",at:value(row.created_at)||value(row.captured_at)||value(row.received_at),target,facts:Object.entries(fields).flatMap(([key,label])=>value(body[key])?[[label,states[value(body[key])]??value(body[key])] as [string,string]]:[])});
    }
  }
  const nextCursor=value(nested(raw,"history_page").next_cursor)||null;
  if(cursor&&nextCursor===cursor) throw new Error("历史记录分页未能继续，请刷新后重试。");
  return {rows,incomplete:raw.has_more===true,unavailable:Number(raw.unavailable_count)||0,nextCursor};
}
