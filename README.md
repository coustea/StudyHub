# md-notes 自托管 Markdown 笔记站

一个自托管的中文 Markdown 笔记 / 教程站点。内容按「项目 - 目录 - 笔记」三层组织，支持直接把一个本地文件夹导入成项目，自带全文搜索、RSS 与 sitemap，适合当个人知识库或教程站对外发布。

单进程 Node.js 服务 + 单个 SQLite 文件，部署成本很低：一台 1 核 1G 的小机器就能跑，不需要外部数据库、Redis 或对象存储。

## 功能

- **今日学习**：按「学习日」记录每天的代码笔记，打卡热力图（最近 364 天）+ 连续天数 + 累计打卡；首页一条提示直接开写今天的笔记，翻到以前的日期还能补写那天的
- **在线写 MD**：站内编辑器，写 / 并排预览双模式，工具栏插入标题、粗体、行内代码、链接、引用；Ctrl+S 保存，3 秒防抖本地草稿，误关页面可恢复
- **上传 MD**：编辑器里可直接「导入 md」把本地文件读进正文；项目内也能整文件夹导入，按相对路径重建多级目录，读取 front matter 的 title / tags / order / date
- **粘贴上传**：截图直接 Ctrl+V 贴进正文，自动上传成附件并插入 Markdown 图片语法
- **回收站**：删除的笔记与目录先进回收站，可恢复（目录连同子内容一起还原）或彻底删除；界面上一键清空，接口还支持 `DELETE /api/trash?days=N` 只清 N 天前的
- **阅读**：Markdown 渲染（GFM 表格、任务列表、代码高亮、标题锚点），SPA 路由，首屏一次请求拿齐首页数据
- **目录树**：项目内多级文件夹，笔记可按「排序」字段调整先后，父目录可折叠，移动时有环检测
- **标签**：笔记可打多个标签；项目页左侧按本项目标签筛选目录树，首页按全站频次聚合，点标签直接跳全文搜索
- **全文搜索**：标题、正文、标签模糊匹配；空格分隔多个关键词时按 AND 取交集（最多 5 个）；摘要自动剥掉 Markdown 记号；草稿只有作者本人可见
- **RSS / sitemap**：`/rss.xml` 输出最新 30 篇已发布笔记，`/sitemap.xml` 配合 `/robots.txt` 供搜索引擎抓取
- **暗色模式**：跟随系统，可手动切换，主题在首屏渲染前生效（无闪烁）
- **附件**：图片（PNG / JPEG / GIF / WebP）与 PDF，单文件 10MB，随机 UUID 命名，长期缓存
- **账户设置**：站内改密码、查看站点信息与回收站占用，不用再登服务器改库
- **健康检查**：`GET /api/healthz` 返回 `{"ok":true,"uptime":N}`，数据库异常时返回 503
- **安全**：helmet（CSP、生产环境 HSTS）、登录限流（10 分钟 20 次）、上传限流（1 小时 120 次）、CORS 白名单、bcrypt 密码哈希

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | React 18 + TypeScript + Vite 5，React Router 6，react-markdown + remark-gfm + rehype-slug + 自研 rehypeHighlight（lowlight） |
| 后端 | Node.js 20 + Express 4 |
| 数据库 | SQLite（better-sqlite3 11，WAL 模式） |
| 认证 | JWT（30 天有效）+ bcryptjs |
| 安全 / 中间件 | helmet、compression、cors、express-rate-limit |
| 测试 | node:test（`node --test`，需要 Node 20+） |

## 目录结构

