const fs=require('node:fs'),path=require('node:path');
const ts=require("/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/web/node_modules/typescript"),root="/Users/huhanwei/Documents/ai-native-R&D-platform/pdos-next/web";
for(const name of ['verification-professional.ts','verification-professional.test.ts']) {
 const source=fs.readFileSync(path.join(root,'src/lib',name),'utf8');
 const compiled=ts.transpileModule(source,{fileName:name,compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.CommonJS,esModuleInterop:true}});
 fs.writeFileSync(path.join(__dirname,name.replace(/\.ts$/,'.js')),compiled.outputText);
}
