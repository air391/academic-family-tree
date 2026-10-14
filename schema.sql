# 师承谱系数据库 schema（SQLite / PostgreSQL 通用，SQLite 单文件即可维护）
-- 核心原则：树不嵌套存储，用"邻接表"（edges 表）存关系，树形由查询时递归生成

CREATE TABLE IF NOT EXISTS institutions (
  id   INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL UNIQUE          -- 学校/院系，如 清华大学工程物理系
);

CREATE TABLE IF NOT EXISTS persons (
  id          TEXT PRIMARY KEY,      -- 如 P00001；跨校唯一
  name        TEXT NOT NULL,
  alias       TEXT DEFAULT '',       -- 同名区分，如 李亮@康克军
  institution_id INTEGER REFERENCES institutions(id),
  title       TEXT DEFAULT '',       -- 职称/身份标签
  affiliation TEXT DEFAULT '',       -- 详细职务
  honor       TEXT DEFAULT '',       -- 院士/将军等
  source      TEXT DEFAULT '',       -- 信息来源
  note        TEXT DEFAULT ''
);

CREATE TABLE IF NOT EXISTS mentorship_edges (
  advisor_id  TEXT NOT NULL REFERENCES persons(id),
  student_id  TEXT NOT NULL REFERENCES persons(id),
  rel_type    TEXT DEFAULT '博士导师',  -- 博士导师/硕士导师/博士后合作导师等
  year        INTEGER,               -- 学生毕业/答辩年份（可选）
  source      TEXT DEFAULT '',
  PRIMARY KEY (advisor_id, student_id)
);
CREATE INDEX IF NOT EXISTS idx_edges_student ON mentorship_edges(student_id);

-- 可选：挂原始论文记录
CREATE TABLE IF NOT EXISTS theses (
  id TEXT PRIMARY KEY,
  author_id TEXT REFERENCES persons(id),
  title TEXT, defense_date TEXT, url TEXT
);

-- 示例：查某人的全部学术后代（SQLite/PostgreSQL 递归CTE，代际即深度）
-- WITH RECURSIVE descendants(pid, generation) AS (
--   SELECT advisor_id, 0 FROM mentorship_edges WHERE advisor_id = 'P00001'
--   UNION ALL
--   SELECT e.student_id, d.generation + 1
--   FROM mentorship_edges e JOIN descendants d ON e.advisor_id = d.pid
-- ) SELECT p.name, d.generation FROM descendants d JOIN persons p ON p.id = d.pid;
