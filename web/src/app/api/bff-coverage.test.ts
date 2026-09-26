import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";

import { describe, expect, it } from "vitest";
import ts from "typescript";

/**
 * Every `/api/...` the browser calls must have a Next route handler behind it.
 *
 * Component tests mock `fetch`, so a missing route handler is invisible to them:
 * the page passes its unit tests and then shows "unavailable" in the real app.
 * That is exactly how the My Work page shipped broken. This test compares the
 * two sides directly.
 */

const SRC = join(process.cwd(), "src");

/** iCloud leaves " 2" copies behind in this repo; they are not real sources. */
function isDuplicate(name: string): boolean {
  return / 2(\.|$)/.test(name);
}

function walk(dir: string, onFile: (path: string) => void): void {
  for (const entry of readdirSync(dir)) {
    if (isDuplicate(entry)) continue;
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) walk(path, onFile);
    else onFile(path);
  }
}

function sourceTargets(source: string, path: string): string[] {
  const file = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  type FunctionNode = ts.FunctionDeclaration | ts.ArrowFunction | ts.FunctionExpression;
  type Binding = { name: string; node: ts.Node; value?: ts.Expression; parameter?: ts.ParameterDeclaration; property?: string };
  const bindings: Binding[] = [];
  const functions: FunctionNode[] = [];
  const calls: ts.CallExpression[] = [];
  const elements: (ts.JsxOpeningElement | ts.JsxSelfClosingElement)[] = [];
  const isFunction = (node: ts.Node): node is FunctionNode => ts.isFunctionDeclaration(node) || ts.isArrowFunction(node) || ts.isFunctionExpression(node);
  function visit(node: ts.Node) {
    if (isFunction(node)) functions.push(node);
    if (ts.isVariableDeclaration(node) || ts.isParameter(node)) {
      if (ts.isIdentifier(node.name)) bindings.push({ name: node.name.text, node, value: node.initializer, parameter: ts.isParameter(node) ? node : undefined });
      if (ts.isObjectBindingPattern(node.name)) {
        for (const item of node.name.elements) {
          if (ts.isIdentifier(item.name)) bindings.push({ name: item.name.text, node, value: item.initializer, parameter: ts.isParameter(node) ? node : undefined, property: item.propertyName?.getText(file) ?? item.name.text });
        }
      }
    }
    if (ts.isCallExpression(node)) calls.push(node);
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) elements.push(node);
    ts.forEachChild(node, visit);
  }
  visit(file);
  function scope(node: ts.Node): ts.Node {
    if (ts.isParameter(node)) return node.parent;
    let parent = node.parent;
    while (parent && !ts.isBlock(parent) && !ts.isSourceFile(parent)) parent = parent.parent;
    return parent ?? file;
  }
  function contains(outer: ts.Node, inner: ts.Node) { return outer.pos <= inner.pos && outer.end >= inner.end; }
  function lookup(node: ts.Identifier): Binding | undefined {
    return bindings.filter(entry => entry.name === node.text && contains(scope(entry.node), node) && (entry.parameter || entry.node.pos < node.pos))
      .sort((left, right) => scope(right.node).pos - scope(left.node).pos || right.node.pos - left.node.pos)[0];
  }
  function functionName(node: FunctionNode): string | undefined {
    return ts.isFunctionDeclaration(node) || ts.isFunctionExpression(node) ? node.name?.text : ts.isVariableDeclaration(node.parent) && ts.isIdentifier(node.parent.name) ? node.parent.name.text : undefined;
  }
  function calledFunction(call: ts.CallExpression): FunctionNode | undefined {
    if (!ts.isIdentifier(call.expression)) return;
    const name = call.expression.text;
    return functions.filter(fn => functionName(fn) === name && contains(scope(fn), call))
      .sort((left, right) => scope(right).pos - scope(left).pos)[0];
  }
  const unique = (values: string[]) => [...new Set(values)];
  const concat = (left: string[], right: string[]) => unique(left.flatMap(a => right.map(b => a + b)));
  function unwrap(node: ts.Expression): ts.Expression {
    return ts.isParenthesizedExpression(node) || ts.isAsExpression(node) || ts.isSatisfiesExpression(node) || ts.isNonNullExpression(node) ? unwrap(node.expression) : node;
  }
  function object(node: ts.Expression, seen = new Set<ts.Node>()): ts.ObjectLiteralExpression | undefined {
    node = unwrap(node);
    if (seen.has(node)) return;
    if (ts.isObjectLiteralExpression(node)) return node;
    if (ts.isIdentifier(node)) {
      const value = lookup(node)?.value;
      if (value) return object(value, new Set(seen).add(node));
    }
  }
  function literalType(type?: ts.TypeNode): string[] {
    if (!type) return [];
    if (ts.isLiteralTypeNode(type) && ts.isStringLiteral(type.literal)) return [type.literal.text];
    if (ts.isUnionTypeNode(type)) {
      const values = type.types.map(literalType);
      return values.every(value => value.length > 0) ? values.flat() : [];
    }
    return [];
  }
  function resolve(node: ts.Expression, seen = new Set<ts.Node>()): string[] {
    node = unwrap(node);
    if (seen.has(node)) return [":param"];
    const next = new Set(seen).add(node);
    if (ts.isStringLiteralLike(node)) return [node.text];
    if (ts.isTemplateExpression(node)) {
      return node.templateSpans.reduce((values, span) => concat(concat(values, resolve(span.expression, next)), [span.literal.text]), [node.head.text]);
    }
    if (ts.isConditionalExpression(node)) return unique([...resolve(node.whenTrue, next), ...resolve(node.whenFalse, next)]);
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) return concat(resolve(node.left, next), resolve(node.right, next));
    if (ts.isElementAccessExpression(node) || ts.isPropertyAccessExpression(node)) {
      const value = object(node.expression);
      if (value) {
        const keys = ts.isPropertyAccessExpression(node) ? [node.name.text] : resolve(node.argumentExpression, next);
        const values = value.properties.filter(ts.isPropertyAssignment).filter(property => keys.includes(":param") || keys.includes(property.name.getText(file).replace(/^["']|["']$/g, "")));
        if (values.length) return unique(values.flatMap(property => resolve(property.initializer, next)));
      }
    }
    if (ts.isIdentifier(node)) {
      const binding = lookup(node);
      if (binding?.parameter && isFunction(binding.parameter.parent)) {
        const parameter = binding.parameter;
        const fn = parameter.parent as FunctionNode;
        const index = fn.parameters.indexOf(parameter);
        const values: string[] = [];
        for (const call of calls.filter(call => calledFunction(call) === fn)) {
          const argument = call.arguments[index] ?? parameter.initializer;
          if (!argument) continue;
          if (binding.property) {
            const property = object(argument)?.properties.find(property => ts.isPropertyAssignment(property) && property.name.getText(file) === binding.property);
            if (property && ts.isPropertyAssignment(property)) values.push(...resolve(property.initializer, next));
          } else values.push(...resolve(argument, next));
        }
        if (binding.property && index === 0) {
          for (const element of elements.filter(element => element.tagName.getText(file) === functionName(fn))) {
            const attribute = element.attributes.properties.find(attribute => ts.isJsxAttribute(attribute) && attribute.name.getText(file) === binding.property);
            if (attribute && ts.isJsxAttribute(attribute) && attribute.initializer) {
              const value = ts.isJsxExpression(attribute.initializer) ? attribute.initializer.expression : attribute.initializer;
              if (value) values.push(...resolve(value, next));
            }
          }
        }
        if (values.length) return unique(values);
        const type = binding.property && parameter.type && ts.isTypeLiteralNode(parameter.type) ? parameter.type.members.find(member => ts.isPropertySignature(member) && member.name.getText(file) === binding.property) : parameter;
        const literals = type && (ts.isParameter(type) || ts.isPropertySignature(type)) ? literalType(type.type) : [];
        if (literals.length) return literals;
      }
      if (binding?.value) return resolve(binding.value, next);
    }
    return [":param"];
  }
  return unique(calls.flatMap(call => {
    if (!ts.isIdentifier(call.expression) || !call.arguments[0]) return [];
    const prefix = call.expression.text === "fetch" ? "" : call.expression.text === "caseLinkRequest" ? "/api/" : undefined;
    if (prefix === undefined) return [];
    return resolve(call.arguments[0]).map(value => (prefix + value).split(/[?#]/)[0].replace(/\/+$/, ""))
      .filter(target => target.startsWith("/api/") && target !== "/api/:param");
  }));
}

function fetchTargets(): Set<string> {
  const targets = new Set<string>();
  walk(join(SRC, "components"), (path) => {
    if (!/\.tsx?$/.test(path) || path.includes(".test.")) return;
    for (const target of sourceTargets(readFileSync(path, "utf8"), path)) targets.add(target);
  });
  return targets;
}

function routeHandlers(): string[] {
  const routes: string[] = [];
  walk(join(SRC, "app", "api"), (path) => {
    if (!path.endsWith(`${sep}route.ts`)) return;
    const dir = relative(join(SRC, "app"), path).replace(`${sep}route.ts`, "");
    routes.push(`/${dir.split(sep).join("/")}`);
  });
  return routes;
}

function covers(route: string, target: string): boolean {
  const routeParts = route.replace(/^\//, "").split("/");
  const targetParts = target.replace(/^\//, "").split("/");
  const last = routeParts[routeParts.length - 1] ?? "";
  // `[...x]` needs at least one segment after the fixed prefix; `[[...x]]` also
  // matches the prefix on its own.
  const isCatchAll = last.startsWith("[...") || last.startsWith("[[...");
  const optionalCatchAll = last.startsWith("[[...");
  const fixed = isCatchAll ? routeParts.slice(0, -1) : routeParts;
  const minimum = optionalCatchAll ? fixed.length : fixed.length + 1;
  if (isCatchAll ? targetParts.length < minimum : routeParts.length !== targetParts.length) {
    return false;
  }
  return fixed.every(
    (part, index) => part.startsWith("[") || part === targetParts[index],
  );
}

describe("BFF route coverage", () => {
  it("resolves helper call sites and locally composed paths", () => {
    expect(sourceTargets('const base = `projects/${id}`; caseLinkRequest(`${base}/missing`); fetch(`/api/${path}`);', "sample.tsx")).toEqual(["/api/projects/:param/missing"]);
  });
  it("enumerates conditional path branches and strips only actual query or fragment suffixes", () => {
    const targets = sourceTargets(`
      const suffix = before ? "?before=" + before : "";
      fetch("/api/projects/" + id + "/items" + suffix);
      fetch(approved ? "/api/approved" : "/api/missing");
      fetch("/api/items#selection");
    `, "sample.tsx");
    expect(targets).toEqual(["/api/projects/:param/items", "/api/approved", "/api/missing", "/api/items"]);
    expect(targets.filter(target => !["/api/projects/[id]/items", "/api/approved", "/api/items"].some(route => covers(route, target)))).toEqual(["/api/missing"]);
  });

  it("follows helper parameters at any position through nested calls and defaults", () => {
    expect(sourceTargets(`
      async function request(project: string, path = "/history") {
        return fetch("/api/projects/" + project + path);
      }
      async function read(path: string) { return request(id, path); }
      read("/missing");
      request(id);
    `, "sample.tsx")).toEqual(["/api/projects/:param/missing", "/api/projects/:param/history"]);
  });

  it("resolves a local component's supplied base and constant object suffixes without mixing scopes", () => {
    expect(sourceTargets(`
      const suffixes = { approved: "/approved", missing: "/missing" } as const;
      function Child({ base, kind }: { base: string; kind: "approved" | "missing" }) {
        return fetch(base + suffixes[kind]);
      }
      function Parent() { const base = "/api/projects/" + id; return <Child base={base} kind="missing" />; }
      function Other() { const base = "/api/unrelated"; return base; }
    `, "sample.tsx")).toEqual(["/api/projects/:param/missing"]);
    expect(sourceTargets(`
      const suffixes = { approved: "/approved", missing: "/missing" };
      fetch("/api" + suffixes[kind]);
    `, "sample.tsx")).toEqual(["/api/approved", "/api/missing"]);
  });

  it("does not let unresolved path pieces match arbitrary static routes", () => {
    const [target] = sourceTargets('fetch("/api/projects/" + id + "/fixed-" + unknown);', "sample.tsx");
    expect(target).toBe("/api/projects/:param/fixed-:param");
    expect(covers("/api/projects/[id]/fixed-known", target)).toBe(false);
    expect(covers("/api/projects/[id]/[...path]", target)).toBe(true);
    expect(covers("/api/projects/[id]/[...path]", "/api/projects/:param")).toBe(false);
    expect(covers("/api/projects/[id]/[[...path]]", "/api/projects/:param")).toBe(true);
  });

  it("has a route handler for every /api path the browser fetches", () => {
    const routes = routeHandlers();
    const uncovered = [...fetchTargets()]
      .filter((target) => !routes.some((route) => covers(route, target)))
      .sort();
    expect(uncovered).toEqual([]);
  });

  it("actually found both sides, so a silent empty scan cannot pass", () => {
    expect(fetchTargets().size).toBeGreaterThan(20);
    expect(routeHandlers().length).toBeGreaterThan(20);
  });
});
