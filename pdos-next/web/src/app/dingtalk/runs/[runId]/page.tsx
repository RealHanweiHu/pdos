import { notFound } from "next/navigation";
import { AppShell } from "@/components/app-shell";

/** IDs only. The normal login and original personal Run/source READ run again. */
export default async function Page({ params, searchParams }: { params: Promise<{ runId: string }>; searchParams?: Promise<{ category?: string | string[] }> }) {
  const { runId } = await params;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(runId)) notFound();
  const categoryId = (await searchParams)?.category;
  if (categoryId !== undefined && (typeof categoryId !== "string" || !/^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(categoryId))) notFound();
  return <AppShell runPage={{ runId, ...(categoryId ? { categoryId } : {}) }} />;
}
