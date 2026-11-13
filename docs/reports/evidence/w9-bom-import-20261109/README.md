# W9 D98 BOM 导入、版本差异与规则卡（D282、P113）· 证据

worktree `hopeful-joliot-438789`，分支 `claude/hopeful-joliot-438789`，2026-11-09 至 11-10，本地提交未推送。全部是合成数据；没有调用模型，也没有真实外发。

## 范围
- 导入：XLSX/CSV 原件走既有的上传、扫描和隔离解析。`POST …/configurations/bom-import/inputs`（READ）只读解析出的单元格和定位，用确定性规则转换：表头同义词建议列映射，逐行校验，不能照原样导入的行逐条处置。保存仍用 `engineering.bom.revise`（T1，整版一次确认）。确认时服务端按 `import_basis` 再转换一次，行不一致就拒绝。
- 差异：`domain/builds/configurations/bom_diff.py`，页面 `GET …/configurations/boms/{bom_id}/review` 和 Excel 导出共用（D282）。
- 规则卡五条：重复位号、位号数与用量不符、缺单位、数量非正或未知、替代料无资格。都是确定性规则，不经模型，只提示，不阻止保存。
- 替代料（P113）：BOM 行上只是声明，不构成资格。“替代料无资格”只读 Build 级批准记录；D47 合入前显示“暂不能判断（批准记录未接入）”（D433）。

## 验证
- 后端无库：`tests/builds/test_bom_import_rules.py` 16 项，含替代料和规则卡的未接入状态。
- 迁移：`tools/local_environment.py create` 用含 `s0_0900`（11-10 第五轮集成改号为 `s0_0876`）的链做了 head→base→head 往返，并跑了 seed（两次建库都通过）。
- PG，隔离临时库 `pdos_test`，显式 `TEST_DATABASE_URL`：
  - `tests/builds/test_bom_import_pg.py` 2 项端到端：上传、扫描、隔离解析 → 转换 → 逐行处置 → 篡改行被拒 → 保存 → 续版：内部编号复用、ERP 提示、替代料、差异 → 导出带位号和替代料列 → CSV → 他人私有原件被拒、非 CSV 文本被拒。
  - 受影响的既有用例：配置命令、BOM 差异导出、工程投影共 46 项；BOM 链（Build、供应与成本执行、开工、G0 下游、原件、上传视图）131 项；加了替代料之后，在重建的库上又跑了工程投影、Build、供应执行、开工、G0 下游、上传视图共 83 项。都通过。测试库已销毁。
  - 第一次跑时，既有配置用例有 17 项失败：空的导入依据被写成了 JSON null，撞上检查约束。改用 `JSONB(none_as_null=True)` 后全过。
- 前端：`next typegen && tsc --noEmit`、`eslint src/features/builds` 0 错误；`bom-review.test.mjs` 5 项；上传与代理相关的 `.mjs`、`.test.ts` 共 276+131 项都通过。
- 合同：`tools/export_contracts.py`，`openapi.json` 只增两条读取路径；`tools/validate_contracts.py` 通过。

## 浏览器走查（本地 dev，webpack）
- `version-review-light.jpg`、`version-review-dark.jpg`：v2 对 v1 的差异，包括用量、位号 +R4、替代料 +RD-300，删除和新增的行；规则卡中“替代料无资格 · 暂不能判断”；导入摘要显示“未导入替代料 1 个（RD-999）”。
- `version-review-375-dark.jpg`：375px 宽度下页面不横向滚动，规则卡正常折行；差异表在自己的区域内横向滚动。
- `import-review-light.jpg`：导入 v3。ERP 料号相同的行等待处置，规则卡标出重复位号 M1 和位号数与用量不符。截图在修正前：行标识和“变化”列在窄栏里会折断，之后已改为不换行。
- `import-confirm-light.jpg`：一次确认对话框显示服务端预览的差异和规则卡，确认后保存为 v3。截图在修正前：对话框偏在左上角，之后已加 `m-auto` 居中。页面其他旧确认框也有同样问题，登记为 D434。
- 走查用的种子是临时测试 `test_zz_bom_browser_seed.py`（未提交）。为了与种子的合成扫描端口一致，API 用同一合成扫描运行时启动；用默认本地运行时时，原件显示为 stale，导入面板按设计不列出它们。

## 余项
D430（小Pai 建议列映射）、D431（同次导入新建的物料不能当替代料）、D433（接入 D47 的替代料批准记录）、D434（旧确认框不居中）。
