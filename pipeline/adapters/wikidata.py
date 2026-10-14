"""WikiData 适配器：通过 SPARQL 拉取"在中国高校学习过且有博士导师(P184)"的师承边。

数据协议 CC0，可自由使用。endpoint 默认走 QLever 公共镜像（国内访问
query.wikidata.org 不稳定）。

QLever 与官方端点的差异（已实测，勿回退）：
- 必须显式 PREFIX 声明（官方端点预注册前缀，QLever 不报 400 以外的错）
- 不支持 SERVICE wikibase:label，标签用 rdfs:label + COALESCE(zh→en) 实现

注意：WikiData 的人用 WD:Qxxxxx 作 id，与中文论文库的人（中文姓名 id）是两套
命名空间，后续在 entity_resolver 里做姓名+单位模糊匹配合并（TODO）。
"""
import json
import time
import urllib.parse
import urllib.request


class WikidataAdapter:
    name = "wikidata"

    SPARQL = """PREFIX wd: <http://www.wikidata.org/entity/>
PREFIX wdt: <http://www.wikidata.org/prop/direct/>
PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
SELECT DISTINCT ?student ?studentName ?advisor ?advisorName WHERE {{
  VALUES ?school {{ {schools} }}
  ?student wdt:P69 ?school .
  ?student wdt:P184 ?advisor .
  OPTIONAL {{ ?student rdfs:label ?sL . FILTER(LANG(?sL)='zh') }}
  OPTIONAL {{ ?student rdfs:label ?sLe . FILTER(LANG(?sLe)='en') }}
  OPTIONAL {{ ?advisor rdfs:label ?aL . FILTER(LANG(?aL)='zh') }}
  OPTIONAL {{ ?advisor rdfs:label ?aLe . FILTER(LANG(?aLe)='en') }}
  BIND(COALESCE(?sL, ?sLe) AS ?studentName)
  BIND(COALESCE(?aL, ?aLe) AS ?advisorName)
}}
LIMIT {limit} OFFSET {offset}
"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.endpoint = cfg.get("url") or "https://qlever.dev/api/wikidata"
        self.delay = float(cfg.get("rate_limit_s", 0.2))

    def _query(self, sparql):
        body = urllib.parse.urlencode({"query": sparql}).encode()
        req = urllib.request.Request(
            self.endpoint, data=body,
            headers={"Accept": "application/sparql-results+json",
                     "User-Agent": "academic-family-tree-zh/0.1 (research)"})
        with urllib.request.urlopen(req, timeout=300) as resp:
            return json.loads(resp.read())

    def fetch(self, cursor):
        """cursor: 数字字符串 = 已入库的 OFFSET，翻页继续拉"""
        offset = int(cursor or 0)
        page_size = int(self.cfg.get("page_size", 5000))
        schools = " ".join(self.cfg.get("institution_qids", ["wd:Q16955"]))
        while True:
            q = self.SPARQL.format(schools=schools, limit=page_size, offset=offset)
            data = self._query(q)
            rows = data.get("results", {}).get("bindings", [])
            if not rows:
                return
            for b in rows:
                yield {
                    "student_qid": b["student"]["value"].rsplit("/", 1)[-1],
                    "student": b.get("studentName", {}).get("value", ""),
                    "advisor_qid": b["advisor"]["value"].rsplit("/", 1)[-1],
                    "advisor": b.get("advisorName", {}).get("value", ""),
                }
            if len(rows) < page_size:
                return
            offset += page_size
            time.sleep(self.delay)

    def next_cursor(self, cursor, recs, now):
        """游标 = 已处理条数；本轮无新增则不推进（断点续跑）"""
        return str((int(cursor or 0)) + len(recs)) if recs else cursor

    def to_persons_edges(self, recs):
        persons, edges = [], []
        seen = set()
        for r in recs:
            for qid, name in ((r["student_qid"], r["student"]),
                              (r["advisor_qid"], r["advisor"])):
                if qid not in seen:
                    seen.add(qid)
                    persons.append((f"WD:{qid}", name or qid, "", None, "", "", "",
                                    "wikidata"))
            edges.append((f"WD:{r['advisor_qid']}", f"WD:{r['student_qid']}",
                          "博士导师", "wikidata"))
        return persons, edges
