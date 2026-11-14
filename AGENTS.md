# AGENTS.md — FrameForge System Architecture & Engineering Guide

## 1. Project Overview

**FrameForge** is an AI educational video generation agent platform tailored for Computer Science and software engineering explanations (algorithms, operating systems, networking, distributed systems, data structures). Given a natural-language prompt, an agentic workflow plans instructional storyboards, generates modular **Hyperframes** HTML/CSS/JS/GSAP animation code, runs static checks and deterministic headless rendering via **Hyperframes + FFmpeg**, repairs errors automatically from execution logs, and outputs playable MP4 videos with scene-level partial editing.

### Core Tech Stack
- **API & Async Service**: Python 3.12+, FastAPI (`0.162+`), Pydantic v2, Uvicorn, `asyncer`
- **Agent Orchestration**: LangGraph (`StateGraph` + ReAct repair subgraph), LangChain
- **Video Compilation**: Hyperframes (`npx hyperframes render`, headless Chromium + FFmpeg)
- **Persistence & Caching**: MySQL 8.0 (`InnoDB`, `utf8mb4_unicode_ci`) via `SQLModel` + `aiomysql` + `Alembic`; Redis 7+ (task queue, SSE Pub/Sub, JWT JTI revocation cache)
- **Auth & Security**: PyJWT (`HS256` access + refresh tokens), `pwdlib[argon2]`
- **Frontend (Planned Phase)**: React + TypeScript + Vite (not implemented in current backend-first phase)
- **Tooling**: `uv`, `ruff`, `pytest`, `pytest-asyncio`, Docker

---

## 2. Repository & Backend Layout

> **Implementation Status**: Currently **Phase 1** is implemented (`users` table in `backend/sql/schema.sql`, `User` model, Alembic + SQLModel automatic startup migration in `lifespan`, `JWTAuthMiddleware`, and `/api/v1/auth/{register,login,me}` + `/api/v1/health`). Modules marked `[Planned]` below represent the target architecture for upcoming phases.

```text
FrameForge/
├── AGENTS.md                        # System architecture & agent rules (this file)
├── .agents/skills/fastapi/          # Official FastAPI skill (installed via library-skills)
└── backend/
    ├── pyproject.toml               # uv dependencies, [tool.fastapi], [tool.ruff], [tool.pytest]
    ├── alembic.ini                  # Alembic config (SQLModel.metadata, async migrations)
    ├── alembic/                     # Migration scripts (auto-upgraded to head on app startup)
    ├── .env.example                 # Environment variable template
    ├── sql/
    │   └── schema.sql               # MySQL 8.0 DDL (currently Phase 1 `users` table)
    ├── app/
    │   ├── main.py                  # FastAPI app factory, lifespan (auto-migrate), CORS & JWT middleware
    │   ├── core/
    │   │   ├── config.py            # pydantic-settings configuration (mysql/redis/auto_migrate)
    │   │   ├── database.py          # AsyncEngine, async_sessionmaker, get_session(), init_database()
    │   │   ├── redis.py             # Async Redis client pool, init_redis(), get_redis()
    │   │   ├── security.py          # Argon2 hashing (pwdlib), JWT encode/decode (PyJWT)
    │   │   └── exceptions.py        # Domain error classes & FastAPI exception handlers
    │   ├── middleware/
    │   │   └── jwt_auth.py          # Pure ASGI JWTAuthMiddleware (Bearer check & state injection)
    │   ├── models/
    │   │   └── user.py              # User SQLModel table
    │   ├── schemas/
    │   │   └── auth.py              # RegisterRequest, LoginRequest, TokenResponse, UserPublic
    │   ├── api/
    │   │   ├── deps.py              # Annotated Depends aliases (SettingsDep, SessionDep, CurrentUserDep)
    │   │   └── v1/
    │   │       ├── health.py        # Liveness probe (/api/v1/health)
    │   │       ├── auth.py          # Register, Login, Me (/api/v1/auth/*)
    │   │       ├── projects.py      # [Planned] Video project & scene CRUD / partial edit
    │   │       └── tasks.py         # [Planned] Task status, SSE progress stream, artifacts
    │   ├── services/
    │   │   └── auth.py              # User registration, credential check, JWT issuance
    │   ├── agent/                   # [Planned] LangGraph workflow & Agent Harness
    │   └── worker/                  # [Planned] Redis queue consumer & Hyperframes CLI runner
    └── tests/                       # pytest + httpx ASGITransport async tests
```

---

## 3. Database Schema Design (MySQL 8.0)

