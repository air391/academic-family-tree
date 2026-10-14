"""从 Turso 云端库重建谱系树，填充 template.html，输出 docs/index.html（GitHub Pages 前端）。

在 GitHub Actions 里手动触发本脚本，即可让 Pages 前端始终与数据库同步。
本地运行同样可行（需要环境变量 TURSO_DATABASE_URL / TURSO_AUTH_TOKEN）。
"""
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from turso_client import TursoClient

GEN_FIELDS = ("title", "affiliation", "honor", "source")


def build_trees(persons, edges):
    """persons: {pid: {...}}, edges: [(advisor, student)] -> 前端所需 tree 列表"""
    adj = collections.defaultdict(list)      # advisor -> students
    advisors_of = collections.defaultdict(list)
    for a, s in edges:
        adj[a].append(s)
        advisors_of[s].append(a)

    # 并查集：连通分量 = 树
    parent = {p: p for p in persons}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, s in edges:
        ra, rs = find(a), find(s)
        if ra != rs:
            parent[ra] = rs

    comps = collections.defaultdict(list)
    for p in persons:
        comps[find(p)].append(p)

    # 代际：从"从未当学生的人"（gen-0 根）BFS
    gen = {}
    dq = collections.deque()
    for p in persons:
        if p not in advisors_of:
            gen[p] = 0
            dq.append(p)
    while dq:
        u = dq.popleft()
        for v in adj.get(u, []):
            if v not in gen:
                gen[v] = gen[u] + 1
                dq.append(v)
    for p in persons:                       # 防御环
        gen.setdefault(p, 0)

    def disp(pid):
        """前端节点名：有同名区分的用 '姓名@导师'（与原始数据格式一致），否则用姓名"""
        p = persons[pid]
        return p["alias"] or p["name"]

    def node(pid):
        p = persons[pid]
        d = {"name": disp(pid), "gen": gen[pid],
             "children": [node(c) for c in adj.get(pid, [])]}
        if p.get("title"):
            d["tag"] = p["title"]
        if p.get("affiliation"):
            d["aff"] = p["affiliation"]
        if p.get("honor"):
            d["honor"] = p["honor"]
        if p.get("source"):
            d["src"] = p["source"]
        return d

    trees = []
    for members in comps.values():
        roots = sorted(p for p in members if gen[p] == 0)
        if not roots:                       # 全是环时兜底
            roots = [min(members)]
        forest = [node(r) for r in roots]
        if len(forest) == 1:
            t = forest[0]
        else:                               # 多根分量包一层虚拟根
            depth = max(gen[p] for p in members)
            t = {"name": roots[0] if len(roots) == 1 else f"{len(roots)}位导师",
                 "gen": -1, "virtual": True,
                 "children": forest}
            for f in forest:
                f["gen"] = 0
        size = len(members)
        depth = max(gen[p] for p in members)
        level2 = sorted({disp(p) for p in members if gen[p] == 1})
        trees.append({
            "id": roots[0], "size": size, "depth": depth + 1,
            "roots": [disp(r) for r in roots],
            "display": "、".join(disp(r) for r in roots),
            "level2": level2,
            "tree": t,
        })
    trees.sort(key=lambda t: -t["size"])
    return trees


def main():
    c = TursoClient()
    prows = c.query("SELECT id,name,alias,title,affiliation,honor,source FROM persons")
    persons = {r[0]: {"name": r[1], "alias": r[2] or "", "title": r[3] or "",
                      "affiliation": r[4] or "", "honor": r[5] or "",
                      "source": r[6] or ""} for r in prows}
    erows = c.query("SELECT advisor_id,student_id FROM mentorship_edges")
    trees = build_trees(persons, [(r[0], r[1]) for r in erows])
    total = sum(t["size"] for t in trees)

    here = os.path.dirname(os.path.abspath(__file__))
    template = open(os.path.join(here, "template.html")).read()
    def dump_node(n):
        kids = n.get("children") or []
        base = json.dumps({k: v for k, v in n.items() if k != "children"},
                          ensure_ascii=False, separators=(",", ":"))
        if not kids:
            return base[:-1] + ',"children":[]}'
        return base[:-1] + ',"children":[\n' + ",\n".join(dump_node(c) for c in kids) + "\n]}"

    def dump_list(key, lst):
        if not lst:
            return f'"{key}":[]'
        return f'"{key}":[\n' + ",\n".join(json.dumps(x, ensure_ascii=False) for x in lst) + "\n]"

    def dump_tree(t):
        meta = {k: v for k, v in t.items() if k not in ("roots", "level2", "tree")}
        base = json.dumps(meta, ensure_ascii=False, separators=(",", ":"))[:-1] + ","
        parts = [base + dump_list("roots", t["roots"]),
                 dump_list("level2", t["level2"]),
                 '"tree":' + dump_node(t["tree"])]
        return ",\n".join(parts) + "}"

    # 每个节点/列表项独占一行：换行只出现在 token 之间（JSON/JS 均合法），避免超长行
    payload = "[\n" + ",\n".join(dump_tree(t) for t in trees) + "\n]"
    out = template.replace("%DATA%", payload)
    os.makedirs(os.path.join(here, "..", "docs"), exist_ok=True)
    dest = os.path.normpath(os.path.join(here, "..", "docs", "index.html"))
    open(dest, "w").write(out)
    print(f"docs/index.html 已生成: {len(trees)} 棵树 / {total} 节点 -> {dest}")


if __name__ == "__main__":
    main()
