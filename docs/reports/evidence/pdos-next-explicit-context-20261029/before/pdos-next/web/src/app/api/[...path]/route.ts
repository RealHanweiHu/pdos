import { cookies } from "next/headers";
import { NextRequest } from "next/server";
import { sameOrigin } from "@/lib/request-origin";
import { candidateTransportOptions } from "@/lib/candidate-transport";

const paths = /^(?:v1\/(?:session|products|commands(?:\/preview)?)|v1\/products\/[a-f0-9-]+\/(?:workspace|definitions|projects|configurations|builds|supply|supply-captures|costs|cost-captures|verification|verification-professional|verification-handoff|verification-launch(?:\/inputs)?|verification-results(?:\/(?:inputs|captures))?|sample-handoff|build-start(?:\/assessment-inputs)?|build-execution(?:\/compare)?|model-calls|variants(?:\/[a-f0-9-]+\/compare)?|original-lifecycle(?:\/[a-f0-9-]+\/candidate|\/intents\/[a-f0-9-]+\/reconcile)?|originals(?:\/[a-f0-9-]+\/(?:download|scan))?|receipts\/[a-f0-9-]+\/revert-preview))$/;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
const agentPaths = /^v1\/agent-runs(?:\/[a-f0-9-]{36}(?:\/(?:events|candidates|answers|cancel|reconciliation|process|feedback|continuation|calls\/[a-f0-9-]{36}\/recover))?)?$/i;
const personalAgentPaths = /^v1\/personal\/agent-runs(?:\/[a-f0-9-]{36}(?:\/(?:events|answers|cancel|reconciliation|process|feedback|continuation|calls\/[a-f0-9-]{36}\/recover))?)?$/i;
const personalViewPaths = /^v1\/personal\/(?:projects(?:\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?|run-activity|search|project-work|agent-skills)$/i;
const preprojectPaths = /^v1\/(?:proposals(?:\/[a-f0-9-]{36}(?:\/(?:items|participants|handoff))?)?|g0-definitions\/[a-f0-9-]{36}|projects\/[a-f0-9-]{36}\/open-items)$/i;
const proposalViewPaths = /^v1\/views\/(?:positioning|spec-benchmark|feature-config|definition-maturity)$/;
const categoryKnowledgePaths = /^v1\/(?:knowledge|parameters)$/;
const platformPaths = /^v1\/(?:platforms(?:\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?|products\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/platform-links)$/i;
const proposalClaimPaths = /^v1\/claims(?:\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?$/i;
const resourceInspectPaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/builds\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/resources\/inspect$/;
const projectPlanningPaths = /^v1\/products\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/projects\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}(?:\/(?:plan-comparison|governance(?:\/review-inputs)?))?$/i;
const manufacturingPreparationPaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/manufacturing-preparations(?:\/inputs|\/(?:work_instruction|control_plan|manufacturing_baseline)\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12})?$/;
const manufacturingPreparationCommands = new Set(["npi.work_instruction.record", "npi.control_plan.record", "npi.manufacturing_baseline.record"]);
const manufacturingPublicationPaths = /^v1\/products\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/manufacturing-publications(?:\/inputs|\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?$/i;
const manufacturingPublicationCommands = new Set(["npi.manufacturing_baseline.publish"]);
const nativePilotPaths = /^v1\/products\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/pilots(?:\/inputs|\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?$/i;
const nativePilotCommands = new Set(["npi.pilot.create", "npi.pilot.result.record"]);
const releasePaths = /^v1\/products\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/(?:release\/inputs|release-packages(?:\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?)$/i;
const projectWorkPaths = /^v1\/products\/[a-f0-9-]{36}\/project-work(?:\/templates|\/activity|\/fulfillment(?:\/inputs)?|\/external-waits(?:\/inputs)?|\/risks(?:\/inputs)?|\/inputs)?$/i;
const projectWorkCommands = new Set(["work.risk.followup.record", "work.external_wait.record", "work.task.create", "work.task.assign", "work.task.accept", "work.commitment.accept", "work.commitment.review", "work.task.start", "work.task.submit", "work.task.review", "work.status_update.create"]);
const knowledgeExperiencePaths = /^v1\/(?:products\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/)?experience(?:\/inputs)?$/i;
const fieldFeedbackPaths = /^v1\/(?:products\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/)?field-feedback(?:\/inputs)?$/i;
const fieldCommands = new Set(["field.feedback.create", "field.feedback.locate", "field.feedback.action.record", "field.feedback.followup.link"]);
const knowledgeCommands = new Set(["knowledge.candidate.create", "knowledge.rule.publish"]);
const automationPaths = /^v1\/automation-rules(?:\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}(?:\/trigger)?)?$/i;
const releaseCommands = new Set(["release.package.assemble", "release.engineering.approve", "release.manufacturing.approve"]);
const externalHandoffPaths = /^v1\/products\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/(?:external-handoff\/inputs|external-handoffs(?:\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}(?:\/receipts)?)?)$/i;
const externalHandoffCommands = new Set(["integration.handoff.authorize", "integration.receipt.record"]);
const releaseExceptionPaths = /^v1\/products\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}\/(?:release-exception\/inputs|release-exceptions(?:\/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12})?)$/i;
const releaseExceptionCommands = new Set(["release.exception.decide", "release.exception.withdraw"]);
const qualityChangePaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/(?:quality-execution(?:\/inputs)?|change-execution(?:\/(?:inputs|captures|order-context|selection-material|implementation-captures|completion-context|completion-material))?)$/;
const qualityFollowupPaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/quality-followup(?:\/inputs)?$/;
const capaCandidatePaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/capa-candidates$/;
const capaFactPaths = /^v1\/products\/[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}\/capa-facts(?:\/inputs)?$/;
const capaFactCommands = new Set(["quality.capa.observation.record", "quality.capa.verification.review"]);
const qualityFollowupCommands = new Set(["quality.issue.root_cause.decide", "quality.capa.actions.complete", "quality.capa.followup.link", "quality.capa.verification.candidate.record"]);
const isRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const positiveRevision = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0 && value <= 2147483647;
function validSelectionMaterial(value: unknown): boolean {
  if (!isRecord(value) || typeof value.change_id !== "string" || !uuid.test(value.change_id) || !positiveRevision(value.expected_change_revision)) return false;
  if ("source" in value) {
    if (Object.keys(value).some(key => !["change_id", "expected_change_revision", "source"].includes(key)) || !isRecord(value.source)) return false;
    const source = value.source;
    return Object.keys(source).every(key => ["id", "revision", "kind", "position"].includes(key)) && typeof source.id === "string" && uuid.test(source.id) && positiveRevision(source.revision) && source.kind === "artifact" && typeof source.position === "string" && /^line:[1-9]\d*;quote_sha256:[0-9a-f]{64}$/.test(source.position);
  }
  if (Object.keys(value).some(key => !["change_id", "expected_change_revision", "field_intent", "item", "status", "valid_until", "reason"].includes(key)) || !isRecord(value.field_intent)) return false;
  const target = value.field_intent;
  if (Object.keys(target).some(key => !["kind", "feedback", "executor_id"].includes(key)) || target.kind !== "field_intent" || !isRecord(target.feedback) || Object.keys(target.feedback).some(key => !["id", "revision"].includes(key)) || typeof target.feedback.id !== "string" || !uuid.test(target.feedback.id) || !positiveRevision(target.feedback.revision) || typeof target.executor_id !== "string" || !uuid.test(target.executor_id)) return false;
  if (!["applicable", "not_applicable", "unknown"].includes(String(value.status)) || typeof value.reason !== "string" || value.reason.trim().length < 3 || value.reason.trim().length > 2000 || value.valid_until !== undefined && value.valid_until !== null && (typeof value.valid_until !== "string" || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value.valid_until) || !Number.isFinite(Date.parse(value.valid_until)))) return false;
  const item = value.item;
  if (!isRecord(item) || Object.keys(item).some(key => !["id", "discipline", "selection", "intent", "verification_requirement"].includes(key)) || typeof item.id !== "string" || !uuid.test(item.id) || !["engineering", "manufacturing", "customer", "regulatory"].includes(String(item.discipline)) || typeof item.verification_requirement !== "string" || !item.verification_requirement.trim() || !isRecord(item.selection) || !isRecord(item.intent)) return false;
  // The BFF checks a complete input shape; native references, applicability,
  // authority and scope remain the domain owner's independent decisions.
  const selection = item.selection, intent = item.intent;
  return Object.keys(selection).every(key => ["objects", "units", "conditions", "sources"].includes(key)) && [selection.objects, selection.units, selection.conditions, selection.sources].every(rows => Array.isArray(rows) && rows.length > 0) && Object.keys(intent).every(key => ["id", "kind", "basis", "description"].includes(key)) && typeof intent.id === "string" && uuid.test(intent.id) && ["new_engineering_configuration", "new_manufacturing_configuration", "new_build", "new_test_run", "erp_mes_effectivity"].includes(String(intent.kind)) && Array.isArray(intent.basis) && intent.basis.length > 0 && typeof intent.description === "string" && !!intent.description.trim();
}
function validImplementationCapture(value: unknown): boolean {
  if (!isRecord(value) || Object.keys(value).some(key => !["capture_key", "change_id", "expected_change_revision", "visibility", "order_id", "item_id", "source"].includes(key)) || typeof value.capture_key !== "string" || [...value.capture_key].length < 8 || [...value.capture_key].length > 160 || typeof value.order_id !== "string" || !uuid.test(value.order_id) || typeof value.item_id !== "string" || !uuid.test(value.item_id) || (value.visibility !== undefined && !["private", "category", "audience"].includes(String(value.visibility)))) return false;
  return validSelectionMaterial({ change_id: value.change_id, expected_change_revision: value.expected_change_revision, source: value.source });
}
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
function validManufacturingCommand(value: unknown, productId: string, publication = false): boolean {
  const fixed = isRecord(value) && isRecord(value.payload) ? publication ? value.payload.baseline : value.payload.process : null;
  if (!isRecord(value) || Object.keys(value).some(key => !["command_id", "idempotency_key", "operation", "category_id", "product_id", "expected_revision", "payload", "source_read_set"].includes(key)) || typeof value.command_id !== "string" || !uuid.test(value.command_id) || typeof value.idempotency_key !== "string" || !uuid.test(value.idempotency_key) || typeof value.operation !== "string" || !(publication ? manufacturingPublicationCommands : manufacturingPreparationCommands).has(value.operation) || typeof value.product_id !== "string" || !uuid.test(value.product_id) || value.product_id.toLowerCase() !== productId.toLowerCase() || !positiveRevision(value.expected_revision) || !isRecord(value.payload) || typeof value.payload.project_id !== "string" || !uuid.test(value.payload.project_id) || !isRecord(fixed) || typeof fixed.id !== "string" || !uuid.test(fixed.id) || !positiveRevision(fixed.revision) || (publication && fixed.kind !== "manufacturing_baseline") || !Array.isArray(value.source_read_set) || value.source_read_set.length < 1) return false;
  const seen = new Set<string>();
  for (const read of value.source_read_set) {
    if (!isRecord(read) || Object.keys(read).some(key => !["artifact_id", "expected_revision"].includes(key)) || typeof read.artifact_id !== "string" || !uuid.test(read.artifact_id) || !positiveRevision(read.expected_revision) || seen.has(read.artifact_id.toLowerCase())) return false;
    seen.add(read.artifact_id.toLowerCase());
  }
  return true; // The actual strict domain DTO and owner evaluate complete sources and qualification.
}
function validPilotCommand(value: unknown, productId: string): boolean {
  if (!isRecord(value) || Object.keys(value).some(key => !["command_id", "idempotency_key", "operation", "category_id", "product_id", "expected_revision", "payload", "source_read_set"].includes(key)) || typeof value.command_id !== "string" || !uuid.test(value.command_id) || typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160 || typeof value.operation !== "string" || !nativePilotCommands.has(value.operation) || value.product_id !== productId || !positiveRevision(value.expected_revision) || !isRecord(value.payload) || !Array.isArray(value.source_read_set)) return false;
  const target = value.operation === "npi.pilot.create" ? value.payload.project_id : value.payload.pilot_id;
  if (typeof target !== "string" || !uuid.test(target)) return false;
  if (value.operation === "npi.pilot.result.record" && (!positiveRevision(value.payload.expected_pilot_revision) || !isRecord(value.payload.record))) return false;
  const seen = new Set<string>();
  for (const read of value.source_read_set) {
    if (!isRecord(read) || Object.keys(read).some(key => !["artifact_id", "expected_revision"].includes(key)) || typeof read.artifact_id !== "string" || !uuid.test(read.artifact_id) || !positiveRevision(read.expected_revision) || seen.has(read.artifact_id.toLowerCase())) return false;
    seen.add(read.artifact_id.toLowerCase());
  }
  return true; // The actual domain owner supplies the complete read set and facts.
}
function validReleaseCommand(value: unknown, productId: string): boolean {
  if (!isRecord(value) || Object.keys(value).some(key => !["command_id", "idempotency_key", "operation", "category_id", "product_id", "expected_revision", "payload", "source_read_set"].includes(key)) || typeof value.command_id !== "string" || !uuid.test(value.command_id) || typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160 || typeof value.operation !== "string" || !releaseCommands.has(value.operation) || value.product_id !== productId || !positiveRevision(value.expected_revision) || !isRecord(value.payload) || !Array.isArray(value.source_read_set)) return false;
  const target = value.operation === "release.package.assemble" ? value.payload.project_id : isRecord(value.payload.package) ? value.payload.package.id : null;
  if (typeof target !== "string" || !uuid.test(target)) return false;
  if (value.operation !== "release.package.assemble" && (!isRecord(value.payload.package) || !positiveRevision(value.payload.package.revision))) return false;
  const seen = new Set<string>();
  for (const read of value.source_read_set) {
    if (!isRecord(read) || Object.keys(read).some(key => !["artifact_id", "expected_revision"].includes(key)) || typeof read.artifact_id !== "string" || !uuid.test(read.artifact_id) || !positiveRevision(read.expected_revision) || seen.has(read.artifact_id.toLowerCase())) return false;
    seen.add(read.artifact_id.toLowerCase());
  }
  return true; // Fixed content, authority and actual scope belong to the domain owner.
}
function validExternalHandoffCommand(value: unknown, productId: string): boolean {
  if (!isRecord(value) || Object.keys(value).some(key => !["command_id", "idempotency_key", "operation", "category_id", "product_id", "expected_revision", "payload", "source_read_set"].includes(key)) || typeof value.command_id !== "string" || !uuid.test(value.command_id) || typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160 || typeof value.operation !== "string" || !externalHandoffCommands.has(value.operation) || value.product_id !== productId || !positiveRevision(value.expected_revision) || !isRecord(value.payload) || !Array.isArray(value.source_read_set)) return false;
  const authorize = value.operation === "integration.handoff.authorize";
  if (authorize && (typeof value.payload.project_id !== "string" || !uuid.test(value.payload.project_id))) return false;
  const refs = authorize ? [value.payload.package, value.payload.engineering_decision, value.payload.manufacturing_decision] : [value.payload.handoff, value.payload.intent];
  if (refs.some(ref => !isRecord(ref) || typeof ref.id !== "string" || !uuid.test(ref.id) || !positiveRevision(ref.revision))) return false;
  if ("issuer" in value.payload || "issuer_current" in value.payload) return false;
  if (!authorize && (!isRecord(value.payload.source) || value.payload.source.kind !== "artifact" || typeof value.payload.source.id !== "string" || !uuid.test(value.payload.source.id) || !positiveRevision(value.payload.source.revision))) return false;
  const seen = new Set<string>();
  for (const read of value.source_read_set) {
    if (!isRecord(read) || Object.keys(read).some(key => !["artifact_id", "expected_revision"].includes(key)) || typeof read.artifact_id !== "string" || !uuid.test(read.artifact_id) || !positiveRevision(read.expected_revision) || seen.has(read.artifact_id.toLowerCase())) return false;
    seen.add(read.artifact_id.toLowerCase());
  }
  return true; // Fixed content, authority and actual scope belong to the domain owner.
}
function validReleaseExceptionCommand(value: unknown, productId: string): boolean {
  if (!isRecord(value) || Object.keys(value).some(key => !["command_id", "idempotency_key", "operation", "category_id", "product_id", "expected_revision", "payload", "source_read_set"].includes(key)) || typeof value.command_id !== "string" || !uuid.test(value.command_id) || typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160 || typeof value.operation !== "string" || !releaseExceptionCommands.has(value.operation) || value.product_id !== productId || !positiveRevision(value.expected_revision) || !isRecord(value.payload) || !Array.isArray(value.source_read_set)) return false;
  const payload = value.payload;
  const ref = value.operation === "release.exception.decide" ? value.payload.basis_package : value.payload.exception;
  if (!isRecord(ref) || Object.keys(ref).some(key=>!["id","revision"].includes(key)) || typeof ref.id!=="string" || !uuid.test(ref.id) || !positiveRevision(ref.revision)) return false;
  if (["project_id","visibility","issuer","authority","policy_fact","policy_version","signers"].some(key=>key in payload)) return false;
  const seen = new Set<string>();
  for (const read of value.source_read_set) {
    if (!isRecord(read) || Object.keys(read).some(key => !["artifact_id", "expected_revision"].includes(key)) || typeof read.artifact_id !== "string" || !uuid.test(read.artifact_id) || !positiveRevision(read.expected_revision) || seen.has(read.artifact_id.toLowerCase())) return false;
    seen.add(read.artifact_id.toLowerCase());
  }
  return true; // Fixed content, authority and actual scope belong to the domain owner.
}
function validProjectWorkCommand(value: unknown, productId: string, categoryId: string): boolean {
  if (!isRecord(value) || Object.keys(value).some(key=>!["command_id","idempotency_key","operation","category_id","product_id","expected_revision","payload","source_read_set"].includes(key)) || value.category_id!==categoryId || value.product_id!==productId || typeof value.operation!=="string" || !projectWorkCommands.has(value.operation) || typeof value.command_id!=="string" || !uuid.test(value.command_id) || typeof value.idempotency_key!=="string" || value.idempotency_key.length<8 || value.idempotency_key.length>160 || !positiveRevision(value.expected_revision) || !Array.isArray(value.source_read_set) || !isRecord(value.payload)) return false;
  const payload=value.payload;
  if (typeof payload.project_id!=="string" || !uuid.test(payload.project_id) || ["owner_id","visibility","actor_id","authority","policy"].some(key=>key in payload)) return false;
  const seen=new Set<string>();
  for (const read of value.source_read_set) {
    if (!isRecord(read) || Object.keys(read).some(key=>!["artifact_id","expected_revision"].includes(key)) || typeof read.artifact_id!=="string" || !uuid.test(read.artifact_id) || !positiveRevision(read.expected_revision) || seen.has(read.artifact_id.toLowerCase())) return false;
    seen.add(read.artifact_id.toLowerCase());
  }
  return true;
}
function validKnowledgeCommand(value: unknown, productId: string | null, categoryId: string): boolean {
  if (!isRecord(value) || Object.keys(value).some(key => !["command_id", "idempotency_key", "operation", "category_id", "product_id", "expected_revision", "payload", "source_read_set"].includes(key)) || value.category_id !== categoryId || (value.product_id ?? null) !== productId || typeof value.operation !== "string" || !knowledgeCommands.has(value.operation) || typeof value.command_id !== "string" || !uuid.test(value.command_id) || typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160 || !positiveRevision(value.expected_revision) || !isRecord(value.payload) || !Array.isArray(value.source_read_set) || !value.source_read_set.length || productId !== null && !uuid.test(productId)) return false;
  const p = value.payload, candidate = value.operation === "knowledge.candidate.create";
  const ref = (v: unknown) => isRecord(v) && Object.keys(v).every(key => ["id", "revision"].includes(key)) && typeof v.id === "string" && uuid.test(v.id) && positiveRevision(v.revision);
  const nonempty = (v: unknown, max = 4000) => typeof v === "string" && !!v.trim() && v.trim().length <= max;
  const instant = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
  const nullableProject = p.project_id == null || typeof p.project_id === "string" && uuid.test(p.project_id);
  const allowed = candidate ? ["candidate", "project_id", "visibility", "title", "lesson", "evidence_summary", "applicability_hypothesis", "result_receipts", "sources", "reason"] : ["project_id", "candidate", "rule", "title", "rule_text", "applicability", "sources", "reason", "approval_token"];
  if (Object.keys(p).some(key => !allowed.includes(key)) || !nullableProject || !nonempty(p.title, 200) || !nonempty(p.reason) || !Array.isArray(p.sources) || !p.sources.length) return false;
  const seen = new Map<string, number>();
  for (const read of value.source_read_set) {
    if (!isRecord(read) || Object.keys(read).some(key => !["artifact_id", "expected_revision"].includes(key)) || typeof read.artifact_id !== "string" || !uuid.test(read.artifact_id) || !positiveRevision(read.expected_revision) || seen.has(read.artifact_id.toLowerCase())) return false;
    seen.set(read.artifact_id.toLowerCase(), read.expected_revision);
  }
  if (!p.sources.every(source => isRecord(source) && Object.keys(source).every(key => ["id", "revision", "kind", "position"].includes(key)) && typeof source.id === "string" && uuid.test(source.id) && positiveRevision(source.revision) && source.kind === "artifact" && nonempty(source.position, 2000) && seen.get(source.id.toLowerCase()) === source.revision)) return false;
  if (candidate) {
    if (p.candidate != null && !ref(p.candidate) || productId === null && p.project_id != null || ![undefined, "private", "category"].includes(p.visibility as string | undefined) || !nonempty(p.lesson) || !nonempty(p.evidence_summary) || !nonempty(p.applicability_hypothesis)) return false;
    if (p.result_receipts === undefined) return true;
    return Array.isArray(p.result_receipts) && p.result_receipts.every(row => isRecord(row) && Object.keys(row).every(key => key === "receipt_id") && typeof row.receipt_id === "string" && uuid.test(row.receipt_id)) && new Set(p.result_receipts.map(row => row.receipt_id.toLowerCase())).size === p.result_receipts.length;
  }
  if (productId === null || typeof p.project_id !== "string" || !ref(p.candidate) || p.rule != null && !ref(p.rule) || !nonempty(p.rule_text) || !isRecord(p.applicability) || !(p.approval_token == null || typeof p.approval_token === "string" && p.approval_token.length >= 20 && p.approval_token.length <= 128)) return false;
  const a = p.applicability, t = a.target;
  return Object.keys(a).every(key => ["target", "purpose", "differences", "adopted_rule", "conditions", "decision", "rationale", "valid_from", "valid_until"].includes(key)) && isRecord(t) && Object.keys(t).every(key => ["kind", "id", "revision"].includes(key)) && ["engineering_configuration", "process_revision"].includes(String(t.kind)) && ref({ id: t.id, revision: t.revision }) && nonempty(a.purpose, 2000) && Array.isArray(a.differences) && a.differences.every(row => nonempty(row)) && nonempty(a.adopted_rule) && Array.isArray(a.conditions) && a.conditions.every(row => nonempty(row)) && ["applicable", "not_applicable", "unknown", "conflicted"].includes(String(a.decision)) && nonempty(a.rationale) && instant(a.valid_from) && (a.valid_until == null || instant(a.valid_until) && Date.parse(a.valid_until) > Date.parse(a.valid_from));
}
function validFieldCommand(value: unknown, productId: string | null, categoryId: string): boolean {
  if (!isRecord(value) || Object.keys(value).some(key => !["command_id","idempotency_key","operation","category_id","product_id","expected_revision","payload","source_read_set"].includes(key)) || value.category_id !== categoryId || (value.product_id ?? null) !== productId || typeof value.operation !== "string" || !fieldCommands.has(value.operation) || typeof value.command_id !== "string" || !uuid.test(value.command_id) || typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160 || !positiveRevision(value.expected_revision) || !isRecord(value.payload) || !Array.isArray(value.source_read_set) || !value.source_read_set.length) return false;
  const p=value.payload, seen=new Map<string,number>();
  const text=(x:unknown,max=4000)=>typeof x==="string" && !!x.trim() && x.trim().length<=max;
  const ref=(x:unknown)=>isRecord(x) && Object.keys(x).every(k=>["id","revision"].includes(k)) && typeof x.id==="string" && uuid.test(x.id) && positiveRevision(x.revision);
  for(const r of value.source_read_set){if(!isRecord(r) || Object.keys(r).some(k=>!["artifact_id","expected_revision"].includes(k)) || typeof r.artifact_id!=="string" || !uuid.test(r.artifact_id) || !positiveRevision(r.expected_revision) || seen.has(r.artifact_id.toLowerCase()))return false;seen.set(r.artifact_id.toLowerCase(),r.expected_revision);}
  if (!text(p.reason) || !Array.isArray(p.sources) || !p.sources.length || !p.sources.every(r=>isRecord(r) && Object.keys(r).every(k=>["id","revision","kind","position"].includes(k)) && r.kind==="artifact" && typeof r.id==="string" && uuid.test(r.id) && positiveRevision(r.revision) && text(r.position,2000) && seen.get(r.id.toLowerCase())===r.revision))return false;
  const create=value.operation==="field.feedback.create", locate=value.operation==="field.feedback.locate", link=value.operation==="field.feedback.followup.link";
  const allowed=create?["sources","reason","visibility","title","description","channel","feedback_kind","received_at","reported","purpose"]:locate?["sources","reason","feedback","confirmation_token","project_id","engineering_configuration","manufacturing_configuration","batch"]:["sources","reason","feedback","confirmation_token","description","occurred_at","visibility",link?"result_receipts":"action_kind"];
  if(Object.keys(p).some(k=>!allowed.includes(k)))return false;
  if(create)return text(p.title,200) && text(p.description) && text(p.purpose,2000) && ["field","customer"].includes(String(p.channel)) && ["observation","opinion","change_request","conditional_acceptance","formal_acceptance_claim"].includes(String(p.feedback_kind)) && isRecord(p.reported) && Object.keys(p.reported).every(k=>["product_label","batch_label","configuration_label"].includes(k));
  if(!ref(p.feedback) || !(p.confirmation_token==null || text(p.confirmation_token,128)))return false;
  if(locate)return productId!==null && ref(p.engineering_configuration) && (p.manufacturing_configuration==null || ref(p.manufacturing_configuration)) && (p.batch==null || ref(p.batch)) && (p.project_id==null || typeof p.project_id==="string" && uuid.test(p.project_id));
  return text(p.description) && (link?Array.isArray(p.result_receipts) && p.result_receipts.length>0 && p.result_receipts.every(r=>isRecord(r) && Object.keys(r).every(k=>k==="receipt_id") && typeof r.receipt_id==="string" && uuid.test(r.receipt_id)):["containment","improvement"].includes(String(p.action_kind)));
}
const longCommands = new Set([
  ...fieldCommands,
  ...manufacturingPreparationCommands,
  ...manufacturingPublicationCommands,
  ...nativePilotCommands,
  ...releaseCommands,
  ...projectWorkCommands,
  ...knowledgeCommands,
  ...externalHandoffCommands,
  ...releaseExceptionCommands,
  ...qualityFollowupCommands,
  ...capaFactCommands,
  "test.results.import", "test.result.compute", "test.run.review", "test.disposition.decide",
  "quality.issue.create", "quality.issue.merge", "quality.issue.triage",
  "quality.issue.containment.record", "quality.capa.draft", "change.request.create", "change.impact.compute",
  "change.selection.decide", "change.order.prepare", "change.order.approve", "change.implementation.record",
  "change.effectivity.record", "change.verification.record", "change.close",
]);