```text
.
├── server/
│   ├── index.js          # Express 应用：路由、鉴权、RSS/sitemap、静态托管、优雅退出
│   └── db.js             # 建表、PRAGMA、closeDatabase（退出前 checkpoint WAL）
├── src/                  # React 前端源码
│   ├── pages/            # Home / Daily / Project / Editor / Search / Recent / Trash / Settings / Login
│   ├── components/       # CodeBlock / MarkdownView / Icon / ErrorBoundary
│   ├── hooks/useReveal.ts # 视口淡入（IntersectionObserver）
│   ├── lib/folder.ts     # 文件夹导入的路径处理
│   ├── lib/highlight.ts  # 只注册用得到的语言，控制高亮包体积
│   ├── lib/rehypeHighlight.ts # 自研 rehype 插件：lowlight 出 hast，再套 CodeBlock
│   ├── api.ts            # 后端接口封装
│   ├── auth.tsx          # 登录态
│   ├── site.tsx          # 站点信息 / 页面 meta / JSON-LD
│   ├── theme.tsx         # 明暗主题
│   └── styles.css        # 设计令牌 + 全部组件样式（单文件，无 CSS-in-JS）
├── tests/
│   ├── api.test.js       # 主流程接口集成测试
│   └── extra.test.js     # 每日学习 / 回收站 / 用户隔离
├── scripts/
│   ├── shoot.js          # 设计自检截图（playwright-core，浅色/深色/移动端）
│   ├── reset-password.js # 忘记密码时直接在服务器上改库
│   └── clean-orphan-uploads.js # 清理没有任何笔记引用的附件文件
├── examples/golang-basics # 可直接导入的示例 Markdown 文件夹
├── data/                 # 运行时数据，不纳入版本控制，是唯一需要备份的目录
│   ├── notes.db          # SQLite 主库
│   ├── notes.db-wal      # WAL 日志
│   ├── notes.db-shm      # 共享内存索引
│   ├── uploads/<userId>/ # 上传的附件，按用户分目录
│   └── .jwt-secret       # 未设置 JWT_SECRET 时自动生成的签名密钥
├── dist/                 # 前端构建产物，由服务端托管
├── deploy/
│   ├── md-notes.service  # systemd 单元
│   ├── nginx.conf        # nginx server 块（含 80 跳转）
│   └── backup.sh         # 一致性备份脚本
├── Dockerfile            # 多阶段生产镜像
├── docker-compose.yml    # 单服务编排
├── .env.example          # 环境变量模板
├── .gitattributes        # 强制 LF 换行（Dockerfile 用 CRLF 会让续行失效）
├── .editorconfig         # 编辑器层同样强制 LF，避免 Windows 上又写回 CRLF
└── README.md
```

## 接口一览

所有接口都在 `/api` 下，除公开读取外都需要 `Authorization: Bearer <token>`（登录接口返回，30 天有效）。写操作会校验 `owner_id`，越权返回 403。

| 方法 | 路径 | 说明 | 需要登录 |
| --- | --- | --- | --- |
| GET | `/api/healthz` | 健康检查，数据库异常时 503 | 否 |
| POST | `/api/auth/login` | 登录，返回 token 与 user；限流 20 次 / 10 分钟 | 否 |
| POST | `/api/auth/register` | 固定 403，本站不开放注册 | — |
| GET | `/api/auth/me` | 当前账号 | 是 |
| POST | `/api/auth/change-password` | 改密码（校验原密码，新密码 ≥ 6 位） | 是 |
| GET | `/api/projects` | 项目列表（含 doc/folder 计数与前 4 个标签） | 否（草稿仅作者可见） |
| POST | `/api/projects` | 新建项目；仅站点所有者 | 是 |
| GET | `/api/projects/:id` | 项目详情 + 目录树 | 否 |
| PATCH | `/api/projects/:id` | 改名 / 描述 / 排序 / 发布状态 | 是 |
| DELETE | `/api/projects/:id` | 删除项目（连同全部节点，硬删） | 是 |
| POST | `/api/projects/from-folder` | 用上传的文件夹建项目；仅站点所有者 | 是 |
| POST | `/api/nodes` | 新建笔记 / 目录，可带 `dailyDate` | 是 |
| GET | `/api/nodes/:id` | 单篇笔记 | 否 |
| PATCH | `/api/nodes/:id` | 改标题 / 正文 / 标签 / 排序 / 状态 / `dailyDate` | 是 |
| DELETE | `/api/nodes/:id` | 进回收站；加 `?purge=1` 彻底删除 | 是 |
| GET | `/api/trash` | 回收站列表（只列顶层，附项目名与总数） | 是 |
| POST | `/api/trash/:id/restore` | 恢复（父目录已删则挂回根目录） | 是 |
| DELETE | `/api/trash/:id` | 彻底删除单条 | 是 |
| DELETE | `/api/trash?days=N` | 清空回收站，带 `days` 时只清理 N 天前的 | 是 |
| GET | `/api/daily?date=&days=` | 某个学习日的笔记 + 打卡热力图数据（`days` 7–365，默认 120） | 否（未登录返回空） |
| POST | `/api/daily/new` | 在「每日学习」项目里新建当天笔记，可带 `date` / `title` | 是 |
| POST | `/api/import` | 批量导入 md（单文件 2MB、总计 20MB、最多 300 个） | 是 |
| GET | `/api/search?q=` | 标题 / 正文 / 标签模糊搜索（空格分隔多词取交集），返回命中摘要与 `terms` | 否 |
| GET | `/api/tags` | 标签云（按使用频次） | 否 |
| GET | `/api/recent?limit=` | 最近更新 | 否 |
| POST | `/api/uploads` | base64 上传附件（图片 / PDF，10MB） | 是 |
| GET | `/api/uploads/:owner/:file` | 读附件，长期缓存 | 否 |
| DELETE | `/api/uploads/:owner/:file` | 删附件 | 是 |
| GET | `/api/site` | 站点名 / 描述 / 计数 / 站点地址 | 否 |
| GET | `/api/overview` | 首页聚合：站点 + 项目 + 最近 + 标签 + 今日学习摘要 | 否 |
| GET | `/rss.xml` | 最新 30 篇已发布笔记 | 否 |
| GET | `/sitemap.xml` | 全部已发布项目与笔记 | 否 |
| GET | `/robots.txt` | 爬虫规则，含 sitemap 地址 | 否 |