Phase 1 implements the `users` table in `backend/sql/schema.sql` and `backend/app/models/user.py`. The remaining tables below define the planned schema for video projects, scene-level versioning, async tasks, and LangGraph audit logs. All tables use `InnoDB`, `utf8mb4_unicode_ci`, explicit foreign keys, and UTC `DATETIME(6)` timestamps.

### 3.1 Identity & Auth Tables
1. **`users`** *(Implemented)*
   - Columns: `id` (PK BIGINT AI), `username` (UNIQUE VARCHAR(64)), `email` (UNIQUE VARCHAR(255)), `password_hash` (VARCHAR(255)), `display_name` (VARCHAR(100)), `avatar_url` (VARCHAR(512)), `role` (`user`/`admin`), `is_active` (BOOLEAN), `last_login_at`, `created_at`, `updated_at`.
2. **`refresh_tokens`** *(Planned)*
   - Enables stateful refresh-token rotation and immediate revocation.
   - Columns: `id` (PK BIGINT AI), `user_id` (FK -> `users.id`), `jti` (UNIQUE CHAR(36)), `token_hash` (CHAR(64) SHA-256), `expires_at`, `revoked_at` (nullable), `user_agent` (VARCHAR(255)), `ip_address` (VARCHAR(64)), `created_at`.
   - Indexes: `idx_refresh_user_revoked (user_id, revoked_at)`, `idx_refresh_expires (expires_at)`.

### 3.2 Video Project & Scene-Level Versioning Tables
3. **`video_projects`**
   - Top-level project container & workspace anchor.
   - Columns: `id` (PK BIGINT AI), `user_id` (FK -> `users.id`), `title` (VARCHAR(200)), `prompt` (TEXT), `target_audience` (VARCHAR(100)), `aspect_ratio` (`16:9`/`9:16`), `fps` (INT, default 30), `duration_sec` (DECIMAL(8,2)), `status` (`draft`/`planning`/`generating`/`rendering`/`completed`/`failed`), `workspace_path` (VARCHAR(512)), `current_manifest_json` (JSON), `latest_video_artifact_id` (BIGINT nullable), `created_at`, `updated_at`.
4. **`project_scenes`**
   - Atomic storyboard + code unit supporting **scene-level partial modification**.
   - Columns: `id` (PK BIGINT AI), `project_id` (FK -> `video_projects.id`), `scene_index` (INT), `scene_key` (VARCHAR(64), e.g. `scene_01_bplus_tree`), `title` (VARCHAR(200)), `narration_script` (TEXT), `visual_spec_json` (JSON), `start_sec` (DECIMAL(8,2)), `duration_sec` (DECIMAL(8,2)), `entry_file` (VARCHAR(255), e.g. `scenes/scene_01_bplus_tree/index.html`), `status` (`pending`/`generated`/`checked`/`error`), `current_revision_id` (BIGINT nullable), `created_at`, `updated_at`.
   - Unique Constraints: `(project_id, scene_key)`, `(project_id, scene_index)`.
5. **`scene_revisions`**
   - Immutable code snapshot per scene for diffing, audit, and safe rollback.
   - Columns: `id` (PK BIGINT AI), `scene_id` (FK -> `project_scenes.id`), `revision_no` (INT), `code_snapshot_json` (JSON mapping relative paths -> file contents), `content_hash` (CHAR(64)), `edit_instruction` (TEXT nullable), `source` (`ai_initial`/`ai_repair`/`user_partial_edit`), `created_by_task_id` (BIGINT nullable), `created_at`.
   - Unique Constraint: `(scene_id, revision_no)`.

### 3.3 Async Tasks, SSE Events, Agent Audit & Artifacts
6. **`generation_tasks`**
   - Tracks full-generation, partial-scene-edit, and rerender jobs dispatched via Redis.
   - Columns: `id` (PK BIGINT AI), `project_id` (FK), `user_id` (FK), `target_scene_id` (FK -> `project_scenes.id` nullable; non-null indicates partial scene edit), `task_type` (`full_generate`/`partial_edit`/`rerender`), `user_instruction` (TEXT), `status` (`queued`/`running`/`succeeded`/`failed`/`cancelled`), `current_stage` (`planner`/`coder`/`checker`/`repairer`/`renderer`), `progress_pct` (TINYINT UNSIGNED), `retry_count` (INT), `max_retries` (INT), `error_message` (TEXT nullable), `started_at`, `finished_at`, `created_at`, `updated_at`.
7. **`task_events`**
   - Durable SSE event stream backing `Last-Event-ID` replay upon client reconnection.
   - Columns: `id` (PK BIGINT AI, serves as SSE `id`), `task_id` (FK -> `generation_tasks.id`), `event_type` (`stage_change`/`agent_thought`/`tool_call`/`check_error`/`render_progress`/`completed`/`failed`), `stage` (VARCHAR(32)), `payload_json` (JSON), `created_at`.
   - Index: `idx_task_events_task_id (task_id, id)`.
