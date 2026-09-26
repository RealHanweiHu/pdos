/* global occtimportjs, gerberToSvg, importScripts */
// One original per worker. The caller terminates this worker on completion, cancellation or timeout.
const STEP_RUNTIME = "/vendor/drawings/occt-import-js-0.0.23/";
const GERBER_RUNTIME = "/vendor/drawings/gerber-to-svg-4.2.8/";
const MAX_VERTICES = 2000000;
const MAX_TRIANGLES = 2000000;
self.onmessage = async event => {
  try {
    const { kind, buffer } = event.data;
    if (!(buffer instanceof ArrayBuffer) || !buffer.byteLength || buffer.byteLength>20*1024*1024) throw new Error("原件为空或超过20 MiB解析范围");
    if (kind === "step") {
      importScripts(`${STEP_RUNTIME}occt-import-js.js`);
      const warnings = []; let warningCount = 0;
      const warn = value => { warningCount++; if (warnings.length<20) warnings.push(String(value).slice(0,500)); };
      const occt = await occtimportjs({ locateFile: path => `${STEP_RUNTIME}${path}`, print: warn, printErr: warn });
      const result = occt.ReadStepFile(new Uint8Array(buffer), { linearUnit: "millimeter", linearDeflectionType: "bounding_box_ratio", linearDeflection: 0.001, angularDeflection: 0.5 });
      if (!result.success || !Array.isArray(result.meshes) || !result.meshes.length) throw new Error("STEP未生成可显示几何，原件仍可下载");
      if (result.meshes.length>2048) throw new Error("模型包含超过2048个网格，超出当前浏览器预览范围");
      let vertices = 0, triangles = 0, faces = 0; const transfer = [];
      const meshes = result.meshes.map(mesh => {
        const positions = new Float32Array(mesh.attributes.position.array), indices = new Uint32Array(mesh.index.array);
        faces += (mesh.brep_faces ?? []).length;
        if (faces>30000) throw new Error("模型包含超过30,000个边界面分组，超出当前浏览器显示范围");
        vertices += positions.length/3; triangles += indices.length/3;
        if (vertices>MAX_VERTICES || triangles>MAX_TRIANGLES || positions.length%3 || indices.length%3 || !positions.length || !indices.length) throw new Error("模型网格为空、不完整或超过当前预览容量，请下载原件核对");
        if (!positions.every(Number.isFinite) || !mesh.index.array.every(v => Number.isInteger(v) && v>=0 && v<positions.length/3)) throw new Error("解析结果包含无效几何坐标或索引");
        const normal = mesh.attributes.normal?.array;
        const normals = normal && normal.length===positions.length && normal.every(Number.isFinite) ? new Float32Array(normal) : null;
        transfer.push(positions.buffer, indices.buffer); if (normals) transfer.push(normals.buffer);
        return { name: String(mesh.name || "未命名网格").slice(0,256), positions, indices, normals, color: mesh.color ?? null, faces: mesh.brep_faces ?? [] };
      });
      self.postMessage({ kind, meshes, vertices, triangles, units: "mm", warnings, warningCount, parser: "occt-import-js@0.0.23" }, transfer);
    } else if (kind === "gerber") {
      importScripts(`${GERBER_RUNTIME}gerber-to-svg.min.js`);
      const input = new TextDecoder("utf-8", { fatal: true }).decode(buffer).trim();
      // Do not silently use the parser's inch/coordinate defaults for ambiguous originals.
      if (!/%MO(?:MM|IN)\*%/.test(input) || !/%FS[LT][AI]X\d\dY\d\d\*%/.test(input)) throw new Error("此Gerber未声明完整单位/坐标格式，不能可靠确定图层尺寸；请核对原件");
      const warnings = []; let warningCount = 0;
      let converter;
      const svg = await new Promise((resolve, reject) => {
        converter = gerberToSvg(input, { id: "pdos-gerber", filetype: "gerber", attributes: { color: "#c2410c" } }, (error, value) => error ? reject(error) : resolve(value));
        converter.on("warning", warning => { warningCount++; if (warnings.length<20) warnings.push(`第${warning.line ?? "?"}行：${String(warning.message).slice(0,500)}`); });
      });
      if (typeof svg!=="string" || svg.length>20*1024*1024 || !converter.layer.length || !["in","mm"].includes(converter.units) || !Number.isFinite(converter.width) || !Number.isFinite(converter.height) || converter.width<=0 || converter.height<=0) throw new Error("图层为空或超出当前显示范围，请下载原件核对");
      self.postMessage({ kind, svg, units: converter.units, width: converter.width, height: converter.height, viewBox: converter.viewBox, warnings, warningCount, parser: "gerber-to-svg@4.2.8" });
    } else throw new Error("尚未接入此图纸格式");
  } catch (error) { self.postMessage({ error: error instanceof Error ? error.message : "图纸解析失败" }); }
};