## 本地开发

需要 Node.js 20 或更高版本。

```bash
npm install
npm run dev        # 同时起后端 (3001) 和 vite (5173)，浏览器打开 http://localhost:5173
```

`npm run dev` 用 concurrently 同时跑 `node server/index.js` 与 `vite`，vite 把 `/api`、`/rss.xml`、`/sitemap.xml` 代理到 3001，所以开发时只需要访问 5173 一个地址。

首次启动会在 `data/` 下自动建库，并用默认账号 `coustea` / `coustea` 建管理员。开发环境不用管，上线前必须改（见检查清单）。

其他命令：

```bash
npm test           # 跑接口测试，需要 Node 20+（node --test）
npm run reset-password -- <用户名> <新密码>   # 忘记密码时改库
npm run clean-uploads                          # 预演清理孤儿附件（加 --apply 才真删）
npm run shots      # 截图自检，产物在 .shots/（需要本机 chromium）
npm run build      # tsc -p tsconfig.json && vite build，产出 dist/
npm start          # 只起后端，托管已构建的 dist/，访问 http://localhost:3001
```

单独跑后端（不经过 vite）时，记得先 `npm run build`，否则只有 API 没有页面。

## 生产部署

三条路径按推荐程度排列。无论走哪条，都要先准备好 `.env`：

```bash
cp .env.example .env
# 生成 JWT_SECRET
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
# 把输出的 64 位字符串填进 .env 的 JWT_SECRET=
chmod 600 .env
```

`NODE_ENV=production` 时服务启动会做一次配置自检，把最容易漏的几项逐条打印出来（JWT_SECRET / SITE_URL / ALLOWED_ORIGINS / TRUST_PROXY / DEFAULT_ADMIN_PASSWORD）。全部配好时只输出一行 `生产自检通过`；有遗漏就输出编号清单，改完重启即可。自检只提醒、不阻止启动，方便你先跑起来再补配置。

### 路径一：裸机 + systemd + nginx（推荐）

适合一台长期运行的 VPS。进程由 systemd 托管，nginx 负责 TLS 与反代，升级就是 `git pull` + 重新 build。

```bash
# 1. 装 Node 20 与 nginx
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs nginx git
node -v                                  # 确认 >= v20

# 2. 建专用用户
sudo useradd --system --home /opt/md-notes --shell /usr/sbin/nologin notes

# 3. 拉代码并构建
sudo mkdir -p /opt/md-notes
sudo git clone git@github.com:coustea/StudyHub.git /opt/md-notes
cd /opt/md-notes
sudo npm ci
sudo npm run build

# 4. 数据目录
sudo mkdir -p /opt/md-notes/data
sudo chown -R notes:notes /opt/md-notes/data
sudo chmod 700 /opt/md-notes/data

# 5. 环境变量
sudo cp /opt/md-notes/.env.example /opt/md-notes/.env
sudo nano /opt/md-notes/.env
#   必改：DEFAULT_ADMIN_PASSWORD、JWT_SECRET、SITE_URL、ALLOWED_ORIGINS
#   建议：HOST=127.0.0.1（只让本机 nginx 访问）
sudo chown notes:notes /opt/md-notes/.env
sudo chmod 600 /opt/md-notes/.env

# 6. 安装并启动 systemd 服务
sudo cp /opt/md-notes/deploy/md-notes.service /etc/systemd/system/md-notes.service
sudo systemctl daemon-reload
sudo systemctl enable --now md-notes
systemctl status md-notes
curl -fsS http://127.0.0.1:3001/api/healthz && echo      # 期望 {"ok":true,"uptime":N}

# 7. nginx 反代
sudo cp /opt/md-notes/deploy/nginx.conf /etc/nginx/conf.d/md-notes.conf
sudo sed -i 's/notes.example.com/你的域名/g' /etc/nginx/conf.d/md-notes.conf
sudo nginx -t && sudo systemctl reload nginx

# 8. HTTPS（certbot 会自动改写 ssl_certificate 两行并配好自动续期）
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot --nginx -d 你的域名
sudo systemctl list-timers | grep certbot

# 9. 备份 cron（每天 3:10）
sudo chmod +x /opt/md-notes/deploy/backup.sh
sudo mkdir -p /var/backups/md-notes && sudo chown notes:notes /var/backups/md-notes
sudo chmod 700 /var/backups/md-notes
sudo crontab -u notes -e
#   写入：
#   10 3 * * * /opt/md-notes/deploy/backup.sh >> /var/log/md-notes-backup.log 2>&1
```

