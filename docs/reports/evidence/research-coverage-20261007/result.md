# 小Pai多轮研究与热门产品覆盖

2026-10-07。用户要求扩大原3000/8000预览的资料搜索及代表产品覆盖，保留此前关闭的每日/累计 token 额度。0431及v7最终真实公开研究已answered：5次查询、30条不同网址线索、17次读取/13份正文，8款/7品牌产品对比及13个引用完整返回；这是当前公开样本的采集与回复通过，不是全部热门排名或产品八能力资格。

## 实现与边界

- `xiaopai-public-research-v2`：最多7次模型研究选择、6次查询，每次至多10条候选，自动读3条新网址；总读取尝试最多24次。模型根据资料覆盖选择继续查询、读取或回答，重复网址/查询不再次派发。
- 品类研究提示覆盖产品发现、官方规格及独立评测/用户声音，通常目标8–12款跨品牌、价格带和供电/场景代表产品。热门结论要求地区/时间及排名、评论量或重复评测依据；未证实仅为热门候选或代表样本。不是全网穷尽或销量资格声明。
- 全来源身份保留；真实大资料量失败后，正文投影从24,000字符改为共用12,000字符，保留开头及优先包含规格单位、价格、评论/评测的逐字原文片段，按原顺序展示并标明省略/截断，完整原文与工具回执不裁减。候选模型窗口最多12条/4,000字符，总线索计数及完整观察不变。v1旧回复可读，v2每轮必须匹配实际冻结授权和模型checkpoint，旧回执前缀不可改写，伪造追加拒绝。
- 0431只替换相关守卫函数，不建表/改角色。已采用v2历史拒绝降级；独立空库往返通过。固定提示新增版本，不更改旧版本；预算profile、真实计量包、资格、权限及T1/T2批准不变。
- 进度窗口保留最近16步，较早数量明确提示，完整研究观察独立保存。解决第四轮后流式回调找不到已被旧上限丢弃步骤的真实缺陷。

## 验证范围

原候选[后端42项](backend-final.log)41通过，1项旧降级错误文案断言失败；修正为当前0431拒绝原因后[7项复核](backend-recheck.log)通过，包含该病例及6项额度回归。合计48个不同受影响病例，不声称单次48项全部通过。较早v1触发器/授权版本绑定及合成输入窗口失败分别保留于backend-first/v2/v3日志。

[原前端18项](frontend.log)、类型/规范通过。真实失败后当前源码[进度与覆盖9项](backend-progress-recovery.log)通过：四轮读取10份不同品牌的合成公开资料，真实授权/checkpoint/工具账本、流式思考/正文回调和最终回答、重复/伪造/重放、窗口与停用、来源失败归因；公网上游为合成传输。[相关前端15项](frontend-progress-recovery.log)及[窗口提示3项](frontend-progress-note.log)通过，规范通过。新整库类型检查首次因另一活动任务的provider测试mock签名报错，见typecheck-recovery.log；该任务修正其mock参数后[最终类型检查](typecheck-final.log)通过。尚未重复全构建或正式联合Exit。

repo测试仅自有独立容器/卷及显式TEST_DATABASE_URL。初始49457、重启后53194/pdos_test；主57432/pdos未运行repo测试。前后收尾保留test-closeout-before-progress-fix.json与test-closeout.json，私有备份并验证归档，清理停服，卷保留。

## 实际预览与失败恢复

[私有备份](live-backup.json)验证后[应用0431](application-migration.json)，原unknown journal和三个legacy trace摘要保持。[合法Owner只读回读](runtime-readback.json)确认MiniMax-M3可用、token额度false，无重复政策写入。

[首个真实公开请求](real-public-research.json)最终unavailable。实际回执有4次查询、29条不同网址线索、12次读取/11份部分正文，四个已知模型调用25,256输入/3,494输出token；第五次在流式进度回调中断，未取得完整用量，其14,672 token预留继续unknown，模型会话仍unknown。未将预留当实际消费或零用量，没有删除历史、假造失败trace或释放名额。直接原因是16步旧窗口丢弃后续model_step，随后回调next()抛StopIteration；共享代码同期变化已核对并保留，但不是已证实的直接中断原因。见[失败账本核对](real-public-research-proof.json)。

修复后补四轮流式回归，确认本地无open会话（原unknown保留）后[稳定重启](progress-fix-restart.json)。[第二次新公开请求](real-public-research-recovered.json)在1次查询/3份部分正文后因 `APPLICATION_CONTEXT_BUNDLE_CHANGED` 停止，未重复原未知调用。十份当前关键文件摘要未变化，但bundle覆盖全server/app、提示、迁移及安全SQL，共享工作区其他活动改动触发了守卫。记录另在real-public-research-recovered-proof.json，不把被拒绝的后续调用宣称为成功。

为持续完成授权内研究，将server/app、迁移及安全SQL复制到0700的固定本地运行副本，保存[1574份文件摘要](runtime-snapshot.json)，原golden、脚本、资产/证书只读引用，未复制或改写凭据。API8000及提醒worker从该固定副本运行，web3000仍为原应用；无源码守卫绕过、资格替换或账本重置。启动脚本为tmp/research-coverage-preview.sh，正常源码更新需重新启动采用。[第三次固定版本公开请求](real-public-research-frozen.json)在4次查询、32条不同网址线索及12次读取/11份正文后因 `PROVIDER_OUTPUT_TRUNCATED` 结束。完整用量和原失败记录见real-public-research-frozen-proof.json；输出触及单次边界仍不发布为最终答复。

