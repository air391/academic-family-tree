"""libSQL/Turso HTTP 客户端 — 仅标准库，任何环境可直接用。

环境变量:
  TURSO_DATABASE_URL  形如 https://xxx.turso.io（libsql:// 开头会自动转 https）
  TURSO_AUTH_TOKEN    数据库级 rw token
"""
import json, os, urllib.request


class TursoClient:
    def __init__(self, url=None, token=None):
        url = url or os.environ["TURSO_DATABASE_URL"]
        if url.startswith("libsql://"):
            url = "https://" + url[len("libsql://"):]
        self.url = url.rstrip("/") + "/v2/pipeline"
        self.token = token or os.environ["TURSO_AUTH_TOKEN"]

    def exec(self, sql_list):
        reqs = [{"type": "execute", "stmt": {"sql": s}} for s in sql_list]
        reqs.append({"type": "close"})
        body = json.dumps({"requests": reqs}).encode()
        req = urllib.request.Request(
            self.url, data=body, method="POST",
            headers={"Authorization": "Bearer " + self.token,
                     "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=180) as resp:
            out = json.loads(resp.read())
        results = []
        for item in out.get("results", []):
            r = item.get("response", item)
            if r.get("type") == "error":
                raise RuntimeError(r["error"])
            results.append(r.get("result", {}))
        return results

    def query(self, sql):
        """单条查询，返回 [[col1, col2...], ...] 的纯值矩阵"""
        res = self.exec([sql])[0]
        rows = []
        for raw in res.get("rows", []):
            rows.append([c.get("value") if isinstance(c, dict) else c for c in raw])
        return rows


def esc(v):
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"


def upsert_persons(client, persons, now):
    """persons: [(id, name, alias, institution_id, title, affiliation, honor, source)] 幂等写入"""
    stmts = []
    for p in persons:
        stmts.append(
            f"""INSERT INTO persons(id,name,alias,institution_id,title,affiliation,honor,source,first_seen_at,last_seen_at)
VALUES ({esc(p[0])},{esc(p[1])},{esc(p[2])},{esc(p[3])},{esc(p[4])},{esc(p[5])},{esc(p[6])},{esc(p[7])},'{now}','{now}')
ON CONFLICT(id) DO UPDATE SET title=excluded.title, affiliation=excluded.affiliation,
honor=excluded.honor, last_seen_at=excluded.last_seen_at""")
    for i in range(0, len(stmts), 100):
        client.exec(stmts[i:i + 100])


def upsert_edges(client, edges, now):
    """edges: [(advisor_id, student_id, rel_type, source)] 幂等写入"""
    stmts = []
    for e in edges:
        stmts.append(
            f"""INSERT INTO mentorship_edges(advisor_id,student_id,rel_type,source,first_seen_at,last_seen_at)
VALUES ({esc(e[0])},{esc(e[1])},{esc(e[2])},{esc(e[3])},'{now}','{now}')
ON CONFLICT(advisor_id,student_id) DO UPDATE SET last_seen_at=excluded.last_seen_at""")
    for i in range(0, len(stmts), 100):
        client.exec(stmts[i:i + 100])