`deploy/md-notes.service` 里已经开了 `ProtectSystem=strict`、`ProtectHome=true`、`NoNewPrivileges=true`、`PrivateTmp=true` 等加固项，并把 `/opt/md-notes/data` 设为唯一可写路径。注意它默认用 `/usr/bin/node`，如果你用 nvm 装的 Node，要用 `which node` 查到真实路径后改 `ExecStart`（systemd 不读用户的 PATH）。

### 路径二：Docker Compose

适合已经有 Docker 的机器，或者想和别的服务跑在同一台主机上。

```bash
cp .env.example .env
nano .env        # 必改 DEFAULT_ADMIN_PASSWORD / JWT_SECRET / SITE_URL
                 # Docker 下 HOST 保持 0.0.0.0，DATA_DIR 由 compose 强制为 /app/data

docker compose up -d --build
docker compose ps                  # 等 STATUS 出现 (healthy)
docker compose logs -f
curl -fsS http://127.0.0.1:3001/api/healthz && echo
```

镜像构建顺序：阶段一 `builder`（node:20-bookworm-slim + python3/make/g++ + `npm ci` + `npm run build`）产出 `dist/`；阶段二 `runtime`（同样是 node:20-bookworm-slim）只装生产依赖，`dist/` 直接从 builder 阶段拷过来，`server/` 从构建上下文拷，最后 `USER node` + `HEALTHCHECK` + `STOPSIGNAL SIGTERM`。两个阶段锁同一个 Node 主版本，保证 better-sqlite3 的原生 ABI 一致。

常用运维命令：

```bash
docker compose restart                     # 重启，走优雅退出
docker compose down                        # 停止并删除容器，命名卷 md-notes-data 保留
docker compose up -d --build               # 升级：重新构建并滚动替换
docker compose exec md-notes node -e "fetch('http://127.0.0.1:3001/api/healthz').then(r=>r.text()).then(console.log)"
docker volume ls | grep md-notes           # 确认数据卷还在
```

更新代码后必须加 `--build`，否则 compose 会复用旧镜像。`docker compose down` 默认**不会**删命名卷，但 `down -v` 会，别顺手加 `-v`。

Docker 部署的备份：镜像里不含 `deploy/`（已在 .dockerignore 排除），所以用一次性容器把宿主机的脚本和数据卷一起挂进去跑。注意镜像默认以 `node`（uid 1000）运行，宿主机备份目录要让它可写：

```bash
sudo mkdir -p /var/backups/md-notes
sudo chown 1000:1000 /var/backups/md-notes
sudo chmod 700 /var/backups/md-notes

docker run --rm \
  -v md-notes-data:/data \
  -v /var/backups/md-notes:/backup \
  -v /opt/md-notes/deploy:/deploy:ro \
  -e APP_DIR=/app \
  -e DATA_DIR=/data \
  -e BACKUP_DIR=/backup \
  --entrypoint bash \
  md-notes:latest /deploy/backup.sh
```

cron 里把上面这条写成一行即可（注意 docker 需要 root 或 docker 组权限）：

```cron
10 3 * * * docker run --rm -v md-notes-data:/data -v /var/backups/md-notes:/backup -v /opt/md-notes/deploy:/deploy:ro -e APP_DIR=/app -e DATA_DIR=/data -e BACKUP_DIR=/backup --entrypoint bash md-notes:latest /deploy/backup.sh >> /var/log/md-notes-backup.log 2>&1
```

