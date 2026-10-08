# 本地自动研究启用材料

2026-10-06。当前状态：计量包正式发布与本地预算切换已完成，旧未知用量保留并追加用户批准的占账，同网站来源登记冲突已修复，实际搜索、原文读取、引用回复和GUI回读已完成，内容质量与完整品类保存整链待齐。见[本地启用结果](enablement-result.md)。最新状态见[发布与采用记录](meter-adoption.md)，原候选参数见[计量复核记录](meter-review.md)。下方保留准备阶段的历史条件，不能视为当前待批事项。

## 已准备的可检查内容

已有 `server/scripts/probe_minimax_input_metering.py` 只生成候选证据，不写golden或计量资格。重新取得[MiniMax-M3固定提交的官方资产](https://huggingface.co/MiniMaxAI/MiniMax-M3/blob/f0e1c1e04d40177e4673a22097036854f536e9c0/chat_template.jinja)，三份SHA-256与仓库之前登记的预检完全一致：[资产记录](meter-assets.json)。当前国内API端点的离线预检见[meter-preflight.json](meter-preflight.json)，未执行模型请求。

真实校准计划限四条合成输入，包含短文本、Unicode、结构化schema和接近拟定输入上限。离线估计合计16,604输入tokens，各次最大输出32tokens，无自动重试。输入只使用脚本内的虚构文本，计数样本与客户资料、提案及业务数据库无关。脚本保存每次实际usage与request_id；用量未知或供应商未遵守输出上限时立即停止，保留不确定回执。

以下命令已在用户授权后执行一次，四次调用观察已保存；不要重复执行或覆盖旧回执：

```sh
cd /Users/huhanwei/Documents/ai-native-R\&D-platform/server
.venv/bin/python -m scripts.probe_minimax_input_metering \
  --tokenizer-dir ../tmp/minimax-m3-meter-assets-20261006 \
  --output ../docs/reports/evidence/preproject-research-runtime-20261006/meter-observations.json \
  --execute
```

## 仍需满足的条件

1. 若已有真实计量发布包，先读取其路径、独立可信SHA-256和配套材料，核对模型、端点、适用范围及有效期。当前只有API Key和MiniMax-M3模型golden资格，不能当作输入计量发布包。
2. 四条实际请求已按用户授权发送至当前MiniMax端点，输入计数4/4一致，合计16,604输入和128输出token。用户确认后正式发布文件和固定摘要预算配置已生成，实际发布包只读核验通过。
3. 采用现有获批 `research_discussion` 等适用的预算profile，固定真实发布包绝对路径和由可信部署配置提供的摘要。不能通过运行时读文件自行计算摘要来代替可信配置。
4. 按[现有模式切换流程](../../../runbooks/application-budget-adoption.md)检查租户admission、未完模型调用和未知用量，先draining再切换。旧失败运行保留原终态；在原对话继续研究时生成新的受控运行，不覆盖旧证据。
5. 预算通道就绪后，再检查公开来源DNS和真实搜索→原文→引用候选→人工采用的整链。不能把本次配置问题与来源DNS问题合并为同一个“已修好”。

本轮没有修改私有 `.env`、golden可信根、租户模式、额度、角色权限或真实业务数据。真实请求限已授权的四条合成校准；原候选空白人工字段保留，独立正式文件依用户确认发布。旧未知用量须有真实回执核对，合法Owner/Admin完成准入后才能应用已确认配置和执行研究验证。
