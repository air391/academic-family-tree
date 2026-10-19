#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""高校教师主页抓取器（中科大 / 复旦 物理·核相关院系）

数据源（均为公开教师主页/导师名录）：
  USTC:  https://dslx.ustc.edu.cn/?menu=expertlist&year=2025 （招生导师一览，单页）
         → 教师主页解析（faculty.ustc.edu.cn 模板：.edu 块）
  Fudan: https://faculty.fudan.edu.cn units_teacher.jsp?...id=2662|2870 （教师个人主页系统）
         → 教师主页解析（dt.kaishi/jieshu/shijian 模板）

用法：
  python3 faculty_portal.py crawl           # 只抓取，缓存到 data/faculty_*.json
  python3 faculty_portal.py import          # 只把缓存导入 Turso（需 TURSO_* 环境变量）
  python3 faculty_portal.py all             # 抓取 + 导入（默认）

纪律：请求间隔 >=3.2s；增量缓存（data/faculty_cache.json 记录已抓 expertid/slug）；
幂等导入（INSERT OR IGNORE + 同名消歧）。
"""
import json
import os
import re
import sys
import time
import datetime
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(os.path.dirname(BASE), 'data')
UA = {'User-Agent': 'academic-genealogy-bot/0.2 (research; contact: repo owner)'}
POLITE = 3.2

USTC_COLLEGES = ['物理学院', '核科学技术学院']
FUDAN_UNITS = [(2662, '物理学系'), (2870, '现代物理研究所/核科学与技术系')]
FUDAN_COLLEGE_NAME = {2662: '物理学系', 2870: '核科学与技术系'}


def fetch(url):
    time.sleep(POLITE)
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=60).read().decode('utf-8', 'ignore')


def esc(s):
    return "'" + str(s).replace("'", "''") + "'"


# ---------------- USTC ----------------

def ustc_roster(html):
    """dslx 导师一览 → {college: [(specialty, name, expertid)]}"""
    out = {}
    college = None
    for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
        m = re.search(r'bgcolor="#6699CC"[^>]*>([^<]+)</td>', tr)
        if m:
            college = m.group(1).strip()
            continue
        if college not in USTC_COLLEGES:
            continue
        tds = re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)
        if len(tds) < 4:
            continue
        specialty = re.sub(r'<[^>]+>', '', tds[2])
        specialty = re.sub(r'\s+', '', specialty)
        for href, name in re.findall(r'<a href="[^"]*expertid=(\d+)[^"]*"[^>]*>([^<]+)</a>', tr):
            name = name.replace('&nbsp;', '').strip()
            if len(name) >= 2:
                out.setdefault(college, []).append((specialty, name, href))
    return out


def ustc_homepage(expertid):
    """expert_paper 页是 JS 跳转 location.href='...'"""
    html = fetch(f'https://dslx.ustc.edu.cn/?menu=expert_paper&expertid={expertid}')
    m = re.search(r"location\.href='([^']+)'", html)
    if m:
        return m.group(1).strip()
    m = re.search(r'window\.location\s*=\s*"([^"]+)"', html)
    return m.group(1).strip() if m else ''


def follow_js(url, max_hops=3):
    """follow JS 跳转链（MyHomePage.jsp → /~xxx/zh_CN/index.htm），规范化 %7E→~、升级 https"""
    seen = set()
    for _ in range(max_hops):
        if url in seen:
            break
        seen.add(url)
        html = fetch(url)
        m = re.search(r'(?:location\.href|document\.location)\s*=\s*["\']([^"\']+)', html)
        if not m:
            return html, url
        nxt = m.group(1).replace('%7E', '~').replace('%7e', '~')
        if nxt.startswith('http://faculty.ustc.edu.cn'):
            nxt = 'https://faculty.ustc.edu.cn' + nxt[len('http://faculty.ustc.edu.cn'):]
        if nxt == url:
            return html, url
        url = nxt
    return html, url


def _clean(s):
    return re.sub(r'\s+', ' ', s.replace('&nbsp;', ' ')).strip()


def parse_ustc_page(html):
    """faculty.ustc.edu.cn 模板A：div.edu > div.tit_in(节名) + p[条目]；
    模板B（默认主题）：div.index-title(节名) + div.text > p[条目]"""
    name = ''
    m = re.search(r'<title>([^<(—-]+)', html)
    if m:
        name = m.group(1).strip()
    sections = _parse_ustc_a(html) or _parse_ustc_b(html)
    return name, sections


def _parse_ustc_a(html):
    sections = {}
    for block in re.findall(r'<div class="edu">(.*?)</div>\s*(?=<div class="edu">|</div>\s*</div>|$)', html, re.S):
        t = re.search(r'<div class="tit_in">([^<]+)</div>', block)
        if not t:
            continue
        sec = t.group(1).strip()
        items = []
        for p in re.findall(r'<p[^>]*>(.*?)</p>', block, re.S):
            txt = _clean(re.sub(r'<[^>]+>', '', p))
            txt = re.sub(r'^\[\d+\]\s*', '', txt)
            if txt:
                items.append(txt)
        if items:
            sections.setdefault(sec, []).extend(items)
    return sections


def _parse_ustc_b(html):
    sections = {}
    for sec, body in re.findall(
            r'<div class="index-title">\s*(教育经历|工作经历|社会兼职|研究方向)\s*</div>\s*<div class="text">(.*?)</div>',
            html, re.S):
        items = []
        for p in re.findall(r'<p[^>]*>(.*?)</p>', body, re.S):
            txt = _clean(re.sub(r'<[^>]+>', '', p))
            txt = re.sub(r'^\[\d+\]\s*[.、]?\s*', '', txt)
            if txt and txt != '暂无内容':
                items.append(txt)
        if items:
            sections.setdefault(sec, []).extend(items)
    return sections
def parse_fudan_page(html):
    """faculty.fudan.edu.cn 模板：dt.kaishi/dt.jieshu/dt.shijian（inst → major → degree → status）"""
    name = ''
    m = re.search(r'<title>([^<(]+)', html)
    if m:
        name = m.group(1).strip()
    sections = {}
    # slideTxtBox 结构：hd 里是全部选项卡标题，bd 里按相同顺序排列 <ul>
    i = html.find('slideTxtBox')
    if i < 0:
        return name, sections
    box = html[i:]
    j = box.find('<div class="bd"')
    tabs = re.findall(r'<li>([^<]{2,6})</li>', box[:j])
    uls = re.findall(r'<ul[^>]*>(.*?)</ul>', box[j:], re.S)
    for sec, body in zip(tabs, uls):
        if sec not in ('教育经历', '工作经历'):
            continue
        items = []
        for dl in re.findall(r'<dl[^>]*>(.*?)</dl>', body, re.S):
            s = re.search(r'class="kaishi"[^>]*>([^<]*)</dt>', dl)
            e = re.search(r'class="jieshu"[^>]*>([^<]*)</dt>', dl)
            t = re.search(r'class="shijian"[^>]*>(.*?)</dt>', dl, re.S)
            line = _clean(re.sub(r'<[^>]+>', '', t.group(1) if t else ''))
            line = re.sub(r'\s*→\s*', '，', line)
            items.append(f"{_clean(s.group(1) if s else '')}~{_clean(e.group(1) if e else '')}，{line}")
        if items:
            sections.setdefault(sec, []).extend(items)
    return name, sections


# ---------------- 抓取 ----------------

def load_cache():
    p = os.path.join(DATA_DIR, 'faculty_cache.json')
    if os.path.exists(p):
        return json.load(open(p, encoding='utf-8'))
    return {'ustc': {}, 'fudan': {}}


def save_cache(c):
    os.makedirs(DATA_DIR, exist_ok=True)
    json.dump(c, open(os.path.join(DATA_DIR, 'faculty_cache.json'), 'w', encoding='utf-8'),
              ensure_ascii=False, indent=1)


def crawl_ustc(cache):
    print('[USTC] 抓取导师一览 …')
    html = fetch('https://dslx.ustc.edu.cn/?menu=expertlist&year=2025')
    roster = ustc_roster(html)
    total = sum(len(v) for v in roster.values())
    print('[USTC] 目标学院导师:', {k: len(v) for k, v in roster.items()})
    teachers = {}
    for college, items in roster.items():
        for specialty, name, expertid in items:
            key = f'{expertid}:{name}'
            if key in cache['ustc']:
                teachers[key] = cache['ustc'][key]
                continue
            rec = {'name': name, 'college': college, 'specialty': specialty, 'homepage': ''}
            try:
                hp = ustc_homepage(expertid)
                rec['homepage'] = hp
                if 'faculty.ustc.edu.cn' in hp:
                    html, final_url = follow_js(hp)
                    rec['final_url'] = final_url
                    nm, sections = parse_ustc_page(html)
                    rec['page_name'] = nm
                    rec['sections'] = sections
            except Exception as ex:
                rec['error'] = f'{type(ex).__name__}: {ex}'
            teachers[key] = rec
            cache['ustc'][key] = rec
            done = len(cache['ustc'])
            if done % 25 == 0:
                save_cache(cache)
                print(f'  …{done}/{total}')
    save_cache(cache)
    ok = sum(1 for r in teachers.values() if r.get('sections'))
    print(f'[USTC] 完成 {len(teachers)} 人，其中主页解析成功 {ok} 人')
    return teachers


def crawl_fudan(cache):
    teachers = {}
    for uid, cname in FUDAN_UNITS:
        page = 1
        while True:
            url = (f'https://faculty.fudan.edu.cn/units_teacher.jsp?urltype=tsites.CollegeTeacherList'
                   f'&wbtreeid=1002&st=0&id={uid}&lang=zh_CN')
            if page > 1:
                url += f'&totalpage=9&PAGENUM={page}'
            html = fetch(url)
            entries = re.findall(r'addimg\("[^"]*","([^"]+)","([^"]+)"', html)
            print(f'[Fudan] 单元{uid} 第{page}页 {len(entries)} 人')
            if not entries:
                break
            for path, name in entries:
                name = name.strip()
                if not name:
                    continue
                slug = path.split('/')[1] if '/' in path else path
                key = f'{slug}:{name}'
                if key in cache['fudan']:
                    teachers[key] = cache['fudan'][key]
                    continue
                rec = {'name': name, 'college': cname, 'homepage': f'https://faculty.fudan.edu.cn{path}'}
                try:
                    nm, sections = parse_fudan_page(fetch(rec['homepage']))
                    rec['page_name'] = nm
                    rec['sections'] = sections
                except Exception as ex:
                    rec['error'] = f'{type(ex).__name__}: {ex}'
                teachers[key] = rec
                cache['fudan'][key] = rec
            tp = re.search(r'totalpage=(\d+)', html)
            if not tp or page >= int(tp.group(1)):
                break
            page += 1
    save_cache(cache)
    ok = sum(1 for r in teachers.values() if r.get('sections'))
    print(f'[Fudan] 完成 {len(teachers)} 人，其中主页解析成功 {ok} 人')
    return teachers


# ---------------- 导入 ----------------

class NameSpace:
    def __init__(self, db, own_sources, suffix):
        self.info = {r[0]: r[1] for r in db.query("SELECT id, source FROM persons")}
        self.map = {}
        self.own = own_sources
        self.suffix = suffix

    def pid(self, name):
        if name in self.map:
            return self.map[name]
        if name not in self.info or self.info[name] in self.own:
            pid = name
        else:
            pid = f'{name}@{self.suffix}'
            n = 2
            while pid in self.info and self.info.get(pid) not in self.own:
                pid = f'{name}@{self.suffix}{n}'; n += 1
        self.map[name] = pid
        return pid


# 机构名清洗：常见别名合并到规范名，去除空白/学位词前缀
INST_ALIAS = {
    '中科大': '中国科学技术大学', '中国科技大学': '中国科学技术大学', '科大': '中国科学技术大学',
    'USTC': '中国科学技术大学', '清华大学': '清华大学', '清华': '清华大学',
    '北京大学': '北京大学', '北大': '北京大学', '复旦': '复旦大学',
    '上交大': '上海交通大学', '西安交大': '西安交通大学',
}


def clean_inst(raw):
    s = re.sub(r'\s+', '', str(raw))
    s = re.sub(r'^(学士|硕士|博士)研究生[，,]?', '', s)
    s = re.sub(r'^\d[\d\s.\-/年月日]*', '', s)   # 残留日期前缀
    return INST_ALIAS.get(s, s)


def clean_fields(fields):
    out = []
    for f in fields:
        if re.search(r'[A-Za-z]', f):
            f = re.sub(r'\s+', ' ', f).strip()   # 含英文：保留单词间隔
        else:
            f = re.sub(r'\s+', '', f)
        f = re.sub(r'^(本科|研究生)\(([^)]+)\)毕业$', r'\2', f)
        if f:
            out.append(f)
    return out


def split_item(txt):
    """'1998年9月~2002年6月，中科大，物理学，本科(学士)，学士学位' → (start,end,[fields])"""
    parts = [p.strip() for p in txt.split('，') if p.strip()]
    if not parts:
        return None
    m = re.match(r'(.+?)\s*[~～—-]\s*(.+)', parts[0])
    if m:
        start, end = m.group(1).strip(), m.group(2).strip()
        fields = parts[1:]
    else:
        start, end = parts[0], ''
        fields = parts[1:]
    fields = clean_fields(fields)
    if fields:
        fields = [clean_inst(fields[0])] + fields[1:]
    return start, end, fields


def norm_year(s):
    m = re.search(r'(19|20)\d{2}', s or '')
    return int(m.group(0)) if m else None


def import_teachers(db, teachers, source_id, source_name, school, own_sources, suffix, stats_college=None):
    ns = NameSpace(db, own_sources, suffix)
    now = datetime.datetime.now().isoformat(timespec='seconds')
    sqls = [f"INSERT OR IGNORE INTO sources (id, name, adapter, url, schedule) VALUES "
            f"({source_id}, {esc(source_name)}, 'faculty_portal', 'https://faculty.ustc.edu.cn / faculty.fudan.edu.cn / dslx.ustc.edu.cn', 'monthly')"]
    inst_names = set()
    for r in teachers.values():
        for sec in ('教育经历', '工作经历'):
            for it in r.get('sections', {}).get(sec, []):
                p = split_item(it)
                if p and p[2]:
                    inst_names.add(p[2][0])
    for nm in sorted(inst_names):
        sqls.append(f"INSERT OR IGNORE INTO institutions (name) VALUES ({esc(nm)})")
    sqls.append(f"INSERT OR IGNORE INTO institutions (name) VALUES ({esc(school)})")
    db.exec(sqls)
    inst_id = {r[1]: r[0] for r in db.query("SELECT id, name FROM institutions")}

    buf = []
    n_p = n_a = 0
    for r in teachers.values():
        name = r['name']
        pid = ns.pid(name)
        college = r.get('college', '')
        title = ''
        works = r.get('sections', {}).get('工作经历', [])
        if works:
            p = split_item(works[0])
            if p and len(p[2]) >= 2:
                title = p[2][-1]
        note = r.get('homepage', '')
        buf.append("INSERT OR IGNORE INTO persons (id, name, title, affiliation, source, note) "
                   f"VALUES ({esc(pid)}, {esc(name)}, {esc(title)}, {esc(college)}, {esc(source_name)}, {esc(note)})")
        n_p += 1
        # 本校院系 affiliation
        if college:
            buf.append("INSERT OR IGNORE INTO affiliations (person_id, institution_id, role, detail, start_year, end_year, source) "
                       f"VALUES ({esc(pid)}, {inst_id[school]}, '任教', {esc(college)}, NULL, NULL, {esc(source_name)})")
        # 教育/工作经历 → affiliations
        for sec, role in (('教育经历', '学习'), ('工作经历', '任教')):
            for it in r.get('sections', {}).get(sec, []):
                p = split_item(it)
                if not p or not p[2]:
                    continue
                inst = p[2][0]
                if inst not in inst_id:
                    continue
                detail = '，'.join(p[2][1:]) or ''
                y0, y1 = norm_year(p[0]), norm_year(p[1])
                buf.append("INSERT OR IGNORE INTO affiliations (person_id, institution_id, role, detail, start_year, end_year, source) "
                           f"VALUES ({esc(pid)}, {inst_id[inst]}, {esc(role)}, {esc(detail)}, "
                           f"{y0 or 'NULL'}, {y1 or 'NULL'}, {esc(source_name)})")
                n_a += 1
        if len(buf) >= 400:
            db.exec(buf); buf = []
    if buf:
        db.exec(buf)
    print(f'[{source_name}] persons+{n_p} 候选, affiliations+{n_a} 候选')


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'all'
    cache = load_cache()
    ustc = fudan = None
    if mode in ('crawl', 'all'):
        ustc = crawl_ustc(cache)
        fudan = crawl_fudan(cache)
    if mode in ('import', 'all'):
        from turso_client import TursoClient
        db = TursoClient()
        if ustc is None:
            ustc = cache.get('ustc', {})
        if fudan is None:
            fudan = cache.get('fudan', {})
        import_teachers(db, ustc, 4, 'ustc_faculty', '中国科学技术大学',
                        {'ustc_pyxt', 'ustc_faculty'}, 'ustc')
        import_teachers(db, fudan, 5, 'fudan_faculty', '复旦大学', {'fudan_faculty'}, 'fudan')
        print('persons 总数:', db.query("SELECT COUNT(*) FROM persons")[0][0])

if __name__ == '__main__':
    main()