如果觉得这套太绕，把 compose 里的命名卷换成 bind mount（`./data:/app/data`）会简单很多：宿主机上的 `deploy/backup.sh` 可以直接对 `./data` 跑，不需要进容器。

### 路径三：仅内网 / 本机

不需要 nginx、不需要 Docker，直接跑：

```bash
npm ci
npm run build
cp .env.example .env
# 内网用可以简化：HOST=0.0.0.0、SITE_URL=http://192.168.1.10:3001、TRUST_PROXY=false
node server/index.js
```

要点：

- **没有反代时一定要设 `TRUST_PROXY=false`**。默认值 `1` 表示信任一层代理，直连公网时客户端可以伪造 `X-Forwarded-For` 绕过登录限流。
- `SITE_URL` 要写成内网可访问的完整地址（如 `http://192.168.1.10:3001`），否则 RSS 与 sitemap 里的链接会是错的。
- 想开机自启就用 `deploy/md-notes.service` 但把 `HOST` 改成 `0.0.0.0`，`SITE_URL` 改成内网地址。

## 环境变量

| 变量 | 默认值 | 说明 | 必填 |
| --- | --- | --- | --- |
| `ENV_FILE` | `<项目根>/.env` | 配置文件路径，存在就自动读取；已存在的环境变量优先 | 否 |
| `PORT` | `3001` | 监听端口 | 否 |
| `HOST` | `0.0.0.0` | 监听地址。裸机反代建议 `127.0.0.1` | 否 |
| `DATA_DIR` | `./data` | 数据目录，唯一需要持久化的目录 | 否 |
| `NODE_ENV` | 未设置 | 生产必须设 `production`，否则不发 HSTS | **是（生产）** |
| `TRUST_PROXY` | `1` | 信任的反代层数。一层 nginx 用 `1`，直连公网用 `false` | 否 |
| `JWT_SECRET` | 空（自动生成 `data/.jwt-secret`） | JWT 签名密钥，64 位十六进制 | **是（生产）** |
| `ALLOWED_ORIGINS` | 空（允许所有来源） | CORS 白名单，逗号分隔 | **是（生产）** |
| `SITE_NAME` | `笔记库` | 站点名，用于页面标题与 RSS | 否 |
| `SITE_DESCRIPTION` | `教程、笔记与代码示例，按项目归档。` | 站点描述 | 否 |
| `SITE_OWNER` | `coustea` | 唯一可建项目 / 导入的账号；设空字符串 = 任意登录账号 | 否 |
| `SITE_URL` | 空（按请求头推断） | 站点根地址，用于 RSS / sitemap / robots 的绝对链接 | **是（生产）** |
| `DEFAULT_ADMIN_USERNAME` | `coustea` | 首次启动创建的管理员账号 | 否 |
| `DEFAULT_ADMIN_PASSWORD` | `coustea` | 首次启动创建的管理员密码 | **是（生产必改）** |
| `DEFAULT_ADMIN_DISPLAY_NAME` | `站长` | 管理员显示名 | 否 |
| `DISABLE_DEFAULT_ADMIN` | 未设置 | 设 `1` 跳过默认管理员创建 | 否 |
| `HOST_PORT` | `3001` | 仅 Docker Compose 用，宿主机映射端口 | 否 |

服务启动时会自动读取项目根目录的 `.env`（不依赖 dotenv，约 20 行解析），所以裸机、Docker（compose 的 `env_file`）、systemd（`EnvironmentFile`）三条路径共用同一份配置。临时覆盖直接写在命令前面即可，不用改文件：

```bash
PORT=4000 SITE_NAME=临时站点 node server/index.js
```

`DEFAULT_ADMIN_*` 只在库里没有同名账号时生效，改密码不会影响已存在的账号（要用站内「修改密码」或直接改库）。`ALLOWED_ORIGINS` 留空时 CORS 允许所有来源，只适合纯内网。

## 首次部署检查清单

上线前逐条确认，任何一条没做都可能被扫站脚本利用：

