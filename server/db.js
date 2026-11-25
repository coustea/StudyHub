const Database = require('better-sqlite3')
const fs = require('fs')
const path = require('path')

const DATA_DIR = process.env.DATA_DIR || path.join(__dirname, '..', 'data')
fs.mkdirSync(DATA_DIR, { recursive: true })

const db = new Database(path.join(DATA_DIR, 'notes.db'))
db.pragma('journal_mode = WAL')
db.pragma('foreign_keys = ON')
// 等待写锁而不是立刻抛 SQLITE_BUSY，备份脚本与写入并发时更稳
db.pragma('busy_timeout = 5000')
db.pragma('synchronous = NORMAL')

db.exec(`
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  username      TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name  TEXT NOT NULL DEFAULT '',
  created_at    TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS projects (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name        TEXT NOT NULL,
  slug        TEXT NOT NULL,
  description TEXT NOT NULL DEFAULT '',
  status      TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
  sort_order  INTEGER NOT NULL DEFAULT 0,
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (owner_id, slug)
);

CREATE TABLE IF NOT EXISTS nodes (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id   INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  parent_id  INTEGER NOT NULL DEFAULT 0,
  kind       TEXT NOT NULL CHECK (kind IN ('folder', 'doc')),
  title      TEXT NOT NULL,
  slug       TEXT NOT NULL DEFAULT '',
  content    TEXT NOT NULL DEFAULT '',
  tags       TEXT NOT NULL DEFAULT '',
  sort_order INTEGER NOT NULL DEFAULT 0,
  status     TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes (project_id, parent_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_nodes_updated ON nodes (kind, status, updated_at DESC);
`)

// 轻量迁移：老库补列，新库直接跳过。SQLite 的 ADD COLUMN 幂等性靠列名检查保证。
function ensureColumn(table, column, definition) {
  const columns = db.prepare(`PRAGMA table_info(${table})`).all()
  if (columns.some((item) => item.name === column)) return
  db.exec(`ALTER TABLE ${table} ADD COLUMN ${column} ${definition}`)
}

// deleted_at：软删除时间戳，NULL 表示未删除。回收站与误删恢复都靠它。
ensureColumn('nodes', 'deleted_at', 'TEXT')
// daily_date：笔记归属的学习日（YYYY-MM-DD），用于「今日/打卡」统计；老笔记按创建日回填。
ensureColumn('nodes', 'daily_date', "TEXT NOT NULL DEFAULT ''")

db.exec(`
CREATE INDEX IF NOT EXISTS idx_nodes_deleted ON nodes (deleted_at);
CREATE INDEX IF NOT EXISTS idx_nodes_daily ON nodes (owner_id, daily_date);
`)

db.prepare(`
  UPDATE nodes SET daily_date = date(created_at, 'localtime')
  WHERE daily_date = '' AND kind = 'doc'
`).run()

/** 关闭前把 WAL 合并回主库，备份脚本可以直接复制 notes.db */
function closeDatabase() {
  try {
    db.pragma('wal_checkpoint(TRUNCATE)')
  } catch {
    // 数据库已关闭时忽略
  }
  try {
    db.close()
  } catch {
    // 重复关闭时忽略
  }
}

module.exports = { db, DATA_DIR, closeDatabase }
