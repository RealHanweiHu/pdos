"use client";

export type ToolingResourceState = {
  state: string;
  resource?: { id: string; name: string; kind: string };
  capacity: { id: string; version: number; parallel_units: string; window_start: string; window_end: string; basis: string } | null;
  nodes: { id: string; kind: string; is_round: boolean; title: string | null }[];
  reservations: { id: string; node_id: string; state: string; version: number; window_start: string; window_end: string; parallel_units: string; occupancy_policy: string; uses_latest_capacity: boolean }[];
  has_more_reservations?: boolean;
};
const states: Record<string, string> = { proposed: "待确认提案", reserved: "已预约", released: "已释放", cancelled: "已取消" };

export function ToolingResourceView({ projectId, value }: { projectId: string; value: ToolingResourceState }) {
  if (!value.resource) return <p className="text-xs text-muted-foreground">尚未关联实际资源；容量与预约待核对。</p>;
  return <details className="space-y-2 rounded-md border p-2 text-xs">
    <summary className="cursor-pointer">实际资源：{value.resource.name} · 容量与相关预约</summary>
    {value.capacity ? <><p>当前声明容量 v{value.capacity.version}：{value.capacity.parallel_units} 并行单位 · {new Date(value.capacity.window_start).toLocaleString()} — {new Date(value.capacity.window_end).toLocaleString()}</p><p>{value.capacity.basis}</p></> : <p>尚无已发布容量，请先在资源管理中配置。</p>}
    <p className="text-muted-foreground">声明容量未扣除实际占用。提出预约后，由原预约流程核对全局占用、旧资源归并和资源日历，再独立确认。工装可用证据与资源预约分别办理。</p>
    <div className="flex flex-wrap gap-2">{value.nodes.map(node => <a key={node.id} className="text-primary underline" href={`/projects?project=${projectId}&tab=overview&reservation_node_id=${node.id}&reservation_resource_id=${value.resource!.id}#resource-reservations`}>{node.is_round ? "本工装轮次" : node.title ?? `需用节点 ${node.id}`} · 提出预约</a>)}</div>
    {!value.nodes.length && <p>请先登记工装排程节点或关联实际需用节点，再提出预约。</p>}
    <p>本资源在本轮及所选需用节点上的预约：</p>
    {value.reservations.map(item => <div className="border-l pl-2" key={item.id}><a className="text-primary underline" href={`/projects?project=${projectId}&tab=overview&resource_reservation_id=${item.id}#reservation-${item.id}`}>{states[item.state] ?? item.state} · v{item.version}</a><p>{new Date(item.window_start).toLocaleString()} — {new Date(item.window_end).toLocaleString()} · {item.parallel_units} 单位 · {item.occupancy_policy === "working_only" ? "工作时段占用" : "全窗口占用"}</p>{!item.uses_latest_capacity && <p>原预约固定容量已有新版本；调整时须重新核对。</p>}</div>)}
    {!value.reservations.length && <p>尚无匹配预约；关联资源本身不会占用容量。</p>}
    {value.has_more_reservations && <p>显示最近20条，完整预约保留在项目预约入口。</p>}
  </details>;
}
