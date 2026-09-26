// Copy pinned browser runtimes and their notices; no CDN or file conversion service.
import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { mkdir, copyFile, readFile } from "node:fs/promises";
const require = createRequire(import.meta.url);
const root = resolve(import.meta.dirname, "..");
for (const [name, version, files] of [
  ["occt-import-js", "0.0.23", ["occt-import-js.js", "occt-import-js.wasm", "license.occt-import-js.txt", "license.occt.txt"]],
  ["gerber-to-svg", "4.2.8", ["gerber-to-svg.min.js", "gerber-to-svg.min.js.LICENSE.txt"]],
]) {
  const packagePath = require.resolve(`${name}/package.json`);
  const metadata = JSON.parse(await readFile(packagePath, "utf8"));
  if (metadata.version !== version) throw new Error(`${name} runtime version changed; update the drawing worker and review its API`);
  const target = resolve(root, "public/vendor/drawings", `${name}-${version}`);
  await mkdir(target, { recursive: true });
  for (const file of files) await copyFile(resolve(dirname(packagePath), "dist", file), resolve(target, file));
}
