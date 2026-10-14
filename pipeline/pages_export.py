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


def build_trees(persons, edges):
    """persons: {pid: {...}}, edges: [(advisor, student)] -> 前端所需 tree 列表"""
    adj = collections.defaultdict(list)
    advisors_of = collections.defaultdict(list)
    for a, s in edges:
        adj[a].append(s)
        advisors_of[s].append(a)

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
    for p in persons:
        gen.setdefault(p, 0)

    def disp(pid):
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
        if not roots:
            roots = [min(members)]
        forest = [node(r) for r in roots]
        if len(forest) == 1:
            t = forest[0]
        else:
            t = {"name": f"{len(roots)}位导师",
                 "gen": -1, "virtual": True, "children": forest}
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
    out = template.replace("%DATA%", json.dumps(trees, ensure_ascii=False))
    os.makedirs(os.path.join(here, "..", "docs"), exist_ok=True)
    dest = os.path.normpath(os.path.join(here, "..", "docs", "index.html"))
    open(dest, "w").write(out)
    print(f"docs/index.html 已生成: {len(trees)} 棵树 / {total} 节点 -> {dest}")


if __name__ == "__main__":
    main()
