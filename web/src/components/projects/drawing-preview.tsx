"use client";
/* eslint-disable @next/next/no-img-element -- Render the locally generated SVG blob directly. */

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";

type Mesh = { name: string; positions: Float32Array; indices: Uint32Array; normals: Float32Array | null; color: number[] | null; faces: { first: number; last: number; color: number[] | null }[] };
type Common = { warnings: string[]; warningCount: number; parser: string };
type Step = Common & { kind: "step"; meshes: Mesh[]; units: "mm"; vertices: number; triangles: number };
type Gerber = Common & { kind: "gerber"; svg: string; units: "mm" | "in"; width: number; height: number; viewBox: number[] };
type Result = Step | Gerber;

function StepScene({ data }: { data: Step }) {
  const host = useRef<HTMLDivElement | null>(null);
  const api = useRef<{ view: (direction: string) => void; visible: (index: number, value: boolean) => void } | null>(null);
  const [bounds, setBounds] = useState<number[] | null>(null), [hidden, setHidden] = useState<number[]>([]), [error, setError] = useState("");
  useEffect(() => {
    const element = host.current; if (!element) return;
    let active = true; let dispose = () => {};
    void (async () => { try {
      const THREE = await import("three"), { OrbitControls } = await import("three/addons/controls/OrbitControls.js");
      if (!active) return;
      const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2)); renderer.setClearColor(0xf4f4f5);
      renderer.domElement.setAttribute("role", "img"); renderer.domElement.setAttribute("aria-label", "STEP三维预览，拖动旋转、双指或滚轮缩放");
      element.appendChild(renderer.domElement);
      const scene = new THREE.Scene(), group = new THREE.Group(); scene.add(group);
      const camera = new THREE.PerspectiveCamera(45, 1, 0.01, 1000000);
      const controls = new OrbitControls(camera, renderer.domElement); controls.enableDamping = false;
      const ambient = new THREE.HemisphereLight(0xffffff, 0x777777, 2), light = new THREE.DirectionalLight(0xffffff, 3); light.position.set(2,3,4); scene.add(ambient,light);
      const materials: InstanceType<typeof THREE.MeshStandardMaterial>[] = [], geometries: InstanceType<typeof THREE.BufferGeometry>[] = [], meshes: InstanceType<typeof THREE.Mesh>[] = [];
      const render = () => renderer.render(scene,camera);
      const resize = new ResizeObserver(() => { const width = Math.max(1,element.clientWidth), height = Math.max(360,element.clientHeight); renderer.setSize(width,height); camera.aspect=width/height; camera.updateProjectionMatrix(); render(); });
      dispose = () => { resize.disconnect(); controls.dispose(); for (const geometry of geometries) geometry.dispose(); for (const material of materials) material.dispose(); renderer.dispose(); renderer.forceContextLoss(); renderer.domElement.remove(); scene.clear(); api.current = null; };
      const color = (values: number[] | null) => values?.length === 3 && values.every(v => Number.isFinite(v) && v>=0 && v<=1) ? new THREE.Color().setRGB(values[0],values[1],values[2],THREE.SRGBColorSpace) : new THREE.Color(0x9ca3af);
      for (const source of data.meshes) {
        const geometry = new THREE.BufferGeometry(); geometries.push(geometry);
        geometry.setAttribute("position", new THREE.BufferAttribute(source.positions,3)); geometry.setIndex(new THREE.BufferAttribute(source.indices,1));
        if (source.normals) geometry.setAttribute("normal",new THREE.BufferAttribute(source.normals,3)); else geometry.computeVertexNormals();
        const meshMaterials = [new THREE.MeshStandardMaterial({ color: color(source.color), roughness: 0.7, metalness: 0, side: THREE.DoubleSide })];
        const faces = [...source.faces].sort((a,b) => a.first-b.first); let start = 0;
        for (const face of faces) {
          const first = face.first*3, end = (face.last+1)*3;
          if (!Number.isInteger(first) || !Number.isInteger(end) || first<start || end>source.indices.length || end<=first) continue;
          if (first>start) geometry.addGroup(start,first-start,0);
          let materialIndex = 0;
          if (face.color) { meshMaterials.push(new THREE.MeshStandardMaterial({ color: color(face.color), roughness: 0.7, metalness: 0, side: THREE.DoubleSide })); materialIndex=meshMaterials.length-1; }
          geometry.addGroup(first,end-first,materialIndex); start=end;
        }
        if (start<source.indices.length) geometry.addGroup(start,source.indices.length-start,0);
        materials.push(...meshMaterials); const mesh = new THREE.Mesh(geometry,meshMaterials); mesh.name=source.name; group.add(mesh); meshes.push(mesh);
      }
      const box = new THREE.Box3().setFromObject(group), size = box.getSize(new THREE.Vector3()), center = box.getCenter(new THREE.Vector3());
      if (box.isEmpty() || ![size.x,size.y,size.z].every(Number.isFinite)) throw new Error("模型范围无效，不能正确定位视图");
      const radius = Math.max(size.length()/2,0.01); camera.near=Math.max(radius/10000,0.000001); camera.far=radius*100; camera.updateProjectionMatrix();
      const fit = (direction: string) => { const directions: Record<string, number[]> = { iso:[1,1,1],front:[0,0,1],top:[0,1,0],right:[1,0,0] }; const v=directions[direction] ?? directions.iso; camera.up.set(0,1,0); if (direction === "top") camera.up.set(0,0,-1); camera.position.copy(center).add(new THREE.Vector3(v[0],v[1],v[2]).normalize().multiplyScalar(radius*3.4)); controls.target.copy(center); controls.update(); render(); };
      api.current = { view: fit, visible: (index,value) => { if (meshes[index]) meshes[index].visible=value; render(); } };
      controls.addEventListener("change",render); resize.observe(element); renderer.setSize(Math.max(1,element.clientWidth),Math.max(360,element.clientHeight)); camera.aspect=Math.max(1,element.clientWidth)/Math.max(360,element.clientHeight); camera.updateProjectionMatrix(); fit("iso");
      if (active) setBounds([size.x,size.y,size.z]);
    } catch (e) { dispose(); if (active) setError(e instanceof Error ? e.message : "此设备暂不能显示三维图形"); } })();
    return () => { active=false; dispose(); };
  }, [data]);
  return <div className="space-y-2"><div className="flex flex-wrap gap-2">{Object.entries({iso:"整体",front:"正视",top:"俯视",right:"右视"}).map(([key,label]) => <Button key={key} type="button" size="sm" variant="outline" onClick={() => api.current?.view(key)}>{label}</Button>)}</div><div ref={host} className="h-[60vh] min-h-90 w-full overflow-hidden rounded-md border bg-zinc-100"/>{error && <p role="alert" className="text-sm text-destructive">{error}。请下载原件在工程工具中核对。</p>}{bounds && <p className="text-xs text-muted-foreground">预览网格外框约 {bounds.map(n=>n.toFixed(3)).join(" × ")} mm。拖动旋转，滚轮/双指缩放，右键拖动平移。预览网格不能用于精确尺寸、干涉或制造放行判断。</p>}<details className="text-sm"><summary>显示网格（{data.meshes.length}）{hidden.length ? ` · 已隐藏 ${hidden.length}` : ""}</summary><div className="max-h-48 space-y-1 overflow-auto p-2">{data.meshes.map((m,i) => <label key={i} className="flex items-center gap-2"><input type="checkbox" checked={!hidden.includes(i)} onChange={e=>{const visible=e.target.checked;api.current?.visible(i,visible);setHidden(old=>visible?old.filter(n=>n!==i):[...old,i]);}}/>{m.name} · {m.indices.length/3} 个三角面</label>)}</div></details></div>;
}
function GerberImage({ data }: { data: Gerber }) {
  const [url, setUrl] = useState(""), [zoom, setZoom] = useState(1), [mirror, setMirror] = useState(false);
  useEffect(() => { const result = URL.createObjectURL(new Blob([data.svg],{type:"image/svg+xml"})); queueMicrotask(()=>setUrl(result)); return ()=>URL.revokeObjectURL(result); }, [data.svg]);
  return <div className="space-y-2"><div className="flex flex-wrap items-center gap-2"><Button type="button" size="sm" variant="outline" disabled={zoom<=0.25} onClick={()=>setZoom(n=>Math.max(0.25,n/1.5))}>缩小</Button><Button type="button" size="sm" variant="outline" disabled={zoom>=8} onClick={()=>setZoom(n=>Math.min(8,n*1.5))}>放大</Button><Button type="button" size="sm" variant="outline" onClick={()=>{setZoom(1);setMirror(false);}}>复位</Button><label className="flex gap-1 text-sm"><input type="checkbox" checked={mirror} onChange={e=>setMirror(e.target.checked)}/>镜像显示</label></div><div className="h-[60vh] min-h-90 overflow-auto rounded-md border bg-zinc-100 p-3">{url && <img src={url} alt="Gerber单层图形预览" style={{width:`${zoom*100}%`,maxWidth:"none",height:"auto",transform:mirror?"scaleX(-1)":undefined}}/>}</div><p className="text-xs text-muted-foreground">图层外框 {data.width.toFixed(4)} × {data.height.toFixed(4)} {data.units} · 坐标原点 ({(data.viewBox[0]/1000).toFixed(4)}, {(data.viewBox[1]/1000).toFixed(4)})。{mirror ? "当前已镜像。" : "当前未镜像。"}单层预览不表示完整板层、钻孔或制造文件组。</p></div>;
}

