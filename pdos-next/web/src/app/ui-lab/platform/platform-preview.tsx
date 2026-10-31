"use client";
/* THESIS: 从本人要完成的事进入对象，以同一办理方式贯穿研发全流程。
OWN-WORLD: 沿用冻结的 Geist、橙色、8px 与双主题；列表、留白和按需详情表达层次。
STORY: 看见责任与期限，打开依据，完成当前动作，返回原工作。
FIRST VIEWPORT: 224px 稳定导航，48px 顶栏，个人待办列表；小Pai按需打开。
FORM: 用户指定 Linear 简洁原则，扩展已有产品世界；不运行随机视觉方向选择。 */
import {
  createContext,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";
import {
  ArrowRight,
  ArrowUpRight,
  BookOpen,
  CaretDown,
  CaretRight,
  CheckCircle,
  Circle,
  Cube,
  FileText,
  FolderSimple,
  Stack,
  GearSix,
  Info,
  Tray,
  List,
  ListChecks,
  MagnifyingGlass,
  Moon,
  Plus,
  SidebarSimple,
  Sparkle,
  Sun,
  Warning,
  X,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import {
  coverage,
  items,
  knowledge,
  projects,
  projectScreens,
  projectTabs,
  roles,
  screenNames,
  type Role,
  type Screen,
  type WorkItem,
} from "./design-data";
import s from "./platform.module.css";
import { ProjectDirectoryView } from "@/components/projects/project-directory-view";
import { PaiPreview } from "./pai-preview";
import {
  usePaiPreview,
  type PaiController,
  type PaiScope,
} from "./pai-preview-state";

import {
  attentionKey,
  useOrganizationPreview,
  type OrganizationController,
} from "./organization-state";
import { Commitments, Inbox, ProjectSets } from "./organization-preview";
import {
  ProjectTasks,
  ProjectTaskDialog,
  TaskRows,
  useProjectTasks,
  type TaskController,
} from "./project-tasks";

import {
  ProductCategories,
  ProductProposals,
  ProductContinue,
} from "./product-preview";
import {
  useProductPreview,
  type ProductController,
} from "./product-preview-state";

import type { NpiTaskTemplate } from "./project-task-data";
import { catalogLabels, catalogTabs } from "./catalog-fields";
import type { CatalogKind } from "./category-preview-state";

type Peek = {
  title: string;
  description: string;
  facts: [string, string][];
  source: string;
  resolveConflict?: boolean;
};
type DesignContext = {
  role: Role;
  person: string;
  screen: Screen;
  go: (screen: Screen) => void;
  project: (typeof projects)[number];
  setProject: (id: string) => void;
  open: (item: WorkItem) => void;
  peek: (value: Peek) => void;
  completed: string[];
  resourcePlan: "A" | "B" | null;
  openPai: () => void;
  pai: PaiController;
  openPaiSession: (id: string) => void;
  organization: OrganizationController;
  tasks: TaskController;
  product: ProductController;
  state: string;
  setState: (state: string) => void;
};
const Context = createContext<DesignContext | null>(null);
function useDesign() {
  const context = useContext(Context);
  if (!context) throw new Error("Missing design preview context");
  return context;
}
function Status({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "warning" | "success" | "accent";
}) {
  return (
    <span className={s.status} data-tone={tone}>
      <span />
      {children}
    </span>
  );
}
function Heading({
  title,
  children,
  action,
}: {
  title: string;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className={s.heading}>
      <div>
        <h1>{title}</h1>
        {children && <p>{children}</p>}
      </div>
      {action}
    </header>
  );
}
function Title({
  children,
  aside,
}: {
  children: ReactNode;
  aside?: ReactNode;
}) {
  return (
    <div className={s.sectionTitle}>
      <h2>{children}</h2>
      {aside}
    </div>
  );
}
function Empty({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className={s.empty}>
      <CheckCircle size={25} />
      <h2>{title}</h2>
      <p>{children}</p>
    </div>
  );
}
function Facts({ rows }: { rows: [string, string][] }) {
  return (
    <dl className={s.facts}>
      {rows.map(([key, value]) => (
        <div key={key}>
          <dt>{key}</dt>
          <dd>{value}</dd>
        </div>
      ))}
    </dl>
  );
}
function TextLink({
  children,
  onClick,
}: {
  children: ReactNode;
  onClick: () => void;
}) {
  return (
    <button className={s.textLink} onClick={onClick}>
      {children}
      <ArrowUpRight size={13} />
    </button>
  );
}
function Table({
  headers,
  rows,
  onRow,
}: {
  headers: string[];
  rows: string[][];
  onRow?: (row: string[], index: number) => void;
}) {
  return (
    <div className={s.tableWrap}>
      <table data-columns={headers.length}>
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => (
            <tr key={`${row[0]}-${i}`}>
              {row.map((cell, j) => (
                <td key={j}>
                  {j === 0 && onRow ? (
                    <button onClick={() => onRow(row, i)}>
                      {cell}
                      <ArrowUpRight size={12} />
                    </button>
                  ) : (
                    cell
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
function Tabs({
  values,
  value,
  onChange,
}: {
  values: string[];
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className={s.tabs} aria-label="页面视图">
      {values.map((name) => (
        <button
          key={name}
          aria-pressed={value === name}
          onClick={() => onChange(name)}
        >
          {name}
        </button>
      ))}
    </div>
  );
}
function WorkRows({ data }: { data: WorkItem[] }) {
  const c = useDesign();
  return (
    <div className={s.workRows}>
      {data.map((item) => (
        <button
          key={item.id}
          onClick={() => c.open(item)}
          className={s.workRow}
        >
          <span className={s.rowState}>
            {c.completed.includes(item.id) ? (
              <CheckCircle size={17} />
            ) : item.status.includes("冲突") ? (
              <Warning size={17} />
            ) : (
              <Circle size={17} />
            )}
          </span>
          <span className={s.itemId}>{item.id}</span>
          <strong>{item.title}</strong>
          <span className={s.rowProject}>
            {projects.find((p) => p.id === item.project)?.name}
          </span>
          <span className={s.rowOwner}>
            {c.role === "product" && c.screen === "work"
              ? item.kind
              : item.owner}
          </span>
          <span className={s.due}>
            {c.completed.includes(item.id) ? "已办理" : item.due}
          </span>
          <CaretRight size={13} />
        </button>
      ))}
    </div>
  );
}
function MiniStages({ project }: { project: (typeof projects)[number] }) {
  return (
    <span className={s.miniStages} aria-label={`当前阶段：${project.phase}`}>
      {project.stages.map((stage, i) => (
        <i
          key={stage}
          data-state={
            i < project.at ? "done" : i === project.at ? "current" : "future"
          }
          title={stage}
        />
      ))}
    </span>
  );
}
function ProjectHeader() {
  const c = useDesign();
  return (
    <>
      <header
        className={`${s.projectTitle} ${c.screen === "tasks" ? s.compactProjectTitle : ""}`}
      >
        <span className={s.projectMonogram}>{c.project.id}</span>
        <div>
          <h1>{c.project.name}</h1>
          <button onClick={() => c.go("stage")}>
            <MiniStages project={c.project} />
            {c.project.phase}
            <CaretRight size={12} />
          </button>
        </div>
        <span className={s.projectLead}>负责人 {c.project.lead}</span>
      </header>
      <nav className={s.projectTabs} aria-label="项目工作">
        {projectTabs.map((tab) => (
          <button
            key={tab}
            aria-current={c.screen === tab ? "page" : undefined}
            onClick={() => c.go(tab)}
          >
            {screenNames[tab]}
          </button>
        ))}
        <details
          className={s.moreMenu}
          onClick={(event) => {
            if ((event.target as HTMLElement).closest("button"))
              event.currentTarget.open = false;
          }}
        >
          <summary data-active={!projectTabs.includes(c.screen)}>
            更多
            <CaretDown size={12} />
          </summary>
          <div>
            <button onClick={() => c.go("engineering")}>产品与工程</button>
            <button onClick={() => c.go("builds")}>试制与验证</button>
            <button onClick={() => c.go("issues")}>问题与变更</button>
            <button onClick={() => c.go("release")}>评审与交付</button>
            <button onClick={() => c.go("stage")}>阶段与门禁</button>
            <button onClick={() => c.go("feedback")}>现场反馈</button>
          </div>
        </details>
      </nav>
    </>
  );
}
function Work() {
  const c = useDesign();
  const [tab, setTab] = useState("待我处理");
  const mine = items.filter((item) => item.roles.includes(c.role));
  const active = mine.filter((item) => !c.completed.includes(item.id));
  const myTasks = c.tasks.tasks.filter((task) => task.owner === c.person);
  const activeTasks = myTasks.filter((task) => task.status !== "已完成");
  const doneTasks = myTasks.filter((task) => task.status === "已完成");
  const tabs = ["待我处理", "承诺", "已完成"];
  return (
    <div className={s.page} data-product-work={c.role === "product"}>
      <Heading title="我的工作">
        {c.role === "external"
          ? "核对收到的交付，跟进本人负责的事项。"
          : c.role === "product"
            ? "处理产品取舍，继续提案，跟进定义与项目。"
            : "待办与承诺集中在这里，消息和项目更新在收件箱查看。"}
      </Heading>
      <Tabs values={tabs} value={tab} onChange={setTab} />
      {tab === "待我处理" ? (
        <>
          {c.pai.needsAttention.length > 0 && (
            <section className={s.paiInbox} aria-label="小Pai收件箱">
              <Title aside={<span>{c.pai.needsAttention.length}</span>}>
                小Pai需要你处理
              </Title>
              {c.pai.needsAttention.map((session) => (
                <button
                  key={session.id}
                  onClick={() => c.openPaiSession(session.id)}
                >
                  <Sparkle size={16} />
                  <span>
                    <strong>{session.title}</strong>
                    <small>{session.scope.label} · 补充本轮完成判据</small>
                  </span>
                  <ArrowUpRight size={15} />
                </button>
              ))}
            </section>
          )}
          {c.state === "空态" || !(active.length + activeTasks.length) ? (
            <Empty title="当前事项已处理">
              新的决定、接收和验证事项会出现在这里。你仍可从项目继续工作。
            </Empty>
          ) : (
            <>
              <div className={s.listToolbar}>
                <span>{active.length + activeTasks.length} 项需要关注</span>
                <span>按责任与期限排列</span>
              </div>
              {activeTasks.length > 0 && (
                <section className={s.taskGroup}>
                  <Title aside={<span>{activeTasks.length}</span>}>
                    项目任务
                  </Title>
                  <TaskRows
                    tasks={activeTasks}
                    controller={c.tasks}
                    showProject
                  />
                </section>
              )}
              {c.role === "product" ? (
                <WorkRows data={active} />
              ) : (
                [
                  "要我决定",
                  "要我协调",
                  "要我接收",
                  "要我验证",
                  "我的任务",
                  "等外部回复",
                ].map((kind) => {
                  const group = active.filter((i) => i.kind === kind);
                  return group.length ? (
                    <section key={kind} className={s.taskGroup}>
                      <Title aside={<span>{group.length}</span>}>{kind}</Title>
                      <WorkRows data={group} />
                    </section>
                  ) : null;
                })
              )}
            </>
          )}
        </>
      ) : tab === "承诺" ? (
        <Commitments
          role={c.role}
          person={c.person}
          onProject={(id, target = "tasks") => {
            c.setProject(id);
            c.go(target);
          }}
        />
      ) : mine.some((item) => c.completed.includes(item.id)) ||
        doneTasks.length ? (
        <section className={s.section}>
          {doneTasks.length > 0 && (
            <section className={s.taskGroup}>
              <Title>已完成的项目任务</Title>
              <TaskRows tasks={doneTasks} controller={c.tasks} showProject />
            </section>
          )}
          {mine.some((item) => c.completed.includes(item.id)) && (
            <>
              <Title>已办理的事项</Title>
              <WorkRows
                data={mine.filter((item) => c.completed.includes(item.id))}
              />
            </>
          )}
        </section>
      ) : (
        <Empty title="还没有已办理的事项">
          完成待办后，可在这里回看原事项与结果。
        </Empty>
      )}
      {c.role === "product" && tab === "待我处理" && c.state !== "空态" && (
        <ProductContinue
          controller={c.product}
          onOpen={(id) => {
            c.product.setProposalId(id);
            c.go("proposal");
          }}
          onAll={() => {
            c.product.setProposalId(null);
            c.go("proposal");
          }}
        />
      )}
      {c.role !== "external" && (
        <section className={s.quickProjects}>
          <Title
            aside={
              <TextLink onClick={() => c.go("projects")}>全部项目</TextLink>
            }
          >
            继续项目
          </Title>
          {projects.slice(0, c.role === "management" ? 3 : 2).map((p) => (
            <button
              key={p.id}
              onClick={() => {
                c.setProject(p.id);
                c.go("tasks");
              }}
            >
              <FolderSimple size={17} />
              <strong>{p.name}</strong>
              <span>{p.phase}</span>
              <MiniStages project={p} />
              <ArrowRight size={15} />
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
function Activity() {
  const c = useDesign();
  if (c.role === "external")
    return (
      <p className={s.footnote}>
        你收到了 PKG-04 v2，等待本人核对授权内容与实物。
      </p>
    );
  return (
    <div className={s.activity}>
      {[
        ["周宁", "更新项目状态", "复测与资源冲突需要接续", "今天 09:40"],
        [
          "吴敏",
          "交付首批样件",
          "Lot A · 4 件 · E-06 / M-04 · 等待品质接收",
          "昨天 16:20",
        ],
        ["小Pai", "准备计划调整候选", "等待周宁确认，尚未应用", "昨天 15:10"],
      ].map(([name, verb, body, time]) => (
        <button
          key={verb}
          onClick={() =>
            c.peek({
              title: verb,
              description: body,
              facts: [
                ["记录人", name],
                ["时间", time],
              ],
              source: "项目动态 · 示例记录",
            })
          }
        >
          <span className={s.avatar}>
            {name === "小Pai" ? <Sparkle size={13} /> : name[0]}
          </span>
          <span>
            <strong>
              {name} <em>{verb}</em>
            </strong>
            <small>{body}</small>
          </span>
          <time>{time}</time>
        </button>
      ))}
    </div>
  );
}
function timelinePosition(value: string) {
  const match = value.match(/(\d+)月(\d+)日/);
  if (!match) return 0;
  const day = Number(match[2]) + (Number(match[1]) === 11 ? 5 : -26);
  return Math.max(4, Math.min(92, (day / 21) * 100));
}
function Projects() {
  const c = useDesign();
  const entries = projects.map(p => {
    const project = p.id === "P1" && c.resourcePlan === "B" ? { ...p, forecast: "11月06日" } : p;
    const date = (label: string) => ({ label, position: /未知|未提供|尚未/.test(label) ? undefined : timelinePosition(label) });
    return { ...project, code: project.id, gateDates: `${project.commitment} / ${project.forecast}`, dates: { 基线: date(project.baseline), 预测: date(project.forecast), 承诺: date(project.commitment), 实际: date(project.actual) } };
  });
  return <ProjectDirectoryView entries={entries} phaseOrder={["定义", "工程验证", "试产"]} timeScale={["10月26日", "11月02日", "11月09日", "11月16日"]}
    onStartProposal={["product", "management"].includes(c.role) ? () => { c.setProject("P1"); c.go("category"); } : undefined}
    onOpenProject={id => { c.setProject(id); c.go("tasks"); }} onOpenPlan={id => { c.setProject(id); c.go("plan"); }}/>;
}

function Now() {
  const c = useDesign();
  return (
    <div className={`${s.page} ${s.nowPage}`}>
      <div className={s.nowIntro}>
        <div>
          <Status tone={c.project.health === "正常" ? "success" : "warning"}>
            {c.project.health}
          </Status>
          <h2>{c.project.note}</h2>
        </div>
        <TextLink onClick={() => c.go("stage")}>查看阶段出口</TextLink>
      </div>
      <div className={s.nowColumns}>
        <section>
          <Title
            aside={<TextLink onClick={() => c.go("plan")}>查看计划</TextLink>}
          >
            需要推进
          </Title>
          <WorkRows
            data={items
              .filter(
                (i) =>
                  i.project === c.project.id && !c.completed.includes(i.id),
              )
              .slice(0, 3)}
          />
          <section className={s.section}>
            <Title>最近动态</Title>
            {c.project.id === "P1" ? (
              <Activity />
            ) : (
              <p className={s.footnote}>本项目尚未提供新的活动记录。</p>
            )}
          </section>
        </section>
        <aside className={s.contextRail}>
          <Title
            aside={<TextLink onClick={() => c.go("builds")}>打开</TextLink>}
          >
            下一轮试制
          </Title>
          <h3>
            {c.project.id === "P1"
              ? "B-03 · 现版噪声与装配验证"
              : "下一轮活动待准备"}
          </h3>
          <Facts
            rows={
              c.project.id === "P1"
                ? [
                    ["目的", "确认现版噪声与装配表现"],
                    ["工程 / 制造", "E-06 / M-04"],
                    ["数量 / 样件", "6 件 · 2 批"],
                    ["验证范围", "噪声、装配与耐久"],
                  ]
                : [
                    ["目的", "待明确"],
                    ["配置", "待选择"],
                    ["数量", "未知"],
                    ["验证范围", "待提供"],
                  ]
            }
          />
          <section>
            <Title>关键承诺 · 下一门禁资料</Title>
            <Facts
              rows={[
                ["承诺", c.project.commitment],
                ["预测", c.project.forecast],
                ["接收者", "产品与品质负责人"],
                ["履行", "尚未记录"],
              ]}
            />
            <TextLink onClick={() => c.go("plan")}>展开承诺与接收者</TextLink>
          </section>
        </aside>
      </div>
    </div>
  );
}
function ResourceNeeds() {
  const c = useDesign();
  if (!["P1", "S2"].includes(c.project.id)) return null;
  const conflict = items.find(
    (i) => i.id === (c.role === "management" ? "MG-003" : "PM-016"),
  )!;
  const p1 = c.project.id === "P1";
  const rows = p1
    ? [
        [
          "消音室与测试人员",
          "噪声复测",
          "11月02日–04日",
          c.resourcePlan
            ? `已采用方案 ${c.resourcePlan} · 待执行`
            : "与 S2 时段冲突",
          "周宁",
        ],
        [
          "替代测试时段",
          "噪声复测 · 方案 B",
          "11月05日–06日",
          c.completed.includes("QA-020")
            ? "已核对可用 · 未预约"
            : "方法 / 环境 / 人员待核对",
          "许澄",
        ],
        [
          "第二批电机",
          "B-03 · Lot B",
          "10月26日",
          "供方承诺 · 实到未知",
          "沈禾",
        ],
      ]
    : [
        [
          "消音室与测试人员",
          "接口差异验证",
          "11月02日–04日",
          "与 P1 共同协调 · 本项目计划未自动调整",
          "林悦",
        ],
      ];
  return (
    <section className={s.section} aria-label="项目资源需求">
      <Title>资源需求</Title>
      <Table
        headers={["资源", "用于", "需求时间", "状态", "协调人"]}
        rows={rows}
        onRow={(_, index) =>
          c.open(
            index === 1
              ? items.find((i) => i.id === "QA-020")!
              : index === 2
                ? items.find((i) => i.id === "SU-007")!
                : conflict,
          )
        }
      />
      <p className={s.footnote}>
        选择资源查看影响与下一步。计划调整、实际预约、样件接收分别记录。
      </p>
    </section>
  );
}
function ResourceConflictDetails() {
  const c = useDesign();
  return (
    <section aria-label="资源冲突详情">
      <h2>消音室与测试人员 · R-08</h2>
      <p>
        P1 噪声复测与 S2 接口差异验证均需要
        11月02日–04日的消音室及同一组品质人员。
      </p>
      <Table
        headers={["受影响项目", "原承诺", "当前预测"]}
        rows={projects
          .slice(0, 2)
          .map((p) => [
            p.name,
            p.commitment,
            p.id === "P1" && c.resourcePlan === "B" ? "11月06日" : p.forecast,
          ])}
      />
      <details className={s.resourceComparison}>
        <summary>比较两种调整方案</summary>
        <Table
          headers={["影响", "A · 保持现有顺序", "B · 启用替代时段"]}
          rows={[
            ["P1 复测预测", "11月09日", "11月06日"],
            ["S2 计划", "保持原计划", "保持原计划"],
            [
              "资源",
              "沿用现有安排",
              c.completed.includes("QA-020")
                ? "替代时段已核对，未预约"
                : "替代时段待品质核对",
            ],
            ["仍需接续", "原承诺协商、预约与样件接收", "实际预约与样件接收"],
          ]}
        />
      </details>
      {c.completed.includes("MG-003") && (
        <p>跨项目取舍已记录；各项目的计划与承诺仍分别确认。</p>
      )}
    </section>
  );
}
function Plan() {
  const c = useDesign();
  const [tab, setTab] = useState("里程碑");
  return (
    <div className={s.page}>
      <Heading
        title="计划"
        action={
          <Button variant="outline" onClick={() => c.go("tasks")}>
            查看任务
          </Button>
        }
      >
        计划 {c.resourcePlan ? "v4（预览）" : "v3"} ·
        安排里程碑，协调资源与承诺。
      </Heading>
      <Tabs
        values={["里程碑", "资源需求", "承诺与外部等待"]}
        value={tab}
        onChange={setTab}
      />
      {tab === "里程碑" ? (
        <>
          <Title
            aside={
              <TextLink onClick={() => c.go("stage")}>查看门禁要求</TextLink>
            }
          >
            下一里程碑 · {c.project.next}
          </Title>
          <Table
            headers={["时间口径", "日期", "含义"]}
            rows={[
              ["基线", c.project.baseline, "固定计划依据"],
              ["预测", c.project.forecast, "按当前信息预计"],
              ["承诺", c.project.commitment, "对具体接收者作出"],
              ["实际", c.project.actual, "以真实发生记录为准"],
            ]}
          />
          <p className={s.footnote}>
            预测随进展调整，原承诺独立保留；当前里程碑尚未完成。
          </p>
        </>
      ) : tab === "资源需求" ? (
        <ResourceNeeds />
      ) : (
        <>
          <Table
            headers={["承诺 / 等待", "责任方", "接收者", "期限", "事实"]}
            rows={[
              ["完成噪声复测", "许澄", "周宁", "11月06日", "尚未履行"],
              ["提交验证评审资料", "周宁", "林悦", "11月06日", "尚未履行"],
              [
                "第二批电机到样",
                "供应商 A",
                "沈禾",
                "10月26日",
                "承诺，尚未实到",
              ],
            ]}
            onRow={(row, i) =>
              i === 2
                ? c.open(items.find((i) => i.id === "PM-017")!)
                : c.peek({
                    title: row[0],
                    description:
                      "承诺按责任人与接收者独立记录，预测变动不自动改写。",
                    facts: [
                      ["责任方", row[1]],
                      ["接收者", row[2]],
                      ["期限", row[3]],
                      ["履行", row[4]],
                    ],
                    source: "独立承诺记录",
                  })
            }
          />
          <TextLink
            onClick={() => c.open(items.find((i) => i.id === "SU-007")!)}
          >
            登记供应情况
          </TextLink>
        </>
      )}
    </div>
  );
}
function Engineering() {
  const c = useDesign();
  const [tab, setTab] = useState("产品定义");
  return (
    <div className={s.page}>
      <Heading
        title="产品与工程"
        action={
          <Button
            variant="outline"
            onClick={() => c.open(items.find((i) => i.id === "EN-033")!)}
          >
            {c.role === "engineering" ? "登记新版本" : "查看制品版本"}
          </Button>
        }
      >
        规格、配置和制品在同一处核对，正式基线独立保留。
      </Heading>
      <Tabs
        values={["产品定义", "工程配置", "制品与 BOM", "平台与差异"]}
        value={tab}
        onChange={setTab}
      />
      {tab === "产品定义" ? (
        <>
          <div className={s.inlineSummary}>
            <strong>定义 v3</strong>
            <Status>草稿修订</Status>
            <span>已冻结基线 v2 保留</span>
            <TextLink onClick={() => c.open(items[0])}>预览定义候选</TextLink>
          </div>
          <Table
            headers={["要求", "定义 / 单位", "工况", "依据"]}
            rows={[
              ["用途", "轮胎检查与应急补气", "家庭车主", "用户声音 U-014"],
              ["噪声", "未知", "距离与负载待确认", "待提供"],
              ["接口", "沿用平台接口", "装配边界 v2", "接口定义 IF-03"],
              [
                "验收",
                "按噪声与耐久方法分别判断",
                "方法草稿",
                "验证计划 VP-06",
              ],
            ]}
            onRow={(row) =>
              ["噪声", "噪声目标"].includes(row[0])
                ? c.open(items[0])
                : c.peek({
                    title: row[0],
                    description: "核对当前定义及其来源，未知项保持明确。",
                    facts:
                      row.length === 4
                        ? [
                            ["定义", row[1]],
                            ["工况", row[2]],
                            ["依据", row[3]],
                          ]
                        : [
                            ["当前定义", row[1]],
                            ["依据", row[2]],
                          ],
                    source: "产品定义与提案 · 示例引用",
                  })
            }
          />
        </>
      ) : tab === "工程配置" ? (
        <>
          <div className={s.notice}>
            <Info size={16} />
            <p>
              已有续版候选 E-07；本轮 B-03 仍按固定 E-06
              执行。候选尚未生效，不追改已制批次。
            </p>
          </div>
          <Table
            headers={["配置", "制造配置", "用途", "状态"]}
            rows={[
              ["E-06", "M-04", "B-03 本轮实制", "已固定"],
              [
                "E-07",
                "M-05 候选",
                "支架改善后的后续轮次",
                c.completed.includes("EN-032") && c.completed.includes("MF-011")
                  ? "决定已记录 · 待实际采用"
                  : "待双专业决定",
              ],
            ]}
            onRow={(row, i) =>
              i === 1
                ? c.open(items.find((i) => i.id === "EN-032")!)
                : c.peek({
                    title: "固定配置 E-06 / M-04",
                    description: "本轮实际配置不会随续版候选自动替换。",
                    facts: [
                      ["工程", row[0]],
                      ["制造", row[1]],
                      ["用途", row[2]],
                      ["状态", row[3]],
                    ],
                    source: "B-03 · 固定配置",
                  })
            }
          />
        </>
      ) : tab === "制品与 BOM" ? (
        <Table
          headers={["制品", "版本", "适用配置", "核对"]}
          rows={[
            ["总装图 D-106", "rev.C", "E-06", "已登记"],
            ["BOM-018", "v6", "E-06", "已登记"],
            ["固件 FW-04", "v1.3", "E-06", "版本已固定"],
            ["治具 J-04", "rev.B 候选", "M-05", "待制造核对"],
          ]}
          onRow={(row) =>
            c.peek({
              title: row[0],
              description:
                "核对固定版本与适用对象，已有原件不随新版本自动替换。",
              facts: [
                ["版本", row[1]],
                ["配置", row[2]],
                ["状态", row[3]],
              ],
              source: "制品登记 / 工程配置",
            })
          }
        />
      ) : (
        <>
          <Table
            headers={["差异", "父平台 / 原版", "本案", "结论"]}
            rows={[
              ["接口", "IF-03 v2", "拟沿用", "需确认装配边界"],
              ["减振支架", "E-06", "E-07 候选", "影响装配与治具"],
              ["噪声", "无可比实测", "未知", "不作满足判断"],
            ]}
          />
          <TextLink onClick={() => c.go("model")}>查看型号与平台关联</TextLink>
        </>
      )}
    </div>
  );
}
function Builds() {
  const c = useDesign();
  const [tab, setTab] = useState("批次与样件");
  return (
    <div className={s.page}>
      <Heading
        title="试制与验证"
        action={
          <Button
            variant={
              ["production", "manufacturing", "quality"].includes(c.role)
                ? "default"
                : "outline"
            }
            onClick={() =>
              c.open(
                items.find(
                  (i) =>
                    i.id ===
                    (c.role === "production"
                      ? "PR-004"
                      : c.role === "manufacturing"
                        ? "MF-013"
                        : "QA-018"),
                )!,
              )
            }
          >
            {c.role === "production"
              ? "登记交样"
              : c.role === "manufacturing"
                ? "补充制造准备"
                : c.role === "quality"
                  ? "接收样件"
                  : "核对样件"}
          </Button>
        }
      >
        B-03 · 每批实物、实际配置与验证结果都可追溯。
      </Heading>
      <Tabs
        values={["批次与样件", "交接与测试", "制造准备", "试产"]}
        value={tab}
        onChange={setTab}
      />
      {tab === "批次与样件" ? (
        <>
          <div className={s.inlineSummary}>
            <Cube size={17} />
            <strong>B-03 现版噪声与装配验证</strong>
            <span>E-06 / M-04 · 6 件 · 2 批</span>
          </div>
          <Table
            headers={["批次", "样件", "数量", "交付", "品质接收"]}
            rows={[
              [
                "Lot A",
                "A01–A04",
                "4",
                "已交样",
                c.completed.includes("QA-018") ? "已接收" : "待接收",
              ],
              [
                "Lot B",
                "B01–B02",
                "2",
                c.completed.includes("PR-004") ? "已交样" : "尚未交样",
                c.completed.includes("PR-004")
                  ? "已交样 · 待品质接收"
                  : "等待交付",
              ],
            ]}
            onRow={(_, i) =>
              c.open(
                items.find((t) => t.id === (i === 0 ? "QA-018" : "PR-004"))!,
              )
            }
          />
          <section className={s.section}>
            <Title>本轮验证范围</Title>
            <Table
              headers={["验证", "方法", "样件范围", "运行"]}
              rows={[
                ["噪声复测", "NV-02 草稿", "Lot A · A01/A02", "TR-08"],
                ["装配与耐久", "DV-04 v2", "Lot A · A03/A04", "TR-09"],
              ]}
              onRow={() => setTab("交接与测试")}
            />
          </section>
        </>
      ) : tab === "交接与测试" ? (
        <>
          <Table
            headers={["运行", "绑定样件 / 配置", "原值返回", "专业处置"]}
            rows={[
              [
                "TR-08 · 噪声",
                "A01/A02 · E-06 / M-04",
                "部分返回",
                "待具名处置",
              ],
              ["TR-09 · 耐久", "A03/A04 · E-06 / M-04", "未返回", "尚未判断"],
            ]}
            onRow={(row) =>
              c.peek({
                title: row[0],
                description:
                  "本轮数据尚未完整返回，保留原值与工况，不能直接判定整体通过。",
                facts: [
                  ["样件 / 配置", row[1]],
                  ["原值返回", row[2]],
                  ["专业处置", row[3]],
                ],
                source: "B-03 · 实际测试记录",
              })
            }
          />
          <div className={s.splitSections}>
            <section>
              <Title>TR-08 当前结果</Title>
              <Facts
                rows={[
                  ["覆盖", "2 件中的 1 件已返回"],
                  ["判定", "部分结果，不作整体通过"],
                  ["原值", "保留原单位、工况和采集时间"],
                  ["下一步", "等待剩余原值后独立处置"],
                ]}
              />
            </section>
            <section>
              <Title>交接边界</Title>
              <p>
                {c.completed.includes("PR-004")
                  ? "Lot A 与 Lot B 已分别交付；品质接收各自记录。"
                  : "Lot A 已交付，Lot B 保持等待。"}
                接收、开测承诺、开测与处置是不同事实。
              </p>
              <TextLink
                onClick={() => c.open(items.find((i) => i.id === "QA-018")!)}
              >
                核对接收范围
              </TextLink>
            </section>
          </div>
        </>
      ) : tab === "制造准备" ? (
        <Table
          headers={["准备项", "负责人", "状态", "待补内容"]}
          rows={[
            ["工具 / 治具", "高远", "待改版", "J-04 定位"],
            ["工艺方法", "高远", "候选", "WI-06"],
            ["人员", "吴敏", "待记录", "实际培训"],
            ["物料", "沈禾", "部分到位", "第二批电机"],
            ["检验", "许澄", "待签署", "噪声方法"],
          ]}
          onRow={() => c.open(items.find((i) => i.id === "MF-013")!)}
        />
      ) : (
        <>
          <Table
            headers={["试产", "实际配置", "产出 / 检验范围", "结论"]}
            rows={[
              [
                "Pilot P-01 · 历史探索批",
                "E-05 / M-03",
                "40 件 / 已检 32 件",
                "部分结果",
              ],
              ["待核对", "剩余 8 件未检", "实际原值待返回", "不作整体放行"],
            ]}
            onRow={() =>
              c.peek({
                title: "Pilot P-01 · 历史探索批",
                description:
                  "产出、已检范围和问题分别汇总；部分结果不能冒充完整制造放行。",
                facts: [
                  ["实际配置", "E-05 / M-03"],
                  ["产出", "40 件"],
                  ["已检", "32 件"],
                  ["剩余", "8 件"],
                  ["放行", "待专业决定"],
                ],
                source: "试产实际记录 · 检验原值",
              })
            }
          />
          <TextLink onClick={() => c.go("release")}>准备制造放行资料</TextLink>
        </>
      )}
    </div>
  );
}
function Issues() {
  const c = useDesign();
  const [tab, setTab] = useState("问题");
  return (
    <div className={s.page}>
      <Heading title="问题与变更">
        从异常到措施，再用实际验证判断是否解决。
      </Heading>
      <Tabs
        values={["问题", "变更与双线影响", "措施与验证"]}
        value={tab}
        onChange={setTab}
      />
      {tab === "问题" ? (
        <>
          <Table
            headers={["问题", "实际对象", "状态", "负责人", "下一步"]}
            rows={[
              [
                "I-12 · 异常振动",
                "B-02 · A02 · TR-06",
                "整改中",
                "陈舟",
                "核对双线影响",
              ],
              [
                "I-15 · 接头装配偏紧",
                "B-03 · A03",
                "待分析",
                "高远",
                "补充原值",
              ],
              [
                "I-09 · 低温启机",
                "B-02 · TR-05",
                "待独立验证",
                "许澄",
                "提交验证结论",
              ],
            ]}
            onRow={(_, i) =>
              i === 0
                ? setTab("变更与双线影响")
                : i === 2
                  ? c.open(items.find((t) => t.id === "QA-019")!)
                  : c.peek({
                      title: "I-15 接头装配偏紧",
                      description:
                        "先记录现象、配置与实物，再提出可检验的根因假设。",
                      facts: [
                        ["样件", "B-03 / A03"],
                        ["配置", "E-06 / M-04"],
                        ["根因", "未知"],
                        ["遏制", "隔离待复核"],
                      ],
                      source: "装配现场记录 F-09",
                    })
            }
          />
          <section className={s.section}>
            <Title>I-12 的证据链</Title>
            <div className={s.trace}>
              {[
                "异常原值",
                "根因假设",
                "措施与变更",
                "新轮实际采用",
                "独立验证",
                "分别关闭",
              ].map((v, i) => (
                <button
                  key={v}
                  onClick={() =>
                    setTab(i < 3 ? "变更与双线影响" : "措施与验证")
                  }
                >
                  {v}
                  {i < 5 && <CaretRight size={12} />}
                </button>
              ))}
            </div>
          </section>
        </>
      ) : tab === "变更与双线影响" ? (
        <>
          <div className={s.inlineSummary}>
            <strong>CH-08 · 减振支架改进</strong>
            <Status
              tone={
                c.completed.includes("EN-032") && c.completed.includes("MF-011")
                  ? "success"
                  : "warning"
              }
            >
              {c.completed.includes("EN-032") && c.completed.includes("MF-011")
                ? "专业决定已记录 · 待实施"
                : "分别等待专业决定"}
            </Status>
          </div>
          <div className={s.splitSections}>
            <section>
              <Title>工程影响</Title>
              <p>安装接口、结构刚度和耐久验证范围变化。</p>
              <Facts
                rows={[
                  ["版本", "E-06 → E-07"],
                  ["责任人", "陈舟"],
                  [
                    "决定",
                    c.completed.includes("EN-032")
                      ? "已签署（预览）"
                      : "待工程具名决定",
                  ],
                ]}
              />
              <Button
                variant="outline"
                onClick={() => c.open(items.find((i) => i.id === "EN-032")!)}
              >
                查看工程决定
              </Button>
            </section>
            <section>
              <Title>制造影响</Title>
              <p>治具定位、作业方法与检验方法需要核对。</p>
              <Facts
                rows={[
                  ["版本", "M-04 → M-05"],
                  ["责任人", "高远"],
                  [
                    "决定",
                    c.completed.includes("MF-011")
                      ? "已签署（预览）"
                      : "待制造具名决定",
                  ],
                ]}
              />
              <Button
                variant="outline"
                onClick={() => c.open(items.find((i) => i.id === "MF-011")!)}
              >
                查看制造决定
              </Button>
            </section>
          </div>
        </>
      ) : (
        <>
          <Table
            headers={["措施", "实际履行", "验证", "关闭"]}
            rows={[
              [
                "减振支架调整",
                "陈舟已完成设计",
                "独立复测待完成",
                "变更未关闭",
              ],
              [
                "定位治具调整",
                "高远待登记完成",
                "制造验证待完成",
                "措施未完成",
              ],
              [
                "I-12 问题",
                "不能用措施完成替代",
                "B-04 / TR-10 待准备",
                "问题未关闭",
              ],
            ]}
            onRow={() =>
              c.peek({
                title: "I-12 · 独立验证待准备",
                description:
                  "双专业决定后，在后续活动实际采用 E-07 / M-05，再形成独立验证原值。",
                facts: [
                  ["后续轮次", "B-04 待准备"],
                  ["验证", "TR-10 尚未开始"],
                  ["原问题", "保持未关闭"],
                ],
                source: "I-12 → CH-08 → 后续配置与活动",
              })
            }
          />
          <div className={s.actionLine}>
            <Button
              variant="outline"
              onClick={() => c.open(items.find((i) => i.id === "QA-019")!)}
            >
              查看另一案例的独立验证
            </Button>
            <span>措施完成、变更关闭和问题关闭各自留记录。</span>
          </div>
        </>
      )}
    </div>
  );
}
function Release() {
  const c = useDesign();
  const [tab, setTab] = useState(
    c.role === "external" ? "外部交接" : "评审与固定包",
  );
  return (
    <div className={s.page}>
      <Heading title={c.role === "external" ? "收到的交付" : "评审与交付"}>
        固定版本、明确用途，再完成各自负责的决定。
      </Heading>
      <Tabs
        values={
          c.role === "external"
            ? ["外部交接"]
            : ["评审与固定包", "专业放行", "外部交接"]
        }
        value={tab}
        onChange={setTab}
      />
      {tab === "评审与固定包" ? (
        <>
          <div className={s.inlineSummary}>
            <FileText size={17} />
            <strong>PKG-04 · v2</strong>
            <Status>客户样品评估</Status>
            <span>固定后续版，不覆盖旧包</span>
          </div>
          <Table
            headers={["内容", "固定版本", "状态"]}
            rows={[
              ["产品定义", "v3", "范围已固定"],
              ["工程 / 制造配置", "E-06 / M-04", "本轮实际版本"],
              ["验证摘要", "TR-08 / TR-09", "部分结果，保留未知"],
              ["使用说明", "DOC-16 v2", "可提供"],
              ["例外说明", "EXC-02", "仅限样品评估，不代表量产放行"],
            ]}
            onRow={(row) =>
              c.peek({
                title: row[0],
                description:
                  "固定包保留选定版本、用途和未知项。更新需要形成新包版本。",
                facts: [
                  ["版本", row[1]],
                  ["状态", row[2]],
                ],
                source: "PKG-04 v2 · 固定清单",
              })
            }
          />
          <TextLink onClick={() => setTab("专业放行")}>查看各专业决定</TextLink>
        </>
      ) : tab === "专业放行" ? (
        <>
          <div className={s.splitSections}>
            <section>
              <Title>工程决定</Title>
              <Facts
                rows={[
                  ["签署人", "陈舟"],
                  ["范围", "样品评估"],
                  ["结论", "有条件适用"],
                  ["例外", "仅限本固定包用途"],
                ]}
              />
            </section>
            <section>
              <Title>制造决定</Title>
              <Facts
                rows={[
                  ["签署人", "高远"],
                  ["范围", "制造接收"],
                  ["结论", "尚未作出"],
                  ["缺项", "实际检验方法待确认"],
                ]}
              />
            </section>
          </div>
          <p className={s.footnote}>
            专业决定独立存在。小Pai可以整理材料，不能代签、放行或外发。
          </p>
        </>
      ) : (
        <>
          <Table
            headers={["交接", "接收方", "固定包", "收到 / 生效"]}
            rows={[
              [
                "OUT-08",
                "协作方 A",
                "PKG-04 v2",
                c.completed.includes("EX-002")
                  ? "已收到 / 待对账"
                  : "待收到 / 未生效",
              ],
            ]}
            onRow={() => c.open(items.find((i) => i.id === "EX-002")!)}
          />
          <section className={s.section}>
            <Title>本次可见内容</Title>
            <Table
              headers={["文件", "版本", "用途"]}
              rows={[
                ["规格摘要", "v3", "客户样品评估"],
                ["操作说明", "v2", "样品使用"],
                ["样品标识清单", "v1", "精确核对实物"],
              ]}
              onRow={(row) =>
                c.peek({
                  title: row[0],
                  description:
                    "仅展示本次明确授权的材料，收到回执不自动代表业务生效。",
                  facts: [
                    ["版本", row[1]],
                    ["用途", row[2]],
                  ],
                  source: "OUT-08 · 授权固定包",
                })
              }
            />
          </section>
          <Button onClick={() => c.open(items.find((i) => i.id === "EX-002")!)}>
            查看回应
          </Button>
        </>
      )}
    </div>
  );
}
function Stage() {
  const c = useDesign();
  return (
    <div className={s.page}>
      <Heading title="阶段与门禁">当前出口与下一阶段进入条件分开查看。</Heading>
      <div className={s.stageLine}>
        {c.project.stages.map((stage, i) => (
          <span key={stage} data-current={i === c.project.at}>
            {i < c.project.at ? (
              <CheckCircle size={16} />
            ) : (
              <Circle size={16} />
            )}
            <strong>{stage}</strong>
          </span>
        ))}
      </div>
      <div className={s.splitSections}>
        <section>
          <Title>当前阶段出口 · {c.project.phase}</Title>
          <Table
            headers={["条件", "结论"]}
            rows={[
              ["固定定义与配置", "已提供"],
              ["本轮验证原值", "部分返回"],
              ["专业处置", "待决定"],
            ]}
          />
        </section>
        <section>
          <Title>
            下一阶段进入 · {c.project.stages[c.project.at + 1] ?? "项目收尾"}
          </Title>
          <Table
            headers={["前置准备", "状态"]}
            rows={[
              ["制造准备", "检验方法待确认"],
              ["责任承接", "已明确"],
              ["用途范围", "待确认"],
            ]}
          />
          <p className={s.footnote}>提前显示，不作为本阶段新增阻塞。</p>
        </section>
      </div>
      <section className={s.section}>
        <Title>三种成熟度</Title>
        <div className={s.maturity}>
          {[
            ["产品验证成熟度", "部分结果", "TR-08 仍待完整返回"],
            ["制造成熟度", "待补齐", "检验方法尚未签署"],
            ["交付适用性", "限定用途", "仅供客户样品评估"],
          ].map(([title, status, body]) => (
            <section key={title}>
              <h3>{title}</h3>
              <Status tone="warning">{status}</Status>
              <p>{body}</p>
            </section>
          ))}
        </div>
      </section>
      <TextLink onClick={() => c.go("release")}>查看评审材料</TextLink>
    </div>
  );
}
function ProductSurface({ kind }: { kind: "category" | "proposal" }) {
  const c = useDesign();
  const Component = kind === "category" ? ProductCategories : ProductProposals;
  return (
    <Component
      controller={c.product}
      disabled={["离线", "版本冲突"].includes(c.state)}
      empty={c.state === "空态"}
      onPai={c.openPai}
      onCreateCategoryWithPai={() => {
        c.pai.newChat(
          c.pai.pageScope,
          "帮我新建一个品类，先一起明确名称和主要场景。",
        );
        c.openPai();
      }}
      onProposalPai={(categoryId, baseId, seed) => {
        const context = c.product.proposalContext(categoryId, baseId);
        if (!context) return;
        c.pai.newChat(
          {
            ...c.pai.pageScope,
            proposalContext: context,
            proposalIntent: baseId ? "revise" : "create",
          },
          baseId
            ? "帮我完善当前提案，结合品类资料查漏补缺，保留已有内容。"
            : `帮我起草一份立项提案${seed?.title ? `；提案名称：${seed.title}` : ""}；提案入口：${seed?.entry ?? "自主新品"}`,
        );
        c.openPai();
      }}
      onCatalogPai={(kind, record, values) => {
        if (!c.product.category) return;
        c.pai.newChat(
          {
            id: `category:${c.product.category.id}`,
            label: c.product.category.name,
            screen: "category",
            catalogKind: kind,
            catalogRecord: record,
            catalogValues: values,
          },
          `帮我${record ? "维护" : "新增"}当前品类的${catalogLabels[kind]}${record ? `「${record.values.name}」` : ""}，先整理可核对的候选。`,
        );
        c.openPai();
      }}
      onProposal={(id) => {
        c.product.setProposalId(id ?? null);
        c.go("proposal");
      }}
      onProject={(id) => {
        c.setProject(id);
        c.go("tasks");
      }}
      onModel={(id) => {
        c.setProject(id);
        c.go("model");
      }}
      onInspect={(title, description, facts) =>
        c.peek({ title, description, facts, source: "品类共享依据 · 合成预览" })
      }
    />
  );
}
function Model() {
  const c = useDesign();
  return (
    <div className={s.page}>
      <Heading
        title="P1 · 型号与定义"
        action={
          <Button
            variant="outline"
            onClick={() =>
              c.peek({
                title: "准备 P1-L 派生提案",
                description:
                  "从已冻结父版准备独立草稿，后续进入自己的 G0 评审。",
                facts: [
                  ["父版", "P1 定义 v2"],
                  ["差异", "电池与收纳空间"],
                  ["当前状态", "候选，尚未提交"],
                ],
                source: "派生提案入口设计",
              })
            }
          >
            准备派生提案
          </Button>
        }
      >
        产品定义与项目实施相连，父版和派生差异各自保留。
      </Heading>
      <Facts
        rows={[
          ["用途", "日常轮胎检查与应急补气"],
          ["当前定义", "v3 草稿 / v2 已冻结"],
          ["工程配置", "E-07 候选 / E-06 本轮使用"],
          ["平台关联", "便携泵平台 PL-02"],
          ["当前项目", "P1 工程验证"],
        ]}
      />
      <section className={s.section}>
        <Title>版本与派生</Title>
        <Table
          headers={["版本 / 变体", "来源", "差异", "状态"]}
          rows={[
            ["P1 定义 v2", "已冻结", "本轮基线", "保留"],
            ["P1 定义 v3", "v2 续版", "噪声与工况", "待确认"],
            ["P1-L 变体", "P1 定义 v2", "电池与收纳空间", "提案中"],
          ]}
          onRow={() => c.go("engineering")}
        />
      </section>
      <TextLink onClick={() => c.go("feedback")}>查看现场反馈</TextLink>
    </div>
  );
}
function Knowledge() {
  const c = useDesign();
  const [tab, setTab] = useState("已发布");
  return (
    <div className={s.page}>
      <Heading title="知识">先核对适用范围，再采用经验。</Heading>
      <Tabs
        values={["已发布", "候选", "已失效"]}
        value={tab}
        onChange={setTab}
      />
      <Table
        headers={["知识", "状态", "适用范围", "来源"]}
        rows={knowledge
          .filter((r) => r[2] === tab)
          .map((r) => [r[1], r[2], r[3], r[4]])}
        onRow={(row) =>
          c.peek({
            title: row[0],
            description:
              tab === "已发布"
                ? "适用范围与来源需要随采用保留；已发布不代表适用于所有配置。"
                : tab === "候选"
                  ? "候选仍待具名审阅与发布，不能冒充正式规则。"
                  : "历史可查，但不得作为当前有效规则采用。",
            facts: [
              ["状态", row[1]],
              ["范围", row[2]],
              ["来源", row[3]],
            ],
            source: row[3],
          })
        }
      />
    </div>
  );
}
function Feedback() {
  const c = useDesign();
  return (
    <div className={s.page}>
      <Heading
        title="现场反馈"
        action={
          <Button
            variant="outline"
            onClick={() =>
              c.peek({
                title: "记录现场情况",
                description:
                  "先保存原始现象与精确对象，转写或 AI 归纳保留为候选。",
                facts: [
                  ["对象", "型号 / 序列 / 实际配置"],
                  ["原件", "照片、音频或文字"],
                  ["发生时间", "需记录"],
                  ["后续", "分诊后进入正式改进计划"],
                ],
                source: "现场反馈入口设计",
              })
            }
          >
            <Plus />
            记录现场情况
          </Button>
        }
      >
        把原始反馈接到改进工作，并追到后续实际采用。
      </Heading>
      <Table
        headers={["反馈", "对象", "状态", "接续工作"]}
        rows={[
          ["F-09 · 装配偏紧", "P1 / A03 / E-06", "已分诊", "I-15 待分析"],
          [
            "F-11 · 支架异常振动",
            "P1 / B-02 / E-06",
            "正式改进中",
            "I-12 → CH-08 → 新轮验证",
          ],
        ]}
        onRow={() => c.go("issues")}
      />
      <section className={s.section}>
        <Title>从改进到可复用知识</Title>
        <p className={s.readable}>
          现场事实保留原件。改进方案经专业决定、后续配置实际采用和独立验证后，可形成知识候选；具名发布仍为独立动作。
        </p>
        <TextLink onClick={() => c.go("knowledge")}>查看知识候选</TextLink>
      </section>
    </div>
  );
}
function Documents() {
  const c = useDesign();
  return (
    <div className={s.page}>
      <Heading title="文件">按用途找到文件，再核对它属于哪一版。</Heading>
      <Table
        headers={["资料", "版本", "所属对象", "可用性"]}
        rows={[
          ["装配图 D-106", "rev.C", "E-06", "已登记"],
          ["噪声测试方法 NV-02", "草稿", "TR-08", "待确认"],
          ["G0 立项决定", "v1", "提案 v4", "固定记录"],
          ["供应商规格", "v2", "客户私有资料", "仅授权成员可见"],
        ]}
        onRow={(row) =>
          c.peek({
            title: row[0],
            description:
              "原件、解析结果与业务采用分开呈现；资料读取失败不显示成空文件。",
            facts: [
              ["版本", row[1]],
              ["对象", row[2]],
              ["可用性", row[3]],
            ],
            source: "项目原件与登记文档",
          })
        }
      />
    </div>
  );
}
function Settings() {
  const c = useDesign();
  const [tab, setTab] = useState("个人偏好");
  const [notify, setNotify] = useState(true);
  return (
    <div className={s.page}>
      <Heading title="设置">低频配置集中管理，日常工作保持简洁。</Heading>
      <Tabs
        values={["个人偏好", "成员与范围", "小Pai与模型", "集成与治理"]}
        value={tab}
        onChange={setTab}
      />
      {tab === "个人偏好" ? (
        <div className={s.settingsRows}>
          <div>
            <span>
              <strong>需要我处理的提醒</strong>
              <small>已完成的自动工作进入动态。</small>
            </span>
            <label>
              <input
                type="checkbox"
                checked={notify}
                onChange={(e) => setNotify(e.target.checked)}
              />
              启用预览
            </label>
          </div>
          <div>
            <span>
              <strong>默认首页</strong>
              <small>由本人当前责任组织工作。</small>
            </span>
            <span>我的工作</span>
          </div>
        </div>
      ) : tab === "成员与范围" ? (
        <Table
          headers={["成员", "责任", "范围"]}
          rows={roles
            .filter((r) => r.id !== "external")
            .map((r) => [
              r.person,
              r.name,
              r.id === "management" ? "授权项目组合" : "已分配品类 / 项目",
            ])}
        />
      ) : tab === "小Pai与模型" ? (
        <>
          <Facts
            rows={[
              ["个人会话", "默认私人"],
              ["上下文", "跟随页面，可查看本次携带对象"],
              ["模型与技能", "服务器按当前范围下发"],
              ["自动化资格", "按租户 × 技能包 × 模型版本核对"],
              ["具名决定", "仅由有权本人执行"],
            ]}
          />
          <TextLink onClick={c.openPai}>查看小Pai工作区</TextLink>
        </>
      ) : (
        <Table
          headers={["配置", "用途", "办理边界"]}
          rows={[
            ["外部连接", "已授权资料读取", "按范围与数据类别记录"],
            ["服务商协议", "可选治理工具", "已登记有效限制按类别执行"],
            ["成员权限", "品类为范围根", "岗位名称不授予权限"],
            ["运行记录", "结果、费用与回执", "技术详情按需展开"],
          ]}
        />
      )}
    </div>
  );
}
function AlternateProject() {
  const c = useDesign();
  const data = items.filter((i) => i.project === c.project.id);
  return (
    <div className={s.page}>
      <Heading title={`${c.project.name} · ${screenNames[c.screen]}`}>
        {c.project.note}
      </Heading>
      <Facts
        rows={[
          ["当前阶段", c.project.phase],
          ["负责人", c.project.lead],
          ["下一门禁", c.project.next],
          ["基线", c.project.baseline],
          ["预测", c.project.forecast],
          ["承诺", c.project.commitment],
          ["实际", c.project.actual],
        ]}
      />
      <section className={s.section}>
        <Title>本项目待接续</Title>
        <WorkRows data={data} />
      </section>
      {c.screen === "plan" && <ResourceNeeds />}
      <p className={s.footnote}>
        此项目展示范围与承接关系；完整专业页面以 P1 的合成案例演示。
      </p>
      <div className={s.actionLine}>
        <Button
          variant="outline"
          onClick={() => {
            c.setProject("P1");
            c.go(c.screen);
          }}
        >
          查看 P1 的完整页面设计
        </Button>
      </div>
    </div>
  );
}
function Surface() {
  const c = useDesign();
  if (c.state === "读取失败")
    return (
      <div className={s.page}>
        <div className={s.recovery}>
          <Warning size={22} />
          <h1>当前资料未能读回</h1>
          <p>已有记录未被更改。恢复连接后可重新读取本页。</p>
          <Button onClick={() => c.setState("正常")}>重新读取</Button>
        </div>
      </div>
    );
  if (c.state === "权限失效")
    return (
      <div className={s.page}>
        <div className={s.recovery}>
          <Info size={22} />
          <h1>当前范围已不可访问</h1>
          <p>内容已收起。请核对项目授权或返回本人工作。</p>
          <Button
            onClick={() => {
              c.setState("正常");
              c.go("work");
            }}
          >
            返回我的工作
          </Button>
        </div>
      </div>
    );
  if (
    c.project.id !== "P1" &&
    [...projectScreens, "model"].includes(c.screen) &&
    !["now", "tasks"].includes(c.screen)
  )
    return <AlternateProject />;
  switch (c.screen) {
    case "work":
      return <Work />;
    case "inbox":
      return (
        <Inbox
          controller={c.organization}
          pai={c.pai}
          person={c.person}
          openPai={c.openPaiSession}
          onProject={(id, target = "tasks") => {
            c.setProject(id);
            c.go(target);
          }}
          disabled={c.state === "离线" || c.state === "版本冲突"}
          empty={c.state === "空态"}
        />
      );
    case "sets":
      return (
        <ProjectSets
          controller={c.organization}
          go={c.go}
          onProject={(id, target = "tasks") => {
            c.setProject(id);
            c.go(target);
          }}
          disabled={c.state === "离线" || c.state === "版本冲突"}
        />
      );
    case "projects":
      return <Projects />;
    case "now":
      return <Now />;
    case "tasks":
      return (
        <ProjectTasks
          controller={c.tasks}
          project={c.project.id}
          person={c.person}
          disabled={["离线", "版本冲突"].includes(c.state)}
          empty={c.state === "空态"}
        />
      );
    case "plan":
      return <Plan />;
    case "engineering":
      return <Engineering />;
    case "builds":
      return <Builds />;
    case "issues":
      return <Issues />;
    case "release":
      return <Release />;
    case "stage":
      return <Stage />;
    case "category":
      return <ProductSurface kind="category" />;
    case "proposal":
      return <ProductSurface kind="proposal" />;
    case "model":
      return <Model />;
    case "knowledge":
      return <Knowledge />;
    case "feedback":
      return <Feedback />;
    case "documents":
      return <Documents />;
    case "settings":
      return <Settings />;
  }
}

export function PlatformPreview({
  initialScreen = "work",
  initialRole = "lead",
  taskCatalog,
}: {
  initialScreen?: Screen;
  initialRole?: Role;
  taskCatalog: NpiTaskTemplate[];
}) {
  const [role, setRole] = useState<Role>(initialRole);
  const [screen, setScreen] = useState<Screen>(initialScreen);
  const [projectId, setProjectId] = useState("P1");
  const [dark, setDark] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const [mobile, setMobile] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const [state, setState] = useState("正常");
  const [completed, setCompleted] = useState<string[]>([]);
  const [resourceChoice, setResourceChoice] = useState<"A" | "B">("A");
  const [resourcePlan, setResourcePlan] = useState<"A" | "B" | null>(null);
  const [outcomes, setOutcomes] = useState<Record<string, WorkItem>>({});
  const [selection, setSelection] = useState<WorkItem | Peek | null>(null);
  const [reason, setReason] = useState("");
  const [notice, setNotice] = useState("");
  const [search, setSearch] = useState("");
  const [paiOpen, setPaiOpen] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const mainRef = useRef<HTMLElement>(null);
  const detailRef = useRef<HTMLDialogElement>(null);
  const detailBodyRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLDialogElement>(null);
  const guideRef = useRef<HTMLDialogElement>(null);
  const paiToggleRef = useRef<HTMLButtonElement>(null);
  const person = roles.find((r) => r.id === role)!.person;
  const baseProject = projects.find((p) => p.id === projectId)!;
  const project =
    baseProject.id === "P1" && resourcePlan === "B"
      ? { ...baseProject, forecast: "11月06日" }
      : baseProject;
  const product = useProductPreview(role, person);
  const pageScope: PaiScope =
    role === "external" && screen === "release"
      ? { id: "package", label: "授权交付包 PKG-04", screen: "release" }
      : projectScreens.includes(screen)
        ? { id: projectId, label: project.name, projectId, screen }
        : screen === "proposal" && product.selected
          ? {
              id: `proposal:${product.selected.id}`,
              label: product.selected.title,
              screen,
              proposalContext: product.proposalContext(
                product.selected.category,
                product.selected.id,
              ),
            }
          : screen === "category" && product.category
            ? {
                id: `category:${product.category.id}`,
                label: product.category.name,
                screen,
                proposalContext: product.proposalContext(product.category.id),
                catalogKind: (Object.keys(catalogTabs) as CatalogKind[]).find(
                  (kind) => catalogTabs[kind] === product.categoryTab,
                ),
              }
            : {
                id: ["category", "proposal", "model"].includes(screen)
                  ? `page:${screen}`
                  : "general",
                label: screen === "pai" ? "通用对话" : screenNames[screen],
                screen: screen === "pai" ? undefined : screen,
              };
  const pai = usePaiPreview(
    role,
    pageScope,
    screen === "pai",
    Object.fromEntries(
      product.categories.map((v) => [`category:${v.id}`, v.name]),
    ),
    product.catalogRecords,
  );
  const organization = useOrganizationPreview(role);
  const tasks = useProjectTasks(taskCatalog);
  function openPaiSession(id: string) {
    pai.select(id);
    go("pai");
  }
  function dockPai() {
    if (pai.current.scope.projectId) setProjectId(pai.current.scope.projectId);
    if (pai.current.scope.id.startsWith("proposal:"))
      product.setProposalId(pai.current.scope.id.slice(9));
    if (pai.current.scope.id.startsWith("category:"))
      product.setCategoryId(pai.current.scope.id.slice(9));
    if (pai.current.scope.catalogKind)
      product.setCategoryTab(catalogTabs[pai.current.scope.catalogKind]);
    go(pai.current.scope.screen ?? "work");
    setPaiOpen(true);
  }

  function go(next: Screen) {
    if (role === "external" && !["work", "release", "pai"].includes(next))
      return;
    setScreen(next);
    setMobile(false);
    setNotice("");
  }
  function open(item: WorkItem) {
    setSelection(item);
    setReason(drafts[item.id] ?? "");
    setShowConfirm(false);
    detailRef.current?.showModal();
    detailBodyRef.current?.scrollTo({ top: 0 });
  }
  function peek(value: Peek) {
    setSelection(value);
    setShowConfirm(false);
    detailRef.current?.showModal();
    detailBodyRef.current?.scrollTo({ top: 0 });
  }
  function openPai() {
    setPaiOpen(true);
  }
  useEffect(() => {
    mainRef.current?.scrollTo({ top: 0 });
  }, [screen, projectId, role, product.categoryId, product.proposalId]);
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        searchRef.current?.showModal();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
  const originalItem = selection && "tier" in selection ? selection : null;
  const selectedItem = originalItem
    ? (outcomes[originalItem.id] ??
      (originalItem.id === "PM-016"
        ? {
            ...originalItem,
            action: `采用方案 ${resourceChoice}（保留承诺）`,
            facts: [
              [
                "选定方案",
                resourceChoice === "A" ? "保持现有顺序" : "启用替代时段",
              ],
              ["P1 预测", resourceChoice === "A" ? "11月09日" : "11月06日"],
              ["S2 影响", "原计划不自动调整；11月02日承诺独立保留"],
              ["原承诺", "P1 11月06日，保持独立记录"],
              [
                "资源核对",
                resourceChoice === "A"
                  ? "沿用现有安排；加班可能性未确认"
                  : completed.includes("QA-020")
                    ? "许澄已核对替代时段，实际预约与样件接收仍需接续"
                    : "待许澄核对，暂不可采用",
              ],
            ] as [string, string][],
            result: `已采用方案 ${resourceChoice}（预览），P1 预测为${resourceChoice === "A" ? "11月09日" : "11月06日"}；原承诺保留，实际预约与测试尚未完成。`,
          }
        : originalItem))
    : null;
  const resourceReady =
    selectedItem?.id !== "PM-016" ||
    resourceChoice === "A" ||
    completed.includes("QA-020");
  const canAct =
    selectedItem?.roles.includes(role) &&
    !completed.includes(selectedItem.id) &&
    !["离线", "版本冲突", "权限失效", "读取失败"].includes(state);
  const availableScreens = (
    role === "external"
      ? ["work", "release", "pai"]
      : Object.keys(screenNames).filter(
          (key) =>
            !["category", "proposal", "model"].includes(key) ||
            ["product", "management"].includes(role),
        )
  ) as Screen[];
  const searchResults =
    state === "权限失效"
      ? []
      : availableScreens.filter((key) => screenNames[key].includes(search));
  const context: DesignContext = {
    role,
    person,
    screen,
    go,
    project,
    setProject: setProjectId,
    open,
    peek,
    completed,
    resourcePlan,
    openPai,
    pai,
    openPaiSession,
    organization,
    tasks,
    product,
    state,
    setState,
  };
  const isProject = role !== "external" && projectScreens.includes(screen);
  function handleConfirm() {
    if (!selectedItem || !canAct || !resourceReady || !reason.trim()) return;
    setOutcomes((current) => ({ ...current, [selectedItem.id]: selectedItem }));
    if (selectedItem.id === "PM-016") setResourcePlan(resourceChoice);
    setCompleted((current) => [...new Set([...current, selectedItem.id])]);
    setNotice(selectedItem.result);
    setShowConfirm(false);
    detailRef.current?.close();
  }
  return (
    <Context.Provider value={context}>
      <div className={`${s.root} ${dark ? s.dark : ""}`}>
        <div className={s.previewBar}>
          <span>
            <strong>PDOS 完整体验</strong>
            <em>设计预览 · 全部内容为合成示例</em>
          </span>
          <div>
            <label>
              预览身份
              <select
                aria-label="预览身份"
                value={role}
                onChange={(e) => {
                  setRole(e.target.value as Role);
                  setScreen("work");
                  setState("正常");
                  setNotice("");
                  setPaiOpen(false);
                }}
              >
                {roles.map((r) => (
                  <option key={r.id} value={r.id}>
                    {r.name}
                  </option>
                ))}
              </select>
            </label>
            <select
              aria-label="预览状态"
              value={state}
              onChange={(e) => setState(e.target.value)}
            >
              {["正常", "空态", "读取失败", "离线", "版本冲突", "权限失效"].map(
                (v) => (
                  <option key={v}>{v}</option>
                ),
              )}
            </select>
            <button onClick={() => guideRef.current?.showModal()}>
              设计说明
            </button>
            <button aria-pressed={narrow} onClick={() => setNarrow(!narrow)}>
              {narrow ? "桌面" : "窄屏"}
            </button>
            <button aria-label="切换明暗主题" onClick={() => setDark(!dark)}>
              {dark ? <Sun size={17} /> : <Moon size={17} />}
            </button>
          </div>
        </div>
        <div
          className={s.frame}
          data-collapsed={collapsed}
          data-narrow={narrow}
        >
          <aside className={s.sidebar} data-mobile={mobile}>
            <div className={s.brand}>
              <span>P</span>
              <strong>PDOS</strong>
              <button
                aria-label="折叠侧栏"
                onClick={() => setCollapsed(!collapsed)}
              >
                <SidebarSimple size={16} />
              </button>
            </div>
            <button
              className={s.searchButton}
              onClick={() => searchRef.current?.showModal()}
              aria-label="搜索或跳转"
            >
              <MagnifyingGlass size={16} />
              <span>搜索或跳转</span>
              <kbd>⌘ K</kbd>
            </button>
            <nav aria-label="主导航">
              {[
                { key: "work" as const, name: "我的工作", icon: ListChecks },
                { key: "inbox" as const, name: "收件箱", icon: Tray },
                { key: "pai" as const, name: "小Pai", icon: Sparkle },
                { key: "projects" as const, name: "项目", icon: FolderSimple },
                { key: "sets" as const, name: "项目集", icon: Stack },
                { key: "knowledge" as const, name: "知识", icon: BookOpen },
              ]
                .filter(
                  (v) =>
                    role !== "external" || v.key === "work" || v.key === "pai",
                )
                .map(({ key, name, icon: Icon }) => (
                  <button
                    key={key}
                    title={name}
                    aria-current={screen === key ? "page" : undefined}
                    onClick={() => {
                      if (key === "sets") {
                        organization.setSelectedSetId(null);
                        organization.setSetEditor(null);
                        organization.setSetNotice("");
                      }
                      go(key);
                    }}
                  >
                    <Icon size={17} />
                    <span>{name}</span>
                    {key === "inbox" &&
                      organization.unread +
                        pai.needsAttention.filter(
                          (x) =>
                            !organization.mine.paiRead.includes(
                              attentionKey(x),
                            ),
                        ).length >
                        0 && (
                        <small>
                          {organization.unread +
                            pai.needsAttention.filter(
                              (x) =>
                                !organization.mine.paiRead.includes(
                                  attentionKey(x),
                                ),
                            ).length}
                        </small>
                      )}
                    {key === "work" && (
                      <small>
                        {items.filter(
                          (i) =>
                            i.roles.includes(role) && !completed.includes(i.id),
                        ).length +
                          tasks.tasks.filter(
                            (task) =>
                              task.owner === person && task.status !== "已完成",
                          ).length +
                          pai.needsAttention.length}
                      </small>
                    )}
                  </button>
                ))}
              {role === "external" && (
                <button
                  aria-current={screen === "release" ? "page" : undefined}
                  onClick={() => go("release")}
                  title="收到的交付"
                >
                  <FileText size={17} />
                  <span>收到的交付</span>
                </button>
              )}
            </nav>
            {["product", "management"].includes(role) && (
              <div className={s.navGroup}>
                <p>产品管理</p>
                <button
                  onClick={() => {
                    setProjectId("P1");
                    product.setCategoryId(null);
                    go("category");
                  }}
                  aria-current={screen === "category" ? "page" : undefined}
                  title="品类"
                >
                  <Cube size={17} />
                  <span>品类</span>
                </button>
                <button
                  onClick={() => {
                    setProjectId("P1");
                    product.setProposalId(null);
                    go("proposal");
                  }}
                  aria-current={screen === "proposal" ? "page" : undefined}
                  title="立项提案"
                >
                  <FileText size={17} />
                  <span>立项提案</span>
                </button>
              </div>
            )}
            {role !== "external" && (
              <div className={s.navGroup}>
                <p>常用项目</p>
                {projects.slice(0, 2).map((p) => (
                  <button
                    key={p.id}
                    title={p.name}
                    aria-current={
                      isProject && project.id === p.id ? "page" : undefined
                    }
                    onClick={() => {
                      setProjectId(p.id);
                      go("tasks");
                    }}
                  >
                    <span className={s.projectDot}>{p.id}</span>
                    <span>{p.name}</span>
                  </button>
                ))}
              </div>
            )}
            <div className={s.navBottom}>
              {role !== "external" && (
                <button onClick={() => go("settings")} title="设置">
                  <GearSix size={17} />
                  <span>设置</span>
                </button>
              )}
              <div className={s.profile}>
                <span className={s.avatar}>{person[0]}</span>
                <span>
                  <strong>{person}</strong>
                  <small>{roles.find((r) => r.id === role)?.name}</small>
                </span>
              </div>
            </div>
          </aside>
          <div className={s.workspace}>
            <header className={s.topbar}>
              <button
                className={s.mobileMenu}
                aria-label="打开导航"
                onClick={() => setMobile(!mobile)}
              >
                <List size={19} />
              </button>
              <span>
                {isProject
                  ? project.name
                  : role === "external"
                    ? "外部协作"
                    : "工作空间"}
              </span>
              <CaretRight size={12} />
              <strong>{screenNames[screen]}</strong>
              <div>
                <button
                  aria-label="搜索"
                  onClick={() => searchRef.current?.showModal()}
                >
                  <MagnifyingGlass size={17} />
                </button>
              </div>
            </header>
            {state === "离线" && (
              <div className={s.banner}>
                <Warning size={15} />
                当前离线 · 可查看预览资料；正式确认和签署不可用。
                <button onClick={() => setState("正常")}>恢复连接</button>
              </div>
            )}
            {state === "版本冲突" && (
              <div className={s.banner}>
                <Warning size={15} />
                对象已更新 · 保留你的草稿，核对变化后再确认。
                <button
                  onClick={() =>
                    peek({
                      title: "核对对象版本变化",
                      description:
                        "你的说明保留在本次预览。核对最新对象后，原动作仍需重新确认。",
                      facts: [
                        ["原版本", "计划 v3 · 预测 11月09日"],
                        ["当前版本", "计划 v4 · 测试资源说明已更新"],
                        ["保持不变", "原承诺 11月06日"],
                        ["你的草稿", "保留；不自动提交"],
                      ],
                      source: "演示版本比较 · 非真实业务冲突",
                      resolveConflict: true,
                    })
                  }
                >
                  核对最新版本
                </button>
              </div>
            )}
            {notice && (
              <div role="status" className={s.resultBanner}>
                <CheckCircle size={15} />
                {notice}
                <button aria-label="关闭结果提示" onClick={() => setNotice("")}>
                  <X size={15} />
                </button>
              </div>
            )}
            <div
              className={s.contentBody}
              data-docked={paiOpen && screen !== "pai"}
            >
              {screen !== "pai" && (
                <main className={s.main} id="platform-main" ref={mainRef}>
                  {isProject && state !== "权限失效" && <ProjectHeader />}
                  <Surface key={`${screen}-${role}-${projectId}`} />
                </main>
              )}
              {(screen === "pai" || paiOpen) && (
                <PaiPreview
                  key={role}
                  controller={pai}
                  getProposalParameters={(categoryId) =>
                    product.proposalContext(categoryId)?.records.filter((r) => r.kind === "parameter") ?? []
                  }
                  full={screen === "pai"}
                  role={role}
                  state={state}
                  onExpand={() => go("pai")}
                  onDock={dockPai}
                  onClose={() => {
                    setPaiOpen(false);
                    if (screen === "pai") go("work");
                    requestAnimationFrame(() => paiToggleRef.current?.focus());
                  }}
                  onOpenScope={(scope) => {
                    if (scope.projectId) setProjectId(scope.projectId);
                    if (scope.id.startsWith("category:"))
                      product.setCategoryId(scope.id.slice(9));
                    if (scope.id.startsWith("proposal:"))
                      product.setProposalId(scope.id.slice(9));
                    if (scope.catalogKind)
                      product.setCategoryTab(catalogTabs[scope.catalogKind]);
                    go(scope.screen ?? "work");
                    setPaiOpen(true);
                  }}
                  onCreateCategory={(name, description) => {
                    if (!["正常", "空态"].includes(state) || !product.allowed)
                      return {
                        error: "当前状态无法创建品类，请恢复正常后重试。",
                      };
                    return product.createCategory(name, description);
                  }}
                  onSaveProposal={(draft) => {
                    if (!["正常", "空态"].includes(state) || !product.allowed)
                      return {
                        error: "当前状态无法保存提案，请恢复正常后重试。",
                      };
                    return product.confirmProposalDraft(draft);
                  }}
                  onOpenProposal={(id) => {
                    product.setProposalId(id);
                    go("proposal");
                    setPaiOpen(true);
                  }}
                  onSaveCatalog={(draft) => {
                    if (!["正常", "空态"].includes(state) || !product.allowed)
                      return {
                        error: "当前状态无法保存资料，请恢复正常后重试。",
                      };
                    return product.confirmCatalogDraft(draft);
                  }}
                  onOpenCatalog={(draft) => {
                    product.setCategoryId(draft.categoryId);
                    product.setCategoryTab(catalogTabs[draft.kind]);
                    go("category");
                    setPaiOpen(true);
                  }}
                  onRestore={() => setState("正常")}
                />
              )}
            </div>
            {screen !== "pai" && !paiOpen && (
              <button
                className={s.paiFloating}
                ref={paiToggleRef}
                onClick={openPai}
                aria-label="打开当前页面的小Pai"
                title="小Pai · 帮你处理当前工作"
              >
                <Sparkle size={23} weight="fill" />
                {pai.running.length > 0 && <i aria-label="有工作进行中" />}
              </button>
            )}
            <footer className={s.footer}>
              <span>设计原型 · 本地交互，不写入业务或调用模型</span>
              <button onClick={() => guideRef.current?.showModal()}>
                查看完整覆盖
              </button>
            </footer>
          </div>
        </div>
        <ProjectTaskDialog
          controller={tasks}
          person={person}
          role={role}
          disabled={["离线", "版本冲突", "权限失效", "读取失败"].includes(
            state,
          )}
          completed={completed}
          onRelated={(id) => {
            const item = items.find((item) => item.id === id);
            if (item) open(item);
          }}
        />
        <dialog
          className={s.inspector}
          ref={detailRef}
          aria-labelledby="inspector-title"
        >
          <header>
            <span>{selectedItem?.id ?? "资料详情"}</span>
            <button
              aria-label="关闭详情"
              onClick={() => detailRef.current?.close()}
            >
              <X size={19} />
            </button>
          </header>
          {selection && (
            <div className={s.inspectorBody} ref={detailBodyRef}>
              <h1 id="inspector-title">{selection.title}</h1>
              <p>{selection.description}</p>
              {selectedItem && (
                <div className={s.inlineSummary}>
                  <Status
                    tone={
                      completed.includes(selectedItem.id)
                        ? "success"
                        : "warning"
                    }
                  >
                    {completed.includes(selectedItem.id)
                      ? "已办理（预览）"
                      : selectedItem.status}
                  </Status>
                  <span>
                    {selectedItem.owner} · {selectedItem.due}
                  </span>
                </div>
              )}
              {selectedItem &&
                ["PM-016", "MG-003", "QA-020"].includes(selectedItem.id) && (
                  <ResourceConflictDetails />
                )}
              {selectedItem?.id === "PM-016" &&
                !completed.includes(selectedItem.id) && (
                  <section>
                    <h2>选择调整方案</h2>
                    <fieldset className={s.resourceChoices} disabled={!canAct}>
                      <legend className={s.resourceLegend}>计划调整方案</legend>
                      {(["A", "B"] as const).map((option) => (
                        <label key={option}>
                          <input
                            type="radio"
                            name="resource-option"
                            value={option}
                            checked={resourceChoice === option}
                            disabled={
                              option === "B" && !completed.includes("QA-020")
                            }
                            onChange={() => {
                              setResourceChoice(option);
                              setShowConfirm(false);
                            }}
                          />
                          <span>
                            方案 {option} ·{" "}
                            {option === "A" ? "保持现有顺序" : "启用替代时段"}
                          </span>
                        </label>
                      ))}
                    </fieldset>
                    {!completed.includes("QA-020") && (
                      <p>
                        方案 B
                        待许澄核对替代时段后可用；核对事项已在其“我的工作”中。
                      </p>
                    )}
                  </section>
                )}
              <Facts rows={selectedItem?.facts ?? selection.facts} />
              <section>
                <h2>依据</h2>
                <p>{selection.source}</p>
              </section>
              {"resolveConflict" in selection && selection.resolveConflict && (
                <Button
                  onClick={() => {
                    setState("正常");
                    setNotice("已核对最新版本，原草稿保留；业务动作尚未提交。");
                    detailRef.current?.close();
                  }}
                >
                  采用当前版本，保留草稿
                </Button>
              )}
              {selectedItem && completed.includes(selectedItem.id) && (
                <section>
                  <h2>办理结果</h2>
                  <p>{selectedItem.result}</p>
                  <p>办理说明：{drafts[selectedItem.id]}</p>
                </section>
              )}
              {selectedItem && !completed.includes(selectedItem.id) && (
                <>
                  <section>
                    <h2>当前动作</h2>
                    <p>
                      {selectedItem.tier === "read"
                        ? "此事项只读，业务事实保持原状。"
                        : selectedItem.tier === "sign"
                          ? "由有权本人具名决定；AI不能代签。"
                          : "查看范围与影响后，由本人一次确认。"}
                    </p>
                    {selectedItem.tier !== "read" && (
                      <label>
                        办理说明
                        <textarea
                          placeholder="写明依据、判断或仍保留的未知项…"
                          value={reason}
                          onChange={(e) => {
                            setReason(e.target.value);
                            setDrafts((v) => ({
                              ...v,
                              [selectedItem.id]: e.target.value,
                            }));
                          }}
                        />
                      </label>
                    )}
                  </section>
                  {!selectedItem.roles.includes(role) && (
                    <p className={s.inlineWarning}>
                      此动作由{selectedItem.owner}
                      负责。当前身份可查看，不能代为确认。
                    </p>
                  )}
                  {state === "离线" && (
                    <p className={s.inlineWarning}>
                      离线时不能确认。输入已保留在本次预览中。
                    </p>
                  )}
                  {state === "版本冲突" && (
                    <p className={s.inlineWarning}>
                      当前版本已更新，关闭详情并核对变化后再确认。
                    </p>
                  )}
                  {showConfirm && (
                    <section className={s.confirmation}>
                      <h2>
                        确认本次
                        {selectedItem.tier === "sign" ? "具名决定" : "变更"}
                      </h2>
                      <Facts
                        rows={[
                          ["执行人", person],
                          ["动作", selectedItem.action],
                          [
                            "范围",
                            `${selectedItem.project} / ${selectedItem.id}`,
                          ],
                          ...selectedItem.facts,
                          ["说明", reason],
                        ]}
                      />
                      <p>
                        本预览只更新本地状态；正式接入后保留同一请求与服务端回执。
                      </p>
                      <Button
                        disabled={!canAct || !resourceReady || !reason.trim()}
                        onClick={handleConfirm}
                      >
                        确认{selectedItem.tier === "sign" ? "签署" : "应用"}
                        （预览）
                      </Button>
                    </section>
                  )}
                  <div className={s.inspectorActions}>
                    {selectedItem.tier === "read" ? (
                      <Button
                        variant="outline"
                        onClick={() => {
                          detailRef.current?.close();
                          setProjectId(selectedItem.project);
                          if (selectedItem.screen === "proposal")
                            product.setProposalId(
                              selectedItem.id === "PD-042" ? "PA-003" : null,
                            );
                          go(selectedItem.screen);
                        }}
                      >
                        打开关联工作 <ArrowRight />
                      </Button>
                    ) : (
                      !showConfirm && (
                        <Button
                          disabled={
                            !canAct ||
                            !resourceReady ||
                            !reason.trim() ||
                            completed.includes(selectedItem.id)
                          }
                          onClick={() => setShowConfirm(true)}
                        >
                          {completed.includes(selectedItem.id)
                            ? "已办理"
                            : selectedItem.action}
                          <ArrowRight />
                        </Button>
                      )
                    )}
                    <Button
                      variant="ghost"
                      onClick={() => {
                        detailRef.current?.close();
                        setProjectId(selectedItem.project);
                        if (selectedItem.screen === "proposal")
                          product.setProposalId(
                            selectedItem.id === "PD-042" ? "PA-003" : null,
                          );
                        go(selectedItem.screen);
                      }}
                    >
                      查看关联页面
                    </Button>
                  </div>
                </>
              )}
            </div>
          )}
        </dialog>
        <dialog
          className={s.searchDialog}
          ref={searchRef}
          aria-labelledby="search-title"
        >
          <header>
            <h2 id="search-title">搜索与跳转</h2>
            <button
              aria-label="关闭搜索"
              onClick={() => searchRef.current?.close()}
            >
              <X size={18} />
            </button>
          </header>
          <label className={s.searchInput}>
            <MagnifyingGlass size={18} />
            <input
              autoComplete="off"
              aria-label="搜索页面或工作"
              placeholder="搜索页面或工作…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <div className={s.searchResults}>
            {searchResults.map((key) => (
              <button
                key={key}
                onClick={() => {
                  searchRef.current?.close();
                  go(key);
                }}
              >
                <FolderSimple size={16} />
                {screenNames[key]}
                <ArrowRight size={14} />
              </button>
            ))}
            {items
              .filter(
                (item) =>
                  state !== "权限失效" &&
                  item.roles.includes(role) &&
                  `${item.title}${item.id}`.includes(search),
              )
              .map((item) => (
                <button
                  key={item.id}
                  onClick={() => {
                    searchRef.current?.close();
                    open(item);
                  }}
                >
                  <Circle size={15} />
                  {item.title}
                  <small>{item.id}</small>
                </button>
              ))}
            {!searchResults.length &&
              !items.some(
                (i) =>
                  i.roles.includes(role) &&
                  `${i.title}${i.id}`.includes(search),
              ) && <p>没有匹配项，试试对象名称或编号。</p>}
          </div>
        </dialog>
        <dialog
          className={s.guideDialog}
          ref={guideRef}
          aria-labelledby="guide-title"
        >
          <header>
            <h2 id="guide-title">完整设计 · 从使用者出发</h2>
            <button
              aria-label="关闭设计说明"
              onClick={() => guideRef.current?.close()}
            >
              <X size={18} />
            </button>
          </header>
          <div className={s.guideBody}>
            <p>
              本轮是完整体验设计候选，未替换实际业务页面。身份与状态选择器是评审工具，正式应用按当前账号自动组织工作。
            </p>
            <h3>先看这四条路径</h3>
            <ol>
              <li>
                小Pai → 起草方案 → 展开成果 →
                继续修改；再进入项目，打开页内小Pai。
              </li>
            </ol>
            <ol>
              <li>项目负责人：我的工作 → 计划冲突 → 方案比较 → 一次确认。</li>
              <li>
                品质 / 测试：待接收 → 精确批次与配置 → 分批接收 → 原队列更新。
              </li>
              <li>
                研发 / 制造：变更 → 双线影响 → 各自具名决定 → 后续实施与验证。
              </li>
            </ol>
            <h3>全流程覆盖</h3>
            <Table
              headers={["工作范围", "本轮设计覆盖"]}
              rows={coverage.map((r) => [r[0], r[1]])}
              onRow={(_, i) => {
                guideRef.current?.close();
                if (role === "external")
                  setNotice(
                    "请先使用顶部的预览身份选择器切换到内部岗位，再查看其他流程。",
                  );
                else {
                  setProjectId("P1");
                  go(coverage[i][2] as Screen);
                }
              }}
            />
            <h3>精简的取舍</h3>
            <p>
              项目集拥有独立侧栏入口，可新建并将项目移入。项目默认进入任务，提供概览、任务、计划、文件；专业工作在更多中查看。资源需求和冲突在计划中处理，需要本人处理时进入我的工作。小Pai可以独立聊天，也可通过右下角悬浮入口继续当前工作；成果、技能与执行详情按需展开。
            </p>
            <h3>参考与依据</h3>
            <p>
              <a
                href="https://linear.app/now/behind-the-latest-design-refresh"
                target="_blank"
                rel="noreferrer"
              >
                Linear：降低视觉噪声
              </a>{" "}
              ·{" "}
              <a
                href="https://linear.app/docs/my-issues"
                target="_blank"
                rel="noreferrer"
              >
                本人工作
              </a>{" "}
              ·{" "}
              <a
                href="https://linear.app/docs/projects"
                target="_blank"
                rel="noreferrer"
              >
                项目组织
              </a>
            </p>
            <p>
              业务范围依 PDOS v1.1 §01 / §03 / §05 / §06 与 UI
              基线。预览覆盖不代表实际能力或阶段验收已完成。
            </p>
          </div>
        </dialog>
      </div>
    </Context.Provider>
  );
}