新增reply/preproject v6固定提示，复用其他活动任务的v5质量规则并保留旧文件：补查时只选择工具且answer/citation_ids为空，approach≤120字；广泛产品研究默认8–12行紧凑表、表外≤200字/总计≤1200汉字，商业榜单不当独立评测。未扩张冻结profile或计量资格。[13项相关后端](backend-prompt-final.log)通过后，在新[1577文件固定副本](runtime-snapshot-v6.json)验证8行公开研究简表。[第四次真实请求](real-public-research-compact.json)有5次查询、41条不同网址线索、15次读取/13份正文，但仍因 `PROVIDER_OUTPUT_TRUNCATED` 不发布最终回复；67,681输入/9,040输出token均known并settled，本次会话全部closed，原unknown仍保留，见[回执核对](real-public-research-compact-proof.json)。本机发布计量包与冻结research_discussion均限定单次输出4,000，取消每日/累计额度未改变该边界。

采用上述原文片段投影后，[9项受影响验证](backend-focused-excerpts-recheck.log)通过：新增长文末尾规格与逐字来源验证，四轮流式研究及原守卫复核。首轮7通过/2失败因另一个活动任务新增持久运行服务准入，未配置该测试运行时，见backend-focused-excerpts.log；复核仅在已核对的独立58214/pdos_test使用其明确的 `PDOS_AGENT_RUNTIME_MODE=injected-test` 入口，仍运行实际图，不对真实主预览设置测试模式。自有测试库已私有备份、清理停服，见test-closeout.json；较早收尾原件保存于test-closeout-before-focused-excerpts.json。

主预览先核对open=0/unknown=1，再重启采用投影。固定运行副本以v6为基础，只刷新当前任务的conversation_research.py，未采用同期其他任务新引入的持久运行接线；1259份实际源码bundle摘要见[runtime-snapshot-focused-excerpts.json](runtime-snapshot-focused-excerpts.json)，启动/排空见focused-excerpts-restart.json，当前工作区增量另见candidate-files-focused-excerpts.json。[第五次新公开请求](real-public-research-focused.json)实际6次查询、48条不同网址线索、19次读取/16份正文。临时answer已产生8行表，但最终JSON仍 `PROVIDER_OUTPUT_TRUNCATED`，不能当作正式完整答复；73,672输入/9,690输出token均known/settled，本次会话全部closed、无新增unknown，原unknown保留。见[实际核对](real-public-research-focused-proof.json)。

v7候选进一步减少重复引用编号：公开来源由原服务器最终回执按全部实际已读引用附上，模型无须再次枚举这些长snapshot ID，正文按短域名归因；业务/项目及其他来源仍沿原citation_ids，非法引用和来源漂移守卫不变，仍保留全部原文。[14项相关后端](backend-prompt-v7-recheck.log)通过，覆盖无模型引用ID的多轮全来源附加与非法引用拒绝；初次收集因同期包编辑安装路径未能导入pdos_agent_runtime而失败，见backend-prompt-v7.log，复核显式加入现有包src，不安装、替换或改变运行环境资格。仅核对的独立60638/pdos_test，私有备份后清理停服，test-closeout.json及前件保留。

主预览再次open=0排空后，在原固定副本仅更新两个prompt文件及其版本引用，[1261份实际bundle摘要](runtime-snapshot-v7.json)保留完整范围，未引入其他活动任务的持久运行接线。[最后真实请求](real-public-research-v7.json)耗时约514秒，answered；5次查询、30条不同网址线索、17次读取/13份正文（7份部分截断，4页未取得正文），8行代表产品对比及13份引用返回。8个模型调用记录均成功，含1个结构化重试，实际共9次派发；72,922输入/12,311输出token均known/settled，本次会话全closed，无新增unknown；最后一调用输出3,750，单次4,000、每日/累计额度false及其他冻结政策未改。原unknown与legacy摘要保持，0次品类/提案确认，见[真实账本核对](real-public-research-v7-proof.json)。[8,192可选输出候选](expanded-output-proposal.md)未批准、未采用；此次成功不依赖扩张资格或取消单次边界。

正文仍为AI研究草稿：热度依据中有规格/价格描述，不能当销量证明；商业榜单和历史评测不能替代当前热门/现价或标准测试口径资格。原模型answer保持不改写，界面已明确加草稿提示；对比表用安全原生table渲染，未知值及表前后说明保留，不执行外部HTML。[16项前端复核](frontend-final-table-recheck.log)、受影响规范与类型检查通过；首轮15通过/1失败因新测试缺cleanup导致跨病例DOM残留，原件frontend-final-table.log保留，修正夹具后同16项复核通过。没有重跑无新影响的后端或全构建。最终低风险单元格最小宽度经规范与GUI核对，未增加镜像测试。

[实际GUI回读](browser-final-proof.json)显示过程已完成、5次搜索/30条线索/13份正文、8行表和草稿提示、参考资料13；不宣称逐一打开13个源链接。[截图](preview-final.png)保存正常尺寸的实际表格，未调整浏览器尺寸。原用户页保留，当前结果页也保留。核对中观察到用户在应用中主动续问“生成品类”，保持其运行，没有重启、停止或替用户确认保存；后续品类生成/人工采用不算本次完成。主3000/8000保持固定v7后台及当前前端，[最终增量与实际运行差异](candidate-files-final.json)保留；独立测试库已备份停服，非本轮服务及源码不清理。

保留当前主预览；原人工Exit、产品八能力资格、真实研究到品类候选保存整链不在本次覆盖声明内。原未知调用准确用量仍需供应商真实回执。