- [ ] **改掉默认密码**：`DEFAULT_ADMIN_PASSWORD` 换成 16 位以上随机字符串，或先启动建号后立刻在站内改密码
- [ ] **设置 `JWT_SECRET`**：不要依赖自动生成的 `data/.jwt-secret`，否则迁移 / 重建卷时所有人被踢下线
- [ ] **设置 `SITE_URL`**：写成 `https://你的域名`（带协议、结尾不带斜杠），否则 RSS / sitemap 里是 http 或内网地址
- [ ] **设置 `ALLOWED_ORIGINS`**：填真实域名，不要留空
- [ ] **设置 `NODE_ENV=production`**：否则不发送 HSTS
- [ ] **`TRUST_PROXY` 与实际拓扑一致**：一层 nginx 用 `1`，直连公网用 `false`
- [ ] **配好备份 cron**：`10 3 * * *` 跑 `deploy/backup.sh`，并**实际恢复一次**验证备份可用
- [ ] **启用 HTTPS**：certbot 申请证书，确认自动续期定时器存在
- [ ] **防火墙只开 80 / 443**：`sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable`，3001 不要对公网开放
- [ ] **`chmod 600 .env`**：里面有数据库口令与 JWT 密钥
- [ ] **`/api/healthz` 不对外**：`deploy/nginx.conf` 已限制只允许本机，如果后续改过要复核
- [ ] **确认 `data/` 属主**是运行用户（`notes` 或容器里的 `node`），否则第一次写入就失败

## 备份与恢复

`deploy/backup.sh` 用 better-sqlite3 的 `db.backup()` 做一致性快照，不依赖 `sqlite3` CLI，**可以在服务运行时执行**。

```bash
# 手动跑一次
sudo -u notes /opt/md-notes/deploy/backup.sh

# 自定义参数
sudo -u notes BACKUP_DIR=/mnt/backup/md-notes KEEP_DAYS=30 /opt/md-notes/deploy/backup.sh

# 连 JWT 密钥一起打包（恢复后用户不用重新登录）
sudo -u notes INCLUDE_SECRET=1 /opt/md-notes/deploy/backup.sh
```

产物是 `md-notes-YYYYmmdd-HHMMSS.tar.gz` 加同名的 `.sha256`，内含 `notes.db`、`uploads/`、`BACKUP_INFO.txt`（时间、主机、git commit、node 与 package 版本）。默认 `BACKUP_DIR=/var/backups/md-notes`，保留 `KEEP_DAYS=14` 天。

为什么不用 `cp notes.db`：WAL 模式下主库文件可能缺少最近的事务，直接拷会得到一个「看起来正常但少了最新内容」的库。`db.backup()` 走 SQLite 在线备份 API，在一个读事务里复制，写入不会让备份处于半事务状态，并且备份完成后脚本会立刻对新库做 `PRAGMA integrity_check`。

`.jwt-secret` 默认不进备份。它只是签名密钥，不含用户数据；不备份的唯一后果是恢复后所有已登录用户需要重新登录。如果你在意这一点，用 `INCLUDE_SECRET=1`。

恢复步骤（完整版见脚本头部注释）：

```bash
sudo systemctl stop md-notes
sudo mv /opt/md-notes/data /opt/md-notes/data.before-restore
sudo mkdir -p /opt/md-notes/data
sudo tar -xzf /var/backups/md-notes/md-notes-20260101-031000.tar.gz -C /opt/md-notes/data
sudo rm -f /opt/md-notes/data/notes.db-wal /opt/md-notes/data/notes.db-shm
sudo chown -R notes:notes /opt/md-notes/data
sudo systemctl start md-notes
curl -fsS http://127.0.0.1:3001/api/healthz && echo
```

恢复后一定要打开站点确认首页有内容、能登录、附件图片能显示。确认无误再删掉 `data.before-restore`。

**备份放在同一块盘上等于没有备份。** 生产环境请把 `BACKUP_DIR` 指到另一块盘或挂载的远端存储（NFS、对象存储挂载等）。

### 清理孤儿附件

删除笔记（或删掉正文里的图片语法）时，`uploads/` 里的文件不会跟着消失 —— 笔记正文只存一个 Markdown 链接，服务端无法判断这张图还有没有别处引用。时间一长附件目录会攒下没人用的图片，备份体积也跟着变大。

```bash
# 先预演，看清楚要删什么（不会删任何文件）
sudo -u notes node /opt/md-notes/scripts/clean-orphan-uploads.js

# 确认无误后真删
sudo -u notes node /opt/md-notes/scripts/clean-orphan-uploads.js --apply

# 只删 30 天前没人引用的，给「刚上传还没来得及插入正文」留出余地
sudo -u notes node /opt/md-notes/scripts/clean-orphan-uploads.js --apply --days 30
```

