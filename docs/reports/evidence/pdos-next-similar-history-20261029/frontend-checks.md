# 前端检查记录

以下记录来自本代理 2026-10-29 的实际终端检查；不是浏览器/HTTP/数据库验收。

工作目录：`pdos-next/web`。

```text
node --test src/lib/similar-history.test.mjs src/components/similar-history.test.mjs src/components/app-shell-knowledge.test.mjs src/components/projects/project-professional-records.test.mjs

tests 33
suites 0
pass 33
fail 0
cancelled 0
skipped 0
todo 0
exit_code=0
```

覆盖：打开只读；具名事实和未知展示；明确“不相关”反馈成功后收起；网络丢失按同一 key/body 重试；待重试时另一次打开不替换原反馈；撤权/陈旧隐藏卡片并明确重查；重复准备反馈重试后仍接原 T1 callback；没有现有 merge 资格不展示；Pai 带入双方固定引用但不调用 API；BFF 范围/版本唯一/有限动作/零自由文字/同源/服务器 cookie 身份/错误状态/无缓存/不透传私有头；实际 AppShell 保留固定 pair；跨项目/品类回调拒绝；quality/followup 实际行详情挂载固定 Issue 版本。

```text
./node_modules/.bin/eslint src/components/similar-history.tsx src/components/similar-history-pai.tsx src/lib/similar-history.ts src/lib/similar-history-proxy.ts src/components/app-shell.tsx src/components/projects/project-professional-records.tsx src/components/builds/build-quality-loop.tsx src/components/category-material-editor.tsx 'src/app/api/v1/categories/[categoryId]/products/[productId]/quality-issues/[issueId]/similar-history/route.ts' 'src/app/api/v1/categories/[categoryId]/products/[productId]/quality-issues/[issueId]/similar-history/feedback/route.ts'

exit_code=0（无诊断输出）
```

最终 `tsc` / 全构建 / 新候选浏览器由主会话集中执行。旧偏好 677 输入候选截图不能作为本卡片候选的截图证据。
