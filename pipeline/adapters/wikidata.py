"""WikiData 适配器：通过 SPARQL 拉取"在中国高校学习过且有博士导师(P184)"的师承边。

数据协议 CC0，可自由使用。endpoint 默认走 QLever 公共镜像（国内访问
query.wikidata.org 不稳定；QLever 支持完整 SPARQL 1.1，速度快两个量级）。

注意：WikiData 的人用 WD:Qxxxxx 作 id，与中文论文库的人（中文姓名 id）是两套
命名空间，后续在 entity_resolver 里做姓名+单位模糊匹配合并（TODO）。
"""
import time
import urllib.parse
import urllib.request


class WikidataAdapter:
    name = "wikidata"

    SPARQL = """
SELECT DISTINCT ?student ?studentLabel ?advisor ?advisorLabel ?school ?schoolLabel WHERE {{
  VALUES ?school {{ {schools} }}
  ?student wdt:P69 ?school .
  ?student wdt:P184 ?advisor .
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "zh,en". }}
}}
LIMIT {limit} OFFSET {offset}
"""

    def __init__(self, cfg):
        self.cfg = cfg
        self.endpoint = cfg.get("url") or "https://qlever.dev/api/wikidata"
        self.delay = float(cfg.get("rate_limit_s", 0.2))

    def fetch(self, cursor):
        offset = int(cursor or 0)
        page_size = int(self.cfg.get("page_size", 5000))
        schools = " ".join(self.cfg.get("institution_qids", ["wd:Q16955"]))
        while True:
            q = self.SPARQL.format(schools=schools, limit=page_size, offset=offset)
            body = urllib.parse.urlencode({"query": q}).encode()
            req = urllib.request.Request(
                self.endpoint, data=body,
                headers={"Accept": "application/sparql-results+json",
                         "User-Agent": "academic-family-tree-zh/0.1 (research)"})
            with urllib.request.urlopen(req, timeout=300) as resp:
                data = __import__("json").loads(resp.read())
            rows = data.get("results", {}).get("bindings", [])
            if not rows:
                return
            for b in rows:
                yield {
                    "student_qid": b["student"]["value"].rsplit("/", 1)[-1],
                    "student": b["studentLabel"]["value"],
                    "advisor_qid": b["advisor"]["value"].rsplit("/", 1)[-1],
                    "advisor": b["advisorLabel"]["value"],
                    "school_qid": b["school"]["value"].rsplit("/", 1)[-1],
                    "school": b.get("schoolLabel", {}).get("value", ""),
                }
            if len(rows) < page_size:
                return
            offset += page_size
            time.sleep(self.delay)

    def to_persons_edges(self, recs):
        persons, edges = [], []
        seen = set()
        for r in recs:
            for qid, name in ((r["student_qid"], r["student"]),
                              (r["advisor_qid"], r["advisor"])):
                if qid not in seen:
                    seen.add(qid)
                    persons.append((f"WD:{qid}", name, "", None, "", "", "",
                                    "wikidata"))
            edges.append((f"WD:{r['advisor_qid']}", f"WD:{r['student_qid']}",
                          "博士导师", "wikidata"))
        return persons, edges
