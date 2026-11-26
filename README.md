# md-notes · 自托管 Markdown 笔记站

> 一个自托管的中文 Markdown 笔记 / 教程站点。内容按 **项目 → 目录 → 笔记** 三层组织，可直接把一个本地文件夹导入成项目，自带全文搜索、RSS、sitemap、AI 辅助写作与今日学习打卡。适合作为个人知识库或对外发布的教程站。

**单进程 Node.js + 单个 SQLite 文件**，无需外部数据库、Redis 或对象存储，一台 1 核 1G 的小机器即可运行，部署成本极低。

- 包名 / 版本：`md-notes-site` · `1.1.0`
- 运行要求：**Node.js ≥ 20**
- 技术栈：React 18 + Vite 5 + Express 4 + better-sqlite3

## 目录

- [功能特性](#功能特性)
- [技术栈](#技术栈)
- [快速开始（本地开发）](#快速开始本地开发)
- [目录结构](#目录结构)
- [配置（环境变量）](#配置环境变量)
- [生产部署](#生产部署)
- [接口一览](#接口一览)
- [数据库与迁移](#数据库与迁移)
- [AI 辅助写作](#ai-辅助写作)
- [备份与恢复](#备份与恢复)
- [运维脚本](#运维脚本)
- [测试](#测试)
- [常见问题](#常见问题)
- [许可证](#许可证)

## 功能特性

- **今日学习**：按「学习日」记录每天的代码笔记，打卡热力图（最近 364 天）+ 连续天数 + 累计打卡；首页一键开写当天笔记，也可翻回历史日期补写。
- **在线写 Markdown**：站内编辑器，写作 / 并排预览双模式，工具栏插入标题、粗体、行内代码、链接、引用；`Ctrl+S` 保存，3 秒防抖本地草稿，误关页面可恢复；保存时保留旧版本，可在编辑器中确认回滚。
- **AI 辅助写作**：编辑器支持按要求新写、续写或改写选中内容，生成结果先检查再手动加入正文。兼容 OpenAI、讯飞星火、DeepSeek 等 OpenAI 协议服务。
- **阅读与管理分离**：公开首页 `/` 只展示已发布项目与笔记；`coustea` 登录后进入 `/admin` 工作台，集中管理项目、文章与草稿。
- **导入 Markdown**：编辑器内可「导入 md」把本地文件读进正文；项目内支持整文件夹导入，按相对路径重建多级目录，读取 front matter 的 `title` / `tags` / `order` / `date`；重复路径自动跳过，不覆盖在线修改。
- **粘贴上传**：截图直接 `Ctrl+V` 贴进正文，自动上传为附件并插入 Markdown 图片语法。
- **回收站**：删除的笔记与目录先进回收站，可恢复（目录连同子内容一起还原）或彻底删除；界面一键清空，接口另支持 `DELETE /api/trash?days=N` 只清 N 天前的。
- **阅读渲染**：Markdown 渲染（GFM 表格、任务列表、代码高亮、标题锚点），SPA 路由，首屏一次请求聚合全部数据。
- **文件树**：项目页与编辑页都能就地创建文件夹 / 笔记；拖动手柄移动或排序，或用 `Alt + 方向键` 操作；移动时防止目录形成环。
- **标签**：笔记可打多个标签；项目页按本项目标签筛选目录树，首页按全站频次聚合，点标签直接跳全文搜索。
- **全文搜索**：标题、正文、标签模糊匹配；空格分隔多词按 AND 取交集（最多 5 个）；摘要自动剥离 Markdown 记号；草稿仅作者本人可见。
- **RSS / sitemap**：`/rss.xml` 输出最新 30 篇已发布笔记，`/sitemap.xml` 配合 `/robots.txt` 供搜索引擎抓取。
- **暗色模式**：跟随系统，可手动切换，主题在首屏渲染前生效，无闪烁。
- **附件**：图片（PNG / JPEG / GIF / WebP）与 PDF，单文件 10MB，随机 UUID 命名，长期缓存。
- **账户设置**：站内改密码、查看站点信息与回收站占用，无需登服务器改库。
- **健康检查**：`GET /api/healthz` 返回 `{"ok":true,"uptime":N}`，数据库异常时返回 503。
- **安全**：helmet（CSP、生产环境 HSTS）、登录限流（10 分钟 20 次）、上传限流（1 小时 120 次）、CORS 白名单、bcrypt 密码哈希。

> **关于历史版本**：版本记录从本次升级后的第一次正文 / 标题 / URL 标识 / 标签修改开始。升级前导入且未保存来源路径的旧文件，首次重新导入仍可能新增一份；此后相同路径会被识别并跳过。

## 技术栈

| 层 | 选型 |
| --- | --- |
| 前端 | React 18 + TypeScript + Vite 5，React Router 6，react-markdown + remark-gfm + rehype-slug + 自研 rehypeHighlight（lowlight） |
| 后端 | Node.js 20 + Express 4；AI 写作使用 OpenAI Node SDK |
| 数据库 | SQLite（better-sqlite3 11，WAL 模式） |
| 认证 | JWT（30 天有效）+ bcryptjs |
| 安全 / 中间件 | helmet、compression、cors、express-rate-limit |
| 测试 | node:test（`node --test`，需要 Node 20+） |

## 快速开始（本地开发）

需要 Node.js 20 或更高版本。

```bash
npm install
npm run dev        # 同时起后端 (3001) 和 Vite (5173)，浏览器打开 http://localhost:5173
```

`npm run dev` 用 concurrently 同时运行 `node server/index.js` 与 `vite`。Vite 会把 `/api`、`/rss.xml`、`/sitemap.xml` 代理到 3001，因此开发时只需访问 **5173** 一个地址。

首次启动会在 `data/` 下自动建库，并用默认账号 `coustea` / `coustea` 创建管理员。开发环境无需处理，**上线前必须修改**（见[生产部署检查清单](#生产部署检查清单)）。

**可用命令：**

```bash
npm run dev              # 同时启动后端与前端（开发）
npm run build            # tsc 类型检查 + Vite 构建，产出 dist/
npm start                # 仅启动后端，托管已构建的 dist/，访问 http://localhost:3001
npm run preview          # 先构建再启动后端（一条命令完成生产式本地预览）
npm test                 # 运行接口测试（node --test，需 Node 20+）
npm run reset-password -- <用户名> <新密码>   # 忘记密码时直接改库
npm run clean-uploads    # 预演清理孤儿附件（加 --apply 才真正删除）
npm run shots            # 设计自检截图，产物在 .shots/（需本机 chromium）
```

> 单独运行后端（不经 Vite）前，请先执行 `npm run build`，否则只有 API、没有页面。

## 目录结构

```text
.
├── server/
│   ├── index.js          # Express 应用：路由、鉴权、RSS/sitemap、静态托管、优雅退出
│   └── db.js             # 建表、PRAGMA、closeDatabase（退出前 checkpoint WAL）
├── src/                  # React 前端源码
│   ├── pages/            # Home / Daily / Project / Editor / Search / Recent / Trash / Settings / Login / admin/*
│   ├── components/       # CodeBlock / MarkdownView / Icon / ErrorBoundary / ProjectFileTree / MarkdownAssistant
│   ├── components/ui/    # shadcn/radix 基础组件（button / card / dialog / badge）
│   ├── hooks/useReveal.ts # 视口淡入（IntersectionObserver）
│   ├── lib/folder.ts     # 文件夹导入的路径处理
│   ├── lib/highlight.ts  # 只注册用到的语言，控制高亮包体积
│   ├── lib/rehypeHighlight.ts # 自研 rehype 插件：lowlight 出 hast，再套 CodeBlock
│   ├── api.ts            # 后端接口封装
│   ├── auth.tsx          # 登录态
│   ├── site.tsx          # 站点信息 / 页面 meta / JSON-LD
│   ├── theme.tsx         # 明暗主题
│   └── styles.css        # 设计令牌 + 全部组件样式（单文件，无 CSS-in-JS）
├── tests/
│   ├── api.test.js       # 主流程接口集成测试
│   ├── extra.test.js     # 每日学习 / 回收站 / 用户隔离
│   └── mock-ai-fetch.js  # 模拟四类 AI 上游（OpenAI / 星火 / 星火错误码 / DeepSeek）
├── scripts/
│   ├── shoot.js          # 设计自检截图（playwright-core，浅色/深色/移动端）
│   ├── reset-password.js # 忘记密码时直接在服务器上改库
│   └── clean-orphan-uploads.js # 清理没有任何笔记引用的附件文件
├── examples/golang-basics # 可直接导入的示例 Markdown 文件夹
├── data/                 # 运行时数据，不纳入版本控制，是唯一需要持久化与备份的目录
│   ├── notes.db          # SQLite 主库
│   ├── notes.db-wal      # WAL 日志
│   ├── notes.db-shm      # 共享内存索引
│   ├── uploads/<userId>/ # 上传的附件，按用户分目录
│   └── .jwt-secret       # 未设置 JWT_SECRET 时自动生成的签名密钥
├── dist/                 # 前端构建产物，由服务端托管
├── deploy/
│   ├── md-notes.service       # systemd 单元
│   ├── nginx-bootstrap.conf   # 首次申请证书的临时 HTTP 配置
│   ├── nginx.conf             # nginx server 块（含 80 跳转）
│   └── backup.sh              # 一致性备份脚本
├── Dockerfile            # 多阶段生产镜像
├── docker-compose.yml    # 单服务编排
├── .env.example          # 环境变量模板
├── .gitattributes        # 强制 LF 换行（Dockerfile 用 CRLF 会让续行失效）
├── .editorconfig         # 编辑器层同样强制 LF，避免 Windows 上写回 CRLF
└── README.md
```

## 配置（环境变量）

服务启动时自动读取项目根目录的 `.env`（内置约 20 行解析，不依赖 dotenv），裸机、Docker、systemd 三条部署路径共用同一份配置。**真实环境变量优先于 `.env` 文件**，临时覆盖可直接写在命令前：

```bash
PORT=4000 SITE_NAME=临时站点 node server/index.js
```

`.env` 文件中**不要写行尾注释、不要给值加引号**，权限设为 `chmod 600`。

| 变量 | 默认值 | 说明 | 生产必填 |
| --- | --- | --- | :---: |
| `ENV_FILE` | `<项目根>/.env` | 配置文件路径，存在即自动读取 | 否 |
| `PORT` | `3001` | 监听端口 | 否 |
| `HOST` | `0.0.0.0` | 监听地址。裸机反代建议 `127.0.0.1` | 否 |
| `DATA_DIR` | `./data` | 数据目录，唯一需要持久化的目录 | 否 |
| `NODE_ENV` | 未设置 | 设为 `production` 才发送 HSTS | **是** |
| `TRUST_PROXY` | `1` | 信任的反代层数。一层 nginx 用 `1`，直连公网用 `false` | 否 |
| `JWT_SECRET` | 空（自动生成 `data/.jwt-secret`） | JWT 签名密钥，建议 64 位十六进制 | **是** |
| `ALLOWED_ORIGINS` | 空（允许所有来源） | CORS 白名单，逗号分隔；留空仅适合纯内网 | **是** |
| `SITE_NAME` | `笔记库` | 站点名，用于页面标题与 RSS | 否 |
| `SITE_DESCRIPTION` | `教程、笔记与代码示例，按项目归档。` | 站点描述 | 否 |
| `SITE_OWNER` | `coustea` | 唯一可建项目 / 导入的账号；设为空字符串 = 任意登录账号 | 否 |
| `SITE_URL` | 空（按请求头推断） | 站点根地址，用于 RSS / sitemap / robots 的绝对链接 | **是** |
| `DEFAULT_ADMIN_USERNAME` | `coustea` | 首次启动创建的管理员账号 | 否 |
| `DEFAULT_ADMIN_PASSWORD` | `coustea` | 首次启动创建的管理员密码，**生产必改** | **是** |
| `DEFAULT_ADMIN_DISPLAY_NAME` | `站长` | 管理员显示名 | 否 |
| `DISABLE_DEFAULT_ADMIN` | 未设置 | 设 `1` 跳过默认管理员创建 | 否 |
| `HOST_PORT` | `3001` | 仅 Docker Compose 用，宿主机映射端口 | 否 |

> `DEFAULT_ADMIN_*` 仅在库中不存在同名账号时生效；修改这些值不会影响已存在的账号（需用站内「修改密码」或改库脚本）。`ALLOWED_ORIGINS` 留空时 CORS 允许所有来源，只适合纯内网。

## 生产部署

推荐程度从高到低提供三条路径。无论走哪条，先准备好 `.env`：

```bash
cp .env.example .env
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
# 将输出的 64 位字符串填入 .env 的 JWT_SECRET=
chmod 600 .env
```

`NODE_ENV=production` 时，服务启动会执行一次**配置自检**，把最容易漏的项逐条打印：`JWT_SECRET` / `SITE_URL` / `ALLOWED_ORIGINS` / `TRUST_PROXY` / `DEFAULT_ADMIN_PASSWORD`。全部就绪时只输出一行 `生产自检通过`；有遗漏则输出编号清单，改完重启即可。自检**只提醒、不阻止启动**，方便先跑起来再补配置。

### 路径一：裸机 + systemd + nginx（推荐）

适合长期运行的 VPS。进程由 systemd 托管，nginx 负责 TLS 与反代，升级即 `git pull` + 重新构建。

```bash
# 1. 安装 Node 20 与 nginx
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs nginx git
node -v                                  # 确认 >= v20

# 2. 建专用运行用户
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
sudo cp .env.example /opt/md-notes/.env
sudo nano /opt/md-notes/.env
#   必改：DEFAULT_ADMIN_PASSWORD、JWT_SECRET、SITE_URL、ALLOWED_ORIGINS
#   建议：HOST=127.0.0.1（只让本机 nginx 访问）
sudo chown notes:notes /opt/md-notes/.env
sudo chmod 600 /opt/md-notes/.env

# 6. 安装并启动 systemd 服务
sudo cp deploy/md-notes.service /etc/systemd/system/md-notes.service
sudo systemctl daemon-reload
sudo systemctl enable --now md-notes
systemctl status md-notes
curl -fsS http://127.0.0.1:3001/api/healthz && echo   # 期望 {"ok":true,"uptime":N}

# 7. 先用 HTTP 配置申请证书
sudo mkdir -p /var/www/certbot
sudo cp deploy/nginx-bootstrap.conf /etc/nginx/conf.d/md-notes.conf
sudo sed -i 's/notes.example.com/你的域名/g' /etc/nginx/conf.d/md-notes.conf
sudo nginx -t && sudo systemctl reload nginx
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot certonly --webroot -w /var/www/certbot -d 你的域名

# 8. 启用 HTTPS 反代
sudo cp deploy/nginx.conf /etc/nginx/conf.d/md-notes.conf
sudo sed -i 's/notes.example.com/你的域名/g' /etc/nginx/conf.d/md-notes.conf
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl list-timers | grep certbot

# 9. 配置备份 cron（每天 3:10）
sudo chmod +x /opt/md-notes/deploy/backup.sh
sudo mkdir -p /var/backups/md-notes && sudo chown notes:notes /var/backups/md-notes
sudo chmod 700 /var/backups/md-notes
sudo crontab -u notes -e
#   写入：
#   10 3 * * * /opt/md-notes/deploy/backup.sh >> /var/log/md-notes-backup.log 2>&1
```

`deploy/md-notes.service` 已开启 `ProtectSystem=strict`、`ProtectHome=true`、`NoNewPrivileges=true`、`PrivateTmp=true` 等加固项，并将 `/opt/md-notes/data` 设为唯一可写路径。注意其默认使用 `/usr/bin/node`；若用 nvm 安装 Node，请用 `which node` 查得真实路径后修改 `ExecStart`（systemd 不读取用户 PATH）。

### 路径二：Docker Compose

适合已有 Docker 的机器，或与其他服务同机运行。

```bash
cp .env.example .env
nano .env        # 必改 DEFAULT_ADMIN_PASSWORD / JWT_SECRET / SITE_URL
                 # Docker 下 HOST 保持 0.0.0.0，DATA_DIR 由 compose 强制为 /app/data

docker compose up -d --build
docker compose ps                  # 等待 STATUS 出现 (healthy)
docker compose logs -f
curl -fsS http://127.0.0.1:3001/api/healthz && echo
```

镜像构建顺序：**阶段一 `builder`**（`node:20-bookworm-slim` + `python3/make/g++` + `npm ci` + `npm run build`）产出 `dist/`；**阶段二 `runtime`**（同为 `node:20-bookworm-slim`）只安装生产依赖，`dist/` 从 builder 阶段拷入，`server/` 从构建上下文拷入，最后 `USER node` + `HEALTHCHECK` + `STOPSIGNAL SIGTERM`。两个阶段锁定同一 Node 主版本，保证 better-sqlite3 原生 ABI 一致。

**常用运维命令：**

```bash
docker compose restart             # 重启，走优雅退出
docker compose down                # 停止并删除容器，命名卷 md-notes-data 保留
docker compose up -d --build       # 升级：重新构建并滚动替换
docker volume ls | grep md-notes   # 确认数据卷仍在
```

更新代码后**必须加 `--build`**，否则 compose 会复用旧镜像。`docker compose down` 默认**不**删除命名卷，但 `down -v` 会，请勿随手加 `-v`。

**Docker 备份**：镜像不含 `deploy/`（已在 `.dockerignore` 排除），用一次性容器挂载数据卷与脚本运行。镜像以 `node`（uid 1000）运行，宿主机备份目录需对其可写：

```bash
sudo mkdir -p /var/backups/md-notes
sudo chown 1000:1000 /var/backups/md-notes
sudo chmod 700 /var/backups/md-notes

docker run --rm \
  -v md-notes-data:/data \
  -v /var/backups/md-notes:/backup \
  -v /opt/md-notes/deploy:/deploy:ro \
  -e APP_DIR=/app -e DATA_DIR=/data -e BACKUP_DIR=/backup \
  --entrypoint bash \
  md-notes:latest /deploy/backup.sh
```

cron 中将上述命令写成一行即可。若觉繁琐，可将 compose 命名卷换成 bind mount（`./data:/app/data`），宿主机上的 `deploy/backup.sh` 即可直接对 `./data` 运行，无需进容器。

### 路径三：仅内网 / 本机

无需 nginx、无需 Docker：

```bash
npm ci
npm run build
cp .env.example .env
# 内网简化：HOST=0.0.0.0、SITE_URL=http://192.168.1.10:3001、TRUST_PROXY=false
node server/index.js
```

要点：

- **无反代时务必设 `TRUST_PROXY=false`**。默认值 `1` 表示信任一层代理，直连公网时客户端可伪造 `X-Forwarded-For` 绕过登录限流。
- `SITE_URL` 写成内网可访问的完整地址（如 `http://192.168.1.10:3001`），否则 RSS / sitemap 链接会出错。
- 需开机自启可用 `deploy/md-notes.service`，将 `HOST` 改为 `0.0.0.0`、`SITE_URL` 改为内网地址。

### 生产部署检查清单

上线前逐条确认，任何遗漏都可能被扫描脚本利用：

- [ ] **修改默认密码**：`DEFAULT_ADMIN_PASSWORD` 改为 16 位以上随机串，或启动建号后立即在站内改密。
- [ ] **设置 `JWT_SECRET`**：勿依赖自动生成的 `data/.jwt-secret`，否则迁移 / 重建卷时所有登录失效。
- [ ] **设置 `SITE_URL`**：写成 `https://你的域名`（带协议、结尾不带斜杠）。
- [ ] **设置 `ALLOWED_ORIGINS`**：填真实域名，不要留空。
- [ ] **设置 `NODE_ENV=production`**：否则不发送 HSTS。
- [ ] **`TRUST_PROXY` 与实际拓扑一致**：一层 nginx 用 `1`，直连公网用 `false`。
- [ ] **配置备份 cron** 并**实际恢复验证一次**。
- [ ] **启用 HTTPS** 并确认 certbot 自动续期定时器存在。
- [ ] **防火墙只开 80 / 443**：`sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable`，3001 不对公网开放。
- [ ] **`chmod 600 .env`**：内含数据库口令与 JWT 密钥。
- [ ] **`/api/healthz` 不对外**：`deploy/nginx.conf` 已限本机，若后续改过需复核。
- [ ] **确认 `data/` 属主**为运行用户（`notes` 或容器内 `node`），否则首次写入即失败。

## 接口一览

所有接口均在 `/api` 下，除公开读取外都需要 `Authorization: Bearer <token>`（登录接口返回，30 天有效）。写操作校验 `owner_id`，越权返回 403。

| 方法 | 路径 | 说明 | 需要登录 |
| --- | --- | --- | :---: |
| GET | `/api/healthz` | 健康检查，数据库异常时 503 | 否 |
| POST | `/api/auth/login` | 登录，返回 token 与 user；限流 20 次 / 10 分钟 | 否 |
| POST | `/api/auth/register` | 固定 403，本站不开放注册 | — |
| GET | `/api/auth/me` | 当前账号 | 是 |
| POST | `/api/auth/change-password` | 改密码（校验原密码，新密码 ≥ 6 位） | 是 |
| POST | `/api/ai/markdown` | 按页面提供的 API Key、模型、Base URL 与写作要求生成 Markdown；限流 30 次 / 小时 | 仅 coustea |
| GET | `/api/admin/notes` | 管理工作台文章列表，含草稿 | 仅 coustea |
| POST | `/api/admin/notes/batch` | 批量操作（publish / draft / trash） | 仅 coustea |
| GET | `/api/projects` | 项目列表（含 doc/folder 计数与前 4 个标签） | 否 |
| POST | `/api/projects` | 新建项目；仅站点所有者 | 是 |
| GET | `/api/projects/:id` | 项目详情 + 目录树 | 否 |
| PATCH | `/api/projects/:id` | 改名 / 描述 / 排序 / 发布状态 | 是 |
| DELETE | `/api/projects/:id` | 删除项目（连同全部节点，硬删） | 是 |
| POST | `/api/projects/from-folder` | 用上传的文件夹建项目；仅站点所有者 | 是 |
| POST | `/api/nodes` | 新建笔记 / 目录，可带 `dailyDate` | 是 |
| GET | `/api/nodes/:id` | 单篇笔记 | 否 |
| GET | `/api/nodes/:id/revisions` | 旧版本列表 | 是，仅作者 |
| GET | `/api/nodes/:id/revisions/:revisionId` | 读取旧版本正文 | 是，仅作者 |
| PATCH | `/api/nodes/:id` | 改标题 / 正文 / 标签 / 排序 / 状态 / `dailyDate` | 是 |
| POST | `/api/nodes/:id/move` | 移动或重排文件树，传 `parentId` 与 `beforeId`（末尾为 `null`） | 是 |
| DELETE | `/api/nodes/:id` | 进回收站；加 `?purge=1` 彻底删除 | 是 |
| GET | `/api/trash` | 回收站列表（只列顶层，附项目名与总数） | 是 |
| POST | `/api/trash/:id/restore` | 恢复（父目录已删则挂回根目录） | 是 |
| DELETE | `/api/trash/:id` | 彻底删除单条 | 是 |
| DELETE | `/api/trash?days=N` | 清空回收站，带 `days` 时只清理 N 天前的 | 是 |
| GET | `/api/daily?date=&days=` | 某学习日的笔记 + 打卡热力图（`days` 7–365，默认 120） | 否（未登录返回空） |
| POST | `/api/daily/new` | 在「每日学习」项目新建当天笔记，可带 `date` / `title` | 是 |
| POST | `/api/import` | 批量导入 md（单文件 2MB、总计 20MB、最多 300 个） | 是 |
| GET | `/api/search?q=` | 标题 / 正文 / 标签模糊搜索（空格多词取交集），返回摘要与 `terms` | 否 |
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

## 数据库与迁移

数据库为单个 SQLite 文件，位于 `DATA_DIR/notes.db`，采用 **WAL 模式**。表结构定义在 `server/db.js`，通过 `CREATE TABLE IF NOT EXISTS` 在启动时创建：

| 表 | 用途 |
| --- | --- |
| `users` | 账号（用户名、密码哈希、显示名） |
| `projects` | 项目（所有者、名称、slug、描述、发布状态、排序） |
| `nodes` | 笔记与目录树（父子关系、内容、标签、状态、软删除时间、学习日、来源路径） |
| `node_revisions` | 笔记的历史版本（正文 / 标题 / 标签快照） |
| `app_settings` | 应用配置（如保存在库中的 AI 配置） |

**关于迁移的重要说明：**

- 全新部署时，启动会自动创建完整表结构，无需任何操作。
- **本项目不提供自动的列级迁移**。`server/db.js` 仅使用 `CREATE TABLE IF NOT EXISTS`，不会对已存在的表执行 `ALTER TABLE` 添加新列。因此，若某个旧版本创建的数据库缺少当前表结构中的列，升级后不会自动补列。
- 若后续版本修改了表结构（新增列），从旧版本升级时需要**手动迁移**，并务必**先备份**。

**升级前请先备份**，然后查看 `git log -- server/db.js` 确认是否有表结构变更。若需手动补列：

```bash
# 1. 先备份！
sudo -u notes /opt/md-notes/deploy/backup.sh

# 2. 停服并查看当前表结构
sudo systemctl stop md-notes
sudo -u notes node -e "const D=require('/opt/md-notes/node_modules/better-sqlite3');const d=new D('/opt/md-notes/data/notes.db');console.log(d.prepare('PRAGMA table_info(nodes)').all());d.close()"

# 3. 按新版本 server/db.js 的定义补列（示例）
sudo -u notes node -e "const D=require('/opt/md-notes/node_modules/better-sqlite3');const d=new D('/opt/md-notes/data/notes.db');d.exec(\"ALTER TABLE nodes ADD COLUMN new_column TEXT NOT NULL DEFAULT ''\");d.close()"

# 4. 启动并用 PRAGMA table_info 复核
sudo systemctl start md-notes
```

## AI 辅助写作

AI 写作**仅允许 `coustea` 账号**配置与使用；其他账号看不到入口，直接调用接口也会被拒绝。服务器统一使用 **OpenAI 协议的 Chat Completions 接口**。

在「账户与系统设置」页可将模型配置保存进数据库（`app_settings` 表的 `ai_config`），编辑器中的「AI 辅助写作」会自动沿用，也可在编辑器里临时覆盖。**Base URL 留空**即使用 OpenAI 官方接口，也可填写任意 **HTTPS** 兼容地址。已内置对常见服务的适配：

| 服务 | Base URL | 模型示例 |
| --- | --- | --- |
| OpenAI | 留空或 `https://api.openai.com/v1` | `gpt-4o-mini` |
| 讯飞星火（星辰 MaaS） | `https://maas-api.cn-huabei-1.xf-yun.com/v2` | `spark-x2.6` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |

以下易踩的点已处理：

- 粘贴带 `/chat/completions` 的完整地址（讯飞官方文档即为此形式）会自动收敛为版本前缀，不会拼出 `/chat/completions/chat/completions` 的 404。
- 讯飞在 HTTP 200 中返回的非 0 业务码会被识别为错误并透出原因，不会误判为「模型未返回内容」。
- 思考型模型（如 `spark-x2.6` 默认开启 thinking）正文为空时，会回退读取 `reasoning_content`。

设置页提供「测试连接」按钮，用当前参数发送一次极小的真实请求，并回显实际请求地址与上游错误摘要。**生成结果需手动加入正文后再保存笔记。生产部署须使用 HTTPS，避免密钥在传输中暴露。**

## 备份与恢复

`deploy/backup.sh` 使用 better-sqlite3 的 `db.backup()` 做**一致性快照**，不依赖 `sqlite3` CLI，**可在服务运行时执行**。

```bash
# 手动运行一次
sudo -u notes /opt/md-notes/deploy/backup.sh

# 自定义参数
sudo -u notes BACKUP_DIR=/mnt/backup/md-notes KEEP_DAYS=30 /opt/md-notes/deploy/backup.sh

# 连 JWT 密钥一起打包（恢复后用户无需重新登录）
sudo -u notes INCLUDE_SECRET=1 /opt/md-notes/deploy/backup.sh
```

产物为 `md-notes-YYYYmmdd-HHMMSS.tar.gz` 及同名 `.sha256`，内含 `notes.db`、`uploads/`、`BACKUP_INFO.txt`（时间、主机、git commit、node 与 package 版本）。默认 `BACKUP_DIR=/var/backups/md-notes`，保留 `KEEP_DAYS=14` 天。

**为何不用 `cp notes.db`**：WAL 模式下主库文件可能缺失最近的事务，直接拷贝会得到「看似正常但少了最新内容」的库。`db.backup()` 走 SQLite 在线备份 API，在一个读事务内复制，写入不会让备份处于半事务状态；备份完成后脚本会立即对新库做 `PRAGMA integrity_check`。

`.jwt-secret` 默认不入备份。它仅是签名密钥、不含用户数据，唯一后果是恢复后所有已登录用户需重新登录；在意这一点请用 `INCLUDE_SECRET=1`。

**恢复步骤**（完整版见脚本头部注释）：

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

恢复后务必打开站点确认：首页有内容、能登录、附件图片正常显示。确认无误后再删除 `data.before-restore`。

> **备份放在同一块盘上等于没有备份。** 生产环境请将 `BACKUP_DIR` 指向另一块盘或挂载的远端存储（NFS、对象存储挂载等）。

## 运维脚本

### 清理孤儿附件

删除笔记（或删除正文中的图片语法）时，`uploads/` 中的文件不会随之消失——正文只存一个 Markdown 链接，服务端无法判断图片是否还有别处引用。日积月累附件目录会堆满无用图片，备份体积也随之增大。

```bash
# 先预演，查看将删除的内容（不会删任何文件）
sudo -u notes node /opt/md-notes/scripts/clean-orphan-uploads.js

# 确认无误后真删
sudo -u notes node /opt/md-notes/scripts/clean-orphan-uploads.js --apply

# 只删 30 天前无引用的，为「刚上传尚未插入正文」留出余地
sudo -u notes node /opt/md-notes/scripts/clean-orphan-uploads.js --apply --days 30
```

脚本会扫描**所有**笔记正文（含回收站），收集 `/api/uploads/<owner>/<file>` 形式的引用作为白名单，磁盘上不在白名单的即为孤儿。回收站中的笔记也算引用，因此恢复后图片仍在。可挂到备份 cron 后每月运行一次。

Docker 部署时脚本不在镜像中（`.dockerignore` 排除了 `scripts/`），用 `cp` 拷入：

```bash
docker compose cp scripts/clean-orphan-uploads.js md-notes:/tmp/clean.js
docker compose exec md-notes node /tmp/clean.js            # 预演
docker compose exec md-notes node /tmp/clean.js --apply    # 真删
```

### 重置密码

忘记密码时无需重装或手工拼 SQL。项目自带改密脚本，直接读取同一数据库：

```bash
cd /opt/md-notes
sudo -u notes node scripts/reset-password.js --list                       # 查看账号
sudo -u notes node scripts/reset-password.js coustea '新密码至少6位'      # 改密
# 或：sudo -u notes npm run reset-password -- coustea '新密码'
```

Docker 部署时同样需 `cp` 拷入：

```bash
docker compose cp scripts/reset-password.js md-notes:/tmp/reset.js
docker compose exec md-notes node /tmp/reset.js --list
docker compose exec md-notes node /tmp/reset.js coustea '新密码至少6位'
```

改密后旧 token 仍然有效。若需立即将其他设备踢下线，同时更换 `JWT_SECRET` 并重启服务。

## 测试

使用 Node 内置测试框架 `node:test`，需要 Node 20+。

```bash
npm test
```

包含两套集成测试：`tests/api.test.js`（主流程接口）与 `tests/extra.test.js`（每日学习 / 回收站 / 用户隔离）。AI 相关用例由 `tests/mock-ai-fetch.js` 拦截假域名并模拟 OpenAI、星火、星火错误码、DeepSeek 四类上游，不依赖真实密钥。

## 常见问题

**端口被占用：`Error: listen EADDRINUSE: address already in use 0.0.0.0:3001`**

```bash
sudo ss -ltnp | grep 3001        # 找出占用进程
sudo systemctl stop md-notes     # 若是它自己
# 或改端口：.env 中设 PORT=3002，并同步修改 nginx 的 proxy_pass
```

常见原因是重复启动了服务，或上次 `npm run dev` 未关闭。

**忘记密码，登不进去了**

使用[重置密码脚本](#重置密码)，无需重装。

**better-sqlite3 编译失败**

通常是 `node-gyp` 找不到 python / make / g++，或 `NODE_MODULE_VERSION` 不匹配。

```bash
sudo apt-get install -y python3 make g++
sudo npm rebuild better-sqlite3        # 更换 Node 大版本后必须执行
# 或彻底重装：sudo rm -rf node_modules && sudo npm ci
```

`NODE_MODULE_VERSION` 不匹配指 `node_modules` 中的 `.node` 文件为其他 Node 大版本编译。构建镜像与运行镜像须同为 Node 20；裸机更换 Node 版本后必须 `npm rebuild better-sqlite3`，用 nvm 切换版本后亦然。

**反代后 RSS / sitemap 里的链接是 http**

按顺序排查：

1. `.env` 未设 `SITE_URL`。设为 `https://你的域名` 即可彻底解决，无需依赖请求头推断。
2. nginx 未传 `X-Forwarded-Proto`。确认 `deploy/nginx.conf` 中 `proxy_set_header X-Forwarded-Proto $scheme;` 仍在。
3. `TRUST_PROXY` 设为 `false`。此时 Express 忽略 `X-Forwarded-*`，`req.protocol` 恒为 `http`。

验证：

```bash
curl -s https://你的域名/rss.xml | head -20
curl -s https://你的域名/robots.txt
```

**上传返回 413**

413 是 nginx 在应用之前拒绝，说明超过 `client_max_body_size`。当前配置为 `25m`，足够 10MB 附件（base64 后约 13.3MB）与 20MB 文件夹导入。确属合理需求再调大：

```nginx
client_max_body_size 50m;
sudo nginx -t && sudo systemctl reload nginx
```

若 nginx 未拦截（直连 3001 或反代配了更大值），应用自身也会返回 413 并提示「请求体过大，单次请求上限 24MB」——这是 `express.json({ limit: '24mb' })` 的上限，需同时调大。若应用返回 400 并提示「文件不能超过 10MB」，则为应用侧硬限制，只能压缩文件；上传接口仅接受 PNG / JPEG / GIF / WebP / PDF。

**请求返回 400「请求体不是合法的 JSON」**

应用解析请求体失败，通常是脚本或第三方工具发出的正文非合法 JSON（尾逗号、缺引号、把表单数据当 JSON 发送）。浏览器中的正常操作不会出现。

**触发限流**

- 登录：10 分钟内同 IP 最多 20 次，超过返回 `尝试次数过多，请稍后再试`。
- 上传：1 小时内同 IP 最多 120 次。

反代后若所有人被当作同一 IP，说明 nginx 未传真实 IP 或 `TRUST_PROXY` 配置错误：前者检查 `X-Real-IP` / `X-Forwarded-For`，后者确认层数与拓扑一致。直连公网时 `TRUST_PROXY` 必须为 `false`，否则限流可被伪造请求头绕过。

**页面 404 但 API 正常**

`dist/` 不存在或未构建。服务端仅在 `dist/index.html` 存在时才托管前端，否则只提供 API（生产启动日志会打印提示）。

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

常见原因是 `data/` 权限不对（容器内为 `node` 用户，uid 1000），或数据库文件被 root 拥有导致打不开。使用命名卷通常无此问题；换成 bind mount 需 `sudo chown -R 1000:1000 ./data`。

**数据目录权限错误：`SQLITE_CANTOPEN` / `EACCES`**

服务以 `notes`（裸机）或 `node`（容器）运行，`data/` 须对相应用户可写：

```bash
sudo chown -R notes:notes /opt/md-notes/data    # 裸机
sudo chown -R 1000:1000 ./data                  # Docker bind mount
```

## 许可证

本项目为自托管个人知识库，未指定开源许可证。未经授权请勿用于商业用途或公开分发。
