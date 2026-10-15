# 台大学位论文系统（TDR）适配器调研笔记

调研日期：2026-10-15。结论：**可用，走 HTML 抓取路线**（OAI-PMH 接口存在但索引为空）。

## 目标站点

- 系统：DSpace 5/6（jspui），台大博硕士论文典藏系统 <https://tdr.lib.ntu.edu.tw/>
- 物理相关收藏集（collection handle → OAI set 映射失败，直接用 handle）：
  - 物理学系：`/handle/123456789/69`（约 1605 篇）
  - 应用物理研究所：`/handle/123456789/65`
  - 天文物理研究所：`/handle/123456789/62`
- 核工程方向：台大无核工系；核工目标可后续评估新竹清大（华艺系统，预计有反爬，未测）。

## 接口探测结果

| 接口 | 结果 |
| --- | --- |
| OAI-PMH Identify | 正常（DSpace 标准端点 /oai/request） |
| OAI-PMH ListSets | 正常列出集合 |
| OAI-PMH ListRecords/GetRecord | **noRecordsMatch / idDoesNotExist，全库 0 条记录，索引失效** |
| 收藏集列表页 /handle/123456789/69 | 正常，每页 20 条 |
| 翻页 /handle/123456789/69?offset=N | 正常（N 步长 20） |
| 元数据页 /handle/123456789/{id}?mode=full | 正常，含完整 DC 元数据表 |
| /browse?type=advisor（按指导教授浏览） | **触发 WAF "Request Rejected"，勿再尝试** |

## 元数据字段（?mode=full 页面解析）

页面为 `DC 欄位 | 值 | 語言` 三列 table，正则按行提取：

| DC 字段 | 用途 |
| --- | --- |
| dc.contributor.advisor | 指导教授（师承边 advisor） |
| dc.contributor.author (zh_TW) | 学生中文名（persons 主名） |
| dc.contributor.author (en) | 英文名（alias） |
| dc.date.issued | 学位年（edges.thesis_year） |
| dc.title | 论文标题（theses 表） |
| dc.description / dc.type | 学位层级（硕士/博士） |

样例记录 123456789/74259：author=邱冠儒 (Kuan-Ru Chiou)，advisor=陳政維(Jeng-Wei Chen)，issued=2019。

## 抓取纪律（项目约束）

- 每次外部请求间隔 ≥ 3 秒；UA 使用 `academic-genealogy-bot/0.1 (research; contact: repo owner)`
- 不绕过 WAF/验证码；被拒即退（HKU Scholars Hub 403、TDR advisor-browse 被拒绝，均已放弃该路径）
- 1605 篇 × (1 列表页/20 条 + 详情页) ≈ 1690 请求 ≈ 85 分钟，适合 GitHub Actions 定时 + checkpoint

## GitHub Actions 工作流设计

1. `schedule: cron` 每日一次；`workflow_dispatch` 手动触发
2. checkpoint：已抓 handle 列表存 repo `data/ntu_tdr_done.json`，断点续抓
3. 新记录解析 → 生成 edges（advisor→student, source='ntu_tdr'）→ 写 Turso（RW token 存 GitHub Secrets）
4. 全量完成后触发 pages_export 重新生成图谱页
5. 失败重试：指数退避；连续 3 次 503/拒绝则 abort 并保留 checkpoint

## 写入映射

- persons: id=中文名；alias=en name；institution=國立臺灣大學物理學系；source='ntu_tdr'
- mentorship_edges: advisor_id=advisor（新人则先建 person，title=''，note='advisor@ntu_physics'），student_id=author，year=dc.date.issued，source='ntu_tdr'
- theses: person=student，title，year，degree（博士/硕士），url=handle 链接
- 与清华 etd 边去重：UNIQUE(advisor,student) 冲突时保留先到的 source，source 追加 ';ntu_tdr'
