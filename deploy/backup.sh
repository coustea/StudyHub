#!/usr/bin/env bash
#
# md-notes 一致性备份脚本
#
# 设计要点：
#   1. 数据库不用 cp / sqlite3 CLI，而是用 node + better-sqlite3 的 db.backup()。
#      它调用 SQLite 的在线备份 API，会在一个读事务里复制，运行中的写入不会让备份处于
#      “半个事务”的状态；WAL 里未合并的内容也会一并落进备份文件。
#      因此本脚本可以在服务运行中执行，不需要停机。
#   2. 备份产物是单个 tar.gz：notes.db + uploads/ + 一份 BACKUP_INFO.txt（版本、时间、校验信息）。
#   3. data/.jwt-secret 默认不进备份（它只是 JWT 签名密钥，不属于用户数据）。
#      后果：恢复后所有已登录用户需要重新登录，其余功能不受影响。
#      如果你的恢复流程必须保证“用户无感”，把 INCLUDE_SECRET=1 打开即可一起打包。
#   4. 备份完成后立刻对备份出来的 notes.db 做 PRAGMA integrity_check，
#      避免留下一个看起来成功、实际损坏的文件。
#
# 用法：
#   sudo chmod +x deploy/backup.sh
#   sudo -u notes deploy/backup.sh                      # 用应用用户跑，避免文件属主混乱
#   BACKUP_DIR=/mnt/backup KEEP_DAYS=30 deploy/backup.sh
#
# 参数（全部可用环境变量覆盖）：
#   APP_DIR      项目根目录            默认 /opt/md-notes
#   DATA_DIR     数据目录              默认 $APP_DIR/data
#   BACKUP_DIR   备份输出目录          默认 /var/backups/md-notes
#   KEEP_DAYS    保留天数              默认 14
#   INCLUDE_SECRET 是否打包 .jwt-secret  默认 0（不打包）
#   NODE_BIN     node 可执行文件        默认 node
#
# 退出码：0 成功；非 0 表示任一环节失败（set -euo pipefail + trap），便于 cron / 监控判断。
#
# ============================================================================
# 恢复步骤（中文速查）
# ============================================================================
#   1) 停服务，避免恢复过程中有写入：
#        sudo systemctl stop md-notes
#        # Docker 部署：docker compose down
#
#   2) 先备份当前数据，留一条退路（目录整体改名即可，不要直接删除）：
#        sudo mv /opt/md-notes/data /opt/md-notes/data.before-restore
#        sudo mkdir -p /opt/md-notes/data
#
#   3) 解开备份包。tar 里的结构是 notes.db 与 uploads/ 直接在根下：
#        sudo tar -xzf /var/backups/md-notes/md-notes-20260101-031000.tar.gz -C /opt/md-notes/data
#
#   4) 校验完整性（可选但强烈建议）：
#        cd /opt/md-notes
#        sudo -u notes node -e "const D=require('better-sqlite3');const d=new D('/opt/md-notes/data/notes.db',{readonly:true});console.log(d.pragma('integrity_check',{simple:true}));d.close()"
#        正常输出 ok。
#
#   5) 修正属主，否则服务以 notes 用户运行时无法写库：
#        sudo chown -R notes:notes /opt/md-notes/data
#        sudo chmod 600 /opt/md-notes/data/notes.db
#
#   6) 删除旧的 WAL 残留（备份包里不含 -wal / -shm，混用会读到旧的未提交数据）：
#        sudo rm -f /opt/md-notes/data/notes.db-wal /opt/md-notes/data/notes.db-shm
#
#   7) 恢复 .jwt-secret（仅当当初打包了它，或者你想沿用旧密钥）：
#        sudo install -m 600 -o notes -g notes <备份里的 .jwt-secret> /opt/md-notes/data/.jwt-secret
#        不恢复也没关系：应用启动时会自动生成新的，代价是所有用户重新登录。
#
#   8) 启动并验证：
#        sudo systemctl start md-notes
#        curl -fsS http://127.0.0.1:3001/api/healthz && echo
#        # 浏览器打开站点，确认首页有内容、能登录、附件图片能显示。
#
#   9) 确认无误后再删除 data.before-restore：
#        sudo rm -rf /opt/md-notes/data.before-restore
#
# ============================================================================
# crontab 示例（每天 3:10 执行，日志追加到 /var/log/md-notes-backup.log）
# ============================================================================
#   sudo crontab -u notes -e
#   # 内容：
#   10 3 * * * /opt/md-notes/deploy/backup.sh >> /var/log/md-notes-backup.log 2>&1
#
#   首次使用前先建好目录并交给 notes 用户：
#     sudo mkdir -p /var/backups/md-notes /var/log
#     sudo chown notes:notes /var/backups/md-notes
#     sudo touch /var/log/md-notes-backup.log
#     sudo chown notes:notes /var/log/md-notes-backup.log
#     sudo chmod 700 /var/backups/md-notes
#
#   注意：/var/backups 在同一块盘上，磁盘坏掉会连备份一起丢。
#   生产建议把 BACKUP_DIR 指到另一块盘或挂载的远端存储，例如：
#     10 3 * * * BACKUP_DIR=/mnt/backup/md-notes /opt/md-notes/deploy/backup.sh >> /var/log/md-notes-backup.log 2>&1
#
# ============================================================================
# 日志与容错
# ============================================================================
# 每行日志带 [时间] 与级别（信息 / 警告 / 错误），方便 grep。
# 任何一步失败都会清理临时目录并以非零码退出，不会留下半成品 tar.gz。