脚本会把**所有**笔记正文（含回收站里的）扫一遍，收集 `/api/uploads/<owner>/<file>` 形式的引用作为白名单，磁盘上不在白名单里的才算孤儿。回收站里的笔记也算引用，所以恢复后图片还在。

可以挂到备份 cron 后面每月跑一次：

```bash
# 每月 1 号 4:10 清理
10 4 1 * * /opt/md-notes/scripts/clean-orphan-uploads.js --apply --days 30 >> /var/log/md-notes-clean.log 2>&1
```

Docker 部署时脚本不在镜像里（`.dockerignore` 排除了 `scripts/`），和 `reset-password.js` 一样用 `cp` 拷进去：

```bash
docker compose cp scripts/clean-orphan-uploads.js md-notes:/tmp/clean.js
docker compose exec md-notes node /tmp/clean.js              # 预演
docker compose exec md-notes node /tmp/clean.js --apply      # 真删
```

## 升级流程

```bash
cd /opt/md-notes
sudo systemctl stop md-notes          # 可选，应用能容忍不停机升级，但停机更稳
sudo -u notes /opt/md-notes/deploy/backup.sh    # 升级前先备份
sudo git pull
sudo npm ci
sudo npm run build
sudo systemctl start md-notes
curl -fsS http://127.0.0.1:3001/api/healthz && echo
journalctl -u md-notes -n 50 --no-pager
```

Docker 部署：

```bash
docker compose down
git pull
docker compose up -d --build
docker compose ps
```

**数据库迁移**：新表用 `CREATE TABLE IF NOT EXISTS` 创建，全新部署不用管。已有库的**加列**由 `server/db.js` 的 `ensureColumn()` 自动完成 —— 它用 `PRAGMA table_info` 检查列是否已存在，缺了才 `ALTER TABLE ... ADD COLUMN`，所以启动时自动迁移、可重复执行、不会破坏数据。

当前自动迁移的列：

| 列 | 作用 |
| --- | --- |
| `nodes.deleted_at` | 软删除时间戳，NULL 表示未删除（回收站靠它） |
| `nodes.daily_date` | 笔记归属的学习日 `YYYY-MM-DD`，老笔记按 `created_at` 本地日期回填 |

新增列时记得同时更新 `ensureColumn()` 调用与上面的表格。**动手前仍然先备份**：

```bash
sudo -u notes /opt/md-notes/deploy/backup.sh
```

如果自动迁移失败（例如库文件权限不对），手工补列的命令是：

```bash
# 先备份！
sudo systemctl stop md-notes
sudo -u notes /opt/md-notes/deploy/backup.sh
# 查当前表结构
sudo -u notes node -e "const D=require('/opt/md-notes/node_modules/better-sqlite3');const d=new D('/opt/md-notes/data/notes.db');console.log(d.prepare('PRAGMA table_info(nodes)').all());d.close()"
# 按新版本 server/db.js 里的定义补列，例如：
sudo -u notes node -e "const D=require('/opt/md-notes/node_modules/better-sqlite3');const d=new D('/opt/md-notes/data/notes.db');d.exec(\"ALTER TABLE nodes ADD COLUMN new_column TEXT NOT NULL DEFAULT ''\");d.close()"
sudo systemctl start md-notes
```

升级前看一眼 `git log -- server/db.js`：改过表定义就先确认新列名，升级后 `PRAGMA table_info` 复核一次。

## 常见问题

**端口被占用：`Error: listen EADDRINUSE: address already in use 0.0.0.0:3001`**

```bash
sudo ss -ltnp | grep 3001        # 找出占用进程
sudo systemctl stop md-notes     # 如果就是它自己
# 或者换端口：.env 里改 PORT=3002，nginx 的 proxy_pass 同步改
```

常见原因是重复启动了服务，或者上一次 `npm run dev` 忘了关。

**忘记密码，登不进去了**

不需要重装，也不需要手动拼 SQL。项目自带一个改密码脚本，直接读同一个数据库：

```bash
cd /opt/md-notes
sudo -u notes node scripts/reset-password.js --list                    # 先看有哪些账号
sudo -u notes node scripts/reset-password.js coustea '新密码至少6位'    # 再改
```

也可以写成 `sudo -u notes npm run reset-password -- coustea '新密码'`。

Docker 部署时脚本不在镜像里（`.dockerignore` 排除了 `scripts/`），用 `cp` 拷进去：

```bash
docker compose cp scripts/reset-password.js md-notes:/tmp/reset.js
docker compose exec md-notes node /tmp/reset.js --list
docker compose exec md-notes node /tmp/reset.js coustea '新密码至少6位'
```

