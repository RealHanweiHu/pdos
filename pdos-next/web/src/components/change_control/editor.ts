import { sameRef, TIERS, type ChangeIntent, type ChangeRequest, type Context, type Draft, type Source } from "./contracts";

/** UI guards are advisory; the domain ports independently bind every policy fact. */
export function editorIntent(draft: Draft, request: ChangeRequest | null, context: Context): { intent: ChangeIntent | null; problem: string | null } {
  const reject = (problem: string) => ({ intent: null, problem });
  if (!context.portReady) return reject(context.unavailableReason || "对象、来源与办理权限待接入。");
  const capability = context.capabilities[draft.operation];
  if (!capability?.registered) return reject("此动作未注册，待主线接入共同命令入口。");
  if (capability.tier !== TIERS[draft.operation]) return reject("动作分级不匹配，须核对共同政策。");
  if (!context.actor?.id.trim() || !context.actor.label.trim()) return reject("当前身份待服务器绑定。");
  const aiCandidate = context.actor.kind === "ai" && capability.tier === "T2";
  if (aiCandidate ? !capability.candidateAllowed : !capability.allowed) return reject(capability.reason || "服务器尚未授权当前办理范围。");
  if (request?.requiresRecheck && !["change.recheck", "change.request.revise"].includes(draft.operation)) return reject("来源或配置已变化，旧决定待重核。");
  const sourcesCurrent = (sources: readonly Source[]) => sources.length > 0 && sources.every(value => value.status === "current" && value.position.trim() && value.id && value.revision > 0);
  const text = draft.text.trim();
  if (draft.operation === "change.request.create" || draft.operation === "change.request.revise") {
    if (!draft.title.trim() || !text) return reject("填写请求标题与变更原因。");
    const references = context.referenceOptions.filter(value => draft.referenceKeys.includes(value.key));
    const roots = context.rootOptions.filter(value => draft.rootKeys.includes(value.key));
    const sources = [...roots, ...references].map(value => value.source);
    if (!roots.length || roots.length !== new Set(draft.rootKeys).size || references.length !== new Set(draft.referenceKeys).size || !sourcesCurrent(sources)) return reject("选择当前可见、有精确出处的变更根对象和固定引用。");
    const fields = { title: draft.title.trim(), reason: text, roots: roots.map(value => value.ref), references: references.map(value => value.ref), sources };
    if (draft.operation === "change.request.revise") {
      if (!request) return reject("选择待修订的服务器变更请求。");
      return { intent: { operation: draft.operation, ...fields, request: { id: request.id, revision: request.revision, kind: request.kind }, order: null }, problem: null };
    }
    return { intent: { operation: draft.operation, ...fields }, problem: null };
  }
  if (!request) return reject("先选择服务器读取的变更请求。");
  const target = { request: { id: request.id, revision: request.revision, kind: request.kind }, order: request.order ? { id: request.order.id, revision: request.order.revision, kind: request.order.kind } : null };
  if (draft.operation === "change.recheck") return text ? { intent: { ...target, operation: draft.operation, text }, problem: null } : reject("填写待重核原因，保留旧历史。");
  if (draft.operation === "change.impact.compute") {
    const bundle = context.inputBundles.find(value => value.key === draft.inputBundleKey);
    if (!bundle?.current || bundle.snapshot.kind !== "graph_snapshot" || !bundle.refs.length || !bundle.sourceScope.trim() || !bundle.audience.length) return reject("固定版本、来源范围或受众不完整；影响仍为 UNKNOWN。");
    return { intent: { ...target, operation: draft.operation, snapshot: bundle.snapshot, fixedInputs: bundle.refs, sourceScope: bundle.sourceScope, audience: bundle.audience }, problem: null };
  }
  if (!request.impact?.current) return reject("当前固定影响评估待计算或重核。");
  if (draft.operation === "change.order.prepare") {
    const plan = context.planCandidates.find(value => value.key === draft.planKey);
    if (!plan?.current || !sameRef(plan.assessment, request.impact) || !plan.plan.scopes.length || !plan.plan.intents.length || !text) return reject("选择匹配本次固定影响版本的完整生效计划并填写说明。");
    if (plan.commandPlan.id !== plan.plan.id || !plan.commandPlan.items.length || (plan.commandPlan.expires_at !== null && !Number.isFinite(Date.parse(plan.commandPlan.expires_at)))) return reject("原始生效候选载荷与显示范围不匹配，须重新核对。");
    return { intent: { ...target, operation: draft.operation, assessment: plan.assessment, plan: plan.commandPlan, text }, problem: null };
  }
  const order = request.order;
  if (!order) return reject("变更令及明确生效范围待准备。");
  if (!sameRef(order.assessment, request.impact)) return reject("变更令引用的影响版本已漂移，须重新核对。");
  if (draft.operation === "change.order.approve") {
    if (request.impact.unknowns.length) return reject("影响评估仍有缺边、来源或覆盖 UNKNOWN，补齐后才能准备批准。");
    if (order.plan.dispositions.some(value => value.handling === "unknown")) return reject("已知影响对象仍有 UNKNOWN 处置，不得批准。");
    if (!order.requiredDisciplines.includes(draft.discipline) || !text) return reject("选择本次专业批准范围并填写具名决定说明。");
    if (request.requestedBy === context.actor.id) return reject("请求提出人不能自批本次变更。");
    if (!/(Z|[+-]\d{2}:\d{2})$/.test(draft.approvalExpiresAt) || !Number.isFinite(Date.parse(draft.approvalExpiresAt))) return reject("填写带时区的本次专业批准到期时点。");
    return { intent: { ...target, operation: draft.operation, discipline: draft.discipline, text, expiresAt: draft.approvalExpiresAt }, problem: null };
  }
  if (draft.operation === "change.implementation.record") {
    if (context.actor.kind !== "human") return reject("实际实施记录由服务器绑定的人类实施者办理。");
    const candidate = context.implementationCandidates.find(value => value.key === draft.implementationKey);
    if (!candidate?.serverVerified || !candidate.factId || !order.plan.scopes.some(value => value.id === candidate.itemId) || !order.plan.intents.some(value => value.id === candidate.fact.intentId) || !sourcesCurrent(candidate.fact.sources)) return reject("实际实施需所有者核验的精确事实、意图与生效项；不能以计划代替。");
    if (candidate.fact.actorId !== context.actor.id) return reject("实际实施记录须由当前实施者本人确认。");
    return { intent: { ...target, operation: draft.operation, itemId: candidate.itemId, factId: candidate.factId }, problem: null };
  }
  if (draft.operation === "change.effectivity.record") {
    const receipt = context.receiptCandidates.find(value => value.key === draft.receiptKey);
    if (!receipt?.serverVerified || !receipt.receipt.receiptId.trim() || !sourcesCurrent(receipt.receipt.sources)) return reject("实际回执及其当前来源待服务器核验，不推断已经生效。");
    if (receipt.receipt.scopeIds.some(id => !order.plan.scopes.some(scope => scope.id === id))) return reject("实际回执超出固定生效范围，须重新核对。");
    if (!receipt.receipt.factId || !order.plan.scopes.some(value => value.id === receipt.receipt.itemId)) return reject("实际回执缺所有者事实 ID 或对应生效项。");
    return { intent: { ...target, operation: draft.operation, itemId: receipt.receipt.itemId, factId: receipt.receipt.factId }, problem: null };
  }
  if (draft.operation === "change.verification.record") {
    const evidence = context.verificationCandidates.find(value => value.key === draft.verificationKey);
    if (!evidence?.current || !evidence.independent || !evidence.refs.length || !sourcesCurrent(evidence.sources) || !text) return reject("独立复核证据、固定新 Run 或具名说明不足。");
    if (order.excludedReviewerIds.includes(context.actor.id) || evidence.excludedActorIds.includes(context.actor.id)) return reject("提出、批准、实施或测量执行者不能自证独立有效。");
    if (order.awaitingScopeIds.length || order.plan.scopes.some(scope => !order.effectiveScopeIds.includes(scope.id) || !evidence.scopeIds.includes(scope.id))) return reject("部分生效或复核覆盖不足，须补足全部明确范围。");
    if (!evidence.factId) return reject("独立复核事实 ID 待所有者接入。");
    return { intent: { ...target, operation: draft.operation, factId: evidence.factId, text }, problem: null };
  }
  if (draft.operation === "change.close") {
    const latest = order.verification.at(-1);
    if (!latest || latest.result !== "effective" || !latest.independent || order.awaitingScopeIds.length || !sourcesCurrent(latest.sources)) return reject("尚无覆盖全范围的当前独立有效性决定，不能关闭。");
    if (context.actor.kind !== "human" || context.actor.id !== latest.actorId) return reject("关闭须由本次具名独立复核人办理。");
    return text ? { intent: { ...target, operation: draft.operation, text }, problem: null } : reject("填写本次关闭说明。");
  }
  return reject("此动作尚待接入。");
}
