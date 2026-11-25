# md-notes 生产镜像
# 构建：docker build -t md-notes:latest .
# 运行：docker compose up -d   （或 docker run -p 3001:3001 -v md-notes-data:/app/data --env-file .env md-notes:latest）
#
# 关键点：
# 1. builder 与 runtime 都用 node:20-bookworm-slim，保证 better-sqlite3 的 ABI（NODE_MODULE_VERSION）一致。
# 2. better-sqlite3 是原生模块，两个阶段都准备 python3/make/g++，没有预编译包时也能现场编译。
# 3. runtime 阶段用 npm ci --omit=dev 只装生产依赖，编译工具在同一个 RUN 层里装完即删，不落进最终镜像。

# syntax=docker/dockerfile:1

############################################################
# 阶段一：builder，装全量依赖并构建前端 dist/
############################################################
FROM node:20-bookworm-slim AS builder

WORKDIR /app

# better-sqlite3 在没有匹配的预编译产物时需要 node-gyp 现场编译
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 make g++ \
 && rm -rf /var/lib/apt/lists/*

# 先只拷贝依赖清单：源码改动不会让 docker 重新下载依赖
COPY package.json package-lock.json ./

# 用 ci 而不是 install，严格按 lock 文件安装，结果可复现
RUN npm ci

# 构建前端：npm run build = tsc -p tsconfig.json && vite build，产出 /app/dist
# public/ 必须一起拷：vite 会把里面的 theme-init.js、favicon.svg 原样搬到 dist/，
# 漏掉的话镜像里就没有首屏主题脚本（会闪一下白）和站点图标。
COPY tsconfig.json vite.config.ts index.html ./
COPY public ./public
COPY src ./src
RUN npm run build

############################################################
# 阶段二：runtime，最小可运行镜像
############################################################
FROM node:20-bookworm-slim AS runtime

WORKDIR /app

# 运行期基础配置。NODE_ENV 故意放到下面依赖安装之后设置，
# 避免 npm 在安装原生模块时按生产模式跳过 postinstall 编译步骤。
ENV PORT=3001 \
    HOST=0.0.0.0 \
    DATA_DIR=/app/data

COPY package.json package-lock.json ./

# 只装生产依赖。编译工具在同一个 RUN 里安装、用完立即 purge，
# 这样 python3/make/g++ 不会留在最终镜像的层里。
RUN apt-get update \
 && apt-get install -y --no-install-recommends python3 make g++ \
 && npm ci --omit=dev \
 && npm cache clean --force \
 && apt-get purge -y --auto-remove python3 make g++ \
 && rm -rf /var/lib/apt/lists/*

# 应用代码从构建上下文拷贝（.dockerignore 已排除 tests/、src/、.git、data/ 等）
COPY --chown=node:node server ./server

# 前端产物必须从 builder 阶段拷贝，不能 COPY dist ./dist：
# .dockerignore 排除了 dist，构建上下文里根本没有这个目录，那样写会直接构建失败。
COPY --from=builder --chown=node:node /app/dist ./dist

# 数据目录必须由 node 用户可写：notes.db、WAL、uploads/、.jwt-secret 都在这里
RUN mkdir -p /app/data \
 && chown node:node /app/data

ENV NODE_ENV=production

USER node

EXPOSE 3001

# 先给 SIGTERM，让 server/index.js 走优雅退出（关 server、checkpoint WAL、最多等 10 秒），
# docker stop / compose down 请留 >= 15 秒，compose 里已配 stop_grace_period: 20s。
STOPSIGNAL SIGTERM

# 健康检查只用 Node 内置 fetch，不依赖 curl/wget（slim 镜像里也没有）。
# 数据库异常时 /api/healthz 返回 503，这里按非 2xx 判失败。
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD node -e "fetch('http://127.0.0.1:' + (process.env.PORT || 3001) + '/api/healthz').then((r) => { if (!r.ok) process.exit(1); return r.json() }).then((j) => process.exit(j && j.ok ? 0 : 1)).catch(() => process.exit(1))"

CMD ["node", "server/index.js"]
