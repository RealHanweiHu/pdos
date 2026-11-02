"use client";

import { useState, type ReactNode } from "react";
import {
  ArrowLeft,
  ArrowUpRight,
  CaretDown,
  FileText,
  LockSimple,
  MagnifyingGlass,
  Plus,
  PencilSimple,
  X,
} from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { roles } from "./design-data";
import { Sheet } from "./product-preview-ui";
import { CategoryBasics } from "./category-basics";
import { CategoryMaintenance } from "./category-maintenance";
import {
  latestCatalogRecords,
  type ProductCategory,
  type CatalogKind,
  type CatalogRecord,
} from "./category-preview-state";
import s from "./platform.module.css";
import p from "./product-preview.module.css";
import { type ProductController, type Proposal } from "./product-preview-state";

type Props = {
  controller: ProductController;
  disabled: boolean;
  empty: boolean;
  onPai: () => void;
  onCreateCategoryWithPai: () => void;
  onProposalPai: (
    categoryId: string,
    baseId?: string,
    seed?: { title: string; entry: Proposal["entry"] },
  ) => void;
  onCatalogPai: (
    kind: CatalogKind,
    record?: CatalogRecord,
    values?: Record<string, string>,
  ) => void;
  onProposal: (id?: string) => void;
  onProject: (id: string) => void;
  onModel: (id: string) => void;
  onInspect: (
    title: string,
    description: string,
    facts: [string, string][],
  ) => void;
};
function Header({
  title,
  children,
  action,
  titleAction,
}: {
  title: string;
  titleAction?: ReactNode;
  children?: ReactNode;
  action?: ReactNode;
}) {
  return (
    <header className={p.header}>
      <div>
        <div className={p.titleLine}>
          <h1>{title}</h1>
          {titleAction}
        </div>
        {children && <p>{children}</p>}
      </div>
      <div className={p.headerActions}>{action}</div>
    </header>
  );
}
function Search({
  value,
  onChange,
  label,
}: {
  value: string;
  onChange: (value: string) => void;
  label: string;
}) {
  return (
    <div className={p.search} role="search" aria-label={label}>
      <MagnifyingGlass size={14} />
      <input
        aria-label={label}
        placeholder={label}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Escape") onChange("");
        }}
      />
    </div>
  );
}
function Segments({
  values,
  value,
  onChange,
  label,
}: {
  values: string[];
  value: string;
  onChange: (value: string) => void;
  label: string;
}) {
  return (
    <nav className={p.tabs} aria-label={label}>
      {values.map((v) => (
        <button key={v} aria-pressed={v === value} onClick={() => onChange(v)}>
          {v}
        </button>
      ))}
    </nav>
  );
}
function DataTable({
  headers,
  rows,
  onRow,
}: {
  headers: string[];
  rows: string[][];
  onRow?: (row: string[], i: number) => void;
}) {
  return (
    <div className={`${s.tableWrap} ${p.table}`}>
      <table>
        <thead>
          <tr>
            {headers.map((h) => (
              <th key={h} scope="col">
                {h}
              </th>
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
function Empty({ children }: { children: ReactNode }) {
  return (
    <div className={p.empty}>
      <FileText size={22} />
      <h2>暂无匹配内容</h2>
      <p>{children}</p>
    </div>
  );
}
function ProposalRows({
  proposals,
  onOpen,
  compact = false,
  categories,
}: {
  categories: ProductCategory[];
  proposals: Proposal[];
  onOpen: (id: string) => void;
  compact?: boolean;
}) {
  return (
    <div className={`${s.tableWrap} ${p.table}`}>
      <table>
        <thead>
          <tr>
            <th scope="col">提案</th>
            {!compact && <th scope="col">品类</th>}
            <th scope="col">入口</th>
            <th scope="col">状态</th>
            <th scope="col">更新</th>
          </tr>
        </thead>
        <tbody>
          {proposals.map((item) => (
            <tr key={item.id}>
              <td>
                <button className={p.name} onClick={() => onOpen(item.id)}>
                  <FileText size={15} />
                  <span>{item.title}</span>
                  {!item.shared && (
                    <LockSimple size={12} aria-label="私有提案" />
                  )}
                </button>
              </td>
              {!compact && (
                <td>{categories.find((c) => c.id === item.category)?.name}</td>
              )}
              <td>{item.entry}</td>
              <td>
                <span className={p.status} data-status={item.status}>
                  {item.status}
                </span>
              </td>
              <td>{item.updated}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
export function ProductContinue({
  controller: c,
  onOpen,
  onAll,
}: {
  controller: ProductController;
  onOpen: (id: string) => void;
  onAll: () => void;
}) {
  const current = c.visible.filter(
    (v) => v.owner === c.person && v.status === "草稿",
  );
  return (
    <section className={p.continue}>
      <header>
        <h2>继续提案</h2>
        <button onClick={onAll}>
          全部提案 <ArrowUpRight size={13} />
        </button>
      </header>
      {current.length ? (
        <ProposalRows
          proposals={current.slice(0, 3)}
          categories={c.categories}
          onOpen={onOpen}
          compact
        />
      ) : (
        <p>暂无进行中的草稿，可从立项提案开始。</p>
      )}
    </section>
  );
}

export function ProductCategories(props: Props) {
  const {
    controller: c,
    empty,
    disabled,
    onCreateCategoryWithPai,
    onCatalogPai,
    onProposal,
    onInspect,
    onModel,
  } = props;
  const [query, setQuery] = useState("");
  const tab = c.categoryTab;
  const setTab = c.setCategoryTab;
  const [finding, setFinding] = useState(false);
  const [creating, setCreating] = useState(false);
  const [editing, setEditing] = useState(false);
  const category = c.category;
  if (!c.allowed)
    return (
      <div className={s.page}>
        <Empty>当前身份未分配产品管理范围。</Empty>
      </div>
    );
  if (!category) {
    const shown = empty
      ? []
      : c.categories.filter((v) =>
          `${v.name}${v.description}`
            .toLowerCase()
            .includes(query.trim().toLowerCase()),
        );
    return (
      <div className={`${s.page} ${p.page}`}>
        <Header
          title="品类"
          action={
            <Button disabled={disabled} onClick={() => setCreating(true)}>
              <Plus size={14} />
              新建品类
            </Button>
          }
        >
          从共享依据出发，管理型号与产品方向。
        </Header>
        <div className={p.toolbar}>
          <span>{shown.length} 个品类</span>
          <Search label="搜索品类" value={query} onChange={setQuery} />
        </div>
        {shown.length ? (
          <DataTable
            headers={["品类", "主要场景", "负责人", "型号", "我的草稿"]}
            rows={shown.map((v) => [
              v.name,
              v.description || "待补充",
              v.owner,
              String(v.models.length),
              String(
                c.visible.filter(
                  (a) =>
                    a.category === v.id &&
                    a.owner === c.person &&
                    a.status === "草稿",
                ).length,
              ),
            ])}
            onRow={(_, i) => {
              c.setCategoryId(shown[i].id);
              setTab("共享知识");
            }}
          />
        ) : (
          <Empty>新建一个品类，或调整搜索关键词。</Empty>
        )}
        {creating && (
          <CategoryBasics
            controller={c}
            disabled={disabled}
            onClose={() => setCreating(false)}
            onSaved={(id) => {
              c.setCategoryId(id);
              setTab("共享知识");
              setCreating(false);
              setQuery("");
            }}
            onPai={() => {
              setCreating(false);
              onCreateCategoryWithPai();
            }}
          />
        )}
      </div>
    );
  }
  const activeRecords = empty
    ? []
    : latestCatalogRecords(c.catalogRecords).filter(
        (v) => v.category === category.id && v.state === "active",
      );
  const competitors = activeRecords.filter((v) => v.kind === "competitor");
  const voices = activeRecords.filter((v) => v.kind === "voice");
  const parameters = activeRecords.filter((v) => v.kind === "parameter");
  const knowledge = [
    [
      "用户与场景",
      category.description || "尚未补充使用场景",
      "当前产品方向",
      "待持续核对",
    ],
    [
      "竞品库",
      `${competitors.length} 条竞品记录`,
      "实测 / 宣传 / 推断分别记录",
      competitors.length ? "查看与维护" : "尚未登记",
    ],
    [
      "用户声音",
      `${voices.length} 条声音记录`,
      "保留出处与样本量",
      voices.length ? "查看与维护" : "尚未登记",
    ],
    [
      "法规认证",
      category.id === "auto" ? "目标地区法规目录" : "尚未登记法规资料",
      category.id === "auto" ? "已登记资料" : "暂无来源",
      "版本与适用性待复核",
    ],
  ];
  const maintenanceKind =
    tab === "竞品库"
      ? "competitor"
      : tab === "用户声音"
        ? "voice"
        : tab === "规格字典"
          ? "parameter"
          : null;
  const categoryProposals = c.visible.filter((v) => v.category === category.id);
  return (
    <div className={`${s.page} ${p.page}`}>
      <button
        className={p.back}
        onClick={() => {
          c.setCategoryId(null);
          setQuery("");
        }}
      >
        <ArrowLeft size={13} />
        全部品类
      </button>
      <Header
        title={category.name}
        titleAction={
          <button
            className={p.editCategory}
            aria-label="编辑品类"
            title="编辑品类"
            disabled={disabled}
            onClick={() => setEditing(true)}
          >
            <PencilSimple size={16} />
          </button>
        }
        action={
          <>
            <Button variant="outline" onClick={() => setFinding(true)}>
              查看提案
            </Button>
            <Button
              disabled={disabled}
              onClick={() => props.onProposalPai(category.id)}
            >
              准备立项提案
            </Button>
          </>
        }
      >
        {category.description || "逐步补充当前品类的研究依据"} · 负责人{" "}
        {category.owner}
      </Header>
      {editing && (
        <CategoryBasics
          controller={c}
          category={category}
          disabled={disabled}
          onClose={() => setEditing(false)}
          onSaved={() => setEditing(false)}
          onPai={onCreateCategoryWithPai}
        />
      )}
      <Segments
        values={[
          "共享知识",
          "竞品库",
          "用户声音",
          "规格字典",
          "型号",
          "品类矩阵",
        ]}
        value={tab}
        onChange={setTab}
        label="品类内容"
      />
      {maintenanceKind ? (
        <CategoryMaintenance
          key={`${category.id}:${maintenanceKind}`}
          controller={c}
          kind={maintenanceKind}
          onPai={(record, values) =>
            onCatalogPai(maintenanceKind, record, values)
          }
          disabled={disabled}
          empty={empty}
        />
      ) : tab === "共享知识" ? (
        <>
          <div className={p.knowledgeRows}>
            {knowledge.map((row) => (
              <button
                key={row[0]}
                onClick={() =>
                  ["竞品库", "用户声音"].includes(row[0])
                    ? setTab(row[0])
                    : onInspect(
                        row[1],
                        "共享资料保留来源、适用范围与当前状态；客户原件在对应私有提案中查看。",
                        [
                          ["范围", row[0]],
                          ["依据", row[2]],
                          ["状态", row[3]],
                        ],
                      )
                }
              >
                <span>
                  <strong>{row[0]}</strong>
                  <small>
                    {row[2]} · {row[3]}
                  </small>
                </span>
                <span>{row[1]}</span>
                <ArrowUpRight size={14} />
              </button>
            ))}
          </div>
          <p className={p.note}>
            已登记 {parameters.length}{" "}
            个参数。客户原件保留在私有提案中，经人工去标识后才能沉淀为共享知识。
          </p>
        </>
      ) : tab === "型号" ? (
        category.models.length ? (
          <DataTable
            headers={["型号", "定义", "当前工作"]}
            rows={category.models.map((name) => [
              name,
              name.startsWith("P1")
                ? "v2 已发布 · v3 草稿"
                : name.startsWith("S1")
                  ? "v2 已发布"
                  : "版本待核对",
              name.startsWith("S1") ? "作为派生基线" : "查看定义与项目",
            ])}
            onRow={(row) =>
              row[0].startsWith("S1")
                ? onInspect(
                    row[0],
                    "派生提案保留固定父版，不自动跟随父版变化。",
                    [["定义", "v2 已发布"]],
                  )
                : category.project && onModel(category.project)
            }
          />
        ) : (
          <Empty>
            当前品类尚无型号。新建提案不自动建立型号，批准后再进入项目。
          </Empty>
        )
      ) : (
        <>
          {category.models.length || competitors.length ? (
            <DataTable
              headers={["产品 / 竞品", "细分场景", "报价", "数据类型"]}
              rows={[
                ...category.models.map((name) => [
                  name,
                  category.description || "待补充",
                  "尚无同口径数据",
                  "待补充",
                ]),
                ...competitors.map(({ values: v }) => [
                  v.name,
                  v.scenario || "待补充",
                  v.price
                    ? `${v.currency} ${v.price} · ${v.priceBasis}`
                    : "未知",
                  v.evidence,
                ]),
              ]}
            />
          ) : (
            <Empty>新增竞品后会显示在这里；未知价格不会自动补齐。</Empty>
          )}
          <p className={p.note}>
            矩阵随当前有效竞品记录更新。缺少同口径价格与性能时不生成分布图，私有提案不进入共享矩阵。
          </p>
        </>
      )}
      {finding && (
        <Sheet title="查找品类提案" onClose={() => setFinding(false)}>
          <h1>{category.name} · 提案</h1>
          <p>仅显示当前身份可访问的提案。</p>
          {categoryProposals.length ? (
            categoryProposals.map((v) => (
              <button
                className={p.finderRow}
                key={v.id}
                onClick={() => {
                  setFinding(false);
                  onProposal(v.id);
                }}
              >
                <span>
                  {v.title}
                  <small>
                    {v.entry} · v{v.version} · {v.shared ? "品类共享" : "私有"}
                  </small>
                </span>
                <span>{v.status}</span>
              </button>
            ))
          ) : (
            <p className={p.note}>
              该品类尚无可访问的提案，可关闭后与小Pai准备。
            </p>
          )}
        </Sheet>
      )}
    </div>
  );
}

export function ProductProposals(props: Props) {
  const { controller: c, disabled, empty, onProposal } = props;
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("全部");
  const [category, setCategory] = useState("全部品类");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [newCategory, setNewCategory] = useState("auto");
  const [entry, setEntry] = useState<Proposal["entry"]>("自主新品");
  if (!c.allowed)
    return (
      <div className={s.page}>
        <Empty>当前身份未分配产品管理范围。</Empty>
      </div>
    );
  if (c.selected)
    return (
      <ProposalDetail key={c.selected.id} {...props} proposal={c.selected} />
    );
  const shown = empty
    ? []
    : c.visible.filter(
        (v) =>
          `${v.title}${v.id}`
            .toLowerCase()
            .includes(query.trim().toLowerCase()) &&
          (status === "全部" || v.status === status) &&
          (category === "全部品类" || v.category === category),
      );
  return (
    <div className={`${s.page} ${p.page}`}>
      <Header
        title="立项提案"
        action={
          <Button
            disabled={disabled}
            onClick={() => {
              setName("");
              setCreating(true);
            }}
          >
            <Plus size={14} />
            新建提案
          </Button>
        }
      >
        把想法和需求整理为可判断的产品方案。
      </Header>
      <div className={p.listTools}>
        <Segments
          values={["全部", "草稿", "评审中", "已批准"]}
          value={status}
          onChange={setStatus}
          label="提案状态"
        />
        <div className={p.controls}>
          <div className={p.select}>
            <select
              aria-label="筛选提案品类"
              value={category}
              onChange={(e) => setCategory(e.target.value)}
            >
              <option>全部品类</option>
              {c.categories.map((v) => (
                <option value={v.id} key={v.id}>
                  {v.name}
                </option>
              ))}
            </select>
            <CaretDown size={12} />
          </div>
          <Search label="搜索提案" value={query} onChange={setQuery} />
        </div>
      </div>
      {shown.length ? (
        <ProposalRows
          proposals={shown}
          categories={c.categories}
          onOpen={onProposal}
        />
      ) : (
        <Empty>调整搜索或筛选条件，也可以新建一个私有草稿。</Empty>
      )}
      <p className={p.note}>
        <LockSimple size={12} /> 新建提案默认私有；G0
        批准后才建立型号定义与项目。
      </p>
      {creating && (
        <Sheet title="新建提案" onClose={() => setCreating(false)}>
          <h1>先记录要解决的问题</h1>
          <p>创建私有草稿后，可以直接编辑，也可以与小Pai一起完善。</p>
          <form
            className={p.form}
            onSubmit={(e) => {
              e.preventDefault();
              if (!name.trim() || disabled) return;
              c.create(name, newCategory, entry);
              setCreating(false);
            }}
          >
            <label>
              提案名称
              <input
                autoFocus
                value={name}
                onChange={(e) => setName(e.target.value)}
                placeholder="例如：更适合长途出行的充气方案"
                required
              />
            </label>
            <label>
              所属品类
              <select
                value={newCategory}
                onChange={(e) => setNewCategory(e.target.value)}
              >
                {c.categories.map((v) => (
                  <option value={v.id} key={v.id}>
                    {v.name}
                  </option>
                ))}
              </select>
            </label>
            <label>
              提案入口
              <select
                value={entry}
                onChange={(e) => setEntry(e.target.value as Proposal["entry"])}
              >
                {["自主新品", "派生迭代", "客户需求"].map((v) => (
                  <option key={v}>{v}</option>
                ))}
              </select>
            </label>
            <p className={p.note}>
              <LockSimple size={13} /> 私有 · 仅本人，提交后向具名评审人开放
            </p>
            <div className={p.controls}>
              <Button
                type="button"
                disabled={disabled}
                onClick={() => {
                  props.onProposalPai(newCategory, undefined, {
                    title: name,
                    entry,
                  });
                  setCreating(false);
                }}
              >
                让小Pai起草
              </Button>
              <Button
                variant="outline"
                type="submit"
                disabled={disabled || !name.trim()}
              >
                手动创建
              </Button>
            </div>
          </form>
        </Sheet>
      )}
    </div>
  );
}

function ProposalDetail({
  proposal: item,
  ...props
}: Props & { proposal: Proposal }) {
  const { controller: c, disabled, onProject, onPai } = props;
  const [tab, setTab] = useState("提案");
  const [submitting, setSubmitting] = useState(false);
  const [reviewer, setReviewer] = useState("");
  const [message, setMessage] = useState("");
  const draft = c.drafts[item.id];
  const editable = item.status === "草稿" && item.owner === c.person;
  const canSubmit = !!(
    item.summary.trim() &&
    item.audience.trim() &&
    item.options.every((v) => v.trim()) &&
    item.choice.trim() &&
    item.specs.length > 0 &&
    item.specs.every((row) => row[0].trim() && row[1].trim()) &&
    item.questions.every((v) => v.title.trim() && v.owner && v.due.trim())
  );
  const setDraft = (value: Proposal | null) =>
    c.setDrafts((current) => {
      const next = { ...current };
      if (value) next[item.id] = value;
      else delete next[item.id];
      return next;
    });
  const patch = (value: Partial<Proposal>) => {
    if (draft) setDraft({ ...draft, ...value });
  };
  return (
    <div className={`${s.page} ${p.page}`}>
      <button className={p.back} onClick={() => c.setProposalId(null)}>
        <ArrowLeft size={13} />
        全部提案
      </button>
      <Header
        title={item.title}
        action={
          item.status === "已批准" ? (
            <Button onClick={() => item.project && onProject(item.project)}>
              进入项目
              <ArrowUpRight size={14} />
            </Button>
          ) : editable ? (
            draft ? (
              <>
                <Button variant="outline" onClick={() => setDraft(null)}>
                  取消编辑
                </Button>
                <Button
                  disabled={disabled || !draft.title.trim()}
                  onClick={() => {
                    c.save(draft);
                    setMessage("修订已保存到预览，原版本保留。");
                  }}
                >
                  保存修订
                </Button>
              </>
            ) : (
              <>
                <Button
                  variant="outline"
                  disabled={disabled}
                  onClick={() => {
                    setDraft({ ...item, options: [...item.options] });
                    setTab("提案");
                    setMessage("");
                  }}
                >
                  编辑草稿
                </Button>
                <Button
                  disabled={disabled || !canSubmit}
                  onClick={() => {
                    setReviewer("");
                    setSubmitting(true);
                  }}
                >
                  提交 G0 评审
                </Button>
              </>
            )
          ) : (
            <span className={p.note}>等待 {item.reviewer} 评审</span>
          )
        }
      >
        {c.categories.find((v) => v.id === item.category)?.name} · {item.entry}{" "}
        · {item.id}
      </Header>
      <div className={p.meta}>
        <span className={p.status} data-status={item.status}>
          {item.status}
        </span>
        <span>v{item.version}</span>
        {item.aiDraft && <span>AI 起草 · 已确认保存</span>}
        <span>负责人 {item.owner}</span>
        <span>
          {item.shared ? (
            "品类共享"
          ) : (
            <>
              <LockSimple size={12} />
              私有
            </>
          )}
        </span>
        <button
          disabled={disabled}
          onClick={
            editable ? () => props.onProposalPai(item.category, item.id) : onPai
          }
        >
          {editable ? "与小Pai完善" : "与小Pai讨论"}
          <ArrowUpRight size={12} />
        </button>
      </div>
      {message && (
        <p className={p.notice} role="status">
          {message}
        </p>
      )}
      {item.status !== "草稿" && (
        <p className={p.frozen}>
          {item.status === "已批准"
            ? "立项时的版本已固定。后续产品定义修订在项目中继续。"
            : `v${item.version} 已固定并提交给 ${item.reviewer}，尚未批准，不产生新项目。`}
        </p>
      )}
      <Segments
        values={["提案", "规格对标", "功能配置", "定义成熟度", "证据与决定"]}
        value={tab}
        onChange={setTab}
        label="提案视图"
      />
      {tab === "提案" ? (
        <div className={p.documentLayout}>
          <article className={p.document}>
            {draft ? (
              <div className={p.form}>
                <label>
                  提案名称
                  <input
                    value={draft.title}
                    onChange={(e) => patch({ title: e.target.value })}
                  />
                </label>
                <label>
                  目标用户与场景
                  <input
                    value={draft.audience}
                    onChange={(e) => patch({ audience: e.target.value })}
                  />
                </label>
                <label>
                  要解决的问题
                  <textarea
                    value={draft.summary}
                    onChange={(e) => patch({ summary: e.target.value })}
                  />
                </label>
                <div className={p.optionFields}>
                  {draft.options.map((value, i) => (
                    <label key={i}>
                      方案 {i === 0 ? "A" : "B"}
                      <textarea
                        value={value}
                        onChange={(e) => {
                          const options: [string, string] = [...draft.options];
                          options[i] = e.target.value;
                          patch({ options });
                        }}
                      />
                    </label>
                  ))}
                </div>
                <label>
                  当前取舍与理由
                  <textarea
                    value={draft.choice}
                    onChange={(e) => patch({ choice: e.target.value })}
                  />
                </label>
                <section className={p.editSection}>
                  <header>
                    <h2>关键定义</h2>
                    <button
                      onClick={() =>
                        patch({
                          specs: [
                            ...draft.specs,
                            ["", "", "待确认来源", "待确认"],
                          ],
                        })
                      }
                    >
                      <Plus size={13} />
                      添加规格
                    </button>
                  </header>
                  {draft.specs.map((row, index) => (
                    <div className={p.specFields} key={index}>
                      {["规格名称", "当前定义", "参数引用 / 来源"].map(
                        (label, column) => (
                          <label key={label}>
                            {label}
                            <input
                              aria-label={`${label} ${index + 1}`}
                              value={row[column]}
                              onChange={(e) =>
                                patch({
                                  specs: draft.specs.map((v, i) =>
                                    i === index
                                      ? v.map((cell, j) =>
                                          j === column ? e.target.value : cell,
                                        )
                                      : v,
                                  ),
                                })
                              }
                            />
                          </label>
                        ),
                      )}
                      <button
                        aria-label={`移除规格 ${index + 1}`}
                        onClick={() =>
                          patch({
                            specs: draft.specs.filter((_, i) => i !== index),
                          })
                        }
                      >
                        <X size={14} />
                      </button>
                    </div>
                  ))}
                </section>
                <section className={p.editSection}>
                  <header>
                    <h2>待决问题</h2>
                    <button
                      onClick={() =>
                        patch({
                          questions: [
                            ...draft.questions,
                            { title: "", owner: c.person, due: "" },
                          ],
                        })
                      }
                    >
                      <Plus size={13} />
                      添加问题
                    </button>
                  </header>
                  {draft.questions.map((question, index) => (
                    <div className={p.questionFields} key={index}>
                      <label>
                        问题
                        <input
                          aria-label={`待决问题 ${index + 1}`}
                          value={question.title}
                          onChange={(e) =>
                            patch({
                              questions: draft.questions.map((v, i) =>
                                i === index
                                  ? { ...v, title: e.target.value }
                                  : v,
                              ),
                            })
                          }
                        />
                      </label>
                      <label>
                        负责人
                        <select
                          aria-label={`问题负责人 ${index + 1}`}
                          value={question.owner}
                          onChange={(e) =>
                            patch({
                              questions: draft.questions.map((v, i) =>
                                i === index
                                  ? { ...v, owner: e.target.value }
                                  : v,
                              ),
                            })
                          }
                        >
                          <option value="">待认领</option>
                          {roles
                            .filter((r) => r.id !== "external")
                            .map((r) => (
                              <option key={r.id}>{r.person}</option>
                            ))}
                        </select>
                      </label>
                      <label>
                        期限
                        <input
                          aria-label={`问题期限 ${index + 1}`}
                          value={question.due}
                          placeholder="如 10月28日"
                          onChange={(e) =>
                            patch({
                              questions: draft.questions.map((v, i) =>
                                i === index ? { ...v, due: e.target.value } : v,
                              ),
                            })
                          }
                        />
                      </label>
                      <button
                        aria-label={`移除问题 ${index + 1}`}
                        onClick={() =>
                          patch({
                            questions: draft.questions.filter(
                              (_, i) => i !== index,
                            ),
                          })
                        }
                      >
                        <X size={14} />
                      </button>
                    </div>
                  ))}
                </section>
                <p className={p.note}>
                  草稿暂存在本次预览中；点击“保存修订”后更新版本。
                </p>
              </div>
            ) : (
              <>
                <section>
                  <h2>要解决的问题</h2>
                  <p className={p.audience}>
                    {item.audience || "目标用户与场景待补充"}
                  </p>
                  <p>
                    {item.summary ||
                      "先写清楚为谁解决什么问题，再比较可行方案。"}
                  </p>
                </section>
                <section>
                  <h2>关键定义</h2>
                  {item.specs.length ? (
                    <DataTable
                      headers={["规格", "当前定义", "引用", "状态"]}
                      rows={item.specs}
                    />
                  ) : (
                    <p className={p.note}>
                      尚未录入关键规格；可与小Pai讨论并整理候选。
                    </p>
                  )}
                </section>
                <section>
                  <h2>方案与取舍</h2>
                  <div className={p.options}>
                    {item.options.map((value, i) => (
                      <div key={i}>
                        <h3>方案 {i === 0 ? "A" : "B"}</h3>
                        <p>{value || "待补充方案、投入与周期"}</p>
                      </div>
                    ))}
                  </div>
                  <p className={p.choice}>{item.choice || "尚未选择方案。"}</p>
                </section>
              </>
            )}
            {!draft && (
              <section>
                <h2>
                  {item.status === "已批准"
                    ? "已转入项目的待决问题"
                    : "待决问题"}
                </h2>
                {item.questions.length ? (
                  <DataTable
                    headers={["问题", "负责人", "期限"]}
                    rows={item.questions.map((v) => [
                      v.title,
                      v.owner || "待认领",
                      v.due || "待确认",
                    ])}
                  />
                ) : (
                  <p className={p.note}>尚未登记待决问题，不代表没有风险。</p>
                )}
              </section>
            )}
          </article>
          <aside className={p.context}>
            <h2>提案信息</h2>
            {!!item.categorySources?.length && (
              <details className={p.sourceDetails}>
                <summary>品类资料 · {item.categorySources.length} 条</summary>
                {item.categorySources.map((r) => (
                  <p key={`${r.id}:${r.version}`}>
                    <strong>{r.name}</strong>
                    <br />
                    {r.id} v{r.version}
                    <br />
                    {r.source}
                  </p>
                ))}
              </details>
            )}
            <dl>
              <dt>范围</dt>
              <dd>{item.shared ? "品类成员" : "负责人 / 具名评审人"}</dd>
              <dt>最近更新</dt>
              <dd>{item.updated}</dd>
              {item.baseline && (
                <>
                  <dt>固定父版</dt>
                  <dd>{item.baseline}</dd>
                </>
              )}
              {item.reviewer && (
                <>
                  <dt>评审人</dt>
                  <dd>{item.reviewer}</dd>
                </>
              )}
            </dl>
            <h2>当前依据</h2>
            <p>{item.source}</p>
            <button onClick={() => setTab("证据与决定")}>
              查看依据与版本
              <ArrowUpRight size={12} />
            </button>
            {editable && !canSubmit && (
              <p className={p.note}>
                提交前请补齐场景、关键定义、两个方案与取舍，并为待决问题安排负责人和期限。
              </p>
            )}
          </aside>
        </div>
      ) : tab === "规格对标" ? (
        <>
          <DataTable
            headers={["规格", "我方定义", "可比较依据", "比较结论"]}
            rows={item.specs.map((v) => [
              v[0],
              v[1],
              v[2],
              item.id === "PA-001"
                ? "口径尚未统一，不作优劣判断"
                : "尚未形成可比数据",
            ])}
          />
          <p className={p.note}>
            未知项不画点；实测、宣传与推断分开记录。私有客户原件不进入品类对标。
          </p>
        </>
      ) : tab === "功能配置" ? (
        <DataTable
          headers={["方案", "功能与范围", "当前取舍"]}
          rows={item.options.map((v, i) => [
            `方案 ${i === 0 ? "A" : "B"}`,
            v || "待补充",
            item.choice || "待确认",
          ])}
        />
      ) : tab === "定义成熟度" ? (
        <DataTable
          headers={["定义范围", "当前状态", "下一步"]}
          rows={[
            [
              "用户与场景",
              item.audience ? "已描述" : "待补充",
              "继续核对使用者与依据",
            ],
            [
              "关键规格",
              `${item.specs.length} 条已登记，仍有待确认项`,
              "补齐目标、工况与版本",
            ],
            [
              "方案取舍",
              item.choice ? "已记录选择" : "待补充",
              "核对投入与周期",
            ],
            ["成本、认证与制造", "待专业判断", "不以提案填写代替专业结论"],
          ]}
        />
      ) : (
        <div className={p.document}>
          <section>
            <h2>证据与适用范围</h2>
            <p>{item.source}</p>
            {item.entry === "客户需求" && (
              <p className={p.note}>
                原件覆盖不完整，标准品匹配仍待核对；创建提案不等于需要立项开发。
              </p>
            )}
          </section>
          <section>
            <h2>版本与决定</h2>
            <ol className={p.history}>
              {[...item.history].reverse().map((v, i) => (
                <li key={`${v.version}-${i}`}>
                  <span>v{v.version}</span>
                  <div>
                    <strong>{v.text}</strong>
                    <p>{v.summary}</p>
                    {v.snapshot && (
                      <details className={p.versionDetails}>
                        <summary>查看保留版本</summary>
                        <p>{v.snapshot.title}</p>
                        <p>{v.snapshot.audience}</p>
                        {v.snapshot.source && <p>{v.snapshot.source}</p>}
                        <p>{v.snapshot.options.join(" / ")}</p>
                        <p>{v.snapshot.choice}</p>
                        <DataTable
                          headers={["规格", "定义", "引用", "状态"]}
                          rows={v.snapshot.specs}
                        />
                        <DataTable
                          headers={["待决问题", "负责人", "期限"]}
                          rows={v.snapshot.questions.map((q) => [
                            q.title,
                            q.owner,
                            q.due,
                          ])}
                        />
                      </details>
                    )}
                  </div>
                </li>
              ))}
            </ol>
          </section>
        </div>
      )}
      {submitting && (
        <Sheet title="提交 G0 评审" onClose={() => setSubmitting(false)}>
          <h1>提交当前版本</h1>
          <p>
            {item.title} · v{item.version}
          </p>
          <div className={p.reviewSummary}>
            <p>
              本次固定提案内容、方案取舍与 {item.questions.length}{" "}
              项待决问题。评审人判断是否立项，提交本身不创建项目。
            </p>
            <p>{item.choice}</p>
          </div>
          <label className={p.reviewer}>
            具名评审人
            <select
              value={reviewer}
              onChange={(e) => setReviewer(e.target.value)}
            >
              <option value="">选择评审人</option>
              {["林悦", "郑言"]
                .filter((name) => name !== c.person)
                .map((name) => (
                  <option key={name}>{name}</option>
                ))}
            </select>
          </label>
          <p className={p.note}>
            预览使用已分配品类产品管理权限的合成人员；不执行真实提交。
          </p>
          <Button
            disabled={disabled || !reviewer || !canSubmit}
            onClick={() => {
              c.submit(item.id, reviewer);
              setSubmitting(false);
              setMessage("已在预览中提交，等待具名评审。");
            }}
          >
            确认提交 v{item.version}
          </Button>
        </Sheet>
      )}
    </div>
  );
}
