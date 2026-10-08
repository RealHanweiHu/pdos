import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, test, vi } from "vitest";
import { ProductProposals } from "./product-proposals";
import { request, type ProductCatalog, type Workspace } from "./product-work-api";
import type { Proposal } from "./proposal-types";
import type { CategoryBundle } from "./category-types";

vi.mock("./product-work-api", async importOriginal => ({ ...await importOriginal<typeof import("./product-work-api")>(), request:vi.fn() }));
const base = "spaces/11111111-1111-4111-8111-111111111111";
const row: Proposal = { id:"22222222-2222-4222-8222-222222222222",title:"骑行充气泵",entry_kind:"odm",brief:"续航30分钟",state:"draft",version:1,payload_digest:"a".repeat(64),owner_user_id:"owner",reviewer_user_id:null,product_line_id:null,updated_at:"2026-10-06T00:00:00Z",can_edit:true,can_decide:false,source_catalog:[{id:"brief",label:"客户需求片段",digest:"b".repeat(64),locator:"brief"}],history:[],ai_history:[],decisions:[],document:{narrative:"客户希望便携",specifications:[{id:"runtime",label:"续航",value:"",unit:"分钟",conditions:"",state:"unknown",source_ids:[]}],options:[],differences:[],questions:["销售地区？"],risks:[]} };
const workspace = { space:{id:base.split("/")[1], category_line_id:"line-1"}, current_user_id:"owner",can_contribute:true,members:[{id:"owner",display_name:"产品负责人",access:"manager"}] } as Workspace;
const catalog: ProductCatalog = {nodes:[{id:"line-1",product_line_id:"line-1",market_space_id:base.split("/")[1],parent_id:null,code:"car",level:"line",name:"汽车充气泵",lifecycle:"proposed",owner_user_id:"owner",regions:[],channels:[],version:1,payload_digest:"c".repeat(64)}],members:[],can_create_line:true,line_access:{}};
const props = {base,workspace,catalog,evidence:[],proposalId:row.id,onCatalogChanged:vi.fn(async()=>{}), onAuthorityLost:vi.fn(),onPendingChange:vi.fn()};
const category: CategoryBundle = {category_id:workspace.space.id,category_name:"汽车充气泵",regions:[],parameters:[],knowledge:[],competitors:[],segments:[],test_template:{items:[]},digest:"d".repeat(64)};
afterEach(cleanup);
beforeEach(() => { vi.clearAllMocks(); window.history.replaceState(null,"","/product-work"); });

test("AI rewrites the editable document, one save commits, submission remains a separate gate", async () => {
  const generated = {...row.document,narrative:"AI编辑稿",specifications:[{...row.document.specifications[0],value:"30",state:"ai_draft" as const,source_ids:["brief"]}]};
  let current = structuredClone(row);
  vi.mocked(request).mockImplementation(async (path,method,body) => {
    if (path.endsWith("/ai")) return {status:"prepared",run_id:"run-1",document:generated,completed:["起草了续航规格"],needs_answers:["目标价格？"]};
    if (path.endsWith("/changes")) { current = {...current,version:2,document:(body as {document:Proposal["document"]}).document}; return current; }
    return current;
  });
  render(<ProductProposals {...props}/>);
  await screen.findByDisplayValue("客户希望便携");
  fireEvent.change(screen.getByLabelText("交代小Pai修改提案"),{target:{value:"续航改成30分钟"}});
  fireEvent.click(screen.getByRole("button",{name:"改写编辑稿"}));
  await screen.findByDisplayValue("AI编辑稿");
  expect(screen.getByText("起草了续航规格")).toBeInTheDocument();
  expect(screen.getByText("目标价格？")).toBeInTheDocument();
  expect(screen.getByRole("button",{name:"提交立项评审"})).toBeDisabled();
  expect(vi.mocked(request).mock.calls.some(c => c[0].endsWith("/changes"))).toBe(false);
  fireEvent.click(screen.getByRole("button",{name:"保存草稿"}));
  await waitFor(() => expect(screen.getByRole("button",{name:"提交立项评审"})).toBeEnabled());
  expect(vi.mocked(request).mock.calls.find(c => c[0].endsWith("/changes"))?.[2]).toMatchObject({ai_run_id:"run-1"});
});

test("a failed model request retains the document and retry uses the original identity", async () => {
  vi.mocked(request).mockImplementation(async path => {
    if (path.endsWith("/ai")) throw new Error("连接中断，可重试原请求");
    return structuredClone(row);
  });
  render(<ProductProposals {...props}/>);
  await screen.findByDisplayValue("客户希望便携");
  fireEvent.click(screen.getByRole("button",{name:"让小Pai先起草"}));
  await screen.findByText("连接中断，可重试原请求");
  fireEvent.click(screen.getByRole("button",{name:"让小Pai先起草"}));
  await waitFor(() => expect(vi.mocked(request).mock.calls.filter(c => c[0].endsWith("/ai"))).toHaveLength(2));
  const calls = vi.mocked(request).mock.calls.filter(c => c[0].endsWith("/ai"));
  expect(calls[0][2]).toEqual(calls[1][2]);
  expect(screen.getByDisplayValue("客户希望便携")).toBeInTheDocument();
});

test("category landing renders shared资料 directly without proposal cards or creation form", async () => {
  vi.mocked(request).mockImplementation(async path => path.endsWith("/shared") ? category : {items:[]});
  render(<ProductProposals {...props} proposalId={null}/>);
  await screen.findByRole("heading", {name:"品类资料"});
  expect(screen.queryByText("从一个需求开始")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name:"新建提案"})).not.toBeInTheDocument();
  expect(vi.mocked(request).mock.calls.some(c=>c[0].endsWith("/proposals"))).toBe(false);
});

test("authority loss clears the editable document", async () => {
  const { ProductRequestError } = await import("./product-work-api");
  vi.mocked(request).mockImplementation(async path => {
    if (path.endsWith("/changes")) throw new ProductRequestError("权限已变化",403);
    return structuredClone(row);
  });
  render(<ProductProposals {...props}/>);
  fireEvent.change(await screen.findByLabelText("提案叙述"),{target:{value:"新稿"}});
  fireEvent.click(screen.getByRole("button",{name:"保存草稿"}));
  await waitFor(() => expect(props.onAuthorityLost).toHaveBeenCalledWith("权限已变化"));
  expect(screen.queryByLabelText("提案叙述")).not.toBeInTheDocument();
});


test("old unbound proposal deep links remain editable", async () => {
  vi.mocked(request).mockImplementation(async () => structuredClone(row));
  render(<ProductProposals {...props}/>);
  expect(await screen.findByLabelText("提案叙述")).toHaveValue("客户希望便携");
});