export default function DrawingPreview({ source, kind }: { source: Blob; kind: "step" | "gerber" }) {
  const [data, setData] = useState<Result | null>(null), [error, setError] = useState(""), [attempt, setAttempt] = useState(0), [busy, setBusy] = useState(true);
  const worker = useRef<Worker | null>(null), timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(() => {
    let active=true; let current: Worker;
    try { current=new Worker("/workers/drawing.worker.js"); } catch { queueMicrotask(()=>{if(active){setError("此浏览器未能启动图纸解析器，请下载原件核对");setBusy(false);}}); return()=>{active=false;}; }
    worker.current=current;
    const stop=()=>{current.terminate();if(worker.current===current)worker.current=null;};
    const timeout=setTimeout(()=>{stop();if(active){setError("解析超过60秒，已停止；原件仍可下载核对。");setBusy(false);}},60000);
    timer.current=timeout;
    current.onmessage=event=>{if(worker.current!==current)return;clearTimeout(timeout);stop();if(!active)return;const result=event.data;if(result.error){setError(String(result.error));setBusy(false);}else if(result.kind===kind){setData(result as Result);setError("");setBusy(false);}else{setError("解析器返回了不匹配的文件格式");setBusy(false);}};
    current.onerror=()=>{if(worker.current!==current)return;clearTimeout(timeout);stop();if(active){setError("图纸解析器暂不可用，请重试或下载原件核对");setBusy(false);}};
    void source.arrayBuffer().then(buffer=>{if(active&&worker.current===current)current.postMessage({kind,buffer},[buffer]);}).catch(()=>{clearTimeout(timeout);stop();if(active){setError("原件读取中断，请重新打开文档");setBusy(false);}});
    return()=>{active=false;clearTimeout(timeout);stop();};
  }, [source,kind,attempt]);
  return <div className="space-y-3">{busy && <div className="flex flex-wrap items-center gap-2 text-sm"><p role="status">正在本机解析{kind === "step" ? "三维几何" : "图层"}…</p><Button type="button" size="sm" variant="outline" onClick={()=>{worker.current?.terminate();worker.current=null;if(timer.current)clearTimeout(timer.current);setBusy(false);setError("已停止本次解析，原件仍保留。");}}>停止解析</Button></div>}{error && <div className="space-y-2"><p role="alert" className="text-sm text-destructive">{error}</p><Button type="button" size="sm" variant="outline" onClick={()=>{setData(null);setError("");setBusy(true);setAttempt(n=>n+1);}}>重新解析</Button></div>}{data && <>{data.kind === "step" ? <StepScene data={data}/> : <GerberImage data={data}/>}<p className="text-xs text-muted-foreground">{data.warningCount ? `解析器返回 ${data.warningCount} 条提示，请结合原件核对。` : "已生成预览，尚未作工程正确性确认。"}</p>{data.warnings.length>0 && <details className="text-xs"><summary>查看解析提示{data.warningCount>data.warnings.length ? "（仅显示前20条）" : ""}</summary>{data.warnings.map((w,i)=><p key={i} className="whitespace-pre-wrap break-words py-1">{w}</p>)}</details>}<details className="text-xs text-muted-foreground"><summary>查看器版本与范围</summary><p>{data.parser}{data.kind === "step" ? ` · ${data.triangles}个三角面，输出单位mm；采用固定预览精度。` : " · RS-274X单层，要求文件明确单位及坐标格式。"}</p><a className="underline" href={data.kind === "step" ? "/vendor/drawings/occt-import-js-0.0.23/license.occt-import-js.txt" : "/vendor/drawings/gerber-to-svg-4.2.8/gerber-to-svg.min.js.LICENSE.txt"} target="_blank" rel="noreferrer">开源查看器许可</a></details></>}</div>;
}