8. **`agent_runs`**
   - Records each LangGraph node / ReAct repair invocation and token/tool budgets.
   - Columns: `id` (PK BIGINT AI), `task_id` (FK), `graph_thread_id` (VARCHAR(128)), `node_name` (VARCHAR(64)), `model_name` (VARCHAR(100)), `attempt_no` (INT), `tool_calls_used` (INT), `max_tool_calls` (INT), `prompt_tokens` (INT), `completion_tokens` (INT), `status` (`running`/`completed`/`budget_exceeded`/`failed`), `error_summary` (TEXT nullable), `started_at`, `finished_at`.
9. **`agent_tool_calls`**
   - Fine-grained audit log for every Agent Harness tool call.
   - Columns: `id` (PK BIGINT AI), `agent_run_id` (FK -> `agent_runs.id`), `step_index` (INT), `tool_name` (`read_file`/`write_file`/`edit_file`/`restricted_shell`/`load_skill`), `arguments_json` (JSON), `result_summary` (TEXT), `is_error` (BOOLEAN), `duration_ms` (INT), `created_at`.
10. **`render_artifacts`**
    - Tracks generated MP4, thumbnail, preview HTML bundle, and render log files.
    - Columns: `id` (PK BIGINT AI), `project_id` (FK), `task_id` (FK), `artifact_type` (`mp4`/`thumbnail`/`preview_html`/`render_log`), `storage_path` (VARCHAR(512)), `file_size_bytes` (BIGINT), `duration_sec` (DECIMAL(8,2) nullable), `resolution` (VARCHAR(32) nullable), `checksum_sha256` (CHAR(64) nullable), `created_at`.

---

## 4. LangGraph Workflow & Lightweight Agent Harness

### 4.1 Deterministic Workflow + ReAct Repair Loop
The LangGraph `StateGraph` combines deterministic stage transitions with bounded ReAct self-repair:

1. **`planner` (Deterministic Structured Output)**:
   - Analyzes user prompt & CS domain; outputs ordered storyboard scenes (`scene_key`, `title`, `narration_script`, `duration_sec`, `visual_spec`), persisted into `project_scenes`.
   - For `partial_edit` tasks (`target_scene_id != None`), skips full planning and builds a targeted edit plan for only that scene.
2. **`coder` (Scene Code Generator)**:
   - Generates self-contained Hyperframes scene files (`index.html`, `scene.css`, `scene.js` using GSAP/SVG/Canvas) inside `workspaces/<project_id>/scenes/<scene_key>/` and updates the root composition manifest.
3. **`checker` (Static & Structural Validator)**:
   - Runs HTML/JS syntax validation (`node --check`), Hyperframes timeline attribute checks (`data-start`, `data-duration`), asset reference verification, and optional headless DOM smoke check.
   - Routes to `renderer` if clean; otherwise routes to `repairer` with structured diagnostics (up to `max_retries`).
4. **`repairer` (ReAct Agent Subgraph)**:
   - Uses the Agent Harness tools (`read_file`, `edit_file`, `write_file`, `restricted_shell`, `load_skill`) to inspect error logs, locate failing lines, apply minimal patches, and re-verify before handing back to `checker` or `renderer`.
5. **`renderer` (Hyperframes + FFmpeg Compiler)**:
   - Executes `npx hyperframes render --output artifacts/output_<task_id>.mp4` inside the isolated project workspace.
   - If rendering fails, extracts stderr/frame errors and routes back to `repairer` (if `retry_count < max_retries`), else marks task failed.

### 4.2 Agent Harness Safety & Controls
- **Workspace Isolation**: Every project maps to `<WORKSPACE_ROOT>/<project_id>/`. All file tools canonicalize paths (`Path.resolve()`) and reject any path escaping the project root (or escaping `scenes/<target_scene_key>/` during partial edits).
- **Restricted Shell**: Executes via `subprocess` with `shell=False`, strict command allowlist (`node`, `npx hyperframes`, `ffmpeg`), sanitized environment variables, and per-command timeout.
- **On-Demand Skills**: CS animation & Hyperframes authoring guides (e.g., array/tree/graph animations, code highlighting, timing synchronization) are stored as markdown skill packs and loaded only when requested via `load_skill(skill_name)`.
- **Budget Control**: Every `agent_run` enforces `max_tool_calls` (e.g., 15) and token/time caps, recording each step in `agent_tool_calls`.

---

## 5. Scene-Level Code Organization & Partial Modification

