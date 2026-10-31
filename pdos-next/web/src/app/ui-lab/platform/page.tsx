import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import type { Screen } from "./design-data";
import { PlatformPreview } from "./platform-preview";
import { readNpiTaskCatalog } from "./npi-task-catalog";
export const metadata: Metadata = {
  title: "PDOS · 完整体验设计",
  robots: { index: false, follow: false },
};
export const dynamic = "force-dynamic";
export default async function Page({
  searchParams,
}: {
  searchParams: Promise<{ view?: string; role?: string }>;
}) {
  if (
    !/^(localhost|127\.0\.0\.1)(:\d+)?$/.test(
      (await headers()).get("host") ?? "",
    )
  )
    notFound();
  const params = await searchParams;
  const view = params.view;
  const initialScreen: Screen =
    view &&
    [
      "pai",
      "inbox",
      "projects",
      "sets",
      "plan",
      "tasks",
      "now",
      "category",
      "proposal",
    ].includes(view)
      ? (view as Screen)
      : view === "portfolio"
        ? "plan"
        : "work";
  return (
    <PlatformPreview
      initialScreen={initialScreen}
      initialRole={
        params.role === "product" ||
        ["category", "proposal"].includes(initialScreen)
          ? "product"
          : "lead"
      }
      taskCatalog={await readNpiTaskCatalog()}
    />
  );
}
