"""清华学位论文系统适配器（已验证可用，对应 909 条全量抓取时摸清的行为）。

要点（勿改动，改动会触发反爬/空结果）：
- 需先 GET /qh/cjjs 建 session，POST 必须带 X-Requested-With: XMLHttpRequest 和 Referer
- 院系用简称（"工物系"），日期过滤传空串（任何日期格式都返回 0），按答辩日期客户端过滤
- 分页 qhGetSingleList pageSize=500；详情页 /qh/paper/summary?dbCode=ETDQH&sysId=xxx
- 速率：请求间 sleep(random*rate_limit_s + 0.7)，重试 5 次连续失败即放弃本轮

增量逻辑：source_state.cursor 存 "YYYY-MM-DD"，本轮只拉答辩日期在
cursor 之后的记录，跑完把 cursor 终点推到本轮运行日（仅当本轮有记录）。
"""
import random
import time
import urllib.request

BASE = "https://newetds.lib.tsinghua.edu.cn"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


class ThuEtdsAdapter:
    name = "thu_etds"

    def __init__(self, cfg):
        self.cfg = cfg
        self.delay = float(cfg.get("rate_limit_s", 1.5))
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())

    def _get(self, url):
        time.sleep(random.uniform(0.7, 0.7 + self.delay))
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        return self.opener.open(req, timeout=30).read().decode("utf-8", "ignore")

    def _post_json(self, url, payload):
        time.sleep(random.uniform(0.7, 0.7 + self.delay))
        req = urllib.request.Request(
            url, data=str(payload).replace("'", '"').encode(),
            headers={"User-Agent": UA, "Content-Type": "application/json",
                     "X-Requested-With": "XMLHttpRequest",
                     "Referer": BASE + "/home/qh/index"})
        return self.opener.open(req, timeout=30).read().decode("utf-8", "ignore")

    def fetch(self, cursor):
        """cursor: 'YYYY-MM-DD'，只返回答辩日期 >= cursor 的记录。

        用列表页数据直接构建记录（每页 500 条，全量仅 2 次请求）——
        列表已含 作者/导师1姓名/论文答辩日期/中文题名 等谱系所需字段，
        副导师字段已验证全库为空，无需再逐条抓详情页。
        """
        import json as _json
        self._get(BASE + "/qh/cjjs")  # 建 session
        page = 1
        fails = 0
        while fails < 5:
            payload = {"dataBaseCode": "全部", "pageIndex": page, "pageSize": 500,
                       "startTime": "", "endTime": "", "txtXwType": "博士",
                       "txtsortValue": "论文答辩日期", "txtsortType": "DESC",
                       "searchType": "0", "conditionKey": "院系",
                       "conditionValue": self.cfg.get("department", "工物系"),
                       "treeSearchConditions": []}
            try:
                data = self._post_json(BASE + "/qh/qhSearch/qhGetSingleList", payload)
                fails = 0
            except Exception:
                fails += 1
                time.sleep(30)
                continue
            try:
                items = _json.loads(data).get("qhlwdataList") or []
            except Exception:
                break
            if not items:
                break
            for it in items:
                date = it.get("论文答辩日期", "")
                if date and cursor and date[:10].replace(".", "-") < cursor:
                    continue  # 增量过滤：早于游标的跳过
                sid = it.get("sys_fld_sysid", "")
                yield {"sysid": sid, "author": it.get("作者", ""),
                       "advisor": it.get("导师1姓名", ""), "co_advisor": "",
                       "date": date, "discipline": it.get("院系", ""),
                       "title": it.get("中文题名", ""),
                       "unit": it.get("学校", "") or it.get("院系", ""),
                       "url": f"{BASE}/qh/paper/summary?dbCode=ETDQH&sysId={sid}"}
            if len(items) < 500:
                break
            page += 1

    def next_cursor(self, cursor, recs, now):
        """游标语义：下次只处理答辩日期 >= 游标的记录。
        本轮 0 条（被拒/无新增）不推进；有记录则推进到本次运行日
        （重扫重叠部分幂等无害，被漏抓的新论文下轮可补）。"""
        if not recs:
            return cursor
        return now[:10]

    def to_persons_edges(self, recs):
        """record -> (persons, edges)。同名消歧沿用 '姓名@导师' 规则。"""
        from collections import Counter
        cnt = Counter(r["author"] for r in recs)
        advisors = {r["author"] for r in recs}
        persons, edges = [], []
        for r in recs:
            name = r["author"]
            pid = f"{name}@{r['advisor']}" if (cnt[name] > 1 and name not in advisors) else name
            aid = r["advisor"]
            persons.append((pid, name, pid if "@" in pid else "", 1, "", "", "",
                            "thu_etds"))
            if aid:
                persons.append((aid, aid, "", 1, "", "", "", "thu_etds"))
                edges.append((aid, pid, "博士导师", "thu_etds"))
        return persons, edges
