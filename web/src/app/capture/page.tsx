import { Suspense } from "react";
import { FieldCaptureWorkspace } from "@/components/capture/field-capture-workspace";
export const metadata = { title: "现场采集 · PDOS" };
export default function Page() {
  return <Suspense fallback={<p className="p-6">正在打开现场采集…</p>}><FieldCaptureWorkspace /></Suspense>;
}
