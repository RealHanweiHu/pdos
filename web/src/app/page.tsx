import { AppShell } from "@/features/shell/app-shell";
import { cookies, headers } from "next/headers";
import { redirect } from "next/navigation";
import { loadLocalPreview, localPreviewHost, workspacePreview } from "@/lib/server/local-preview-server";
export default async function Page() {
  const host = (await headers()).get("host");
  const preview = Boolean(process.env.PDOS_NEXT_PREVIEW_CONFIG) && localPreviewHost(host);
  if (preview) {
    const config = await loadLocalPreview(host).catch(() => null);
    const workspace = config && workspacePreview(config);
    if (!workspace || (await cookies()).get("pdos-next-session")?.value !== workspace.role.token) redirect("/preview");
  }
  return <AppShell localPreview={preview} />;
}
