# 本人偏好实际浏览器验证 · 2026-10-29 UTC

本轮使用主会话冻结的677输入前端候选 `/tmp/pdos-parallel-designs-build-20261029/pdos-next/web`，预览端口58262、实际隔离RLS API端口58261。本人登录仅由主会话给定的storage state装入独立Playwright会话 `pdos-preferences-20261029`；未读取或输出actor私有token，未复制cookie/storage文件到证据目录。真实推理start/signal/cancel端口由主会话禁用。

## 实际操作与结果

1. 打开设置，默认值为跟随当前提问、适中、岗位未设置、空部门和零收藏。可读品类“汽车充气泵”出现在候选列表；项目列表显示没有可用范围。本夹具没有项目，没有为浏览器检查虚造项目。
2. 显式选择 `en` / `detailed` / `quality`，部门填“合成质量部”，勾选可读品类，点击保存。页面显示已保存、品类候选和两个质量岗位欢迎示例。完整刷新后值与勾选保留。
3. 在1280px亮/暗、390px暗、320px暗检查并截图。三个宽度下document宽度分别等于1280/390/320；main的scrollWidth等于clientWidth，偏好输入/select/button越出右边界的数量均为0。320px单列无截断，标签、说明、搜索、保存和清空均可读可用。
4. 在320px使用真实点击选择框后Escape与Tab，焦点依次到回答详略→岗位→部门；部门的计算焦点outline为solid，原生控件可键盘进入。
5. 从个人小Pai页读取保存的两个质量岗位示例和常用品类导航。点击“查找类似质量问题的处理记录”后，textarea变为同句并获得焦点；URL仍为 `?area=pai`，背景仍为“通用对话”。点击前后的请求列表完全相同，都是session/categories/projects/preferences/conversations五个GET，没有新增POST或Agent运行。未按发送。
6. 之后显式点击常用品类导航，URL才进入 `?area=projects&category=64a52cf5-3ba2-43e8-a91f-ce98279daec8`；当前可读项目列表为空，正常显示“暂无可见项目”。
7. 返回设置并点击清空，刷新后验证 `auto` / `balanced` / 空岗位 / 空部门 / 零勾选，已保存导航与岗位示例消失。返回小Pai后恢复原三个通用欢迎示例，导航候选为0。之前本人点选的输入草稿仍保留；清空账户偏好不会擅自删除该草稿。

## 截图与DOM证据

| 状态 | 截图 |
|---|---|
| 默认亮色1280 | [01-default-light-1280.png](output/playwright/01-default-light-1280.png) |
| 保存并刷新后的亮色1280 | [02-saved-light-1280.png](output/playwright/02-saved-light-1280.png) |
| 保存后的暗色1280 | [03-saved-dark-1280.png](output/playwright/03-saved-dark-1280.png) |
| 保存后的暗色390 | [04-saved-dark-390.png](output/playwright/04-saved-dark-390.png) |
| 保存后的暗色320 | [05-saved-dark-320.png](output/playwright/05-saved-dark-320.png) |
| 岗位欢迎示例仅填入 | [06-role-welcome-filled-1280.png](output/playwright/06-role-welcome-filled-1280.png) |
| 清空并刷新 | [07-cleared-dark-1280.png](output/playwright/07-cleared-dark-1280.png) |
| 清空后默认欢迎 | [08-default-welcome-1280.png](output/playwright/08-default-welcome-1280.png) |

DOM快照：[默认](output/playwright/01-default-dom.yml)、[已保存](output/playwright/02-saved-dom.yml)、[欢迎仅填入](output/playwright/06-role-welcome-filled-dom.yml)、[已清空](output/playwright/07-cleared-dom.yml)、[恢复默认欢迎](output/playwright/08-default-welcome-dom.md)。

## 控制台与边界

认证后的设置、欢迎、手动导航和清空路径控制台均为0 error / 0 warning，见[认证后控制台](output/playwright/console-authenticated.txt)。首次装入登录状态前，空登录首页记录session401和favicon404，见[初始控制台](output/playwright/console-before-login.log)；二者没有冒充为认证后页面错误。

[最终请求概要](output/playwright/network-final.txt)只包含方法、URL与状态，不包含请求头、cookie或凭据；唯一写请求为本人点击的偏好POST，未发送聊天问题。此会话未触发真实模型或embedding，也未执行领域命令。主会话保留API/运行计数核对的权威证据。

没有发现需要修改本子任务源码的真实UI缺陷，因此此次浏览器验证没有改变冻结前端候选。真实项目收藏浏览器路径因该专用夹具无项目未重复制造样本；其实际PG/API正负例已在主会话14/14专用测试通过。

工具启动曾遇npx元数据解析与沙箱Chrome缓存/Crashpad限制；改用已存在的缓存CLI和获准独立PTY/临时daemon目录后完成上述检查，没有安装依赖、修改Chrome安全设置或触碰其他浏览器/服务进程。

收尾已关闭本次独立Playwright session及其PTY launcher；按本子任务两个已知PID86530/86857复核均不存在。主会话的预览/API服务及共享合成登录文件保持原样，由主会话统一收尾。
