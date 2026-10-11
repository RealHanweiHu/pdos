import { cookies } from "next/headers";
import { NextRequest } from "next/server";
import { sameOrigin } from "@/lib/request-origin";
import { candidateTransportOptions } from "@/lib/candidate-transport";

const paths = /^(?:v1\/(?:session|products|commands(?:\/preview)?)|v1\/products\/[a-f0-9-]+\/(?:workspace|definitions|projects|configurations|builds|supply|supply-captures|costs|cost-captures|verification|verification-professional|verification-handoff|verification-launch(?:\/inputs)?|verification-results(?:\/(?:inputs|captures))?|sample-handoff|build-start(?:\/assessment-inputs)?|build-execution(?:\/compare)?|model-calls|variants(?:\/[a-f0-9-]+\/compare)?|original-lifecycle(?:\/[a-f0-9-]+\/candidate|\/intents\/[a-f0-9-]+\/reconcile)?|originals(?:\/[a-f0-9-]+\/(?:download|scan))?|receipts\/[a-f0-9-]+\/revert-preview))$/;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const agentPaths = /^v1\/agent-runs(?:\/[a-f0-9-]{36}(?:\/(?:events|answers|cancel|calls\/[a-f0-9-]{36}\/recover))?)?$/i;
const personalAgentPaths = /^v1\/personal\/agent-runs(?:\/[a-f0-9-]{36}(?:\/(?:events|answers|cancel|calls\/[a-f0-9-]{36}\/recover))?)?$/i;
const preprojectPaths = /^v1\/(?:proposals(?:\/[a-f0-9-]{36}(?:\/(?:items|participants))?)?|g0-definitions\/[a-f0-9-]{36}|projects\/[a-f0-9-]{36}\/open-items)$/i;
const proposalViewPaths = /^v1\/views\/(?:positioning|spec-benchmark|feature-config|definition-maturity)$/;
const resourceInspectPaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/builds\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/resources\/inspect$/;
const manufacturingPreparationPaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/manufacturing-preparations(?:\/inputs|\/(?:work_instruction|control_plan|manufacturing_baseline)\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})?$/;
const manufacturingPreparationCommands = new Set(["npi.work_instruction.record", "npi.control_plan.record", "npi.manufacturing_baseline.record"]);
const qualityChangePaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/(?:quality-execution(?:\/inputs)?|change-execution(?:\/(?:inputs|captures))?)$/;
const qualityFollowupPaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/quality-followup(?:\/inputs)?$/;
const capaCandidatePaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/capa-candidates$/;
const capaFactPaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/capa-facts(?:\/inputs)?$/;
const capaFactCommands = new Set(["quality.capa.observation.record", "quality.capa.verification.review"]);
const qualityFollowupCommands = new Set(["quality.issue.root_cause.decide", "quality.capa.actions.complete", "quality.capa.followup.link", "quality.capa.verification.candidate.record"]);
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const positiveRevision = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0 && value <= 2147483647;
function validFollowupCommand(value: unknown, productId: string, operations = qualityFollowupCommands): boolean {
  if (!isRecord(value) || Object.keys(value).some(key => !["command_id", "idempotency_key", "operation", "category_id", "product_id", "expected_revision", "payload", "source_read_set"].includes(key)) || typeof value.command_id !== "string" || !uuid.test(value.command_id) || typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160 || typeof value.operation !== "string" || !operations.has(value.operation) || typeof value.product_id !== "string" || !uuid.test(value.product_id) || value.product_id.toLowerCase() !== productId.toLowerCase() || !positiveRevision(value.expected_revision) || !isRecord(value.payload) || typeof value.payload.issue_id !== "string" || !uuid.test(value.payload.issue_id) || !positiveRevision(value.payload.expected_issue_revision) || !Array.isArray(value.source_read_set) || value.source_read_set.length < 1) return false;
  const seen = new Set<string>();
  for (const read of value.source_read_set) {
    if (!isRecord(read) || Object.keys(read).some(key => !["artifact_id", "expected_revision"].includes(key)) || typeof read.artifact_id !== "string" || !uuid.test(read.artifact_id) || !positiveRevision(read.expected_revision) || seen.has(read.artifact_id.toLowerCase())) return false;
    seen.add(read.artifact_id.toLowerCase());
  }
  // The host derives and checks completeness/ACL/currentness; never reconstruct this read set.
  return true;
}
function validManufacturingCommand(value: unknown, productId: string): boolean {
  if (!isRecord(value) || Object.keys(value).some(key => !["command_id", "idempotency_key", "operation", "category_id", "product_id", "expected_revision", "payload", "source_read_set"].includes(key)) || typeof value.command_id !== "string" || !uuid.test(value.command_id) || typeof value.idempotency_key !== "string" || !uuid.test(value.idempotency_key) || typeof value.operation !== "string" || !manufacturingPreparationCommands.has(value.operation) || typeof value.product_id !== "string" || !uuid.test(value.product_id) || value.product_id.toLowerCase() !== productId.toLowerCase() || !positiveRevision(value.expected_revision) || !isRecord(value.payload) || typeof value.payload.project_id !== "string" || !uuid.test(value.payload.project_id) || !isRecord(value.payload.process) || typeof value.payload.process.id !== "string" || !uuid.test(value.payload.process.id) || !positiveRevision(value.payload.process.revision) || !Array.isArray(value.source_read_set) || value.source_read_set.length < 1) return false;
  const seen = new Set<string>();
  for (const read of value.source_read_set) {
    if (!isRecord(read) || Object.keys(read).some(key => !["artifact_id", "expected_revision"].includes(key)) || typeof read.artifact_id !== "string" || !uuid.test(read.artifact_id) || !positiveRevision(read.expected_revision) || seen.has(read.artifact_id.toLowerCase())) return false;
    seen.add(read.artifact_id.toLowerCase());
  }
  return true; // The actual strict domain DTO and owner evaluate complete sources and qualification.
}
const longCommands = new Set([
  ...manufacturingPreparationCommands,
  ...qualityFollowupCommands,
  ...capaFactCommands,
  "test.results.import", "test.result.compute", "test.run.review", "test.disposition.decide",
  "quality.issue.create", "quality.issue.merge", "quality.issue.triage",
  "quality.issue.containment.record", "quality.capa.draft", "change.request.create", "change.impact.compute",
]);

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path: forwardPath } = await context.params;
  const categoryId = forwardPath[0] === "v1" && forwardPath[1] === "categories" && uuid.test(forwardPath[2] ?? "") ? forwardPath[2] : undefined;
  const categoryRoot = forwardPath.join("/") === "v1/categories";
  const categoryPreview = forwardPath.join("/") === "v1/categories/preview";
  const categorySeed = /^v1\/category-seeds\/(?:auto-tire-inflator|bicycle-pump)$/.test(forwardPath.join("/"));
  const personalAgent = personalAgentPaths.test(forwardPath.join("/"));
  const categoryMembers = categoryId && forwardPath.length === 4 && forwardPath[3] === "members";
  if (!categoryId && !categoryRoot && !categoryPreview && !categorySeed && !personalAgent && forwardPath.join("/") !== "v1/session") return Response.json({ code: "NOT_FOUND", message: "此入口不可用。" }, { status: 404 });
  const path = categoryId ? ["v1", ...forwardPath.slice(3)] : forwardPath;
  const pathname = path.join("/");
  const resourceInspect = resourceInspectPaths.test(pathname);
  const preproject = preprojectPaths.test(pathname);
  const proposalView = proposalViewPaths.test(pathname);
  const agent = agentPaths.test(pathname) || personalAgent;
  const modelConfiguration = pathname === "v1/model-configuration";
  const qualityChange = qualityChangePaths.test(pathname);
  const manufacturingPreparation = manufacturingPreparationPaths.test(pathname);
  const factPath = capaFactPaths.test(pathname);
  const qualityFollowup = qualityFollowupPaths.test(pathname) || capaCandidatePaths.test(pathname) || factPath;
  if (!categoryRoot && !categoryPreview && !categorySeed && !categoryMembers && !paths.test(pathname) && !qualityChange && !qualityFollowup && !manufacturingPreparation && !resourceInspect && !preproject && !proposalView && !agent && !modelConfiguration) return Response.json({ code: "NOT_FOUND", message: "此入口不可用。" }, { status: 404 });
  const query = new URLSearchParams();
  if (categoryPreview || categorySeed || categoryRoot) {
    const allowed = categoryRoot ? ["GET", "POST"] : categorySeed ? ["GET"] : ["POST"];
    if (!allowed.includes(request.method)) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405 });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "品类入口不接受额外查询条件。" }, { status: 422 });
  } else if (modelConfiguration) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405 });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "模型设置不接受额外查询条件。" }, { status: 422 });
  } else if (agent) {
    const agentPath = personalAgent ? ["v1", ...path.slice(2)] : path;
    if ((agentPath[2] && !uuid.test(agentPath[2])) || (agentPath[3] === "calls" && !uuid.test(agentPath[4] ?? ""))) return Response.json({ code: "VALIDATION_FAILED", message: "运行或调用编号无效。" }, { status: 422 });
    const collection = agentPath.length === 2;
    const create = collection && request.method === "POST";
    const action = /\/(?:answers|cancel|recover)$/.test(pathname);
    const method = create || action ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405 });
    for (const [key, value] of request.nextUrl.searchParams) {
      const events = pathname.endsWith("/events");
      const valid = method === "GET" && (events || collection) && (key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 200 : key === "cursor" ? collection && uuid.test(value) : key === "after" && events && /^\d+$/.test(value) && Number.isSafeInteger(Number(value)));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "运行分页条件无效。" }, { status: 422 });
      query.set(key, value);
    }
  } else if (proposalView) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405, headers: { Allow: "GET" } });
    const proposalIds = request.nextUrl.searchParams.getAll("proposal_id");
    if (proposalIds.length !== 1 || !uuid.test(proposalIds[0])) return Response.json({ code: "VALIDATION_FAILED", message: "请选择一个有效提案。" }, { status: 422 });
    for (const [key, value] of request.nextUrl.searchParams) {
      if (!["proposal_id", "parameter_ids"].includes(key) || !uuid.test(value)) return Response.json({ code: "VALIDATION_FAILED", message: "请仅提供提案与有效参数编号。" }, { status: 422 });
      // Preserve every parameter occurrence and its order; comparison belongs to the API.
      query.append(key, value);
    }
  } else if (preproject) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405, headers: { Allow: "GET" } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = key === "include_history" ? ["true", "false"].includes(value) : key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 200 : ["cursor", "proposal_id"].includes(key) && uuid.test(value);
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请使用明确的提案范围与分页条件。" }, { status: 422 });
      query.set(key, value);
    }
  } else if (resourceInspect) {
    if (request.method !== "POST") return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: "POST" } });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "请在正文中固定唯一试制资源范围。" }, { status: 422 });
  } else if (manufacturingPreparation) {
    const input = pathname.endsWith("/inputs"), fixed = !input && !pathname.endsWith("/manufacturing-preparations");
    const method = input ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: method } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = !input && (fixed ? key === "revision" && /^[1-9]\d*$/.test(value) && positiveRevision(Number(value)) : ["project_id", "process_id"].includes(key) && uuid.test(value));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请指定真实项目、固定配置或精确正整数版本。" }, { status: 422 });
      query.set(key, value);
    }
    if (!input && !query.has(fixed ? "revision" : "project_id")) return Response.json({ code: "VALIDATION_FAILED", message: "请明确选择制造准备范围。" }, { status: 422 });
  } else if (qualityFollowup) {
    const method = pathname.endsWith("/inputs") ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: method } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = method === "GET" && (key === "issue_id" ? uuid.test(value) :
        factPath && key === "candidate_id" ? uuid.test(value) :
        !capaCandidatePaths.test(pathname) && !factPath && key === "revision" && /^[1-9]\d*$/.test(value) && positiveRevision(Number(value)));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请指定一个真实问题与可选正整数版本。" }, { status: 422 });
      query.set(key, value);
    }
    if (method === "GET" && !query.has("issue_id")) return Response.json({ code: "VALIDATION_FAILED", message: "请明确选择一个问题。" }, { status: 422 });
  } else if (qualityChange) {
    const method = /\/(?:inputs|captures)$/.test(pathname) ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: method } });
    const allowed = method === "POST" ? [] : pathname.endsWith("/quality-execution") ? ["build_id", "run_id", "issue_id"] : ["issue_id", "change_id"];
    for (const [key, value] of request.nextUrl.searchParams) {
      if (!allowed.includes(key) || query.has(key) || !uuid.test(value)) {
        return Response.json({ code: "VALIDATION_FAILED", message: "请使用有效且明确的查询范围。" }, { status: 422 });
      }
      query.set(key, value);
    }
  } else if (pathname.endsWith("/sample-handoff") || pathname.endsWith("/verification-handoff") || pathname.endsWith("/verification-launch") || pathname.endsWith("/verification-results")) {
    const purpose = pathname.endsWith("/sample-handoff") ? request.nextUrl.searchParams.get("purpose") : null;
    const build = request.nextUrl.searchParams.get("build_id");
    const run = pathname.endsWith("/verification-results") ? request.nextUrl.searchParams.get("run_id") : null;
    if (run !== null) {
      if (!/^[a-f0-9-]{36}$/.test(run)) return Response.json({ code: "VALIDATION_FAILED", message: "请选择有效的测试运行。" }, { status: 422 });
      query.set("run_id", run);
    }
    if (purpose !== null) {
      if (!purpose.trim() || purpose.length > 160) return Response.json({ code: "VALIDATION_FAILED", message: "请选择明确的验证用途。" }, { status: 422 });
      query.set("purpose", purpose);
    }
    if (build !== null) {
      if (!/^[a-f0-9-]{36}$/.test(build)) return Response.json({ code: "VALIDATION_FAILED", message: "请选择有效的试制轮次。" }, { status: 422 });
      query.set("build_id", build);
    }
  } else if (pathname.endsWith("/build-execution/compare")) {
    for (const key of ["build_id", "engineering_configuration_id", "manufacturing_configuration_id"]) {
      const value = request.nextUrl.searchParams.get(key);
      if (!value || !/^[a-f0-9-]{36}$/.test(value)) return Response.json({ code: "VALIDATION_FAILED", message: "请选有效的试制轮次与固定配置。" }, { status: 422 });
      query.set(key, value);
    }
  } else if (pathname.endsWith("/compare")) {
    const parent = request.nextUrl.searchParams.get("parent_definition_id");
    if (!parent || !/^[a-f0-9-]{36}$/.test(parent)) return Response.json({ code: "VALIDATION_FAILED", message: "请选有效父版。" }, { status: 422 });
    query.set("parent_definition_id", parent);
  }
  if (request.method !== "GET" && !sameOrigin(request)) {
    return Response.json({ code: "FORBIDDEN_SCOPE", message: "请求来源不匹配。" }, { status: 403 });
  }
  const token = (await cookies()).get("pdos-next-session")?.value;
  if (!token) return Response.json({ code: "FORBIDDEN_SCOPE", message: "请进入有效会话。" }, { status: 401 });
  const base = process.env.PDOS_NEXT_API_URL;
  if (!base) return Response.json({ code: "SOURCE_UNAVAILABLE", message: "服务尚未配置。" }, { status: 503 });
  try {
    const body = request.method === "GET" ? undefined : await request.text();
    if (manufacturingPreparation && request.method === "POST") {
      let value: unknown;
      try { value = JSON.parse(body ?? ""); } catch { return Response.json({ code: "VALIDATION_FAILED", message: "请提交完整制造准备原请求。" }, { status: 422 }); }
      if (!validManufacturingCommand(value, path[2])) return Response.json({ code: "VALIDATION_FAILED", message: "本入口只核对三类制造准备草稿与原范围。" }, { status: 422 });
    }
    if (qualityFollowup && request.method === "POST") {
      let value: unknown;
      try { value = JSON.parse(body ?? ""); } catch { return Response.json({ code: "VALIDATION_FAILED", message: "请提交完整原请求与固定来源读集。" }, { status: 422 }); }
      if (!validFollowupCommand(value, path[2], factPath ? capaFactCommands : qualityFollowupCommands)) return Response.json({ code: "VALIDATION_FAILED", message: "本入口只核对对应业务操作的完整原请求。" }, { status: 422 });
    }
    let longCommand = false;
    let candidateCommand = false;
    let factCommand = false;
    if (body && (qualityFollowup || pathname === "v1/commands" || pathname === "v1/commands/preview")) {
      try {
        const value = JSON.parse(body);
        candidateCommand = value?.operation === "quality.capa.verification.candidate.record";
        factCommand = capaFactCommands.has(value?.operation);
        longCommand = (pathname === "v1/commands" || pathname === "v1/commands/preview") && longCommands.has(value?.operation);
      } catch { /* The domain API validates the unchanged body. */ }
    }
    // Actual paired-output reads exceed three minutes; related reads may wait on
    // the same source locks. Keep their transport budget aligned without retries.
    const deepRead = request.method === "GET" && (qualityChange || qualityFollowup || /\/verification-results$/.test(pathname));
    const extendedTransport = candidateCommand || factCommand || factPath || deepRead;
    const timeout = extendedTransport ? 600000 : longCommand || qualityChange || qualityFollowup || manufacturingPreparation || /\/verification-results(?:\/|$)/.test(pathname) ? 180000 : 60000;
    const response = await fetch(`${base}/${forwardPath.join("/")}${query.size ? `?${query}` : ""}`, {
      ...candidateTransportOptions(extendedTransport),
      method: request.method, headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json" },
      body, cache: "no-store",
      signal: AbortSignal.timeout(timeout), redirect: "error",
    });
    const headers = new Headers({ "Content-Type": response.headers.get("Content-Type") ?? "application/json", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
    const disposition = response.headers.get("Content-Disposition");
    if (disposition) headers.set("Content-Disposition", disposition);
    return new Response(await response.arrayBuffer(), { status: response.status, headers });
  } catch {
    if (request.method === "GET" || resourceInspect) return Response.json({ code: "SOURCE_UNAVAILABLE", detail: { reason: "TRANSPORT_UNAVAILABLE" }, message: "暂未读取到当前事实，请刷新核对。本次读取没有发起操作。" }, { status: 503 });
    return Response.json({ code: "EXTERNAL_OUTCOME_UNKNOWN", detail: { reason: "TRANSPORT_OUTCOME_UNKNOWN" }, message: "暂未取得服务回执。请重试原操作以核对结果。" }, { status: 503 });
  }
}
export const GET = forward;
export const POST = forward;