Inside `workspaces/<project_id>/`:
```text
workspaces/<project_id>/
├── composition.json          # Master timeline manifest (fps, resolution, ordered scene list)
├── index.html                # Root Hyperframes composition embedding scene modules/iframes
├── shared/                   # Shared CSS variables, CS typography, dark-theme tokens
├── scenes/
│   ├── scene_01_intro/
│   │   ├── index.html        # data-start="0" data-duration="6"
│   │   ├── style.css
│   │   └── anim.js           # GSAP timeline scoped to this scene
│   └── scene_02_algorithm/
│       └── ...
└── artifacts/
    └── output_<task_id>.mp4
```
- **Partial Modification Flow**: When a user submits a change request for `scene_id` (e.g., *"Slow down the red-black tree rotation in Scene 3 and highlight node X"*), the API creates a `partial_edit` task with `target_scene_id`. The Agent Harness restricts writes to `scenes/<scene_key>/` (and `composition.json` if duration changes), saves a new `scene_revisions` record (`source='user_partial_edit'`), validates, and re-renders the composition without regenerating untouched scenes.

---

## 6. Async Task Service & SSE Progress Streaming

1. **Task Submission**: `POST /api/v1/projects/{id}/generate` (or `POST /api/v1/scenes/{id}/edit`) inserts a `generation_tasks` row (`status='queued'`) and pushes `task_id` to Redis list/stream `frameforge:tasks:queue`.
2. **Worker Execution**: Background worker consumes `task_id`, drives LangGraph execution, writes durable records to `task_events`, and publishes JSON payloads to Redis Pub/Sub channel `frameforge:tasks:events:{task_id}`.
3. **SSE Endpoint**: `GET /api/v1/tasks/{task_id}/events` uses FastAPI's native `response_class=EventSourceResponse` (`fastapi.sse`) yielding `ServerSentEvent(id=str(event.id), event=event.event_type, data=event.payload_json)`.
   - Supports `Last-Event-ID` header: replays missed rows from MySQL `task_events WHERE task_id = :id AND id > :last_id` before subscribing to live Redis Pub/Sub messages, closing cleanly on `completed`/`failed`.

---

## 7. Authentication & JWT Middleware Architecture

- **Password Hashing**: `pwdlib` with `Argon2Hasher` (never store plaintext or legacy SHA/MD5).
- **JWT Tokens (`PyJWT`)**:
  - **Access Token**: Signed `HS256` token (default 60 min), claims `{sub, jti, type="access", role, iat, exp}`.
- **ASGI JWT Middleware (`app/middleware/jwt_auth.py`)**:
  - Intercepts HTTP requests before route handlers, skips public endpoints (`/api/v1/health`, `/api/v1/auth/register`, `/api/v1/auth/login`, `/docs`, `/redoc`, `/openapi.json`) and `OPTIONS` preflight requests.
  - Validates `Authorization: Bearer <token>`, verifies signature/expiration/type, injects `request.state.user_id` and `request.state.jwt_claims`, and rejects unauthorized requests with `401 Unauthorized`.
- **Planned Auth Extensions**: Stateful `refresh_tokens` rotation and Redis JTI revocation cache (`frameforge:auth:revoked:{jti}`) on logout.

---

## 8. FastAPI & Python Development Rules

This repository includes the official FastAPI skill at `.agents/skills/fastapi/SKILL.md`. All backend code MUST follow these rules:
1. **Dependencies**: Always use `Annotated[Type, Depends(...)]` and define reusable type aliases in `app/api/deps.py` (e.g., `SessionDep`, `RedisDep`, `CurrentUserDep`).
2. **Pydantic Models & Params**: Never use `...` (Ellipsis) for required fields or `Query`/`Path`/`Body` parameters; never use `RootModel`.
3. **Routers**: Define `prefix`, `tags`, and shared `dependencies` directly on `APIRouter(...)` rather than inside `app.include_router()`. One HTTP method per endpoint function.
4. **Responses**: Declare explicit return type annotations on endpoints (or `response_model` when filtering internal/ORM models to public schemas). Never use `ORJSONResponse` or `UJSONResponse`.
5. **Database**: Prefer `SQLModel` with `AsyncSession` (`sqlmodel.ext.asyncio.session.AsyncSession`). Wrap sync/blocking subprocess or CPU work with `asyncer.asyncify()` when called from async code.
6. **SSE Streaming**: Use `response_class=EventSourceResponse` and `ServerSentEvent` from `fastapi.sse` with `yield`.
7. **Tooling & Testing**: Manage packages with `uv`, lint/format with `ruff`, and test endpoints with `pytest` + `httpx.AsyncClient` (`ASGITransport`). Never commit `.env` secrets.
