/* Selected library regression using the installed TypeScript compiler. */
const fs = require("node:fs");
const path = require("node:path");
const Module = require("node:module");
const root = path.resolve(__dirname, "../web");
const dependency = Module.createRequire(path.join(root, "package.json"));
const ts = dependency("typescript");
const modules = new Map();
let icons;
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(fs.existsSync);
  if (!filename) throw new Error("Checkpoint module missing");
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename);
  modules.set(filename, loaded);
  const local = Module.createRequire(filename);
  loaded.require = name => name === "@phosphor-icons/react" ? icons : name.startsWith("@/") ? load(path.join(root, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : local(name);
  const compiled = ts.transpileModule(fs.readFileSync(filename, "utf8"), {fileName: filename, compilerOptions: {target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true}});
  loaded._compile(compiled.outputText, filename);
  return loaded.exports;
}
(async () => {
  const iconFile = path.join(path.dirname(dependency.resolve("@phosphor-icons/react")), "index.es.js");
  icons = await import(require("node:url").pathToFileURL(iconFile).href);
for (const name of (process.argv.length > 2 ? process.argv.slice(2) : ["build-start-view", "build-launch-view", "build-handoff-view", "build-results-view", "verification-professional", "build-preparation-view", "build-resource-reading"])) {
  const filename = [".test.ts", ".test.tsx"].map(ext => path.join(root, name.includes("/") ? "src" : "src/lib", name + ext)).find(fs.existsSync);
  if (filename) load(filename);
  else throw new Error(`Selected regression missing: ${name}`);
}

})().catch(error => { console.error(error.message); process.exitCode = 1; });
