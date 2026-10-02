const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const crypto = require('node:crypto');
const root = path.resolve(__dirname, '../../../..');
const ts = require(path.join(root, 'web/node_modules/typescript'));
const focusPath = path.join(root, 'web/src/components/ai/conversation-work-focus.tsx');
const contextPath = path.join(root, 'web/src/components/ai/xiaopai-page-context.ts');
const focusSource = fs.readFileSync(focusPath, 'utf8');
const parsed = ts.createSourceFile(focusPath, focusSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
const selected = parsed.statements.filter(s => (ts.isFunctionDeclaration(s) && s.name?.text === 'parseWorkFocus') || (ts.isTypeAliasDeclaration(s) && s.name.text === 'WorkFocus'));
function evaluate(source, dependencies = {}) {
  const compiled = ts.transpileModule(source, {compilerOptions: {module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022}}).outputText;
  const sandbox = {exports: {}, URL, URLSearchParams, require(name) {
    if (!(name in dependencies)) throw new Error('Unexpected dependency: ' + name);
    return dependencies[name];
  }};
  vm.runInNewContext(compiled, sandbox);
  return sandbox.exports;
}
const focus = evaluate(selected.map(s => s.getText(parsed)).join('\n'));
const context = evaluate(fs.readFileSync(contextPath, 'utf8'), {'./conversation-work-focus': focus});
const project = '10000000-0000-4000-8000-000000000001';
const entity = '20000000-0000-4000-8000-000000000001';
const probes = [
  ['current issue link', {project, tab:'work-items', view:'issues', entity_id:entity}],
  ['current stage link', {project, tab:'work-items', entity_id:entity}],
  ['recognized legacy issue link', {project, issue:entity}],
  ['explicit typed focus link', {project, focus_kind:'issue', focus_id:entity}],
].map(([label, params]) => ({label, params, result: context.resolveXiaopaiPageContext('/projects', new URLSearchParams(params))}));
const result = {method:'Execute current pure source functions with TypeScript transpilation; no network, model or database access',
  hashes: Object.fromEntries([focusPath, contextPath].map(p => [path.relative(root,p),crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex')])), probes};
fs.writeFileSync(path.join(__dirname,'context-probes.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(probes.map(p => ({label:p.label,project:p.result.projectId,focus:p.result.focus ?? null})),null,2));
