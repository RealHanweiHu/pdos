"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord } from "@/components/workspace-api";
const states: Record<string, string> = { extracted: "已抽取", container: "正文组合", attachment_not_read: "附件或嵌入邮件未读取", alternative_not_selected: "同内容的另一格式未选取", unsupported_part: "此格式未读取", invalid_multipart: "正文组合结构错误", body_unavailable: "正文不可用", malformed_part: "编码或结构有误，未采用正文", decode_failed: "无法按声明编码读取", empty_body: "未得到正文文字" };
const headers: Record<string, string> = { from: "发件人原文", sender: "发送者原文", "reply-to": "回复地址", to: "收件人原文", cc: "抄送", bcc: "密送", subject: "主题", date: "邮件日期原文", "message-id": "原消息标识", "in-reply-to": "回复标识", references: "引用标识" };
const show = (value: unknown) => value == null ? "未提供" : String(value);
export function EmailExtractionNotice({ metadata }: { metadata: unknown }) {
  const [page, setPage] = useState(0), [headerPage, setHeaderPage] = useState(0);
  if (!isRecord(metadata) || metadata.kind !== "email") return null;
  const parts = Array.isArray(metadata.parts) ? metadata.parts.filter(isRecord) : [], originalHeaders = Array.isArray(metadata.headers) ? metadata.headers.filter(isRecord) : [];
  const unread = parts.filter(part => !["extracted", "container"].includes(String(part.status)));
  return <section className="space-y-2 rounded-md border p-3 text-xs">
    <p className="font-medium">邮件读取范围 · {parts.filter(part => part.status === "extracted").length} 个正文部分已抽取，{unread.length} 个部分未读取或未采用</p>
    <p>保留整封EML原件；当前仅抽取邮件头和所选内嵌正文。HTML只取文字，图片、链接目标、附带文件及嵌入邮件未读取。发件人和日期是原文声明，不代表身份核验或当前批准。</p>
    {Array.isArray(metadata.defects) && metadata.defects.length > 0 && <p className="text-destructive">邮件结构缺项：{metadata.defects.map(String).join("、")}。请对照原件核对可读范围。</p>}
    <details><summary className="cursor-pointer">邮件头原值与解码文字</summary>{originalHeaders.slice(headerPage * 20, headerPage * 20 + 20).map((item, i) => <div className="my-2 space-y-1 border-t pt-2" key={`${item.locator}-${i}`}><p className="font-medium">{headers[String(item.name).toLowerCase()] ?? show(item.name)} · {show(item.locator)} · {states[String(item.status)] ?? show(item.status)}</p><p className="max-h-32 overflow-auto whitespace-pre-wrap break-words">{show(item.decoded)}</p><details><summary>邮件头原文（不可解码字节显示转义）</summary><pre className="max-h-32 overflow-auto whitespace-pre-wrap break-words">{show(item.raw)}</pre></details></div>)}{originalHeaders.length > 20 && <div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={!headerPage} onClick={() => setHeaderPage(p => p - 1)}>上一组邮件头</Button><span>{headerPage + 1}/{Math.ceil(originalHeaders.length / 20)}</span><Button type="button" size="sm" variant="outline" disabled={(headerPage + 1) * 20 >= originalHeaders.length} onClick={() => setHeaderPage(p => p + 1)}>下一组邮件头</Button></div>}</details>
    <details><summary className="cursor-pointer">正文及附件读取清单</summary>{parts.slice(page * 20, page * 20 + 20).map(part => <p key={String(part.path)} className="my-2 break-words">部分 {show(part.path)} · {show(part.media_type)} · {part.filename ? `${show(part.filename)} · ` : ""}{states[String(part.status)] ?? show(part.status)}{part.charset ? ` · 声明编码 ${show(part.charset)}` : ""}{Number(part.images_not_read) > 0 ? ` · ${show(part.images_not_read)} 张图片未读取` : ""}{Array.isArray(part.defects) && part.defects.length > 0 ? ` · 结构提示 ${part.defects.map(String).join("、")}` : ""}</p>)}{parts.length > 20 && <div className="flex gap-2"><Button type="button" size="sm" variant="outline" disabled={!page} onClick={() => setPage(p => p - 1)}>上一组部分</Button><span>{page + 1}/{Math.ceil(parts.length / 20)}</span><Button type="button" size="sm" variant="outline" disabled={(page + 1) * 20 >= parts.length} onClick={() => setPage(p => p + 1)}>下一组部分</Button></div>}</details>
  </section>;
}
