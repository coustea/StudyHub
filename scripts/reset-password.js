#!/usr/bin/env node
//
// 忘记密码时的救命脚本：直接在服务器上改库，不需要登录站内。
//
// 用法（在项目根目录执行，与 server 用同一个 DATA_DIR）：
//   node scripts/reset-password.js <用户名> <新密码>
//   node scripts/reset-password.js coustea 'my-new-password'
//
// Docker 部署：
//   docker compose exec md-notes node -e "..." 太啰嗦，直接把脚本拷进容器更方便：
//   docker compose cp scripts/reset-password.js md-notes:/tmp/reset.js
//   docker compose exec md-notes node /tmp/reset.js coustea 'my-new-password'
//
// 注意：
//   1. 服务运行时也能改，SQLite 的写锁会串行化，不需要停机。
//   2. 改完密码后，之前签发的 JWT 仍然有效（它们不校验密码版本）。
//      想立刻踢掉所有旧会话，就同时换掉 JWT_SECRET 并重启。
//   3. 新密码长度下限与站内一致：6 位。建议用 16 位以上随机串。
//   4. 不知道用户名时先列出来：node scripts/reset-password.js --list

const path = require('path')
const fs = require('fs')

// 复用服务端同一套 .env 解析逻辑，保证 DATA_DIR / ENV_FILE 与运行中的服务一致
const ROOT_DIR = path.join(__dirname, '..')
function loadEnvFile(file) {
  if (!fs.existsSync(file)) return
  for (const rawLine of fs.readFileSync(file, 'utf8').split(/\r?\n/)) {
    const line = rawLine.trim()
    if (!line || line.startsWith('#')) continue
    const eq = line.indexOf('=')
    if (eq < 1) continue
    const key = line.slice(0, eq).trim()
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue
    if (process.env[key] !== undefined) continue
    let value = line.slice(eq + 1).trim()
    if (value.length > 1) {
      const first = value[0]
      if ((first === '"' || first === "'") && value.endsWith(first)) value = value.slice(1, -1)
    }
    process.env[key] = value
  }
}
loadEnvFile(process.env.ENV_FILE || path.join(ROOT_DIR, '.env'))
if (process.env.DATA_DIR && !path.isAbsolute(process.env.DATA_DIR)) {
  process.env.DATA_DIR = path.resolve(ROOT_DIR, process.env.DATA_DIR)
}

const Database = require('better-sqlite3')
const bcrypt = require('bcryptjs')

const DATA_DIR = process.env.DATA_DIR || path.join(ROOT_DIR, 'data')
const dbFile = path.join(DATA_DIR, 'notes.db')

if (!fs.existsSync(dbFile)) {
  console.error(`[错误] 找不到数据库：${dbFile}`)
  console.error('       确认 DATA_DIR 是否正确（当前值：' + DATA_DIR + '）')
  process.exit(1)
}

const args = process.argv.slice(2)
const db = new Database(dbFile)

try {
  if (!args.length || args[0] === '--list' || args[0] === '-l') {
    const users = db.prepare('SELECT id, username, display_name, created_at FROM users ORDER BY id').all()
    if (!users.length) {
      console.log('库里还没有任何账号。直接启动服务会用 DEFAULT_ADMIN_* 建一个。')
    } else {
      console.log('现有账号：')
      for (const user of users) {
        console.log(`  #${user.id}  ${user.username}  ${user.display_name || '(无显示名)'}  创建于 ${user.created_at}`)
      }
      console.log('\n改密码：node scripts/reset-password.js <用户名> <新密码>')
    }
    process.exit(0)
  }

  const [username, password] = args
  if (!username || !password) {
    console.error('用法：node scripts/reset-password.js <用户名> <新密码>')
    console.error('      node scripts/reset-password.js --list')
    process.exit(1)
  }
  if (password.length < 6) {
    console.error('[错误] 新密码至少 6 位（与站内改密码的限制一致）')
    process.exit(1)
  }

  const user = db.prepare('SELECT id, username FROM users WHERE username = ?').get(username)
  if (!user) {
    console.error(`[错误] 没有找到用户：${username}`)
    console.error('       用 --list 看现有账号。')
    process.exit(1)
  }

  // 与服务端登录时用的 bcryptjs 保持一致（cost 10），换算法会导致登录失败
  db.prepare('UPDATE users SET password_hash = ? WHERE id = ?')
    .run(bcrypt.hashSync(password, 10), user.id)

  console.log(`[完成] 已重置 ${user.username}（#${user.id}）的密码。`)
  console.log('       旧 token 仍然有效；要立刻踢掉所有会话，换 JWT_SECRET 后重启服务。')
} finally {
  db.close()
}
