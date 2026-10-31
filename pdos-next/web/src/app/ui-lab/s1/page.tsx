import type { Metadata } from "next";
import { headers } from "next/headers";
import { notFound } from "next/navigation";
import { S1DesignLab } from "./s1-design-lab";

export const metadata: Metadata = { title: "S1 界面方案 · PDOS", robots: { index: false, follow: false } };
export const dynamic = "force-dynamic";

export default async function Page({ searchParams }: { searchParams: Promise<Record<string, string | string[] | undefined>> }) {
  if (!/^(localhost|127\.0\.0\.1)(:\d+)?$/.test((await headers()).get("host") ?? "")) notFound();
  const query = await searchParams;
  return <S1DesignLab initialDirection={query.direction === "b" || query.direction === "c" ? query.direction : "a"} initialView={query.view === "proposal" || query.view === "project" ? query.view : "work"} />;
}
