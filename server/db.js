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
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  owner_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id  INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
  parent_id   INTEGER NOT NULL DEFAULT 0,
  kind        TEXT NOT NULL CHECK (kind IN ('folder', 'doc')),
  title       TEXT NOT NULL,
  slug        TEXT NOT NULL DEFAULT '',
  content     TEXT NOT NULL DEFAULT '',
  tags        TEXT NOT NULL DEFAULT '',
  sort_order  INTEGER NOT NULL DEFAULT 0,
  status      TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft', 'published')),
  deleted_at  TEXT,
  daily_date  TEXT NOT NULL DEFAULT '',
  source_path TEXT NOT NULL DEFAULT '',
  created_at  TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at  TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_nodes_project ON nodes (project_id, parent_id, sort_order);
CREATE INDEX IF NOT EXISTS idx_nodes_updated ON nodes (kind, status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_nodes_deleted ON nodes (deleted_at);
CREATE INDEX IF NOT EXISTS idx_nodes_daily ON nodes (owner_id, daily_date);
CREATE INDEX IF NOT EXISTS idx_nodes_source ON nodes (project_id, source_path);

CREATE TABLE IF NOT EXISTS node_revisions (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id    INTEGER NOT NULL REFERENCES nodes(id) ON DELETE CASCADE,
  title      TEXT NOT NULL,
  slug       TEXT NOT NULL,
  content    TEXT NOT NULL,
  tags       TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_node_revisions ON node_revisions (node_id, id DESC);

CREATE TABLE IF NOT EXISTS app_settings (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);
`)

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
