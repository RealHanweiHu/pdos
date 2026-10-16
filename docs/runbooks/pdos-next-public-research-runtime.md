# pdos-next 默认公开研究运行配置

在 [租户模型宿主文件](pdos-next-tenant-model-runtime.md)增加可选 `research` 块，即可让默认 API/Worker 绑定现有 Searx 搜索、隔离网页/PDF读取、研究台账与作业文件，以及 PostgreSQL 子图检查点。省略或设为 `null` 时保持研究未接入，不影响其他业务。

```json
{
  "research": {
    "search_endpoint": "http://127.0.0.1:18888/search",
    "search_provider": "replace-with-registered-search-provider",
    "artifact_root": "/absolute/private/pdos-next/research"
  }
}
```

上面是需要合入宿主文件的字段示例，不是一份独立宿主文件；端口为占位，不代表本机服务已运行或获得外网调用授权。`search_endpoint` 指向管理员实际选择的 Searx JSON 搜索入口，可用服务器受控的 HTTP/HTTPS 地址，禁止 URL 用户名、密码、查询参数和片段；该适配不从环境继承代理或搜索密钥，也不支持在这个块中配置认证凭据。

`search_provider` 必须与当前服务商协议标识一致。网页读取逐站使用 `public-web:<hostname>` 标识，在 DNS 和 HTTP 之前执行当前 Run 出站政策；查询/URL、资料类别和客户身份仍由服务器检查。配置文件不会创建或批准协议。目前这条接线沿用完整 Run 的资料类别：携带 `internal/customer/customer_original` 的运行，搜索及逐站读取都要求相应有效协议；**按实际查询字段投影公开内容与完整私有标识检查仍需继续收敛**，不能把此接线当作该部分 v1.1 出口已完成。

`artifact_root` 为 API 与 Worker 都能访问的同一私有持久目录，须使用绝对路径。多主机部署需要挂载同一底层存储，不能仅让目录名称相同。按运行服务器 UUID 隔离保存正文快照及不可变研究台账；HTTP/模型工具参数不指定文件路径。保留这个目录及其数据库关联作为恢复材料，不把临时缓存目录当成长期作业卷。目录不可用时只禁用依赖的研究端口；恢复挂载后重启 API/Worker。

Worker 沿用 `PDOS_CHECKPOINT_DATABASE_URL` 及既有检查点目标核对机制；研究子图用独立 thread，与主图共同写入已核对的 `pdos_checkpoints`。缺少或不匹配的连接不会降级为内存检查点。本地 profile 需要 `PDOS_STATE_DB_PORT`、`PDOS_STATE_DB_MARKER` 对应现有独立环境，不填写业务库或复用未经核对的目标。

默认接线保留现有读取规则：本轮搜索/本人消息才可提供 URL，只有只读研究子任务接收网页正文；主循环读取逐字核对台账、实际快照引用与代码生成的覆盖/失败。公开 PDF 沿用隔离解析容器和固定镜像，解析服务不可用时如实失败，不在主进程替代解析。正式登记快照经受控命令；无资格/授权时保留 T1 预览和本人一次确认。

修改研究服务端点、provider 或作业卷后须重启 API/Worker。模型/凭据/价格卡继续按原手册逐次读取。完成的研究台账可从同一作业文件恢复，核对原快照与实际读取证明，不重跑搜索或模型；终态 Run 不因此取得发起新工具调用的权限。

[本地闭环证据](../reports/evidence/pdos-next-m3-20261016/research-host/result.md)使用实际默认 API/lifespan、Temporal、Worker 主入口、LangGraph/PostgreSQL、人工确认及业务快照；模型、KMS、搜索、DNS 和网页网络传输均为合成。真实搜索质量、站点连通性、真实协议和模型资格、生产卷/Temporal 恢复与完整 M3/S1 验收仍需对应证据。本次配置不创建云资源、不自动启动真实联网研究。