async function forward(request: NextRequest, context: { params: Promise<{ path: string[] }> }) {
  const { path: forwardPath } = await context.params;
  const categoryId = forwardPath[0] === "v1" && forwardPath[1] === "categories" && uuid.test(forwardPath[2] ?? "") ? forwardPath[2] : undefined;
  const categoryRoot = forwardPath.join("/") === "v1/categories";
  const categoryPreview = forwardPath.join("/") === "v1/categories/preview";
  const categorySeed = /^v1\/category-seeds\/(?:auto-tire-inflator|bicycle-pump)$/.test(forwardPath.join("/"));
  const personalAgent = personalAgentPaths.test(forwardPath.join("/"));
  const personalView = personalViewPaths.test(forwardPath.join("/"));
  const personalWorkProducts = /^v1\/personal\/work-products(?:\/[a-f0-9-]{36}(?:\/revisions)?|\/from-run)?$/i.test(forwardPath.join("/"));
  const workState = /^v1\/(?:personal|categories\/[a-f0-9-]{36})\/agent-sessions\/[a-f0-9-]{36}\/work-state$/i.test(forwardPath.join("/"));
  const enterpriseSearch = /^v1\/(?:personal|categories\/[a-f0-9-]{36})\/enterprise-search$/i.test(forwardPath.join("/"));
  const assistantSource = /^v1\/(?:personal|categories\/[a-f0-9-]{36})\/agent-runs\/[a-f0-9-]{36}\/assistant-sources\/[a-f0-9-]{36}$/i.test(forwardPath.join("/"));
  const projectSets = /^v1\/project-sets(?:\/move)?$/.test(forwardPath.join("/"));
  const inbox = /^v1\/personal\/inbox\/(?:summaries|states|conversations(?:\/[a-f0-9-]{36}\/messages)?)$/i.test(forwardPath.join("/"));
  const categoryMembers = categoryId && forwardPath.length === 4 && forwardPath[3] === "members";
  if (!categoryId && !categoryRoot && !categoryPreview && !categorySeed && !personalAgent && !personalView && !personalWorkProducts && !workState && !enterpriseSearch && !assistantSource && !inbox && !projectSets && forwardPath.join("/") !== "v1/session") return Response.json({ code: "NOT_FOUND", message: "此入口不可用。" }, { status: 404 });
  const path = categoryId ? ["v1", ...forwardPath.slice(3)] : forwardPath;
  const pathname = path.join("/");
  const resourceInspect = resourceInspectPaths.test(pathname);
  const projectPlanning = projectPlanningPaths.test(pathname);
  const preproject = preprojectPaths.test(pathname);
  const proposalView = proposalViewPaths.test(pathname);
  const categoryKnowledge = categoryKnowledgePaths.test(pathname);
  const categoryMetadata = pathname === "v1/metadata";
  const categoryParticipants = pathname === "v1/participants";
  const platform = platformPaths.test(pathname);
  const standardMatch = pathname === "v1/standard-match";
  const proposalClaim = proposalClaimPaths.test(pathname);
  const agent = agentPaths.test(pathname) || personalAgent;
  const modelConfiguration = pathname === "v1/model-configuration";
  const modelConnections = pathname === "v1/model-connections";
  const providerAgreement = /^v1\/provider-agreements(?:\/recover)?$/.test(pathname);
  const skillQualification = /^v1\/agent-skill-qualification(?:\/recover)?$/.test(pathname);
  const mcpManagement = /^v1\/agent-mcp(?:\/(?:[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}(?:\/history)?|recover))?$/i.test(pathname);
  const agentSkill = /^v1\/agent-skills(?:\/recover)?$/.test(pathname);
  const agentBudget = /^v1\/agent-budgets(?:\/recover)?$/.test(pathname);
  const qualityChange = qualityChangePaths.test(pathname);
  const selectionMaterial = qualityChange && pathname.endsWith("/selection-material");
  const implementationCapture = qualityChange && pathname.endsWith("/implementation-captures");
  const completionMaterial = qualityChange && pathname.endsWith("/completion-material");
  const manufacturingPreparation = manufacturingPreparationPaths.test(pathname);
  const manufacturingPublication = manufacturingPublicationPaths.test(pathname);
  const nativePilot = nativePilotPaths.test(pathname);
  const release = releasePaths.test(pathname);
  const externalHandoff = externalHandoffPaths.test(pathname);
  const releaseException = releaseExceptionPaths.test(pathname);
  const projectWork = projectWorkPaths.test(pathname);
  const fieldFeedback = fieldFeedbackPaths.test(pathname);
  const knowledgeExperience = knowledgeExperiencePaths.test(pathname);
  const automation = automationPaths.test(pathname);
  const factPath = capaFactPaths.test(pathname);
  const qualityFollowup = qualityFollowupPaths.test(pathname) || capaCandidatePaths.test(pathname) || factPath;
  if (!categoryRoot && !categoryPreview && !categorySeed && !categoryMembers && !paths.test(pathname) && !qualityChange && !qualityFollowup && !manufacturingPreparation && !manufacturingPublication && !nativePilot && !release && !externalHandoff && !releaseException && !projectWork && !knowledgeExperience && !fieldFeedback && !automation && !resourceInspect && !projectPlanning && !preproject && !proposalView && !proposalClaim && !agent && !modelConfiguration && !modelConnections && !providerAgreement && !mcpManagement && !agentSkill && !skillQualification && !agentBudget && !categoryKnowledge && !categoryMetadata && !categoryParticipants && !standardMatch && !platform && !personalView && !personalWorkProducts && !workState && !enterpriseSearch && !assistantSource && !inbox && !projectSets) return Response.json({ code: "NOT_FOUND", message: "此入口不可用。" }, { status: 404 });
  const query = new URLSearchParams();
  if (assistantSource) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "资料片段只支持读取。" }, { status: 405, headers: { Allow: "GET" } });
    for (const [key, value] of request.nextUrl.searchParams) {
      if (query.has(key) || !(key === "cursor" && /^(0|[1-9]\d*)$/.test(value) || key === "page_chars" && /^[1-9]\d*$/.test(value) && Number(value) <= 2000 || key === "change_id" && /^[a-f0-9]{64}$/.test(value))) return Response.json({ code: "VALIDATION_FAILED", message: "资料片段分页条件无效。" }, { status: 422 });
      query.set(key, value);
    }
  } else if (enterpriseSearch) {
    if (request.method !== "POST") return Response.json({ code: "VALIDATION_FAILED", message: "检索请使用只读查询提交入口。" }, { status: 405, headers: { Allow: "POST" } });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "检索条件只接受正文，不接受其他范围或查询参数。" }, { status: 422 });
  } else if (workState) {
    if (!["GET", "POST"].includes(request.method)) return Response.json({ code: "VALIDATION_FAILED", message: "本次携带只支持读取和本人修改。" }, { status: 405, headers: { Allow: "GET, POST" } });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "本次携带按本人会话读取，不接受额外查询条件。" }, { status: 422 });
  } else if (projectSets) {
    if (!(pathname.endsWith("/move") ? ["POST"] : ["GET", "POST"]).includes(request.method)) return Response.json({ code: "VALIDATION_FAILED", message: "项目集入口不支持此操作。" }, { status: 405 });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "项目集只按当前组织读取。" }, { status: 422 });
  } else if (inbox) {
    if (pathname.endsWith("/summaries") && request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "摘要列表只支持本人读取。" }, { status: 405 });
    if (!["GET", "POST"].includes(request.method)) return Response.json({ code: "VALIDATION_FAILED", message: "此入口只支持读取与保存。" }, { status: 405 });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = request.method === "GET" && !pathname.endsWith("/states") && (key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 100 : pathname.endsWith("/messages") ? key === "before" && /^[1-9]\d*$/.test(value) : key === "cursor" && uuid.test(value));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "消息分页条件无效。" }, { status: 422 });
      query.set(key, value);
    }
  } else if (automation) {
    const method = pathname.endsWith("/trigger") ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "请使用规则读取或明确手动触发入口。" }, { status: 405, headers: { Allow: method } });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "规则只按当前本人和品类读取。" }, { status: 422 });
  } else if (mcpManagement) {
    const recovering = pathname.endsWith("/recover"), method = recovering ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "请使用 MCP 登记读取或原请求核对入口。" }, { status: 405, headers: { Allow: method } });
    const detail = pathname !== "v1/agent-mcp" && !recovering && !pathname.endsWith("/history");
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = !recovering && (key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 100 : detail ? key === "grant_cursor" ? uuid.test(value) : key === "tool_cursor" && value.length > 0 && value.length <= 160 : key === "cursor" && uuid.test(value));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "MCP 只按当前租户、明确连接器和分页条件读取。" }, { status: 422 });
      query.set(key, value);
    }
  } else if (skillQualification) {
    const recovering = pathname.endsWith("/recover"), method = recovering ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "请使用审阅读取或原请求核对入口。" }, { status: 405, headers: { Allow: method } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = !recovering && (key === "skill_key" ? value.length > 0 && value.length <= 160 : key === "cursor" && uuid.test(value));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请明确选择技能和审阅分页。" }, { status: 422 });
      query.set(key, value);
    }
    if (!recovering && !query.has("skill_key")) return Response.json({ code: "VALIDATION_FAILED", message: "请选择一个技能。" }, { status: 422 });
  } else if (agentBudget) {
    const recovering = pathname.endsWith("/recover"), method = recovering ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "请使用预算读取或原请求回执核对入口。" }, { status: 405, headers: { Allow: method } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = !recovering && (key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 200 : key === "cursor" && uuid.test(value));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "预算仅按当前身份和明确分页条件读取。" }, { status: 422 });
      query.set(key, value);
    }
  } else if (agentSkill) {
    const method = pathname.endsWith("/recover") ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "请使用技能状态读取或原请求回执核对入口。" }, { status: 405, headers: { Allow: method } });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "技能状态与回执只按当前租户和原请求核对。" }, { status: 422 });
  } else if (providerAgreement) {
    const recovering = pathname.endsWith("/recover");
    if (recovering && request.method !== "POST") return Response.json({ code: "VALIDATION_FAILED", message: "请提交原登记请求以核对回执。" }, { status: 405, headers: { Allow: "POST" } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = request.method === "GET" && !recovering && (key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 200 : ["provider", "cursor"].includes(key) && /^[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}$/.test(value));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请使用明确的服务商与分页条件；登记和回执核对只使用原正文。" }, { status: 422 });
      query.set(key, value);
    }
  } else if (projectPlanning) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405, headers: { Allow: "GET" } });
    for (const [key,value] of request.nextUrl.searchParams) {
      const accepted = pathname.endsWith("/plan-comparison") ? key === "proposal_id" : pathname.endsWith("/governance/review-inputs") ? key === "package_id" : false;
      if (!accepted || !uuid.test(value) || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请使用当前项目的唯一计划候选或发布包。" }, { status: 422 });
      query.set(key,value);
    }
  } else if (personalWorkProducts) {
    const writing = pathname.endsWith("/from-run") || pathname.endsWith("/revisions");
    const method = writing ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "成果列表/详情只读，创建与修订使用明确提交入口。" }, { status: 405, headers: { Allow: method } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = pathname === "v1/personal/work-products" && key === "session_id" && uuid.test(value);
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "成果只按当前会话读取，不接受其他查询条件。" }, { status: 422 });
      query.set(key, value);
    }
  } else if (personalView) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405, headers: { Allow: "GET" } });
    const collection = ["v1/personal/projects", "v1/personal/run-activity"].includes(pathname);
    const searching = pathname === "v1/personal/search";
    const projectWorkQueue = pathname === "v1/personal/project-work";
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = projectWorkQueue ? (key === "queue" ? ["receive", "verify", "tasks", "commitments"].includes(value)
        : key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 100
        : key === "cursor" && uuid.test(value))
        : searching ? (key === "q" ? !!value.trim() && value.length <= 200
        : key === "kind" ? ["all", "category", "project", "product", "proposal"].includes(value)
        : key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 100
        : key === "cursor" && /^(?:category|project|product|proposal):[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}:[a-f0-9]{16}$/.test(value))
        : collection && (key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 200
        : key === "cursor" ? uuid.test(value)
        : key === "waiting" && pathname.endsWith("/run-activity") && ["true", "false"].includes(value));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "个人视图分页条件无效。" }, { status: 422 });
      query.set(key, value);
    }
    if (searching && !query.has("q")) return Response.json({ code: "VALIDATION_FAILED", message: "请输入名称或完整 ID。" }, { status: 422 });
    if (projectWorkQueue && !query.has("queue")) return Response.json({ code: "VALIDATION_FAILED", message: "请选择本人工作队列。" }, { status: 422 });
  } else if (standardMatch) {
    if (request.method !== "POST") return Response.json({ code: "VALIDATION_FAILED", message: "请提交要核对的规格。" }, { status: 405, headers: { Allow: "POST" } });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "规格核对不接受额外查询条件。" }, { status: 422 });
  } else if (platform) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405, headers: { Allow: "GET" } });
    const collection = pathname === "v1/platforms", productLinks = pathname.endsWith("/platform-links");
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = key === "include_history" ? ["true", "false"].includes(value)
        : (collection || productLinks) && key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 200
        : (collection || productLinks) && ["cursor", "variant_id"].includes(key) ? uuid.test(value)
        : collection && key === "product_id" ? uuid.test(value)
        : collection && ["code", "name_query"].includes(key) ? value.trim().length > 0 && value.length <= 200
        : false;
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "平台查询范围或分页条件无效。" }, { status: 422 });
      query.set(key, value);
    }
    if (collection && query.has("variant_id") && !query.has("product_id")) return Response.json({ code: "VALIDATION_FAILED", message: "查询变体时请选择所属型号。" }, { status: 422 });
  } else if (categoryPreview || categorySeed || categoryRoot) {
    const allowed = categoryRoot ? ["GET", "POST"] : categorySeed ? ["GET"] : ["POST"];
    if (!allowed.includes(request.method)) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405 });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "品类入口不接受额外查询条件。" }, { status: 422 });
  } else if (modelConnections) {
    if (!["GET", "POST"].includes(request.method)) return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅支持读取与保存服务商。" }, { status: 405 });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "服务商配置只使用当前租户及请求正文。" }, { status: 422 });
  } else if (modelConfiguration) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405 });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "模型设置不接受额外查询条件。" }, { status: 422 });
  } else if (agent) {
    const agentPath = personalAgent ? ["v1", ...path.slice(2)] : path;
    if ((agentPath[2] && !uuid.test(agentPath[2])) || (agentPath[3] === "calls" && !uuid.test(agentPath[4] ?? ""))) return Response.json({ code: "VALIDATION_FAILED", message: "运行或调用编号无效。" }, { status: 422 });
    const collection = agentPath.length === 2;
    const create = collection && request.method === "POST";
    const action = /\/(?:answers|cancel|recover)$/.test(pathname);
    const reconciliation = pathname.endsWith("/reconciliation");
    const feedback = pathname.endsWith("/feedback");
    const method = create || action || (reconciliation || feedback) && request.method === "POST" ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405 });
    for (const [key, value] of request.nextUrl.searchParams) {
      const events = pathname.endsWith("/events") || pathname.endsWith("/candidates") || pathname.endsWith("/process");
      const valid = method === "GET" && (feedback ? key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value)<=100 : key === "before" ? /^[1-9]\d*$/.test(value) && Number.isSafeInteger(Number(value)) : key === "request_key" && uuid.test(value) : reconciliation ? key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 100 : ["call_cursor", "receipt_cursor"].includes(key) && uuid.test(value) : (events || collection) && (key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= (pathname.endsWith("/process") ? 100 : 200) : ["source_cursor", "receipt_cursor"].includes(key) && pathname.endsWith("/process") ? uuid.test(value) : key === "cursor" ? collection && uuid.test(value) : ["proposal_id", "project_id"].includes(key) ? collection && !!categoryId && uuid.test(value) : ["after", "before"].includes(key) && events && (key === "before" ? pathname.endsWith("/process") && /^[1-9]\d*$/.test(value) : !pathname.endsWith("/process") && /^\d+$/.test(value)) && Number.isSafeInteger(Number(value))));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "运行分页条件无效。" }, { status: 422 });
      query.set(key, value);
    }
    if (feedback && query.has("request_key") && query.has("before")) return Response.json({ code: "VALIDATION_FAILED", message: "原请求核对不能混用历史游标。" }, { status: 422 });
  } else if (proposalClaim) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405, headers: { Allow: "GET" } });
    const collection = pathname === "v1/claims";
    if (!collection && request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "事实详情不接受额外查询条件。" }, { status: 422 });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = collection && (key === "status" ? ["active", "withdrawn", "reverted"].includes(value) : key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 200 : ["proposal_id", "cursor"].includes(key) && uuid.test(value));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请使用明确的提案事实范围与分页条件。" }, { status: 422 });
      query.set(key, value);
    }
    if (collection && !query.has("proposal_id")) return Response.json({ code: "VALIDATION_FAILED", message: "请明确选择一个提案。" }, { status: 422 });
  } else if (proposalView) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405, headers: { Allow: "GET" } });
    const proposalIds = request.nextUrl.searchParams.getAll("proposal_id");
    if (proposalIds.length !== 1 || !uuid.test(proposalIds[0])) return Response.json({ code: "VALIDATION_FAILED", message: "请选择一个有效提案。" }, { status: 422 });
    for (const [key, value] of request.nextUrl.searchParams) {
      if (!["proposal_id", "parameter_ids"].includes(key) || !uuid.test(value)) return Response.json({ code: "VALIDATION_FAILED", message: "请仅提供提案与有效参数编号。" }, { status: 422 });
      // Preserve every parameter occurrence and its order; comparison belongs to the API.
      query.append(key, value);
    }
  } else if (categoryMetadata || categoryParticipants) {
    const methods = categoryMetadata ? ["GET", "POST"] : ["GET"];
    if (!methods.includes(request.method)) return Response.json({ message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: methods.join(", ") } });
    if (request.nextUrl.searchParams.size) return Response.json({ message: "品类资料只按当前范围读取。" }, { status: 422 });
  } else if (categoryKnowledge) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405, headers: { Allow: "GET" } });
    const kinds = new Set(["boundary", "segment", "competitor", "voice", "regulation", "research_question"]);
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 200
        : key === "include_history" ? ["true", "false"].includes(value)
        : key === "kind" && pathname === "v1/knowledge" ? kinds.has(value)
        : key === "status" && pathname === "v1/knowledge" ? ["active", "withdrawn"].includes(value)
        : key === "origin" && pathname === "v1/knowledge" ? ["human", "ai_draft", "imported"].includes(value)
        : key === "region" && pathname === "v1/knowledge" ? value.length > 0 && value.length <= 120
        : key === "parameter_ids" && pathname === "v1/parameters" ? uuid.test(value)
        : key === "cursor" ? value.length > 0 && value.length <= 200
        : false;
      if (!valid || (key !== "parameter_ids" && query.has(key))) return Response.json({ code: "VALIDATION_FAILED", message: "请使用明确的品类知识与字典范围。" }, { status: 422 });
      query.append(key, value);
    }
  } else if (preproject) {
    if (pathname.endsWith("/handoff") && request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "立项结果只按当前提案读取。" }, { status: 422 });
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405, headers: { Allow: "GET" } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = key === "q" && pathname === "v1/proposals" ? [...value].length <= 160 : key === "status" && pathname === "v1/proposals" ? ["draft", "returned", "in_review", "approved", "rejected", "withdrawn"].includes(value) : key === "include_history" ? ["true", "false"].includes(value) : key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 200 : ["cursor", "proposal_id"].includes(key) && uuid.test(value);
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请使用明确的提案范围与分页条件。" }, { status: 422 });
      query.set(key, value);
    }
  } else if (resourceInspect) {
    if (request.method !== "POST") return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: "POST" } });
    if (request.nextUrl.searchParams.size) return Response.json({ code: "VALIDATION_FAILED", message: "请在正文中固定唯一试制资源范围。" }, { status: 422 });
  } else if (knowledgeExperience || fieldFeedback) {
    const input = pathname.endsWith("/inputs"), method = input ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "请使用经验读取或材料核对入口。" }, { status: 405, headers: { Allow: method } });
    for (const [key, value] of request.nextUrl.searchParams) {
      if (input || key !== "project_id" || !uuid.test(value) || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "经验读取仅接受一个可选实际项目，材料核对只使用原正文。" }, { status: 422 });
      query.set(key, value);
    }
  } else if (projectWork) {
    const input = pathname.endsWith("/inputs"), activity = pathname.endsWith("/activity"), method = input ? "POST" : "GET";
    if (request.method !== method) return Response.json({code:"VALIDATION_FAILED",message:"请使用项目工作读取或材料核对入口。"},{status:405,headers:{Allow:method}});
    for (const [key,value] of request.nextUrl.searchParams) {
      const valid = key === "project_id" ? uuid.test(value) : activity && (key === "page_size" ? /^[1-9]\d*$/.test(value) && Number(value) <= 100 : key === "cursor" && /^[A-Za-z0-9_-]{1,2048}$/.test(value));
      if (input || !valid || query.has(key)) return Response.json({code:"VALIDATION_FAILED",message:"请选择唯一实际项目及有效分页位置。"},{status:422});
      query.set(key,value);
    }
    if (!input && !query.has("project_id")) return Response.json({code:"VALIDATION_FAILED",message:"请选择实际项目。"},{status:422});
  } else if (releaseException) {
    const input = pathname.endsWith("/inputs"), history = pathname.endsWith("/release-exceptions");
    const method = input ? "POST" : "GET";
    if (request.method !== method) return Response.json({code:"VALIDATION_FAILED",message:"此入口不支持这类请求。"},{status:405,headers:{Allow:method}});
    for (const [key,value] of request.nextUrl.searchParams) {
      if (!history || !["project_id","history_cursor"].includes(key) || !uuid.test(value) || query.has(key)) return Response.json({code:"VALIDATION_FAILED",message:"请选择唯一例外项目和原历史位置。"},{status:422});
      query.set(key,value);
    }
    if (history && !query.has("project_id")) return Response.json({code:"VALIDATION_FAILED",message:"请选择例外所属项目。"},{status:422});
  } else if (externalHandoff) {
    const input = pathname.endsWith("/inputs"), history = pathname.endsWith("/external-handoffs"), receipts = pathname.endsWith("/receipts");
    const method = input ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: method } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = history ? ["project_id", "history_cursor"].includes(key) && uuid.test(value) : receipts && key === "before_sequence" && /^[1-9]\d*$/.test(value) && positiveRevision(Number(value));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请选择唯一移交项目与原回执序列。" }, { status: 422 });
      query.set(key, value);
    }
    if (history && !query.has("project_id")) return Response.json({ code: "VALIDATION_FAILED", message: "请选择移交所属项目。" }, { status: 422 });
  } else if (release) {
    const input = pathname.endsWith("/inputs"), history = pathname.endsWith("/release-packages");
    const method = input ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: method } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = history && ["project_id", "history_cursor"].includes(key) && uuid.test(value);
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请选择唯一发布包项目与原历史游标。" }, { status: 422 });
      query.set(key, value);
    }
    if (history && !query.has("project_id")) return Response.json({ code: "VALIDATION_FAILED", message: "请选择发布包所属项目。" }, { status: 422 });
  } else if (nativePilot) {
    const input = pathname.endsWith("/inputs"), history = pathname.endsWith("/pilots");
    const method = input ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: method } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = history && (key === "project_id" ? uuid.test(value) : key === "history_cursor" && uuid.test(value));
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请选择唯一Pilot项目与原历史游标。" }, { status: 422 });
      query.set(key, value);
    }
    if (history && !query.has("project_id")) return Response.json({ code: "VALIDATION_FAILED", message: "请选择Pilot所属项目。" }, { status: 422 });
  } else if (manufacturingPublication) {
    const input = pathname.endsWith("/inputs"), fixed = !input && !pathname.endsWith("/manufacturing-publications");
    const method = input ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: method } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = !input && (fixed ? key === "revision" && /^[1-9]\d*$/.test(value) && positiveRevision(Number(value)) : key === "project_id" ? uuid.test(value) : key === "history_cursor" && value.length > 0 && value.length <= 2000);
      if (!valid || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请选择唯一项目、固定发布版本或原历史游标。" }, { status: 422 });
      query.set(key, value);
    }
    if (!input && !query.has(fixed ? "revision" : "project_id")) return Response.json({ code: "VALIDATION_FAILED", message: "请明确选择制造基线发布范围。" }, { status: 422 });
  } else if (manufacturingPreparation) {
    const input = pathname.endsWith("/inputs"), fixed = !input && !pathname.endsWith("/manufacturing-preparations");
    const method = input ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: method } });
    for (const [key, value] of request.nextUrl.searchParams) {
      const valid = !input && (fixed ? key === "revision" && /^[1-9]\d*$/.test(value) && positiveRevision(Number(value)) : key === "history_cursor" ? value.length > 0 && value.length <= 2000 : ["project_id", "process_id"].includes(key) && uuid.test(value));
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
    const method = /\/(?:inputs|captures|selection-material|implementation-captures|completion-material)$/.test(pathname) ? "POST" : "GET";
    if (request.method !== method) return Response.json({ code: "VALIDATION_FAILED", message: "此入口不支持这类请求。" }, { status: 405, headers: { Allow: method } });
    const orderContext = pathname.endsWith("/order-context") || pathname.endsWith("/completion-context");
    const allowed = method === "POST" ? [] : pathname.endsWith("/quality-execution") ? ["build_id", "run_id", "issue_id"] : orderContext ? ["change_id"] : ["issue_id", "field_feedback_id", "change_id", "project_id"];
    for (const [key, value] of request.nextUrl.searchParams) {
      if (!allowed.includes(key) || query.has(key) || !uuid.test(value)) {
        return Response.json({ code: "VALIDATION_FAILED", message: "请使用有效且明确的查询范围。" }, { status: 422 });
      }
      query.set(key, value);
    }
    if (orderContext && !query.has("change_id")) return Response.json({ code: "VALIDATION_FAILED", message: "请明确选择一个固定变更。" }, { status: 422 });
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
  } else if (pathname.endsWith("/builds")) {
    if (request.method !== "GET") return Response.json({ code: "VALIDATION_FAILED", message: "此入口仅用于读取。" }, { status: 405 });
    for (const [key, value] of request.nextUrl.searchParams) {
      if (key !== "project_id" || !uuid.test(value) || query.has(key)) return Response.json({ code: "VALIDATION_FAILED", message: "请指定唯一有效项目。" }, { status: 422 });
      query.set(key, value);
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
    if (modelConnections && body && new TextEncoder().encode(body).length > 32768) return Response.json({ code: "VALIDATION_FAILED", message: "服务商配置内容过大。" }, { status: 413 });
    if (fieldFeedback && request.method === "POST" || request.method === "POST" && ["v1/commands","v1/commands/preview"].includes(pathname)) {
      let value: unknown;
      try { value=JSON.parse(body ?? ""); } catch { if(fieldFeedback)return Response.json({code:"VALIDATION_FAILED",message:"请提交完整反馈原请求。"},{status:422}); }
      if(fieldFeedback || isRecord(value) && typeof value.operation==="string" && fieldCommands.has(value.operation)){
        const product=fieldFeedback?path[1]==="products"?path[2]:null:isRecord(value) && typeof value.product_id==="string"?value.product_id:null;
        if(!categoryId || request.nextUrl.searchParams.size || !validFieldCommand(value,product,categoryId))return Response.json({code:"VALIDATION_FAILED",message:"请固定当前反馈范围、原件及本次操作。"},{status:422});
      }
    }
    if (knowledgeExperience && request.method === "POST" || request.method === "POST" && ["v1/commands", "v1/commands/preview"].includes(pathname)) {
      let value: unknown;
      try { value = JSON.parse(body ?? ""); } catch { if (knowledgeExperience) return Response.json({ code: "VALIDATION_FAILED", message: "请提交完整经验原请求。" }, { status: 422 }); }
      if (knowledgeExperience || isRecord(value) && typeof value.operation === "string" && knowledgeCommands.has(value.operation)) {
        const product = knowledgeExperience ? path[1] === "products" ? path[2] : null : isRecord(value) && typeof value.product_id === "string" ? value.product_id : null;
        if (!categoryId || request.nextUrl.searchParams.size || !validKnowledgeCommand(value, product, categoryId)) return Response.json({ code: "VALIDATION_FAILED", message: "请固定当前品类、实际型号或品类候选、原件及知识操作。" }, { status: 422 });
      }
    }
    if (automation && request.method === "POST") {
      let value: unknown;
      try { value = JSON.parse(body ?? ""); } catch { return Response.json({ code: "VALIDATION_FAILED", message: "请提交完整原触发请求。" }, { status: 422 }); }
      if (!isRecord(value) || Object.keys(value).some(key => !["expected_rule_revision", "version_id", "idempotency_key"].includes(key)) || !positiveRevision(value.expected_rule_revision) || typeof value.version_id !== "string" || !uuid.test(value.version_id) || typeof value.idempotency_key !== "string" || !positiveRevision(value.expected_rule_revision) || typeof value.idempotency_key !== "string" || value.idempotency_key.trim().length < 8 || value.idempotency_key.length > 120) return Response.json({ code: "VALIDATION_FAILED", message: "请固定当前规则版本和原请求编号。" }, { status: 422 });
    }
    if (selectionMaterial) {
      let value: unknown;
      try { value = JSON.parse(body ?? ""); } catch { return Response.json({ code: "VALIDATION_FAILED", message: "请提交所选变更与精确原文完整行。" }, { status: 422 }); }
      if (!validSelectionMaterial(value)) return Response.json({ code: "VALIDATION_FAILED", message: "请提交明确变更版本的已登记材料，或完整的现场反馈未来计划。" }, { status: 422 });
    }
    if (completionMaterial) {
      let value: unknown;
      try { value = JSON.parse(body ?? ""); } catch { return Response.json({ code: "VALIDATION_FAILED", message: "请提交完整实际采用或复核范围。" }, { status: 422 }); }
      if (!isRecord(value) || Object.keys(value).some(key => !["operation", "payload"].includes(key)) || !["change.effectivity.record", "change.verification.record", "change.close"].includes(String(value.operation)) || !isRecord(value.payload) || typeof value.payload.change_id !== "string" || !uuid.test(value.payload.change_id) || !positiveRevision(value.payload.expected_change_revision) || !["private", "category", "audience"].includes(String(value.payload.visibility)) || value.payload.confirmation_token != null || value.payload.approval_token != null) return Response.json({ code: "VALIDATION_FAILED", message: "请固定当前变更与实际批次、复测范围或关闭说明。" }, { status: 422 });
    }
    if (implementationCapture) {
      let value: unknown;
      try { value = JSON.parse(body ?? ""); } catch { return Response.json({ code: "VALIDATION_FAILED", message: "请提交完整原捕获请求与实际原文行。" }, { status: 422 }); }
      if (!validImplementationCapture(value)) return Response.json({ code: "VALIDATION_FAILED", message: "此入口只捕获明确变更、计划项与精确原文完整行，批准和实际输出由服务器核对。" }, { status: 422 });
    }
    if (manufacturingPublication && request.method === "POST") {
      let value: unknown;
      try { value = JSON.parse(body ?? ""); } catch { return Response.json({ code: "VALIDATION_FAILED", message: "请提交完整制造基线发布原请求。" }, { status: 422 }); }
      if (!validManufacturingCommand(value, path[2], true)) return Response.json({ code: "VALIDATION_FAILED", message: "本入口只核对本型号、项目与固定制造基线的发布。" }, { status: 422 });
    }
    if (projectWork && request.method === "POST") {
      let value: unknown;
      try {value=JSON.parse(body??"");} catch {return Response.json({code:"VALIDATION_FAILED",message:"请提交完整项目工作原请求。"},{status:422});}
      if (!validProjectWorkCommand(value,path[2],categoryId!) || !isRecord(value) || (pathname.endsWith("/risks/inputs") ? value.operation !== "work.risk.followup.record" : pathname.endsWith("/external-waits/inputs") ? value.operation !== "work.external_wait.record" : pathname.endsWith("/fulfillment/inputs") ? value.operation !== "work.commitment.review" : ["work.commitment.review", "work.external_wait.record", "work.risk.followup.record"].includes(String(value.operation)))) return Response.json({code:"VALIDATION_FAILED",message:"请固定本型号项目与已登记办理操作。"},{status:422});
    }
    if (releaseException && request.method === "POST") {
      let value: unknown;
      try {value=JSON.parse(body??"");} catch {return Response.json({code:"VALIDATION_FAILED",message:"请提交完整例外原请求。"},{status:422});}
      if (!validReleaseExceptionCommand(value,path[2])) return Response.json({code:"VALIDATION_FAILED",message:"请选择实际固定包或原例外决定。"},{status:422});
    }
    if (externalHandoff && request.method === "POST") {
      let value: unknown;
      try { value = JSON.parse(body ?? ""); } catch { return Response.json({ code: "VALIDATION_FAILED", message: "请提交完整移交原请求。" }, { status: 422 }); }
      if (!validExternalHandoffCommand(value, path[2])) return Response.json({ code: "VALIDATION_FAILED", message: "请选择本型号真实移交版本及原件。" }, { status: 422 });
    }
    if (release && request.method === "POST") {
      let value: unknown;
      try { value = JSON.parse(body ?? ""); } catch { return Response.json({ code: "VALIDATION_FAILED", message: "请提交完整发布包原请求。" }, { status: 422 }); }
      if (!validReleaseCommand(value, path[2])) return Response.json({ code: "VALIDATION_FAILED", message: "请选择本型号固定包及完整原输入。" }, { status: 422 });
    }
    if (nativePilot && request.method === "POST") {
      let value: unknown;
      try { value = JSON.parse(body ?? ""); } catch { return Response.json({ code: "VALIDATION_FAILED", message: "请提交完整Pilot原请求。" }, { status: 422 }); }
      if (!validPilotCommand(value, path[2])) return Response.json({ code: "VALIDATION_FAILED", message: "请选择本型号Pilot原范围与完整输入。" }, { status: 422 });
    }
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
    const timeout = extendedTransport ? 600000 : longCommand || qualityChange || qualityFollowup || manufacturingPreparation || manufacturingPublication || nativePilot || release || externalHandoff || releaseException || /\/verification-results(?:\/|$)/.test(pathname) ? 180000 : 60000;
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
    if (request.method === "GET" || resourceInspect || standardMatch || selectionMaterial || completionMaterial || (providerAgreement || mcpManagement || agentSkill || skillQualification || agentBudget) && pathname.endsWith("/recover")) return Response.json({ code: "SOURCE_UNAVAILABLE", detail: { reason: "TRANSPORT_UNAVAILABLE" }, message: "暂未读取到当前事实，请刷新核对。本次读取没有发起操作。" }, { status: 503 });
    return Response.json({ code: "EXTERNAL_OUTCOME_UNKNOWN", detail: { reason: "TRANSPORT_OUTCOME_UNKNOWN" }, message: "暂未取得服务回执。请重试原操作以核对结果。" }, { status: 503 });
  }
}
export const GET = forward;
export const POST = forward;
