"""从 Turso 云端库导出谱系图（节点+边），填充 template.html，输出 docs/index.html。

图格式天然支持"一子多父"：每个学生节点只出现一次，多个导师各连一条边；
前端按需渲染某个连通分量，不再一次性平铺全部数据。
本地运行需要环境变量 TURSO_DATABASE_URL / TURSO_AUTH_TOKEN。

输出为自解压引导页：完整页面 gzip+base64 内嵌，浏览器端
DecompressionStream 解压后 document.write 渲染。数据量继续增长时
推送/加载都更轻；workflow 重跑会用同格式重新生成。
"""
import base64
import gzip
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from turso_client import TursoClient


def main():
    c = TursoClient()
    prows = c.query(
        "SELECT id, name, alias, title, affiliation, honor, source FROM persons")
    persons = {r[0]: {"name": r[1], "alias": r[2] or "", "title": r[3] or "",
                      "affiliation": r[4] or "", "honor": r[5] or "",
                      "source": r[6] or ""} for r in prows}
    erows = c.query("SELECT advisor_id, student_id FROM mentorship_edges")

    # 稳定排序：按名字，保证导出 diff 最小
    ids = sorted(persons, key=lambda p: (persons[p]["alias"] or persons[p]["name"], p))
    idx = {p: i for i, p in enumerate(ids)}

    nodes = []
    for p in ids:
        d = persons[p]
        disp = d["alias"] or d["name"]
        node = {"id": p, "n": disp}
        if d["title"]:
            node["t"] = d["title"]
        if d["affiliation"]:
            node["af"] = d["affiliation"]
        if d["honor"]:
            node["h"] = d["honor"]
        if d["source"]:
            node["s"] = d["source"]
        nodes.append(node)

    edges = sorted({(idx[a], idx[s]) for a, s in erows})

    def dump_nodes():
        return "[\n" + ",\n".join(
            json.dumps(n, ensure_ascii=False, separators=(",", ":")) for n in nodes) + "\n]"

    def dump_edges():
        return "[\n" + ",\n".join(
            json.dumps(list(e), separators=(",", ":")) for e in edges) + "\n]"

    here = os.path.dirname(os.path.abspath(__file__))
    template = open(os.path.join(here, "template.html")).read()
    out = template.replace("%NODES%", dump_nodes()).replace("%EDGES%", dump_edges())

    # 自解压引导页：gzip + base64（100 字符折行，便于 diff 与推送）
    boot = BOOT_HTML.replace("%B64%", wrap_b64(gzip.compress(out.encode("utf-8"), 9)))
    os.makedirs(os.path.join(here, "..", "docs"), exist_ok=True)
    dest = os.path.normpath(os.path.join(here, "..", "docs", "index.html"))
    open(dest, "w").write(boot)
    print(f"docs/index.html 已生成: {len(nodes)} 节点 / {len(edges)} 边 "
          f"(gzip 引导页 {len(boot)} 字节) -> {dest}")


def wrap_b64(comp: bytes) -> str:
    b64 = base64.b64encode(comp).decode("ascii")
    return "\n".join(b64[i:i + 100] for i in range(0, len(b64), 100))


BOOT_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>中文学术语承谱系 · Chinese Academic Genealogy</title>
</head>
<body>
<div id="boot" style="font-family:sans-serif;color:#888;padding:40px;text-align:center">
谱系数据加载中&hellip;（首次打开约 1 秒）</div>
<script>
const B64 = `%B64%`;
const bin = Uint8Array.from(atob(B64.replace(/\\s+/g, "")), c => c.charCodeAt(0));
new Response(new Blob([bin]).stream().pipeThrough(new DecompressionStream("gzip"))).text()
  .then(html => { document.open(); document.write(html); document.close(); })
  .catch(() => {
    document.getElementById("boot").textContent =
      "数据解压失败：请使用最新版 Chrome / Edge / Firefox / Safari 打开本页。";
  });
</script>
</body>
</html>
"""


if __name__ == "__main__":
    main()
