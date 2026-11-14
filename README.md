# FrameForge

面向计算机科学与软件工程知识点讲解的 AI 教育视频生成平台后端服务。

> **当前实现阶段**：已完成配置体系、MySQL/Redis 基础设施初始化、ASGI JWT 鉴权中间件、4 张核心数据表（`users`、`projects`、`messages`、`tasks`）的基础 CRUD 接口，以及基于 `deepagents` 的 Agent 基础构建模块（`build_agent`）。多阶段 LangGraph 工作流、异步任务队列与 Hyperframes 视频渲染流水线将在后续阶段接入。

---

## 技术栈

| 类别 | 技术选型 |
|---|---|
| 语言与包管理 | Python 3.12、`uv` |
| Web 框架 | FastAPI、Pydantic v2、Uvicorn |
| 数据持久化 | MySQL 8.0+、`SQLModel`、`aiomysql`（手工维护 DDL） |
| 缓存 / 基础设施 | Redis（`redis.asyncio`） |
| 身份认证 | PyJWT（`HS256` Access + Refresh 双令牌）、`pwdlib[argon2]` |
| Agent 基础层 | `deepagents`、`langchain`、`langchain-openai`、`langchain-tavily`、`langgraph` |
| 代码规范与测试 | `ruff`、`pytest`、`pytest-asyncio`、`httpx`、`aiosqlite` |

---

## 目录结构

```text
FrameForge/
├── AGENTS.md                         # 系统架构与工程约定
├── GEMINI.md                         # Python 编码规范（Google 风格、KISS、中文注释）
├── README.md                         # 本说明文档
└── backend/
    ├── pyproject.toml                # 项目依赖与 ruff / pytest / fastapi 配置
    ├── uv.lock                       # 锁定依赖版本
    ├── .python-version               # Python 版本声明（3.12）
    ├── .env.example                  # 敏感环境变量模板
    ├── sql/
    │   └── schema.sql                # MySQL 8.0 建库与建表 DDL（users/projects/messages/tasks）
    ├── docs/
    │   └── HyperWeaver_后端架构与手动开发实现指南.md
    ├── workspaces/                   # Agent 项目工作区根目录（按配置解析）
    ├── app/
    │   ├── main.py                   # FastAPI 应用工厂、lifespan 与 Uvicorn 启动入口
    │   ├── config/
    │   │   ├── config.py             # Settings / AgentConfig / DatabaseConfig 加载与校验
    │   │   └── config.yaml           # 非敏感运行时配置（支持 ${VAR} 占位符）
    │   ├── core/
    │   │   ├── exceptions.py         # AppError / ConflictError / AuthenticationError / NotFoundError
    │   │   └── security.py           # Argon2 密码哈希与 JWT 签发/校验
    │   ├── db/
    │   │   ├── base.py               # 汇总 SQLModel target_metadata
    │   │   ├── mysql.py              # AsyncEngine、AsyncSession 工厂与依赖注入
    │   │   └── redis.py              # 异步 Redis 客户端初始化与依赖注入
    │   ├── middleware/
    │   │   └── jwt_auth.py           # 纯 ASGI JWTAuthMiddleware 鉴权中间件
    │   ├── models/
    │   │   ├── base.py               # 共享 UTC 时间函数
    │   │   ├── user.py               # User 表模型
    │   │   ├── project.py            # Project 表模型
    │   │   ├── message.py            # Message 表模型
    │   │   └── task.py               # Task 表模型
    │   ├── schemas/                  # Pydantic 请求/响应模型（auth/project/message/task）
    │   ├── services/                 # 纯异步业务与 CRUD 函数（auth/project/message/task）
    │   ├── api/
    │   │   ├── deps.py               # SessionDep / RedisDep / CurrentIdentityDep / CurrentUserDep
    │   │   └── v1/                   # auth / health / projects / messages / tasks 路由
    │   └── agent/
    │       ├── base.py               # Deep Agent 统一构建器 build_agent()
    │       └── skills/               # 共享 Skills 目录（对 Agent 映射为只读 /skills/）
    └── tests/
        ├── conftest.py               # SQLite 内存库与 FakeRedis 测试夹具
        ├── test_auth.py              # 认证、JWT 中间件、资料更新与改密测试
        ├── test_crud.py              # 项目/消息/任务 CRUD 与跨用户 404 隔离测试
        └── test_infra.py             # 配置加载、MySQL 初始化与 Redis 连通性测试
```

