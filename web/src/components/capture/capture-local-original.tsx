"use client";
/* eslint-disable @next/next/no-img-element -- Private local Blob previews cannot use the image optimizer. */

import { useEffect, useRef } from "react";

export function CaptureLocalOriginal({ file }: { file: File }) {
  const image = useRef<HTMLImageElement>(null), audio = useRef<HTMLAudioElement>(null);
  const download = useRef<HTMLAnchorElement>(null);
  useEffect(() => {
    const url = URL.createObjectURL(file);
    const media = image.current ?? audio.current;
    const player = audio.current, link = download.current;
    if (media) media.src = url;
    if (link) link.href = url;
    return () => { player?.pause(); media?.removeAttribute("src"); link?.removeAttribute("href"); URL.revokeObjectURL(url); };
  }, [file]);
  const photo = file.type.startsWith("image/") || /\.(jpe?g|png|webp)$/i.test(file.name);
  return <div className="space-y-2 rounded-md bg-muted/30 p-3">
    <p className="break-all text-sm">当前原件：{file.name} · {(file.size / 1024 / 1024).toFixed(2)} MiB</p>
    {photo ? <img ref={image} alt="待保存的现场照片" className="max-h-80 max-w-full rounded-md object-contain"/> : <audio ref={audio} controls preload="metadata" className="w-full"/>}
    <a ref={download} download={file.name} className="text-sm text-primary underline">下载原件备份</a>
    <p className="text-xs text-muted-foreground">文件暂存在当前页面。刷新或离开前，请完成保存或先下载备份。</p>
  </div>;
}