set -euo pipefail

APP_DIR="${APP_DIR:-/opt/md-notes}"
DATA_DIR="${DATA_DIR:-$APP_DIR/data}"
BACKUP_DIR="${BACKUP_DIR:-/var/backups/md-notes}"
KEEP_DAYS="${KEEP_DAYS:-14}"
INCLUDE_SECRET="${INCLUDE_SECRET:-0}"
NODE_BIN="${NODE_BIN:-node}"

STAMP="$(date +%Y%m%d-%H%M%S)"
ARCHIVE_NAME="md-notes-$STAMP.tar.gz"
ARCHIVE="$BACKUP_DIR/$ARCHIVE_NAME"
STAGE=""

log_info()  { printf '[%s] 信息 %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*"; }
log_warn()  { printf '[%s] 警告 %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }
log_error() { printf '[%s] 错误 %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >&2; }

cleanup() {
  if [ -n "$STAGE" ] && [ -d "$STAGE" ]; then
    rm -rf "$STAGE"
  fi
}
trap cleanup EXIT

on_error() {
  log_error "备份失败，退出码 $1。请检查上面的错误信息。"
  # 失败时不要留下不完整的归档，避免以后误以为有可用备份
  rm -f "$ARCHIVE" "$ARCHIVE.sha256"
}
trap 'on_error $?' ERR

#
# 1. 前置检查
#
if [ ! -d "$APP_DIR" ]; then
  log_error "项目目录不存在：$APP_DIR（可用 APP_DIR=... 覆盖）"
  exit 1
fi
if [ ! -d "$DATA_DIR" ]; then
  log_error "数据目录不存在：$DATA_DIR（可用 DATA_DIR=... 覆盖）"
  exit 1
fi
if [ ! -f "$DATA_DIR/notes.db" ]; then
  log_error "数据库文件不存在：$DATA_DIR/notes.db"
  exit 1
fi
if ! command -v "$NODE_BIN" >/dev/null 2>&1; then
  log_error "找不到 node 可执行文件：$NODE_BIN（可用 NODE_BIN=/usr/bin/node 指定）"
  exit 1
fi
if [ ! -d "$APP_DIR/node_modules/better-sqlite3" ]; then
  log_error "找不到 better-sqlite3：$APP_DIR/node_modules/better-sqlite3，请先在项目目录执行 npm ci"
  exit 1
fi

mkdir -p "$BACKUP_DIR"
# 备份里有全部笔记内容，目录只给自己读
chmod 700 "$BACKUP_DIR" 2>/dev/null || log_warn "无法修改 $BACKUP_DIR 权限，请确认当前用户拥有该目录"

STAGE="$(mktemp -d "$BACKUP_DIR/.stage-XXXXXX")"

log_info "开始备份：APP_DIR=$APP_DIR DATA_DIR=$DATA_DIR BACKUP_DIR=$BACKUP_DIR"

#
# 2. 用 better-sqlite3 的在线备份 API 导出一致性快照
#
#    - 在 $APP_DIR 下执行，才能让 node 从项目的 node_modules 里解析到 better-sqlite3。
#    - 优先按只读方式打开源库：不会在数据目录里创建 -wal/-shm，也不会改变属主。
#      如果只读打开因为 WAL 文件权限失败，则回退到读写方式重试一次。
#
log_info "导出数据库快照（db.backup，一致性备份，无需停机）"
if ! ( cd "$APP_DIR" && \
       SRC_DB="$DATA_DIR/notes.db" DEST_DB="$STAGE/notes.db" "$NODE_BIN" -e '
const fs = require("fs");
const Database = require("better-sqlite3");

const src = process.env.SRC_DB;
const dest = process.env.DEST_DB;

function openSource() {
  try {
    return new Database(src, { readonly: true, fileMustExist: true });
  } catch (err) {
    console.error("[警告] 只读打开数据库失败，改用读写方式重试：" + err.message);
    return new Database(src, { fileMustExist: true });
  }
}

(async () => {
  const db = openSource();
  try {
    // 在线备份 API：在一个读事务内复制所有已提交页，运行中的写入不会撕裂备份
    await db.backup(dest);
  } finally {
    try { db.close(); } catch (_) {}
  }

  // 立即验证备份文件本身可打开且结构完整
  const copy = new Database(dest, { readonly: true });
  try {
    const result = copy.pragma("integrity_check", { simple: true });
    if (String(result).toLowerCase() !== "ok") {
      console.error("[错误] 备份文件完整性校验未通过：" + result);
      process.exit(1);
    }
    const stats = fs.statSync(dest);
    if (!stats.size) {
      console.error("[错误] 备份文件大小为 0");
      process.exit(1);
    }
    console.log("[信息] notes.db 快照完成，大小 " + stats.size + " 字节，integrity_check = ok");
  } finally {
    try { copy.close(); } catch (_) {}
  }
})().catch((err) => {
  console.error("[错误] 数据库备份失败：" + (err && err.stack ? err.stack : err));
  process.exit(1);
});
' ) ; then
  log_error "数据库快照失败，终止备份"
  exit 1
fi

#
# 3. 记录元信息
#
{
  echo "backup_time=$(date -Iseconds)"
  echo "hostname=$(hostname)"
  echo "app_dir=$APP_DIR"
  echo "data_dir=$DATA_DIR"
  if command -v git >/dev/null 2>&1 && [ -d "$APP_DIR/.git" ]; then
    echo "git_commit=$(cd "$APP_DIR" && git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  else
    echo "git_commit=unknown"
  fi
  echo "node_version=$("$NODE_BIN" --version 2>/dev/null || echo unknown)"
  # 只取 version 字段的值，不要把整行 '"version": "1.1.0",' 原样塞进元信息
  package_version="$("$NODE_BIN" -e 'try{process.stdout.write(require(process.argv[1]).version||"unknown")}catch(_){process.stdout.write("unknown")}' "$APP_DIR/package.json" 2>/dev/null || echo unknown)"
  echo "package_version=$package_version"
  echo "include_secret=$INCLUDE_SECRET"
} > "$STAGE/BACKUP_INFO.txt"

#
# 4. 可选：把 JWT 密钥一起打包
#
#    默认不打包。不打包的后果只有一个：恢复后旧 token 全部失效，所有用户需要重新登录。
#    如果你确实需要“恢复后用户还在登录状态”，用 INCLUDE_SECRET=1 运行。
#
if [ "$INCLUDE_SECRET" = "1" ]; then
  if [ -f "$DATA_DIR/.jwt-secret" ]; then
    # 归档内保持同样的权限位，避免恢复后密钥文件变成全局可读
    cp -p "$DATA_DIR/.jwt-secret" "$STAGE/.jwt-secret"
    chmod 600 "$STAGE/.jwt-secret"
    log_warn "已按要求把 .jwt-secret 打进备份，请把备份文件当作敏感数据保管（含签名密钥）"
  else
    log_warn "INCLUDE_SECRET=1 但 $DATA_DIR/.jwt-secret 不存在，跳过"
  fi
else
  log_info "跳过 .jwt-secret（JWT_SECRET 默认不在备份内，恢复后所有用户需重新登录）"
fi

#
# 5. 打包 notes.db 与 uploads/
#
#    uploads/ 可能正被写入；tar 非零退出时不能把不完整归档当作成功备份。
#
TAR_FILES=(notes.db BACKUP_INFO.txt)
TAR_EXTRA=()
if [ -d "$DATA_DIR/uploads" ]; then
  TAR_EXTRA=(-C "$DATA_DIR" uploads)
  log_info "打包附件目录 $DATA_DIR/uploads"
else
  log_warn "$DATA_DIR/uploads 不存在，本次备份不含附件"
fi
if [ -f "$STAGE/.jwt-secret" ]; then
  TAR_FILES+=(.jwt-secret)
fi

log_info "生成归档 $ARCHIVE"
# 先 cd 到 BACKUP_DIR 再写相对文件名：避免路径里出现 "C:"、空格等被 tar 当成远程主机或选项
# --warning=no-file-changed 是 GNU tar 的选项，其他实现(bsdtar)用 -W 语义不同，这里做探测
TAR_OPTS=()
if tar --version 2>/dev/null | grep -q 'GNU tar'; then
  TAR_OPTS+=(--warning=no-file-changed)
else
  log_warn "检测到非 GNU tar，跳过 --warning 选项（附件并发写入时可能返回 1）"
fi
set +e
# ${TAR_OPTS[@]+...} 兼容 bash 4.4 以前版本在 set -u 下展开空数组报错的问题
( cd "$BACKUP_DIR" && tar ${TAR_OPTS[@]+"${TAR_OPTS[@]}"} -czf "$ARCHIVE_NAME" -C "$STAGE" "${TAR_FILES[@]}" ${TAR_EXTRA[@]+"${TAR_EXTRA[@]}"} )
TAR_RC=$?
set -e
if [ "$TAR_RC" -ne 0 ]; then
  log_error "tar 打包失败，退出码 $TAR_RC"
  rm -f "$ARCHIVE"
  exit "$TAR_RC"
fi

# 归档里有用户全部笔记，权限收到 600
chmod 600 "$ARCHIVE"

# 生成校验和，便于传输后验证与长期存档
if command -v sha256sum >/dev/null 2>&1; then
  ( cd "$BACKUP_DIR" && sha256sum "md-notes-$STAMP.tar.gz" > "md-notes-$STAMP.tar.gz.sha256" )
  chmod 600 "$ARCHIVE.sha256"
  log_info "已生成校验和 $ARCHIVE.sha256"
else
  log_warn "系统没有 sha256sum，跳过校验和生成"
fi

ARCHIVE_SIZE="$(du -h "$ARCHIVE" | cut -f1)"
log_info "归档完成：$ARCHIVE（$ARCHIVE_SIZE）"

#
# 6. 清理过期备份
#
#    只删本脚本产出的命名（md-notes-*.tar.gz 与对应 .sha256），不会误删目录里的其他文件。
#
log_info "清理超过 $KEEP_DAYS 天的旧备份"
DELETED=0
while IFS= read -r old; do
  [ -z "$old" ] && continue
  rm -f "$old" "${old}.sha256"
  DELETED=$((DELETED + 1))
  log_info "已删除 $old"
done < <(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'md-notes-*.tar.gz' -mtime +"$KEEP_DAYS" 2>/dev/null || true)

if [ "$DELETED" -eq 0 ]; then
  log_info "没有需要清理的旧备份"
fi

# 兜底：清掉上次异常退出残留的临时目录（超过 1 天的）
find "$BACKUP_DIR" -maxdepth 1 -type d -name '.stage-*' -mtime +1 -exec rm -rf {} + 2>/dev/null || true

REMAIN="$(find "$BACKUP_DIR" -maxdepth 1 -type f -name 'md-notes-*.tar.gz' | wc -l | tr -d ' ')"
log_info "备份成功，当前保留 $REMAIN 份归档"
exit 0
