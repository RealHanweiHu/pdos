import {
  currentSessionToken,
  forwardJson,
  pdosApiFetch,
  sessionError,
} from "@/lib/pdos-api";

export async function forwardProjectGateOrDocuments({
  context,
  surface,
}: {
  context: { params: Promise<{ projectId: string }> };
  surface: "gates" | "documents";
}) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const { projectId } = await context.params;
    const path =
      surface === "gates"
        ? `/api/projects/${encodeURIComponent(projectId)}/gates`
        : `/api/ai/projects/${encodeURIComponent(projectId)}/documents`;
    return forwardJson(
      await pdosApiFetch(path, { headers: { Authorization: `Bearer ${token}` } }),
    );
  } catch {
    return sessionError(503, "PROJECT_SURFACE_UNAVAILABLE", "Project surface unavailable");
  }
}

export async function forwardDocumentUpload(request: Request) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const contentType = request.headers.get("content-type") ?? "";
  if (!contentType.startsWith("multipart/form-data")) {
    return sessionError(400, "INVALID_REQUEST", "Multipart form data is required");
  }
  try {
    const body = await request.formData();
    return forwardJson(
      await pdosApiFetch("/api/ai/analyze-document", {
        method: "POST",
        headers: { Authorization: `Bearer ${token}` },
        body,
      }),
    );
  } catch {
    return sessionError(503, "DOCUMENT_SERVICE_UNAVAILABLE", "Document service unavailable");
  }
}