改完旧 token 依然有效。想立刻把其他设备踢下线，同时换掉 `JWT_SECRET` 并重启服务。

**better-sqlite3 编译失败**

报错通常是 `node-gyp` 找不到 python / make / g++，或 `NODE_MODULE_VERSION` 不匹配。

```bash
# 装编译工具
sudo apt-get install -y python3 make g++
# 重建原生模块（换过 Node 大版本后必须执行）
sudo npm rebuild better-sqlite3
# 或者彻底重装
sudo rm -rf node_modules && sudo npm ci
```

`NODE_MODULE_VERSION` 不匹配的意思是：`node_modules` 里的 `.node` 文件是为别的 Node 大版本编译的。刚才提到过，构建镜像与运行镜像必须同为 Node 20；裸机上换过 Node 版本后必须 `npm rebuild better-sqlite3`。用 nvm 的话，切换版本后也要 rebuild。

**反代后 RSS / sitemap 里的链接是 http**

原因有三个，按顺序排查：

1. `.env` 里没设 `SITE_URL`。设成 `https://你的域名` 就能彻底解决，不需要依赖请求头推断。
2. nginx 没传 `X-Forwarded-Proto`。`deploy/nginx.conf` 里已经有 `proxy_set_header X-Forwarded-Proto $scheme;`，改过配置要确认还在。
3. `TRUST_PROXY` 设成了 `false`。这样 Express 会忽略 `X-Forwarded-*` 头，`req.protocol` 永远是 `http`。

验证方法：

```bash
curl -s https://你的域名/rss.xml | head -20
curl -s https://你的域名/robots.txt
```

**上传返回 413**

413 是 nginx 在应用之前就拒绝的，说明超过了 `client_max_body_size`。当前配置是 `25m`，够 10MB 附件（base64 后约 13.3MB）和 20MB 文件夹导入用。确实是正常需求再调大：

```nginx
client_max_body_size 50m;
```

```bash
sudo nginx -t && sudo systemctl reload nginx
```

如果 nginx 没拦（直连 3001 端口或反代配了更大的值），应用自己也会返回 413 并提示「请求体过大，单次请求上限 24MB」——这是 `express.json({ limit: '24mb' })` 的上限。真需要更大就同时调大这两处。

如果是应用返回 400 并提示「文件不能超过 10MB」，那是应用侧限制，改不了配置，只能压缩文件。上传接口只接受 PNG / JPEG / GIF / WebP / PDF。

**请求返回 400「请求体不是合法的 JSON」**

这是应用在解析请求体时失败，通常是脚本或第三方工具发出的正文不是合法 JSON（多了尾逗号、少了引号、把表单数据当 JSON 发）。浏览器里的正常操作不会出现。

**触发限流**

- 登录：10 分钟内同 IP 最多 20 次，超过返回 `尝试次数过多，请稍后再试`。等一会儿再试，或者确认密码没错再操作。
- 上传：1 小时内同 IP 最多 120 次。

反代后如果所有人都被当成同一个 IP，说明 nginx 没传真实 IP 或 `TRUST_PROXY` 配错了：前者检查 `X-Real-IP` / `X-Forwarded-For` 两行，后者确认 `TRUST_PROXY` 的层数与实际拓扑一致。直连公网时 `TRUST_PROXY` 必须设 `false`，否则限流可以被伪造的请求头绕过。

**页面 404 但 API 正常**

`dist/` 不存在或没构建。服务端只在 `dist/index.html` 存在时才托管前端，否则只提供 API（生产环境启动日志会打印提示）。

```bash
npm run build
ls -l dist/index.html
sudo systemctl restart md-notes
```

**容器一直 unhealthy**

```bash
docker compose logs md-notes
docker inspect --format '{{json .State.Health}}' md-notes
```

常见原因是 `data/` 权限不对（容器里是 `node` 用户，uid 1000），或者数据库文件被 root 拥有导致打不开。用命名卷一般不会有这个问题；换成 bind mount 时要 `sudo chown -R 1000:1000 ./data`。

**数据目录权限错误：`SQLITE_CANTOPEN` / `EACCES`**

服务以 `notes`（裸机）或 `node`（容器）运行，`data/` 必须是它对应用户可写：

```bash
sudo chown -R notes:notes /opt/md-notes/data      # 裸机
sudo chown -R 1000:1000 ./data                    # Docker bind mount
```
