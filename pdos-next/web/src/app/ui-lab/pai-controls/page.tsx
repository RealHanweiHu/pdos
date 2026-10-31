import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { PaiControlsPreview } from "./preview";

export const metadata: Metadata = { title: "小Pai · 运行控件预览", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";

export default async function Page() {
  if (!/^(localhost|127\.0\.0\.1)(:\d+)?$/.test((await headers()).get("host") ?? "")) notFound();
  return <PaiControlsPreview />;
}