---

## 快速开始

### 1. 安装依赖

确保已安装 Python 3.12+ 与 [uv](https://docs.astral.sh/uv/)，以及本地可用的 MySQL 8.0+ 和 Redis：

```bash
cd backend
uv sync
```

### 2. 初始化数据库

本项目不在应用启动时自动建表或执行迁移，请先通过 SQL 脚本初始化数据库与 4 张表（`users`、`projects`、`messages`、`tasks`）：

```bash
mysql -u root -p < sql/schema.sql
```

### 3. 配置环境变量

复制模板文件并填入真实密钥：

```bash
cp .env.example .env
```

`backend/.env` 中支持的变量如下（与 `backend/app/config/config.yaml` 中的 `${VAR}` 占位符对应）：

| 变量名 | 用途 | 备注 |
|---|---|---|
| `JWT_SECRET_KEY` | JWT `HS256` 签名密钥 | 至少 32 字节 |
| `MYSQL_PASSWORD` | MySQL 连接密码 | 对应 `database.mysql.password` |
| `REDIS_PASSWORD` | Redis 连接密码 | 无密码时留空 |
| `OPENAI_API_KEY` | 大模型 API Key | 对应 `agent.llm.api_key` |
| `TAVILY_API_KEY` | Tavily 联网搜索 Key | 对应 `agent.tavily`（为空时不挂载搜索工具） |

其他应用端口、数据库连接池、LLM 参数及路径配置位于 `backend/app/config/config.yaml`：
- `agent.workspace_dir` 默认为 `./workspaces`（相对 `backend/` 自动解析为绝对路径）。
- `agent.skills_dir` 默认为 `./app/agent/skills`（相对 `backend/` 自动解析为绝对路径）。

### 4. 启动服务

在 `backend/` 目录下任选以下方式启动（默认监听 `0.0.0.0:8000`，当 `app.debug=true` 时开启 `backend/app` 热重载）：

```bash
# 方式一：直接运行脚本（也支持在 IDE 中直接 Run backend/app/main.py）
uv run python app/main.py

# 方式二：以模块方式运行
uv run python -m app.main

# 方式三：使用 FastAPI CLI（读取 pyproject.toml [tool.fastapi] entrypoint）
uv run fastapi dev
```

启动后可访问交互式接口文档：
- Swagger UI：`http://127.0.0.1:8000/docs`
- ReDoc：`http://127.0.0.1:8000/redoc`

---

## API 概览（`/api/v1`）

除公共探针、注册/登录/刷新令牌及文档路由外，其余接口均经 `JWTAuthMiddleware` 校验 `Authorization: Bearer <access_token>`。业务资源按当前用户 `user_id` 严格隔离，**访问不存在或不属于当前用户的资源统一返回 `404`**。

### 系统与认证

| 方法 | 路径 | 鉴权 | 说明 |
|---|---|---|---|
| `GET` | `/api/v1/health` | 公开 | 校验 MySQL（`SELECT 1`）与 Redis（`PING`）连通性 |
| `POST` | `/api/v1/auth/register` | 公开 | 注册新用户（Argon2 哈希存储密码），返回 `201` |
| `POST` | `/api/v1/auth/login` | 公开 | 支持用户名或邮箱登录，签发 Access/Refresh Token |
| `POST` | `/api/v1/auth/refresh` | 公开 | 使用 Refresh Token 换取新令牌对 |
| `GET` | `/api/v1/auth/me` | Bearer | 获取当前用户公开资料 |
| `PATCH` | `/api/v1/auth/me` | Bearer | 局部更新当前用户的 `display_name`、`avatar_url` |
| `POST` | `/api/v1/auth/change-password` | Bearer | 校验原密码后更新登录密码，返回 `204` |

### 项目（`projects`）

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/v1/projects` | 创建项目（返回 `201`） |
| `GET` | `/api/v1/projects` | 分页获取当前用户的项目列表（支持 `limit`、`offset`，按最近更新时间倒序） |
| `GET` | `/api/v1/projects/{project_id}` | 获取单个项目详情 |
| `PATCH` | `/api/v1/projects/{project_id}` | 更新项目 `title` 或 `current_revision` |
| `DELETE` | `/api/v1/projects/{project_id}` | 删除项目并级联清理下属消息与任务（返回 `204`） |

### 对话消息（`messages`）

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/v1/projects/{project_id}/messages` | 在项目下新增消息（`role`: `user` \| `assistant`、`content`、`metadata` JSON） |
| `GET` | `/api/v1/projects/{project_id}/messages` | 分页查询项目消息列表（支持 `limit`、`offset`，按消息 ID 升序） |
| `GET` | `/api/v1/messages/{message_id}` | 获取单条消息详情 |
| `PATCH` | `/api/v1/messages/{message_id}` | 更新消息文本 `content` 或 `metadata` |
| `DELETE` | `/api/v1/messages/{message_id}` | 删除单条消息，并将引用它的 `tasks.request_message_id` 置空（返回 `204`） |

### 任务（`tasks`）

| 方法 | 路径 | 说明 |
|---|---|---|
| `POST` | `/api/v1/projects/{project_id}/tasks` | 创建任务记录（`type`: `create` \| `edit`、可选绑定同项目 `request_message_id`、`base_revision`） |
| `GET` | `/api/v1/projects/{project_id}/tasks` | 分页查询项目下任务（支持按 `status` 筛选，按创建时间倒序） |
| `GET` | `/api/v1/tasks/{task_id}` | 获取单条任务详情 |
| `PATCH` | `/api/v1/tasks/{task_id}` | 更新任务 `status`、`phase`、`progress`、`result_revision`、`error_message`、`started_at`、`finished_at` |
| `DELETE` | `/api/v1/tasks/{task_id}` | 删除任务记录（返回 `204`） |

---

## Agent 基础模块

[backend/app/agent/base.py](backend/app/agent/base.py) 提供 `build_agent(system_prompt, workspace_dir=None)`：
- 使用 `config.yaml` 的 `agent.llm` 初始化 `ChatOpenAI`；
- 当配置了 `agent.tavily` 时挂载 `TavilySearch`；
- 通过 `CompositeBackend` 将 `agent.skills_dir` 映射为虚拟路径 `/skills/`，并配置 `FilesystemPermission` 禁止写操作；
- 传入 `workspace_dir` 时将其映射为可读写虚拟路径 `/workspace/`，同时挂载限定在该工作目录内执行的 `ShellToolMiddleware`。

---

## 代码检查与测试

在 `backend/` 目录下运行：

```bash
# 代码风格、导入顺序与 FastAPI 规则检查
uv run ruff check .

# 运行全部单元测试与集成测试
uv run pytest -v
```

测试说明：
- 接口与数据库测试使用 `aiosqlite` 内存/临时文件库与 `FakeRedis` 替身隔离外部数据；
- `tests/test_infra.py::test_local_redis_connection_ping` 会连接本地配置端口 `127.0.0.1:6379` 验证真实 Redis 连通性。

---

## 相关文档

- [AGENTS.md](AGENTS.md)：系统架构设计、LangGraph 与 Hyperframes 整体蓝图、FastAPI 开发约束
- [GEMINI.md](GEMINI.md)：代码风格、命名规范与中文文档字符串规范
- [HyperWeaver 后端架构与手动开发实现指南](backend/docs/HyperWeaver_%E5%90%8E%E7%AB%AF%E6%9E%B6%E6%9E%84%E4%B8%8E%E6%89%8B%E5%8A%A8%E5%BC%80%E5%8F%91%E5%AE%9E%E7%8E%B0%E6%8C%87%E5%8D%97.md)：后续 Agent 工作流与渲染器详细实现方案
