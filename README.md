# Academic Family Tree · 中文学术语师承谱系

目标：以公开数据构建中文学者师承谱系库，对标 [Mathematics Genealogy Project](https://genealogy.math.ndsu.nodak.edu) 与 [Academic Family Tree](https://academictree.org)。

**线上前端**：GitHub Pages（`docs/` 目录）
**云端数据库**：Turso（libSQL/SQLite），schema 见 `schema.sql`
**当前数据**：1477 人 / 1250 边（清华大学工程物理系 2011 年后公开博士论文 + WikiData 师承链；233 棵谱系树，含院士/将军/教授身份富化；affiliations 表已按现有边回填清华部分）

## 仓库结构

```
├── docs/                     # GitHub Pages 前端（workflow 自动生成，勿手改）
├── pipeline/
│   ├── runner.py             # 调度器（读 sources.yaml，幂等 upsert 到 Turso）
│   ├── turso_client.py       # libSQL HTTP 客户端（纯标准库）
│   ├── pages_export.py       # 从 Turso 重建谱系树 → 生成 docs/index.html
│   ├── template.html         # 前端模板（%DATA% 占位）
│   ├── sources.yaml          # 数据源注册表（加源 = 加适配器 + 加配置）
│   └── adapters/             # thu_etds（已验证）/ wikidata（CC0）
└── schema.sql                # 建表语句（Turso/本地 SQLite 通用）
```

## 首次启用（全部手动触发，无任何定时任务）

1. **配 Secrets**：Settings → Secrets and variables → Actions → New repository secret，添加 `TURSO_DATABASE_URL` 与 `TURSO_AUTH_TOKEN`（Turso 面板获取）
2. **建工作流**：Actions → New workflow → 选 **set up a workflow yourself** → 把部署包里的 `genealogy-manual-run.yml` 全文粘贴进去 → Commit changes
3. **首次采集**：Actions → `genealogy-manual-run` → **Run workflow**——增量采集、重建谱系树、生成 `docs/index.html` 并提交回本仓库
4. **开 Pages**：Settings → Pages → Source 选 **Deploy from a branch** → `main` / `/docs` → Save。几分钟后 https://air391.github.io/academic-family-tree/ 上线

之后每次点 Run workflow：数据库增量更新 + 前端自动刷新。

## 新增数据源

1. `pipeline/adapters/` 新增适配器（实现 `fetch(cursor)` 与 `to_persons_edges(recs)`）
2. `pipeline/sources.yaml` 注册（access_type 标 `public`/`campus`/`subscription`）
3. 手动触发一次 workflow 验证

维护纪律：限速只调高不调低；每条边必须带来源；同名用 `姓名@导师` 规则区分。

## 路线图

- [ ] entity_resolver：WikiData `WD:Qxx` 与中文论文库人名合并（两树连成一片的关键）
- [x] affiliations 多值经历表（学习/任教/博士后/工作，已建表并按现有边回填清华部分）
- [ ] 教师名录适配器：先抓清华工物系教师名录，按学术简历清洗后写入 affiliations（任教+detail 职称/院系）
- [ ] 高校核工程/物理系论文系统适配器（第二个中文学位论文源，走 workflow 抓取）
- [ ] edges.year / theses 回填：重跑 thu_etds 时记录答辩年份与论文条目，affiliations.end_year 自动可填
- [ ] Wikidata 节点院校补全：从 employer / educated-at 属性批量写入 affiliations
- [ ] oai_pmh 通用适配器（覆盖 DSpace/CALIS 成员馆）
- [ ] csv_importer（CNKI/万方手工导出导入）
- [ ] 校园网采集节点（解决 IP 白名单源）

## 数据说明与免责

数据来自公开学位论文与公开网页，仅供参考；同名消歧存在不确定性（页面内已标注）；涉密论文不在公开库中，数据为实际规模的下界。
