import type { Metadata } from "next";
import { cookies, headers } from "next/headers";
import { notFound, redirect } from "next/navigation";
import { CurrentMilestones } from "@/components/plan/current-milestones";
import { PreviewGuide } from "@/components/preview-guide";
import { parseCurrentProgress } from "@/lib/current-progress";
import { readPlanSource } from "@/lib/plan-source";
import { loadLocalPreview, workspacePreview } from "@/lib/local-preview-server";
import { ProductPreviewEntry } from "@/components/product-preview-entry";

export const dynamic = "force-dynamic";
export const metadata: Metadata = { title: "本地预览 · PDOS" };

export default async function PreviewPage() {
  const host = (await headers()).get("host") ?? "";
  if (!/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host) || !(process.env.PDOS_NEXT_LOCAL_SESSION || process.env.PDOS_NEXT_PREVIEW_CONFIG)) notFound();
  const preview = await loadLocalPreview(host).catch(() => "unavailable" as const);
  if (preview === "unavailable") return <main className="panel m-8" role="alert">综合预览配置不可用或会话已过期，需要重新准备本地演示环境。</main>;
  if (preview) {
    const workspace = workspacePreview(preview);
    if (!workspace) return <main className="panel m-8" role="alert">产品预览工作区尚未配置。</main>;
    const token = (await cookies()).get("pdos-next-session")?.value;
    if (token === workspace.role.token) redirect(workspace.href);
    return <ProductPreviewEntry />;
  }
  const source = await readPlanSource();
  const progress = "failure" in source
    ? <p role="alert" className="panel">{source.failure}</p>
    : <CurrentMilestones progress={parseCurrentProgress(source.markdown)} />;
  return <PreviewGuide progress={progress} />;
}
