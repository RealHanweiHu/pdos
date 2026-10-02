import {
  currentSessionToken,
  forwardJson,
  InvalidRequestBodyError,
  pdosApiFetch,
  readBoundedJson,
  sessionError,
} from "@/lib/pdos-api";

// Optional catch-all: `/meetings` itself arrives with no `meetingPath` at all.
type Context = {
  params: Promise<{ projectId: string; meetingPath?: string[] }>;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;

function isUuid(value: string | undefined): value is string {
  return typeof value === "string" && UUID.test(value);
}

/**
 * The proxy forwards only the shapes the backend actually serves. An unlisted
 * path is a 404 here rather than an opaque pass-through, so a typo in the app
 * cannot quietly become a request against some other backend route.
 */
function allowedPath(method: "GET" | "POST" | "PUT", segments: string[]) {
  if (segments.length === 2 && isUuid(segments[0]) && segments[1] === "planning-origin") return method === "GET";
  if (segments.length === 2 && segments[0] === "planning-findings" && isUuid(segments[1])) return method === "GET";
  if (segments.length === 3 && segments[0] === "planning-findings" && isUuid(segments[1]) && ["preview", "review", "apply"].includes(segments[2])) return method === "POST";
  if (segments.length === 3 && segments[0] === "planning" && isUuid(segments[1]) && segments[2] === "runs") return method === "GET" || method === "POST";
  if (segments.length === 1 && segments[0] === "planning") return method === "GET" || method === "POST";
  if (segments.length === 1 && segments[0] === "planning-preview") return method === "POST";
  if (segments.length === 1 && segments[0] === "planning-options") return method === "GET";
  if (segments[0] === "recurrences") {
    if (segments.length === 1) return method === "GET" || method === "POST";
    if (segments.length === 2 && segments[1] === "preview") return method === "POST";
    if (segments.length === 3 && isUuid(segments[1])) {
      if (["preview", "generate", "schedule-preview", "schedule", "automation-preview"].includes(segments[2])) return method === "POST";
      if (segments[2] === "history") return method === "GET";
      if (segments[2] === "automation") return method === "GET" || method === "POST";
    }
  }
  if (segments.length === 3 && segments[0] === "recurrences" && isUuid(segments[1]) && segments[2] === "roster") return method === "GET" || method === "POST";
  if (segments.length === 0) return method === "GET" || method === "POST";
  if (method === "GET" && segments.join("/") === "preparation/options") return true;
  if (!isUuid(segments[0])) return false;
  const rest = segments.slice(1);
  if (rest.length === 1 && rest[0] === "ai-event-history") return method === "GET";
  if (rest[0] === "ai-minutes-drafts") {
    if (rest.length === 1) return method === "GET";
    if (rest.length === 2 && rest[1] === "scope") return method === "POST";
    if (rest.length === 3 && isUuid(rest[1]) && rest[2] === "history") return method === "GET";
    if (rest.length === 3 && isUuid(rest[1]) && rest[2] === "actions") return method === "POST";
    return method === "POST" && rest.length === 4 && rest[1] === "runs" && isUuid(rest[2]) && rest[3] === "withdraw";
  }
  if (rest[0] === "transcripts" && isUuid(rest[1])) {
    if (method === "GET" && rest.length === 2) return true;
    if ((method === "GET" || method === "POST") && rest.length === 3 && rest[2] === "reading") return true;
    if (method === "POST" && rest.length === 3 && rest[2] === "speakers") return true;
  }
  if (method === "GET" && rest.length === 3 && rest[0] === "agenda" && isUuid(rest[1]) && rest[2] === "responsibility-history") return true;
  if (method === "POST" && rest.length === 3 && rest[0] === "agenda" && isUuid(rest[1]) && rest[2] === "followup") return true;
  if (method === "GET") {
    return (
      rest.length === 0 ||
      (rest.length === 1 &&
        ["participants", "agenda", "transcripts", "retrospective", "preparation", "followup", "review-candidates", "minutes", "schedule", "notifications", "conference-requests"].includes(rest[0] ?? ""))
    );
  }
  if (method === "PUT") {
    return rest.length === 1 && rest[0] === "agenda";
  }
  return (
    rest.length === 1 &&
    ["conference", "transcripts", "status", "archive", "retrospective", "preparation", "minutes", "schedule", "external-schedule-confirmation", "notification-preview", "notifications", "conference-preview", "conference-requests", "conference-resolution"].includes(rest[0] ?? "")
  );
}

export async function forwardMeetings(
  method: "GET" | "POST" | "PUT",
  request: Request,
  context: Context,
) {
  const { projectId, meetingPath } = await context.params;
  const segments = meetingPath ?? [];
  if (!allowedPath(method, segments)) {
    return sessionError(404, "MEETING_ROUTE_NOT_FOUND", "Meeting route not found");
  }
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    // `archive` is the one write with no body; every other write must carry
    // valid JSON, so a parse failure there stays a 400 rather than silently
    // becoming a bodyless request to the backend.
    const bodyless = method === "GET" || segments[segments.length - 1] === "archive";
    const bodyLimit = ["transcripts", "speakers", "minutes"].includes(segments.at(-1) ?? "") ? 2_097_152
      : ["retrospective", "preparation", "followup"].includes(segments.at(-1) ?? "") ? 524_288 : undefined;
    const body = bodyless ? undefined : await readBoundedJson(request, bodyLimit);
    const suffix = segments.map(encodeURIComponent).join("/");
    const cursor = method === "GET" && segments.at(-1) === "review-candidates"
      ? new URL(request.url).searchParams.get("cursor") : null;
    if (cursor !== null && !isUuid(cursor)) return sessionError(400, "INVALID_CURSOR", "Invalid review cursor");
    const beforeVersion = method === "GET" && segments.at(-1) === "minutes"
      ? new URL(request.url).searchParams.get("before_version") : null;
    if (beforeVersion !== null && !/^[1-9][0-9]{0,8}$/.test(beforeVersion)) return sessionError(400, "INVALID_VERSION", "Invalid minutes version");
    const minutesRecord = method === "GET" && segments.at(-1) === "minutes"
      ? new URL(request.url).searchParams.get("record_id") : null;
    if (minutesRecord !== null && !isUuid(minutesRecord)) return sessionError(400, "INVALID_RECORD_ID", "Invalid minutes record");
    if (minutesRecord && beforeVersion) return sessionError(409, "INVALID_VERSION_QUERY", "指定纪要版本不能同时使用历史分页");
    const beforeId = method === "GET" && ["planning", "responsibility-history", "roster", "history", "schedule", "automation", "notifications", "conference-requests"].includes(segments.at(-1) ?? "")
      ? new URL(request.url).searchParams.get("before_id") : null;
    if (beforeId !== null && !/^[1-9][0-9]{0,18}$/.test(beforeId)) return sessionError(400, "INVALID_CURSOR", "Invalid responsibility cursor");
    const before = method === "GET" && ((segments.length === 1 && segments[0] === "recurrences") || (segments.length === 2 && segments[1] === "ai-event-history"))
      ? new URL(request.url).searchParams.get("before") : null;
    if (before !== null && !isUuid(before)) return sessionError(400, "INVALID_CURSOR", "Invalid history cursor");
    const provider = method === "GET" && segments.at(-1) === "conference-requests" ? new URL(request.url).searchParams.get("provider") : null;
    if (provider !== null && !["dingtalk", "tencent_meeting"].includes(provider)) return sessionError(400, "INVALID_PROVIDER", "Invalid conference provider");
    let path = `/api/projects/${encodeURIComponent(projectId)}/meetings${
      suffix ? `/${suffix}` : ""
    }${cursor ? `?cursor=${encodeURIComponent(cursor)}` : beforeVersion ? `?before_version=${beforeVersion}` : beforeId ? `?before_id=${beforeId}` : before ? `?before=${before}` : ""}`;
    if (minutesRecord) path += `?record_id=${encodeURIComponent(minutesRecord)}`;
    if (segments[1] === "ai-minutes-drafts") {
      const params = new URL(request.url).searchParams;
      const kind = params.get("kind") ?? "minutes";
      if (!["minutes", "actions", "decisions"].includes(kind)) return sessionError(400, "INVALID_DRAFT_KIND", "Invalid meeting draft kind");
      path += `${path.includes("?") ? "&" : "?"}kind=${kind}`;
      const draftBefore = method === "GET" ? params.get("before") : null;
      if (draftBefore !== null) {
        const valid = segments.at(-1) === "history" ? /^[1-9][0-9]{0,8}$/.test(draftBefore) : segments.length === 2 && isUuid(draftBefore);
        if (!valid) return sessionError(400, "INVALID_DRAFT_CURSOR", "Invalid draft cursor");
        path += `&before=${encodeURIComponent(draftBefore)}`;
      }
    }
    if (provider) path += `${path.includes("?") ? "&" : "?"}provider=${provider}`;
    if (method === "GET" && segments.length === 3 && segments[0] === "planning" && segments[2] === "runs") {
      const runBefore = new URL(request.url).searchParams.get("before");
      if (runBefore !== null && !isUuid(runBefore)) return sessionError(400, "INVALID_RUN_CURSOR", "Invalid meeting run cursor");
      if (runBefore) path += `${path.includes("?") ? "&" : "?"}before=${runBefore}`;
    }
    if (method === "GET" && segments.length === 1 && ["planning", "planning-options"].includes(segments[0])) {
      const params = new URL(request.url).searchParams;
      const extra = new URLSearchParams();
      if (segments[0] === "planning") {
        const brief = params.get("brief_id");
        if (brief !== null && !isUuid(brief)) return sessionError(400, "INVALID_BRIEF", "Invalid meeting brief");
        if (brief) extra.set("brief_id", brief);
      } else {
        const kind = params.get("kind") ?? "issue", query = params.get("q") ?? "", before = params.get("before");
        if (!["task", "issue", "risk", "decision"].includes(kind) || query.length > 200 || (before !== null && !isUuid(before))) return sessionError(400, "INVALID_SOURCE_QUERY", "Invalid meeting source query");
        extra.set("kind", kind); extra.set("q", query); if (before) extra.set("before", before);
      }
      if (extra.size) path += `${path.includes("?") ? "&" : "?"}${extra}`;
    }
    return forwardJson(
      await pdosApiFetch(path, {
        method,
        headers: {
          Authorization: `Bearer ${token}`,
          ...(body ? { "Content-Type": "application/json" } : {}),
        },
        ...(body ? { body: JSON.stringify(body) } : {}),
      }),
    );
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) {
      return sessionError(400, "INVALID_REQUEST", "Valid JSON request required");
    }
    return sessionError(503, "MEETING_SERVICE_UNAVAILABLE", "Meeting service unavailable");
  }
}
