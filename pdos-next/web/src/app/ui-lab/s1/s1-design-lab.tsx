"use client";

import { useRef, useState, type ReactNode } from "react";
import { ArrowDown, ArrowLeft, ArrowRight, ArrowUpRight, BookOpen, CaretRight, Check, CheckCircle, Circle, Desktop, FileText, Flag, FolderSimple, Info, List, ListChecks, Moon, PaperPlaneTilt, SidebarSimple, Sparkle, Sun, Tag, Users, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import s from "./s1-design-lab.module.css";

type Direction = "a" | "b" | "c";
type View = "work" | "proposal" | "project";
const directions = [
  { id: "a" as const, name: "清晰工作台", caption: "任务优先 · 紧凑列表 · 按需展开", detail: "保留熟悉的导航，把有内容的任务和下一步放在首屏；空队列合并，动态只留摘要。", fit: "适合日常工作，改动最稳妥。" },
  { id: "b" as const, name: "专注办理", caption: "事项队列 · 单一焦点 · 连续处理", detail: "左侧切换事项，右侧集中看内容、依据和下一步；当前事项始终清楚，减少来回跳转。", fit: "适合连续处理任务和审阅资料。" },
  { id: "c" as const, name: "文档协作", caption: "阅读为主 · 页边注释 · 原位协作", detail: "把工作组织成一份有层次的简报，提案像文档一样阅读，证据和协作工具随内容出现。", fit: "适合产品研究、提案和方案讨论。" },
];
const views = [{ id: "work" as const, name: "我的工作" }, { id: "proposal" as const, name: "立项提案" }, { id: "project" as const, name: "项目驾驶舱" }];
const tasks = [
  { title: "噪声", subtitle: "确定噪声目标，补充判定依据", body: "立项时尚未确定噪声指标。需要补充目标值、适用场景和来源，再进入后续验证准备。", source: "G0 承接事项 · 噪声", label: "指标待确定" },
  { title: "噪声条件待确定", subtitle: "明确测试距离、背景噪声与工作状态", body: "同一个噪声数值在不同工况下不能直接比较。先明确测量方法和适用条件，再与噪声目标一起核对。", source: "G0 承接事项 · 噪声条件待确定", label: "工况待确定" },
];

function Badge({ children, tone = "neutral" }: { children: ReactNode; tone?: "neutral" | "success" | "pending" }) {
  return <span className={s.badge} data-tone={tone}>{children}</span>;
}
function SectionTitle({ children, aside }: { children: ReactNode; aside?: ReactNode }) {
  return <div className={s.sectionTitle}><h2>{children}</h2>{aside}</div>;
}
function Fact({ label, children }: { label: string; children: ReactNode }) {
  return <div className={s.fact}><dt>{label}</dt><dd>{children}</dd></div>;
}

  function PageHeading({ title, sub, action, view }: { title: string; sub: string; action?: ReactNode; view: View }) {
    return <header className={s.pageHeading}><div><p className={s.eyebrow}>{view === "work" ? "周四，10月22日" : "汽车充气泵 / 便携充气泵"}</p><h1>{title}</h1><p>{sub}</p></div>{action}</header>;
  }

export function S1DesignLab({ initialDirection, initialView }: { initialDirection: Direction; initialView: View }) {
  const [direction, setDirection] = useState<Direction>(initialDirection);
  const [view, setView] = useState<View>(initialView);
  const [dark, setDark] = useState(false);
  const [narrow, setNarrow] = useState(false);
  const [aiOpen, setAiOpen] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const [taskIndex, setTaskIndex] = useState(0);
  const [queue, setQueue] = useState("我的任务");
  const [documentTab, setDocumentTab] = useState("提案正文");
  const [chosen, setChosen] = useState<Direction | null>(null);
  const [dialog, setDialog] = useState({ title: "", content: "" });
  const dialogRef = useRef<HTMLDialogElement>(null);
  const [message, setMessage] = useState("");
  const [reply, setReply] = useState(false);
  const selected = directions.find(item => item.id === direction)!;
  const task = tasks[taskIndex];

  function navigate(nextDirection: Direction, nextView: View) {
    setDirection(nextDirection); setView(nextView); setMenuOpen(false);
    const url = new URL(window.location.href);
    url.searchParams.set("direction", nextDirection); url.searchParams.set("view", nextView);
    window.history.replaceState(null, "", url);
  }
  function show(title: string, content: string) {
    setDialog({ title, content }); dialogRef.current?.showModal();
  }
  const source = () => show("来源与记录", "设计预览采用 S1 已有合成案例：便携充气泵、提案 v4、G0 具名批准、固定定义 v1，以及两项 2026-11-20 到期的噪声待办。\n\n版面中的说明经过重写，便于评估阅读体验；不代表新增研究结果。噪声目标和工况仍为未知。实际来源与回执请从原应用查看。");
  const taskDetail = (index: number) => { setTaskIndex(index); show(tasks[index].title, `${tasks[index].body}\n\n负责人：胡汉伟\n期限：2026-11-20\n来源：${tasks[index].source}\n\n这是详情交互预览。选定设计并接入现有接口后，在这里继续办理。`); };
  const primaryAction = () => view === "proposal" ? navigate(direction, "project") : show("建立首版计划", "计划应从已立项的项目接续，并保留两项噪声待办。\n\n下一步：明确工作包、负责人、依赖和时间，再预览计划候选并由本人确认。\n\n本页仅预览这条办理路径，不会生成计划或调用模型。");

  function renderTaskRows(compact = false) {
    return <div className={s.taskRows}>{tasks.map((item, index) => <button key={item.title} className={s.taskRow} onClick={() => taskDetail(index)}>
      <Circle size={17}/><span className={s.taskText}><strong>{item.title}</strong><small>{compact ? item.subtitle : "便携充气泵 · G0 承接"}</small></span><Badge tone="pending">待确定</Badge><span className={s.due}>11月20日</span><ArrowUpRight size={16}/>
    </button>)}</div>;
  }
  function renderActivity() {
    return <div className={s.activity}>
      <div><CheckCircle size={17}/><span><strong>立项已批准</strong><small>胡汉伟 · 固定定义 v1，进入项目</small></span><button onClick={source}>记录</button></div>
      <div><Sparkle size={17}/><span><strong>提案说明已保存</strong><small>小Pai 起草 · 本人确认</small></span><button onClick={source}>来源</button></div>
      <details><summary>较早的运行记录</summary><p>早期起草曾执行未完成。完整指令和运行回执在工作记录中按需查看。</p><button className={s.textButton} onClick={source}>查看记录说明 <ArrowUpRight/></button></details>
    </div>;
  }
  function renderProjectContext() {
    return <aside className={s.context}>
      <SectionTitle>当前项目</SectionTitle><div className={s.projectSymbol}><FolderSimple size={24}/></div>
      <h3>便携充气泵</h3><p>S1 演示项目</p><Badge>待建计划</Badge>
      <dl><Fact label="负责人">胡汉伟</Fact><Fact label="固定定义">v1</Fact><Fact label="下一门禁">待提供</Fact></dl>
      <Button variant="outline" onClick={() => navigate(direction, "project")}>进入项目 <ArrowRight/></Button>
      <div className={s.contextDivider}/><SectionTitle>最近进展</SectionTitle>{renderActivity()}
    </aside>;
  }
  function renderQueues() {
    return <div className={s.queues} aria-label="工作分类">{["我的任务", "要我决定", "要我接收", "要我验证", "等外部回复"].map(label => <button key={label} aria-pressed={queue === label} onClick={() => setQueue(label)}>{label}<span>{label === "我的任务" ? "2" : "0"}</span></button>)}</div>;
  }
  function renderEmptyQueue() {
    return <div className={s.empty}><CheckCircle size={24}/><h3>暂无{queue.replace("要我", "待").replace("等外部回复", "外部回复")}事项</h3><p>你可以继续处理项目中待确定的噪声指标与工况。</p><Button variant="outline" onClick={() => setQueue("我的任务")}>查看我的 2 项任务 <ArrowRight/></Button></div>;
  }
  function renderWorkA() {
    return <div className={s.standardPage}><PageHeading view={view} title="我的工作" sub="汉伟，今天从这些事情继续。" action={<Button variant="outline" onClick={() => setAiOpen(true)}><Sparkle/>找小Pai协作</Button>}/>
      <div className={s.overviewGrid}><div className={s.mainColumn}>
        <div className={s.nextAction}><span className={s.actionIcon}><Flag size={20}/></span><div><strong>便携充气泵已立项</strong><p>下一步建立首版计划，将待确定事项带入项目。</p></div><button onClick={primaryAction}>建立计划 <ArrowRight size={15}/></button></div>
        {renderQueues()}{queue === "我的任务" ? <><SectionTitle aside={<span className={s.muted}>2 项 · 均未到期</span>}>接下来要做</SectionTitle>{renderTaskRows()}<p className={s.quietNote}><CheckCircle size={15}/>当前没有需要你决定、接收或验证的事项。</p></> : renderEmptyQueue()}
        <section className={s.commitment}><SectionTitle>我的承诺</SectionTitle><p>暂无已登记承诺。</p><small>任务期限与承诺分开记录，进入项目可查看具体履行情况。</small></section>
        <button className={s.resume} onClick={() => navigate(direction, "proposal")}><FileText size={22}/><span><strong>继续查看立项提案</strong><small>便携充气泵 · v4 · 已批准 G0</small></span><ArrowRight size={18}/></button>
      </div>{renderProjectContext()}</div>
    </div>;
  }
  function renderWorkB() {
    return <div className={s.focusLayout}><aside className={s.inbox}><h1>我的工作</h1><p>先做好眼前这一件事。</p><div className={s.inboxTabs}><button aria-pressed={queue === "我的任务"} onClick={() => setQueue("我的任务")}>待办 <span>2</span></button><button aria-pressed={queue !== "我的任务"} onClick={() => setQueue("要我决定")}>待决定 <span>0</span></button></div>
      {queue === "我的任务" ? <><p className={s.groupLabel}>稍后 · 11月20日</p>{tasks.map((item, i) => <button key={item.title} className={s.inboxItem} aria-pressed={taskIndex === i} onClick={() => setTaskIndex(i)}><span><Circle size={16}/><strong>{item.title}</strong></span><p>{item.subtitle}</p><small>便携充气泵 <CaretRight size={12}/></small></button>)}</> : <p className={s.groupLabel}>没有待决定事项。</p>}
      <div className={s.inboxBottom}><FolderSimple size={18}/><button onClick={() => navigate(direction, "project")}>查看关联项目 <ArrowRight size={14}/></button></div>
    </aside><article className={s.focusDetail}>{queue === "我的任务" ? <><div className={s.focusTop}><span><Circle size={16}/>待确定</span><span>事项 {taskIndex + 1} / 2</span></div><p className={s.eyebrow}>便携充气泵 / G0 承接</p><h1>{task.title}</h1><p className={s.focusLead}>{task.subtitle}</p><dl className={s.inlineFacts}><Fact label="负责人"><span className={s.miniAvatar}>胡</span>胡汉伟</Fact><Fact label="期限">2026-11-20</Fact><Fact label="来源"><button onClick={source}>G0 决定 <ArrowUpRight size={13}/></button></Fact></dl>
      <section><SectionTitle>需要推进什么</SectionTitle><p>{task.body}</p></section><div className={s.fieldPreview}><div><span>{taskIndex === 0 ? "噪声目标" : "测试工况"}</span><Badge tone="pending">未确定</Badge></div><p>{taskIndex === 0 ? "尚无可引用的目标值，请先核对来源。" : "测量距离、背景噪声与负载条件待明确。"}</p><button className={s.textButton} onClick={source}>查看原提案依据 <ArrowUpRight size={14}/></button></div>
      <section><SectionTitle>推进建议</SectionTitle><p>和产品、测试负责人确认适用场景，将目标与工况一并记录到项目中。</p></section><div className={s.focusActions}><Button onClick={() => taskDetail(taskIndex)}>进入办理预览 <ArrowRight/></Button><Button variant="outline" onClick={() => setAiOpen(true)}><Sparkle/>让小Pai整理依据</Button></div></> : renderEmptyQueue()}</article></div>;
  }
  function renderWorkC() {
    return <div className={s.editorLayout}><aside className={s.outline}><p>我的工作简报</p><a href="#brief-next">下一步</a><a href="#brief-tasks">待确定事项 <span>2</span></a><a href="#brief-progress">最近进展</a><div className={s.outlineFoot}>10月22日<br/>周四</div></aside><article className={s.document}><p className={s.eyebrow}>个人工作 / 10月22日</p><h1>今天，从立项之后开始。</h1><p className={s.documentLead}>便携充气泵已通过 G0。接下来，把定义中的未知项变成可以推进的工作。</p><div className={s.documentMeta}><span className={s.miniAvatar}>胡</span>胡汉伟 <span>·</span>1 个项目 <span>·</span>2 项待办</div>
      <section id="brief-next"><h2>下一步，建立项目计划</h2><p>本轮已形成固定定义 v1。噪声指标和测试工况尚未确定，随项目继续核对；下一门禁与时间承诺待提供。</p><Button onClick={primaryAction}>建立首版计划 <ArrowRight/></Button></section>
      <section id="brief-tasks"><SectionTitle aside={<Badge tone="pending">2 项待确定</Badge>}>把未知变成明确的要求</SectionTitle>{renderTaskRows(true)}</section>
      <section id="brief-progress"><h2>已经完成的进展</h2>{renderActivity()}</section><p className={s.docEnd}>当前没有待决定、待接收和待验证事项。</p>
    </article><aside className={s.marginNotes}><span className={s.noteRule}/><p>项目笔记</p><strong>便携充气泵</strong><small>S1 演示项目</small><button onClick={() => navigate(direction, "project")}>查看项目 <ArrowUpRight size={13}/></button><div className={s.contextDivider}/><Sparkle size={20}/><p>需要补充依据？</p><small>让小Pai围绕当前事项整理资料。</small><button onClick={() => setAiOpen(true)}>打开协作 <ArrowRight size={13}/></button></aside></div>;
  }
  function renderSpecs() {
    return <div className={s.specTable}><div><strong>关键要求</strong><strong>当前定义</strong><strong>依据</strong></div>{[["使用场景", "轮胎检查与应急补气", "合成演示资料"], ["产品方向", "便携款", "G0 具名决定"], ["噪声指标", "待确定", "无已确认数值"], ["测试工况", "待确定", "待补测量条件"]].map((row, i) => <div key={row[0]}><span>{row[0]}</span><span data-unknown={i > 1}>{row[1]}</span><button onClick={source}>{row[2]}<ArrowUpRight size={12}/></button></div>)}</div>;
  }
  function renderProposalBody() {
    return <><section id="proposal-position"><h2>为家庭车主提供便携补气方案</h2><p>围绕日常停车和短途出行时的轮胎检查与应急补气，选择便于携带和收纳的产品方向。当前提案用于 S1 合成演示，尚不支持量产或市场结论。</p><button className={s.sourceLink} onClick={source}><BookOpen size={14}/>合成演示资料 · 查看来源</button></section><section id="proposal-spec"><h2>关键规格与未确定项</h2>{renderSpecs()}</section><section id="proposal-decision"><h2>方案选择与立项决定</h2><div className={s.decision}><CheckCircle size={19}/><div><strong>选择便携款，进入项目开发</strong><p>噪声指标和测试工况保留为未知，转入项目继续核对。</p><button onClick={source}>胡汉伟 · 查看具名决定 <ArrowUpRight size={13}/></button></div></div></section></>;
  }
  function renderProposal() {
    return <div className={`${s.proposalPage} ${direction === "c" ? s.proposalEditorial : ""}`}>
      {direction !== "a" && <aside className={s.outline}><p>{direction === "b" ? "提案内容" : "文档目录"}</p><a href="#proposal-position">定位与用户</a><a href="#proposal-spec">关键规格 <span>2</span></a><a href="#proposal-decision">立项决定</a><div className={s.outlineFoot}><FileText size={18}/>提案 v4<br/>已保存</div></aside>}
      <div className={s.proposalMain}><PageHeading view={view} title="便携充气泵" sub="立项提案 · v4" action={<Button onClick={primaryAction}>进入已立项项目 <ArrowRight/></Button>}/>
        <div className={s.proposalState}><Badge tone="success"><Check size={12}/>G0 已批准</Badge><span>固定定义 v1</span><span>胡汉伟 · 具名决定</span><button onClick={source}>记录 <ArrowUpRight size={13}/></button></div>
        <div className={s.documentTabs}>{["提案正文", "规格对比", "证据与记录"].map(name => <button key={name} aria-pressed={documentTab === name} onClick={() => setDocumentTab(name)}>{name}</button>)}</div>
        <article className={s.proposalBody}>{documentTab === "提案正文" ? renderProposalBody() : documentTab === "规格对比" ? <><h2>已定义与待确定</h2><p>当前没有可核对的竞品实测数据；仅呈现本案定义，未知项不参与数值比较。</p>{renderSpecs()}</> : <><h2>依据随内容保留</h2>{renderActivity()}<button className={s.textButton} onClick={source}>查看本预览的内容口径 <ArrowUpRight/></button></>}</article>
      </div><aside className={s.marginNotes}><p>定义状态</p><strong>保留未知</strong><small>2 项待确定内容已转入项目，不用虚构数值补齐。</small><button onClick={() => navigate(direction, "project")}>查看承接事项 <ArrowUpRight size={13}/></button><div className={s.contextDivider}/><Sparkle size={20}/><p>小Pai协作</p><small>起草内容已由本人确认。来源可随段落查看。</small><button onClick={() => setAiOpen(true)}>查漏与讨论 <ArrowRight size={13}/></button></aside>
    </div>;
  }
  function renderProject() {
    return <div className={`${s.standardPage} ${s.projectPage}`}><PageHeading view={view} title="便携充气泵" sub="S1 演示项目 · 负责人 胡汉伟" action={<Button onClick={primaryAction}>建立首版计划 <ArrowRight/></Button>}/>
      <div className={s.projectStates}><Badge>待建计划</Badge><span>固定定义 <b>v1</b></span><span>健康度 <b>未知</b></span><button onClick={() => navigate(direction, "proposal")}>来自立项提案 <ArrowUpRight size={13}/></button></div>
      <div className={s.projectNav}><button aria-current="page">现在</button>{["阶段与门禁", "工作与计划", "试制与验证", "资料"].map(name => <button key={name} onClick={() => name === "工作与计划" ? primaryAction() : show(name, "此入口在选定方案后接入现有业务页。本次比较聚焦 S1 的工作、提案与项目总览；不创建阶段记录或验证结果。")}>{name}</button>)}</div>
      <div className={s.projectContent}><div><section className={s.projectNext}><p className={s.eyebrow}>接下来</p><h2>让定义进入可执行的计划</h2><p>已批准的提案与固定定义 v1 已准备好。先明确工作包和负责人，再继续试制与验证准备。</p><div className={s.handoffSteps}><span><CheckCircle size={16}/>G0 已批准</span><CaretRight size={14}/><span><CheckCircle size={16}/>定义 v1</span><CaretRight size={14}/><button onClick={primaryAction}><Circle size={16}/>建立计划</button></div></section>
      <section className={s.projectTasks}><SectionTitle aside={<span className={s.muted}>2 项</span>}>需要推进</SectionTitle>{renderTaskRows(true)}</section>
      <section className={s.projectActivity}><SectionTitle aside={<button className={s.textButton} onClick={() => show("写状态更新", "这里将保留具名状态更新入口。真实提交须进入现有项目，本预览不写入任何项目动态。")}>写状态更新 <ArrowUpRight size={14}/></button>}>项目动态</SectionTitle>{renderActivity()}</section></div>
      <aside className={s.context}><SectionTitle>项目基线</SectionTitle><dl><Fact label="品类">汽车充气泵</Fact><Fact label="产品方向">便携款</Fact><Fact label="产品定义">固定 v1</Fact><Fact label="制造配置">待选择</Fact></dl><div className={s.contextDivider}/><SectionTitle>下一门禁</SectionTitle><p>阶段记录待提供</p><small>当前没有可确认的门禁日期。</small><dl><Fact label="承诺日期">未提供</Fact><Fact label="预测日期">未提供</Fact></dl><button className={s.textButton} onClick={source}>查看已有依据 <ArrowUpRight size={14}/></button></aside></div>
    </div>;
  }

  return <div className={`${s.lab} ${dark ? s.dark : ""}`}>
    <header className={s.reviewBar}><div><span className={s.brandMark}>P</span><strong>S1 界面设计</strong><span className={s.reviewTag}>交互预览 · 合成内容</span></div><div className={s.reviewTools}><a href="/preview">原应用 <ArrowUpRight size={13}/></a><button aria-label={narrow ? "切换桌面预览" : "切换窄屏预览"} aria-pressed={narrow} onClick={() => setNarrow(!narrow)}><Desktop size={17}/><span>{narrow ? "窄屏" : "桌面"}</span></button><button aria-label="切换预览明暗主题" onClick={() => setDark(!dark)}>{dark ? <Sun size={18}/> : <Moon size={18}/>}</button></div></header>
    <nav className={s.directionPicker} aria-label="设计方向">{directions.map(item => <button key={item.id} aria-pressed={direction === item.id} onClick={() => navigate(item.id, view)}><span className={s.directionLetter}>{item.id.toUpperCase()}</span><span><strong>{item.name}{item.id === "a" && <em>推荐</em>}</strong><small>{item.caption}</small></span><span className={s.radioDot}>{direction === item.id && <Check size={13}/>}</span></button>)}</nav>
    <div className={s.sceneBar}><div aria-label="预览页面">{views.map(item => <button key={item.id} aria-pressed={view === item.id} onClick={() => navigate(direction, item.id)}>{item.name}</button>)}</div><p>可切换页面、打开事项与小Pai；所有操作仅用于预览。</p></div>

    <div className={s.viewport} data-narrow={narrow}><div className={s.app} data-direction={direction}>
      <aside className={s.sidebar} data-mobile-open={menuOpen}><div className={s.appBrand}><span className={s.brandMark}>P</span><strong>PDOS</strong><SidebarSimple size={17}/></div><p className={s.navLabel}>工作空间</p><nav aria-label="预览工作区导航">{[{ name: "我的工作", icon: ListChecks, id: "work" as const }, { name: "项目", icon: FolderSimple, id: "project" as const }, { name: "立项提案", icon: FileText, id: "proposal" as const }].map(item => <button title={item.name} key={item.id} aria-current={view === item.id ? "page" : undefined} onClick={() => navigate(direction, item.id)}><item.icon size={18}/><span>{item.name}</span>{item.id === "work" && <small>2</small>}</button>)}<button title="知识" onClick={() => show("知识", "现有知识入口会保留。当前预览只比较三个 S1 承重界面。") }><BookOpen size={18}/><span>知识</span></button><button title="组合与资源" onClick={() => show("组合与资源", "全局导航保留组合与资源入口，实际能力按当前权限与实现状态呈现。") }><Users size={18}/><span>组合与资源</span></button></nav><div className={s.recentProject}><p className={s.navLabel}>当前项目</p><button onClick={() => navigate(direction, "project")}><Circle size={13}/><span>便携充气泵</span></button><small>S1 演示项目</small></div><div className={s.sidebarBottom}><button title="小Pai" onClick={() => setAiOpen(!aiOpen)}><Sparkle size={18}/><span>小Pai</span><CaretRight size={14}/></button><div className={s.profile}><span className={s.avatar}>胡</span><span><strong>胡汉伟</strong><small>产品管理 · 演示</small></span></div></div></aside>
      <div className={s.appBody}><header className={s.appHeader}><button className={s.menuButton} aria-label="展开预览导航" onClick={() => setMenuOpen(!menuOpen)}><List size={20}/></button><span>{view === "work" ? "个人空间" : "汽车充气泵"}</span><CaretRight size={13}/><strong>{views.find(item => item.id === view)?.name}</strong><button className={s.aiTrigger} aria-expanded={aiOpen} onClick={() => setAiOpen(!aiOpen)}><Sparkle size={16}/>小Pai</button></header><main className={s.content}>{view === "work" ? direction === "a" ? renderWorkA() : direction === "b" ? renderWorkB() : renderWorkC() : view === "proposal" ? renderProposal() : renderProject()}</main><footer className={s.appFooter}><span><CheckCircle size={13}/>S1 合成案例 · 设计样稿</span><button onClick={source}>内容口径与来源 <Info size={13}/></button></footer></div>
      {aiOpen && <aside className={s.aiPanel} aria-label="小Pai 协作预览"><header><span><Sparkle size={18}/><strong>小Pai</strong></span><button aria-label="关闭小Pai预览" onClick={() => setAiOpen(false)}><X size={18}/></button></header><div className={s.aiScope}><Tag size={14}/>当前范围 · {view === "work" ? "我的工作" : "便携充气泵"}</div><div className={s.aiBody}><span className={s.paiGlyph}><Sparkle size={25}/></span><h2>围绕当前工作，继续。</h2><p>两项噪声相关内容仍待确定。可以从整理依据开始。</p><button onClick={() => { setMessage("整理噪声指标与测试工况的待确认项"); setReply(false); }}>整理待确认项 <ArrowDown size={14}/></button><button onClick={() => navigate(direction, "proposal")}>回看立项提案 <ArrowUpRight size={14}/></button>{reply && <div className={s.aiReply}><Badge>预览回复 · 未调用模型</Badge><p>建议一起确认噪声目标与测试工况；现有材料没有可引用的数值，保留为未知。</p><button className={s.sourceLink} onClick={source}>依据：G0 承接事项 <ArrowUpRight size={13}/></button></div>}</div><form className={s.aiComposer} onSubmit={event => { event.preventDefault(); setReply(true); }}><label htmlFor="preview-pai-input">讨论当前内容</label><textarea id="preview-pai-input" placeholder="告诉小Pai你想推进什么…" value={message} onChange={event => { setMessage(event.target.value); setReply(false); }}/><div><small>仅演示交互</small><Button size="icon" aria-label="查看小Pai预览回复" disabled={!message.trim()}><PaperPlaneTilt/></Button></div></form></aside>}
    </div></div>

    <footer className={s.designNotes}><div><span className={s.directionLetter}>{direction.toUpperCase()}</span><p><strong>{selected.name}</strong><span>{selected.detail}</span><small>{selected.fit}</small></p></div><Button variant={chosen === direction ? "outline" : "default"} onClick={() => setChosen(direction)}>{chosen === direction ? <Check/> : null}{chosen === direction ? `已选 ${direction.toUpperCase()}` : `选择 ${direction.toUpperCase()} 方向`}</Button><p role="status" className={s.selectionNote}>{chosen ? `已在本次预览标记 ${chosen.toUpperCase()}。回到对话告诉我选择或组合偏好，再实施到实际页面。` : "先选方向，再改实际界面。"}</p></footer>
    <dialog ref={dialogRef} className={s.dialog} aria-labelledby="design-dialog-title"><div><h2 id="design-dialog-title">{dialog.title}</h2><button aria-label="关闭详情" onClick={() => dialogRef.current?.close()}><X size={20}/></button></div><p>{dialog.content}</p><Button variant="outline" onClick={() => dialogRef.current?.close()}><ArrowLeft/>返回预览</Button></dialog>
  </div>;
}
