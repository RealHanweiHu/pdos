import json, sys, glob, copy
from replay import call

def inline(node, defs):
    if isinstance(node, dict):
        if "$ref" in node:
            return inline(copy.deepcopy(defs[node["$ref"].split("/")[-1]]), defs)
        return {k: inline(v, defs) for k, v in node.items() if k != "$defs"}
    if isinstance(node, list):
        return [inline(v, defs) for v in node]
    return node

def variant(body, name):
    body = copy.deepcopy(body)
    tool = [t for t in body["tools"] if t["function"]["name"] == "pdos_agent_output"][0]["function"]
    p = tool["parameters"]
    if name == "inline":
        tool["parameters"] = inline(p, p["$defs"])
    elif name == "strings":
        p["$defs"]["WireQuestion"]["properties"]["options"] = {
            "items": {"type": "string"}, "title": "Options", "type": "array",
            "description": "Short answer choices as plain strings; [] when the question is open."}
        p["$defs"].pop("ClarifyOption")
    elif name == "options_json":
        q = p["$defs"]["WireQuestion"]
        q["properties"].pop("options"); q["required"].remove("options")
        q["properties"]["options_json"] = {"title": "Options Json", "type": "string",
            "description": "JSON array of {\"value\",\"label\"} answer choices, as a string; \"[]\" when open."}
        q["required"].insert(3, "options_json")
        p["$defs"].pop("ClarifyOption")
    return body

if __name__ == "__main__":
    files = sorted(glob.glob(sys.argv[1]))[: int(sys.argv[4]) if len(sys.argv) > 4 else None]
    for name in sys.argv[2].split(","):
        for f in files:
            body = variant(json.load(open(f))["request"], name)
            for i in range(int(sys.argv[3])):
                try:
                    print(name, f.split("/")[-1][8:13], json.dumps(call(body, False), ensure_ascii=False)[:330], flush=True)
                except Exception as e:
                    print(name, "transport error", type(e).__name__, flush=True)
