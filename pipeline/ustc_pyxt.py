#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中国科学技术大学 学位论文答辩公示 抓取器
数据源: https://pyxt.ustc.edu.cn/?menu=public_replay (静态HTML, 滚动半年窗口)
输出: persons / mentorship_edges / theses / affiliations(院系) 写入 Turso
纪律: 每次运行仅 1 次 GET；幂等(INSERT OR IGNORE + 去重)；不抓历史(页面无归档)
"""
import os, re, sys, time, urllib.request, datetime

URL = 'https://pyxt.ustc.edu.cn/?menu=public_replay'
UA = {'User-Agent': 'academic-genealogy-bot/0.1 (research; contact: repo owner)'}

# 物理/核相关学科过滤（空字符串=全量）
DISCIPLINE_KEYWORDS = ['核', '物理', '等离子', '同步辐射', '量子', '光学', '天文',
                       '粒子', '凝聚态', '原子', '中子', '聚变', '核能', '加速器']
FULL_HARVEST = os.environ.get('USTC_FULL', '') == '1'

def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'ignore')

def parse_rows(html):
    rows = []
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        cells = [re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', c)).strip()
                 for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
        if len(cells) >= 9 and cells[0].isdigit():
            rows.append(dict(no=cells[0], title=cells[1], major=cells[2],
                             student=cells[3], level=cells[4], defense_at=cells[5],
                             place=cells[6], dept=cells[7], advisor=cells[8]))
    return rows

def split_advisors(s):
    parts = re.split(r'[\s、,，;/；]+', s.strip())
    out = []
    for p in parts:
        p = re.sub(r'(教授|研究员|博导|博士)$', '', p).strip()
        if len(p) >= 2 and re.search(r'[一-龥A-Za-z]', p):
            out.append(p)
    return out

def esc(s):
    return "'" + str(s).replace("'", "''") + "'"

class NameSpace:
    """同名消歧：仅当名字已被【其他来源】占用时，ustc 侧才改用 name@ustc，
    避免不同谱系被同名节点错误合并；ustc 自己已占用的名字保持沿用。"""
    def __init__(self, db):
        self.info = {r[0]: r[1] for r in db.query("SELECT id, source FROM persons")}
        self.map = {}
    def pid(self, name):
        if name in self.map:
            return self.map[name]
        if name not in self.info or self.info[name] == 'ustc_pyxt':
            pid = name                      # 新名字 或 ustc 已占用
        else:
            pid = name + '@ustc'            # 被别源占用 → 消歧
            n = 2
            while pid in self.info and self.info.get(pid) != 'ustc_pyxt':
                pid = f'{name}@ustc{n}'; n += 1
        self.map[name] = pid
        return pid

def check_db(db):
    """预检：明确报出 401 的根因，避免裸堆栈"""
    import urllib.error
    try:
        db.query("SELECT 1")
    except urllib.error.HTTPError as e:
        if e.code == 401:
            sys.exit(
                "401 Unauthorized —— 数据库 token 认证失败。\n"
                "排查：仓库 Settings → Secrets and variables → Actions 里应有两个 secret：\n"
                "  TURSO_DATABASE_URL = libsql://academic-family-tree-zhott6oco.aws-ap-northeast-1.turso.io\n"
                "  TURSO_RW_TOKEN     = 数据库 RW token（注意名字必须是 TURSO_RW_TOKEN，且前后不能带空格/引号）")
        raise

def main():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from turso_client import TursoClient
    db = TursoClient()
    check_db(db)
    ns = NameSpace(db)

    html = fetch(URL)
    rows = parse_rows(html)
    print(f'公示窗口共 {len(rows)} 条')

    if not FULL_HARVEST:
        rows = [r for r in rows if any(k in r['major'] or k in r['dept'] for k in DISCIPLINE_KEYWORDS)]
        print(f'物理/核相关 {len(rows)} 条')

    # 机构/来源登记
    now = datetime.datetime.now().isoformat(timespec='seconds')
    sqls = []
    depts = sorted({r['dept'] for r in rows if r['dept']})
    for d in depts:
        sqls.append(f"INSERT OR IGNORE INTO institutions (name) VALUES ({esc('中国科学技术大学'+d)})")
    sqls.append("INSERT OR IGNORE INTO sources (id, name, adapter, url, schedule) VALUES (3, 'ustc_pyxt', 'ustc_pyxt', "
                + esc(URL) + ", 'weekly')")
    db.exec(sqls)

    inst_id = {r[1]: r[0] for r in db.query("SELECT id, name FROM institutions")}
    src_id = 3

    n_p = n_e = n_t = n_a = 0
    BATCH = 400
    buf = []
    for r in rows:
        st = r['student']
        if not st:
            continue
        level = '博士' if '博士' in r['level'] else ('硕士' if '硕士' in r['level'] else r['level'])
        rel = ('博士' in level) and '博士导师' or '硕士导师'
        year = r['defense_at'][:4] if len(r['defense_at']) >= 4 else None
        # person（幂等 + 同名消歧）
        st_pid = ns.pid(st)
        buf.append("INSERT OR IGNORE INTO persons (id, name, title, source) "
                   f"VALUES ({esc(st_pid)}, {esc(st)}, '', 'ustc_pyxt')")
        n_p += 1
        # 院系 affiliation
        dname = '中国科学技术大学' + r['dept']
        if dname in inst_id:
            buf.append("INSERT OR IGNORE INTO affiliations (person_id, institution_id, role, detail, start_year, end_year, source) "
                       f"VALUES ({esc(st_pid)}, {inst_id[dname]}, '学习', {esc(r['major'])}, {year or 'NULL'}, NULL, 'ustc_pyxt')")
            n_a += 1
        # thesis
        tid = f"ustc_pyxt:{r['no']}:{r['defense_at'][:10]}"
        buf.append("INSERT OR IGNORE INTO theses (id, author_id, title, defense_date, source_id) VALUES "
                   f"({esc(tid)}, {esc(st_pid)}, {esc(r['title'])}, {esc(r['defense_at'])}, {src_id})")
        n_t += 1
        # edges（双导师拆分）
        for adv in split_advisors(r['advisor']):
            adv_pid = ns.pid(adv)
            buf.append("INSERT OR IGNORE INTO persons (id, name, title, source) "
                       f"VALUES ({esc(adv_pid)}, {esc(adv)}, '', 'ustc_pyxt')")
            buf.append(f"INSERT OR IGNORE INTO mentorship_edges (advisor_id, student_id, rel_type, year, source) "
                       f"VALUES ({esc(adv_pid)}, {esc(st_pid)}, {esc(rel)}, {year or 'NULL'}, 'ustc_pyxt')")
            n_e += 1
        if len(buf) >= BATCH:
            db.exec(buf); buf = []
    if buf:
        db.exec(buf)

    print(f'persons+{n_p} 候选, edges+{n_e} 候选, theses+{n_t} 候选, affiliations+{n_a} 候选')
    print('persons 总数:', db.query("SELECT COUNT(*) FROM persons")[0][0])
    print('ustc 边数:', db.query("SELECT COUNT(*) FROM mentorship_edges WHERE source='ustc_pyxt'")[0][0])

if __name__ == '__main__':
    main()
