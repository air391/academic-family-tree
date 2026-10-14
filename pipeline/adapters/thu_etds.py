"""清华学位论文系统适配器（已验证可用，对应 909 条全量抓取时摸清的行为）。

要点（勿改动，改动会触发反爬/空结果）：
- 需先 GET /qh/cjjs 建 session，POST 必须带 X-Requested-With: XMLHttpRequest 和 Referer
- 院系用简称（"工物系"），日期过滤传空串（任何日期格式都返回 0），按答辩日期客户端过滤
- 分页 qhGetSingleList pageSize=500；详情页 /qh/paper/summary?dbCode=ETDQH&sysId=xxx
- 速率：请求间 sleep(random*rate_limit_s + 0.7)，重试 5 次连续失败即放弃本轮

增量逻辑：source_state.cursor 存日期，本轮只拉答辩日期在 cursor 之后的记录。
"""
import random
import re
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
        self._get(BASE + "/qh/cjjs")
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
            items = re.findall(r'"sysId"\s*:\s*"([^"]+)"', data)
            if not items:
                break
            for sid in items:
                yield from self._detail(sid, cursor)
            if len(items) < 500:
                break
            page += 1

    def _detail(self, sid, cursor):
        try:
            html = self._get(f"{BASE}/qh/paper/summary?dbCode=ETDQH&sysId={sid}")
        except Exception:
            return
        kv = dict(re.findall(
            r'<li[^>]*>\s*<div>\s*([^<]+?)\s*</div>\s*<div[^>]*>\s*(.*?)\s*</div>\s*</li>', html))
        date = kv.get("答辩日期", "")
        if date and cursor and date[:10].replace(".", "-") < cursor:
            return
        yield {"sysid": sid, "author": kv.get("作者", ""), "advisor": kv.get("导师", ""),
               "co_advisor": kv.get("副导师", ""), "date": date,
               "discipline": kv.get("学科名", ""), "title": kv.get("中文题名", ""),
               "unit": kv.get("培养单位", ""),
               "url": f"{BASE}/qh/paper/summary?dbCode=ETDQH&sysId={sid}"}

    def to_persons_edges(self, recs):
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
