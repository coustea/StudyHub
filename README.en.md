# md-notes · Self-hosted Markdown Note Site

> A self-hosted Chinese Markdown note / tutorial site. Content is organized in three layers: **project → directory → note**. A local folder can be imported directly as a project, with built-in full-text search, RSS, sitemap, AI-assisted writing, and a daily study check-in. Suitable as a personal knowledge base or a published tutorial site.

**Single-process Node.js + a single SQLite file** — no external database, Redis, or object storage required. It runs on a small 1-core 1G machine with minimal deployment cost.

- Package / version: `md-notes-site` · `1.1.0`
- Requirements: **Node.js ≥ 20**
- Tech stack: React 18 + Vite 5 + Express 4 + better-sqlite3

## Table of Contents

- [Features](#features)
- [Tech Stack](#tech-stack)
- [Quick Start (Local Development)](#quick-start-local-development)
- [Directory Structure](#directory-structure)
- [Configuration (Environment Variables)](#configuration-environment-variables)
- [Production Deployment](#production-deployment)
- [API Reference](#api-reference)
- [Database and Migrations](#database-and-migrations)
- [AI-Assisted Writing](#ai-assisted-writing)
- [Backup and Restore](#backup-and-restore)
- [Operational Scripts](#operational-scripts)
- [Testing](#testing)
- [FAQ](#faq)
- [License](#license)

## Features

- **Today's Learning**: Record daily code notes by "learning day", with a check-in heatmap (last 364 days) + streak + cumulative check-ins. Start today's note in one click from the home page, or go back to past dates to make up notes.
- **Write Markdown Online**: In-site editor with dual write / side-by-side preview modes; a toolbar inserts headings, bold, inline code, links, and quotes. `Ctrl+S` to save, with a 3-second debounced local draft so a page closed by accident can be recovered; old versions are kept on save, and you can confirm and roll back from within the editor.
- **AI-Assisted Writing**: The editor can write, continue, or rewrite selected content according to your request. Generated results are checked first and added to the body manually. Compatible with OpenAI-protocol services such as OpenAI, iFlytek Spark, and DeepSeek.
- **Separated Reading and Management**: The public home page `/` only shows published projects and notes; after `coustea` logs in, the `/admin` workspace centrally manages projects, articles, and drafts.
- **Markdown Import**: An "Import md" action in the editor reads local files into the body; projects support whole-folder import, rebuilding multi-level directories from relative paths and reading front matter `title` / `tags` / `order` / `date`. Duplicate paths are skipped automatically and online edits are not overwritten.
- **Paste to Upload**: Screenshots can be pasted directly into the body with `Ctrl+V`, automatically uploaded as attachments, and Markdown image syntax inserted.
- **Trash**: Deleted notes and directories go to the trash first, where they can be restored (directories are restored along with their contents) or permanently deleted. The UI can empty it in one click, and the API additionally supports `DELETE /api/trash?days=N` to clear only items older than N days.
- **Reading Rendering**: Markdown rendering (GFM tables, task lists, code highlighting, heading anchors), SPA routing, and a single request on first load that aggregates all data.
- **File Tree**: Both the project page and the editor can create folders / notes in place. A drag handle moves or reorders items, or use `Alt + arrow keys`; moving prevents directories from forming cycles.
- **Tags**: Notes can carry multiple tags. The project page filters the directory tree by the project's tags, the home page aggregates tags by site-wide frequency, and clicking a tag jumps directly to full-text search.
- **Full-Text Search**: Fuzzy matching on titles, body text, and tags. Multiple space-separated terms are combined with AND (up to 5); summaries automatically strip Markdown notation; drafts are visible only to their author.
- **RSS / sitemap**: `/rss.xml` outputs the latest 30 published notes; `/sitemap.xml` works with `/robots.txt` for search engine crawling.
- **Dark Mode**: Follows the system, with manual switching; the theme is applied before first-screen rendering, with no flash.
- **Attachments**: Images (PNG / JPEG / GIF / WebP) and PDF, 10MB per file, named with random UUIDs and cached long-term.
- **Account Settings**: Change passwords, view site info and trash usage in-site — no need to log into the server and modify the database.
- **Health Check**: `GET /api/healthz` returns `{"ok":true,"uptime":N}` and returns 503 on database failure.
- **Security**: helmet (CSP, HSTS in production), login rate limiting (20 per 10 minutes), upload rate limiting (120 per hour), a CORS whitelist, and bcrypt password hashing.

> **About version history**: Version records start from the first body / title / URL identifier / tag modification after this upgrade. Old files imported before the upgrade that did not save a source path may still produce a duplicate on first re-import; after that, the same path will be recognized and skipped.

## Tech Stack

| Layer | Choice |
| --- | --- |
| Frontend | React 18 + TypeScript + Vite 5, React Router 6, react-markdown + remark-gfm + rehype-slug + custom rehypeHighlight (lowlight) |
| Backend | Node.js 20 + Express 4; AI writing uses the OpenAI Node SDK |
| Database | SQLite (better-sqlite3 11, WAL mode) |
| Authentication | JWT (valid for 30 days) + bcryptjs |
| Security / Middleware | helmet、compression、cors、express-rate-limit |
| Testing | node:test (`node --test`, requires Node 20+) |

## Quick Start (Local Development)

Requires Node.js 20 or higher.

```bash
npm install
npm run dev        # Starts the backend (3001) and Vite (5173) together; open http://localhost:5173 in your browser
```

`npm run dev` uses concurrently to run `node server/index.js` and `vite` together. Vite proxies `/api`, `/rss.xml`, and `/sitemap.xml` to 3001, so in development you only need to access **5173**.

On first startup the database is created automatically under `data/`, and an admin is created with the default account `coustea` / `coustea`. No action is needed in development, but **you must change it before going live** (see the [production deployment checklist](#production-deployment-checklist)).

**Available commands:**

```bash
npm run dev              # Start the backend and frontend together (development)
npm run build            # tsc type check + Vite build, output to dist/
npm start                # Start only the backend, serving the built dist/, accessible at http://localhost:3001
npm run preview          # Build first, then start the backend (one command for a production-style local preview)
npm test                 # Run API tests (node --test, requires Node 20+)
npm run reset-password -- <username> <new password>   # Reset the password directly in the database when you forget it
npm run clean-uploads    # Dry-run cleanup of orphaned attachments (add --apply to actually delete)
npm run shots            # Design self-check screenshots, output in .shots/ (requires local chromium)
```

> Before running the backend alone (without Vite), run `npm run build` first; otherwise only the API is available and no pages are served.

## Directory Structure

```text
.
├── server/
│   ├── index.js          # Express app: routes, auth, RSS/sitemap, static hosting, graceful shutdown
│   └── db.js             # Table creation, PRAGMA, closeDatabase (checkpoint WAL before exit)
├── src/                  # React frontend source
│   ├── pages/            # Home / Daily / Project / Editor / Search / Recent / Trash / Settings / Login / admin/*
│   ├── components/       # CodeBlock / MarkdownView / Icon / ErrorBoundary / ProjectFileTree / MarkdownAssistant
│   ├── components/ui/    # shadcn/radix base components (button / card / dialog / badge)
│   ├── hooks/useReveal.ts # Viewport fade-in (IntersectionObserver)
│   ├── lib/folder.ts     # Path handling for folder imports
│   ├── lib/highlight.ts  # Only register languages in use to control the highlight bundle size
│   ├── lib/rehypeHighlight.ts # Custom rehype plugin: lowlight produces hast, then wrapped by CodeBlock
│   ├── api.ts            # Backend API wrapper
│   ├── auth.tsx          # Login state
│   ├── site.tsx          # Site info / page meta / JSON-LD
│   ├── theme.tsx         # Light/dark theme
│   └── styles.css        # Design tokens + all component styles (single file, no CSS-in-JS)
├── tests/
│   ├── api.test.js       # Integration tests for the main-flow APIs
│   ├── extra.test.js     # Daily learning / trash / user isolation
│   └── mock-ai-fetch.js  # Mocks four kinds of AI upstream (OpenAI / Spark / Spark error codes / DeepSeek)
├── scripts/
│   ├── shoot.js          # Design self-check screenshots (playwright-core, light/dark/mobile)
│   ├── reset-password.js # Reset the password directly in the database on the server when you forget it
│   └── clean-orphan-uploads.js # Clean up attachment files not referenced by any note
├── examples/golang-basics # Sample Markdown folder, ready to import
├── data/                 # Runtime data, not version-controlled; the only directory that needs persistence and backup
│   ├── notes.db          # Main SQLite database
│   ├── notes.db-wal      # WAL log
│   ├── notes.db-shm      # Shared-memory index
│   ├── uploads/<userId>/ # Uploaded attachments, organized by user
│   └── .jwt-secret       # Signing secret auto-generated when JWT_SECRET is not set
├── dist/                 # Frontend build output, served by the server
├── deploy/
│   ├── md-notes.service       # systemd unit
│   ├── nginx-bootstrap.conf   # Temporary HTTP config for the first certificate issuance
│   ├── nginx.conf             # nginx server block (with the 80 redirect)
│   └── backup.sh              # Consistent backup script
├── Dockerfile            # Multi-stage production image
├── docker-compose.yml    # Single-service orchestration
├── .env.example          # Environment variable template
├── .gitattributes        # Forces LF line endings (CRLF in Dockerfile would break line continuations)
├── .editorconfig         # Also forces LF at the editor level to avoid writing CRLF back on Windows
└── README.md
```

## Configuration (Environment Variables)

At startup the server automatically reads `.env` in the project root (a built-in ~20-line parser, no dotenv dependency), and the three deployment paths — bare metal, Docker, and systemd — share the same configuration. **Real environment variables take precedence over the `.env` file**, so temporary overrides can be written directly before a command:

```bash
PORT=4000 SITE_NAME=Temp Site node server/index.js
```

**Do not write trailing comments or quote values** in the `.env` file, and set permissions to `chmod 600`.

| Variable | Default | Description | Required in Production |
| --- | --- | --- | :---: |
| `ENV_FILE` | `<project root>/.env` | Configuration file path, read automatically if present | No |
| `PORT` | `3001` | Listening port | No |
| `HOST` | `0.0.0.0` | Listening address. For bare-metal reverse proxies, `127.0.0.1` is recommended | No |
| `DATA_DIR` | `./data` | Data directory, the only directory that needs to persist | No |
| `NODE_ENV` | unset | Set to `production` to send HSTS | **Yes** |
| `TRUST_PROXY` | `1` | Number of trusted proxy layers. Use `1` for one nginx layer, `false` for direct public access | No |
| `JWT_SECRET` | empty (auto-generates `data/.jwt-secret`) | JWT signing secret; 64 hex characters recommended | **Yes** |
| `ALLOWED_ORIGINS` | empty (allows all origins) | CORS whitelist, comma-separated; leaving it empty is only suitable for a pure intranet | **Yes** |
| `SITE_NAME` | `Notes Library` | Site name, used for page titles and RSS | No |
| `SITE_DESCRIPTION` | `Tutorials, notes, and code examples, archived by project.` | Site description | No |
| `SITE_OWNER` | `coustea` | The only account that can create projects / import; set to an empty string = any logged-in account | No |
| `SITE_URL` | empty (inferred from request headers) | Site root URL, used for absolute links in RSS / sitemap / robots | **Yes** |
| `DEFAULT_ADMIN_USERNAME` | `coustea` | Admin account created on first startup | No |
| `DEFAULT_ADMIN_PASSWORD` | `coustea` | Admin password created on first startup, **must be changed in production** | **Yes** |
| `DEFAULT_ADMIN_DISPLAY_NAME` | `Site Admin` | Admin display name | No |
| `DISABLE_DEFAULT_ADMIN` | unset | Set `1` to skip creating the default admin | No |
| `HOST_PORT` | `3001` | Docker Compose only; host-side mapped port | No |

> `DEFAULT_ADMIN_*` only takes effect when no account with the same name exists in the database; changing these values does not affect existing accounts (use in-site "Change Password" or a database script instead). When `ALLOWED_ORIGINS` is empty, CORS allows all origins, which is only suitable for a pure intranet.

## Production Deployment

Three deployment paths are provided, in order of recommendation. Whichever you take, prepare `.env` first:

```bash
cp .env.example .env
node -e "console.log(require('crypto').randomBytes(32).toString('hex'))"
# Paste the output 64-character string into JWT_SECRET= in .env
chmod 600 .env
```

When `NODE_ENV=production`, the server runs a **configuration self-check** once at startup, printing the most easily missed items one by one: `JWT_SECRET` / `SITE_URL` / `ALLOWED_ORIGINS` / `TRUST_PROXY` / `DEFAULT_ADMIN_PASSWORD`. When everything is ready it outputs a single line `生产自检通过` (Production self-check passed); if anything is missing it outputs a numbered list — fix the items and restart. The check **only warns and does not block startup**, so you can bring the service up first and fill in the configuration later.

### Path One: Bare Metal + systemd + nginx (Recommended)

Suitable for long-running VPS. The process is managed by systemd, nginx handles TLS and reverse proxying, and upgrading is just `git pull` + rebuild.

```bash
# 1. Install Node 20 and nginx
curl -fsSL https://deb.nodesource.com/setup_20.x | sudo -E bash -
sudo apt-get install -y nodejs nginx git
node -v                                  # verify >= v20

# 2. Create a dedicated runtime user
sudo useradd --system --home /opt/md-notes --shell /usr/sbin/nologin notes

# 3. Clone the code and build
sudo mkdir -p /opt/md-notes
sudo git clone git@github.com:coustea/StudyHub.git /opt/md-notes
cd /opt/md-notes
sudo npm ci
sudo npm run build

# 4. Data directory
sudo mkdir -p /opt/md-notes/data
sudo chown -R notes:notes /opt/md-notes/data
sudo chmod 700 /opt/md-notes/data

# 5. Environment variables
sudo cp .env.example /opt/md-notes/.env
sudo nano /opt/md-notes/.env
#   Required: DEFAULT_ADMIN_PASSWORD, JWT_SECRET, SITE_URL, ALLOWED_ORIGINS
#   Recommended: HOST=127.0.0.1 (only allow the local nginx to reach it)
sudo chown notes:notes /opt/md-notes/.env
sudo chmod 600 /opt/md-notes/.env

# 6. Install and start the systemd service
sudo cp deploy/md-notes.service /etc/systemd/system/md-notes.service
sudo systemctl daemon-reload
sudo systemctl enable --now md-notes
systemctl status md-notes
curl -fsS http://127.0.0.1:3001/api/healthz && echo   # expect {"ok":true,"uptime":N}

# 7. First request a certificate with the HTTP config
sudo mkdir -p /var/www/certbot
sudo cp deploy/nginx-bootstrap.conf /etc/nginx/conf.d/md-notes.conf
sudo sed -i 's/notes.example.com/your-domain/g' /etc/nginx/conf.d/md-notes.conf
sudo nginx -t && sudo systemctl reload nginx
sudo apt-get install -y certbot python3-certbot-nginx
sudo certbot certonly --webroot -w /var/www/certbot -d your-domain

# 8. Enable HTTPS reverse proxy
sudo cp deploy/nginx.conf /etc/nginx/conf.d/md-notes.conf
sudo sed -i 's/notes.example.com/your-domain/g' /etc/nginx/conf.d/md-notes.conf
sudo nginx -t && sudo systemctl reload nginx
sudo systemctl list-timers | grep certbot

# 9. Configure backup cron (3:10 every day)
sudo chmod +x /opt/md-notes/deploy/backup.sh
sudo mkdir -p /var/backups/md-notes && sudo chown notes:notes /var/backups/md-notes
sudo chmod 700 /var/backups/md-notes
sudo crontab -u notes -e
#   Write:
#   10 3 * * * /opt/md-notes/deploy/backup.sh >> /var/log/md-notes-backup.log 2>&1
```

`deploy/md-notes.service` enables hardening options such as `ProtectSystem=strict`, `ProtectHome=true`, `NoNewPrivileges=true`, and `PrivateTmp=true`, and sets `/opt/md-notes/data` as the only writable path. Note that it defaults to `/usr/bin/node`; if Node was installed via nvm, find the real path with `which node` and update `ExecStart` (systemd does not read the user PATH).

### Path Two: Docker Compose

Suitable for machines that already have Docker, or for running alongside other services on the same host.

```bash
cp .env.example .env
nano .env        # required: DEFAULT_ADMIN_PASSWORD / JWT_SECRET / SITE_URL
                 # Under Docker, keep HOST as 0.0.0.0; DATA_DIR is forced to /app/data by compose

docker compose up -d --build
docker compose ps                  # Wait for STATUS to show (healthy)
docker compose logs -f
curl -fsS http://127.0.0.1:3001/api/healthz && echo
```

The image build has two stages: **stage one `builder`** (`node:20-bookworm-slim` + `python3/make/g++` + `npm ci` + `npm run build`) produces `dist/`; **stage two `runtime`** (also `node:20-bookworm-slim`) installs only production dependencies, copies `dist/` from the builder stage and `server/` from the build context, and ends with `USER node` + `HEALTHCHECK` + `STOPSIGNAL SIGTERM`. Both stages lock the same major Node version to keep the better-sqlite3 native ABI consistent.

**Common operations commands:**

```bash
docker compose restart             # Restart, with graceful shutdown
docker compose down                # Stop and remove containers; the named volume md-notes-data is kept
docker compose up -d --build       # Upgrade: rebuild and roll the container
docker volume ls | grep md-notes   # Confirm the data volume still exists
```

After updating code you **must add `--build`**, otherwise compose will reuse the old image. `docker compose down` does **not** delete named volumes by default, but `down -v` does — do not add `-v` casually.

**Docker backup**: The image does not include `deploy/` (it is excluded in `.dockerignore`); run a one-off container with the data volume and the script mounted. The image runs as `node` (uid 1000), so the host backup directory must be writable by that user:

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

In cron, write the command above as a single line. If that feels cumbersome, replace the compose named volume with a bind mount (`./data:/app/data`); `deploy/backup.sh` on the host can then run directly against `./data` without entering the container.

### Path Three: Intranet / Local Only

No nginx, no Docker required:

```bash
npm ci
npm run build
cp .env.example .env
# Simplified for intranet: HOST=0.0.0.0, SITE_URL=http://192.168.1.10:3001, TRUST_PROXY=false
node server/index.js
```

Key points:

- **Without a reverse proxy, be sure to set `TRUST_PROXY=false`**. The default `1` trusts one proxy layer; when connected directly to the public internet, clients can forge `X-Forwarded-For` to bypass login rate limiting.
- Write `SITE_URL` as a complete address reachable from the intranet (e.g. `http://192.168.1.10:3001`), otherwise RSS / sitemap links will be wrong.
- For auto-start on boot, use `deploy/md-notes.service`, changing `HOST` to `0.0.0.0` and `SITE_URL` to the intranet address.

### Production Deployment Checklist

Confirm each item before going live; any omission can be exploited by scanning scripts:

- [ ] **Change the default password**: Change `DEFAULT_ADMIN_PASSWORD` to a random string of 16+ characters, or change the password in-site right after the account is created at first startup.
- [ ] **Set `JWT_SECRET`**: Do not rely on the auto-generated `data/.jwt-secret`, otherwise all logins will be invalidated during migration / volume rebuild.
- [ ] **Set `SITE_URL`**: Write it as `https://your-domain` (with protocol, no trailing slash).
- [ ] **Set `ALLOWED_ORIGINS`**: Fill in the real domain; do not leave it empty.
- [ ] **Set `NODE_ENV=production`**: otherwise HSTS is not sent.
- [ ] **`TRUST_PROXY` matches the actual topology**: use `1` for one nginx layer, `false` for direct public access.
- [ ] **Configure backup cron** and **actually verify one restore**.
- [ ] **Enable HTTPS** and confirm the certbot auto-renewal timer exists.
- [ ] **Only open ports 80 / 443 in the firewall**: `sudo ufw allow OpenSSH && sudo ufw allow 80,443/tcp && sudo ufw enable`, port 3001 is not exposed to the public.
- [ ] **`chmod 600 .env`**: it contains the database password and the JWT secret.
- [ ] **`/api/healthz` is not externally accessible**: `deploy/nginx.conf` already restricts it to the local machine; if you have changed it later, recheck.
- [ ] **Confirm `data/` ownership** belongs to the running user (`notes` or `node` in the container), otherwise the first write will fail.

## API Reference

All APIs live under `/api`. Except for public reads, they all require `Authorization: Bearer <token>` (returned by the login API, valid for 30 days). Write operations check `owner_id`; unauthorized access returns 403.

| Method | Path | Description | Login Required |
| --- | --- | --- | :---: |
| GET | `/api/healthz` | Health check, 503 on database failure | No |
| POST | `/api/auth/login` | Login, returns token and user; rate limited to 20 per 10 minutes | No |
| POST | `/api/auth/register` | Always 403; registration is not open on this site | — |
| GET | `/api/auth/me` | Current account | Yes |
| POST | `/api/auth/change-password` | Change password (verifies the old password; new password ≥ 6 characters) | Yes |
| POST | `/api/ai/markdown` | Generate Markdown using the API key, model, Base URL, and writing requirements provided by the page; rate limited to 30 per hour | coustea only |
| GET | `/api/admin/notes` | Admin workspace article list, including drafts | coustea only |
| POST | `/api/admin/notes/batch` | Batch operations (publish / draft / trash) | coustea only |
| GET | `/api/projects` | Project list (including doc/folder counts and the first 4 tags) | No |
| POST | `/api/projects` | Create a project; site owner only | Yes |
| GET | `/api/projects/:id` | Project details + directory tree | No |
| PATCH | `/api/projects/:id` | Rename / description / ordering / publish status | Yes |
| DELETE | `/api/projects/:id` | Delete a project (along with all nodes, hard delete) | Yes |
| POST | `/api/projects/from-folder` | Create a project from an uploaded folder; site owner only | Yes |
| POST | `/api/nodes` | Create a note / directory, optionally with `dailyDate` | Yes |
| GET | `/api/nodes/:id` | A single note | No |
| GET | `/api/nodes/:id/revisions` | Old version list | Yes, author only |
| GET | `/api/nodes/:id/revisions/:revisionId` | Read old version body | Yes, author only |
| PATCH | `/api/nodes/:id` | Change title / body / tags / ordering / status / `dailyDate` | Yes |
| POST | `/api/nodes/:id/move` | Move or reorder the file tree, pass `parentId` and `beforeId` (`null` for the end) | Yes |
| DELETE | `/api/nodes/:id` | Move to trash; add `?purge=1` to permanently delete | Yes |
| GET | `/api/trash` | Trash list (only top-level entries, with project names and totals) | Yes |
| POST | `/api/trash/:id/restore` | Restore (if the parent directory has been deleted, attach back to the root) | Yes |
| DELETE | `/api/trash/:id` | Permanently delete a single entry | Yes |
| DELETE | `/api/trash?days=N` | Empty the trash; with `days` only clears items older than N days | Yes |
| GET | `/api/daily?date=&days=` | Notes for a learning day + check-in heatmap (`days` 7–365, default 120) | No (returns empty when not logged in) |
| POST | `/api/daily/new` | Create today's note in the "Daily Learning" project, optionally with `date` / `title` | Yes |
| POST | `/api/import` | Batch md import (2MB per file, 20MB total, max 300 files) | Yes |
| GET | `/api/search?q=` | Fuzzy search on title / body / tags (multiple space-separated terms take the intersection), returns summary and `terms` | No |
| GET | `/api/tags` | Tag cloud (by usage frequency) | No |
| GET | `/api/recent?limit=` | Recently updated | No |
| POST | `/api/uploads` | Base64 attachment upload (images / PDF, 10MB) | Yes |
| GET | `/api/uploads/:owner/:file` | Read an attachment, long-term cache | No |
| DELETE | `/api/uploads/:owner/:file` | Delete an attachment | Yes |
| GET | `/api/site` | Site name / description / counts / site URL | No |
| GET | `/api/overview` | Home page aggregation: site + projects + recent + tags + today's learning summary | No |
| GET | `/rss.xml` | Latest 30 published notes | No |
| GET | `/sitemap.xml` | All published projects and notes | No |
| GET | `/robots.txt` | Crawl rules, including the sitemap URL | No |

## Database and Migrations

The database is a single SQLite file located at `DATA_DIR/notes.db`, using **WAL mode**. The table schema is defined in `server/db.js` and created at startup via `CREATE TABLE IF NOT EXISTS`:

| Table | Purpose |
| --- | --- |
| `users` | Accounts (username, password hash, display name) |
| `projects` | Projects (owner, name, slug, description, publish status, ordering) |
| `nodes` | Notes and directory tree (parent-child relationships, content, tags, status, soft-delete time, learning date, source path) |
| `node_revisions` | Note history versions (body / title / tag snapshots) |
| `app_settings` | Application settings (e.g. AI configuration stored in the database) |

**Important notes on migrations:**

- On a fresh deployment, startup automatically creates the complete schema — no action required.
- **This project does not provide automatic column-level migrations.** `server/db.js` only uses `CREATE TABLE IF NOT EXISTS` and never runs `ALTER TABLE` on existing tables to add columns. Therefore, if a database created by an older version lacks columns from the current schema, they will not be added automatically after upgrading.
- If a later version changes the schema (adding columns), upgrading from an older version requires **manual migration**, and you must **back up first**.

**Back up before upgrading**, then check `git log -- server/db.js` for schema changes. To add a column manually:

```bash
# 1. Back up first!
sudo -u notes /opt/md-notes/deploy/backup.sh

# 2. Stop the service and inspect the current table schema
sudo systemctl stop md-notes
sudo -u notes node -e "const D=require('/opt/md-notes/node_modules/better-sqlite3');const d=new D('/opt/md-notes/data/notes.db');console.log(d.prepare('PRAGMA table_info(nodes)').all());d.close()"

# 3. Add the missing columns per the new server/db.js definition (example)
sudo -u notes node -e "const D=require('/opt/md-notes/node_modules/better-sqlite3');const d=new D('/opt/md-notes/data/notes.db');d.exec(\"ALTER TABLE nodes ADD COLUMN new_column TEXT NOT NULL DEFAULT ''\");d.close()"

# 4. Start the service and re-check with PRAGMA table_info
sudo systemctl start md-notes
```

## AI-Assisted Writing

AI writing is **only available to the `coustea` account** for configuration and use; other accounts cannot see the entry point, and direct API calls will be rejected. The server uniformly uses the **OpenAI-protocol Chat Completions API**.

On the "Account and System Settings" page, the model configuration can be saved into the database (`ai_config` in the `app_settings` table); the "AI-Assisted Writing" feature in the editor uses it automatically, and it can also be overridden temporarily in the editor. **Leaving Base URL empty** uses the official OpenAI API; any **HTTPS**-compatible address can also be filled in. Adapters for common services are built in:

| Service | Base URL | Model Example |
| --- | --- | --- |
| OpenAI | leave empty or `https://api.openai.com/v1` | `gpt-4o-mini` |
| iFlytek Spark (Xingchen MaaS) | `https://maas-api.cn-huabei-1.xf-yun.com/v2` | `spark-x2.6` |
| DeepSeek | `https://api.deepseek.com/v1` | `deepseek-chat` |

The following common pitfalls have been handled:

- Pasting a full address containing `/chat/completions` (the iFlytek official docs use this form) is automatically collapsed to the version prefix, so a 404 from `/chat/completions/chat/completions` is never produced.
- Non-zero business codes returned by iFlytek within HTTP 200 are recognized as errors and the reason is surfaced, instead of being misjudged as "the model returned no content".
- For thinking models (e.g. `spark-x2.6` with thinking enabled by default), when the body is empty the `reasoning_content` is read as a fallback.

The settings page provides a "Test Connection" button that sends a tiny real request with the current parameters and echoes the actual request URL and a summary of any upstream error. **Generated results must be added to the body manually before saving the note. Production deployments must use HTTPS to avoid exposing keys in transit.**

## Backup and Restore

`deploy/backup.sh` uses better-sqlite3's `db.backup()` to take a **consistent snapshot**, does not depend on the `sqlite3` CLI, and **can run while the service is running**.

```bash
# Run once manually
sudo -u notes /opt/md-notes/deploy/backup.sh

# Custom parameters
sudo -u notes BACKUP_DIR=/mnt/backup/md-notes KEEP_DAYS=30 /opt/md-notes/deploy/backup.sh

# Bundle the JWT secret as well (users do not need to log in again after restore)
sudo -u notes INCLUDE_SECRET=1 /opt/md-notes/deploy/backup.sh
```

The output is `md-notes-YYYYmmdd-HHMMSS.tar.gz` plus a same-named `.sha256`, containing `notes.db`, `uploads/`, and `BACKUP_INFO.txt` (time, host, git commit, node and package versions). The default is `BACKUP_DIR=/var/backups/md-notes`, keeping `KEEP_DAYS=14` days.

**Why not just `cp notes.db`**: in WAL mode the main database file may be missing the most recent transactions, and copying it directly yields a database that "looks normal but is missing the latest content". `db.backup()` goes through the SQLite online backup API and copies within a single read transaction, so writes cannot leave the backup in a half-transaction state; after the backup completes, the script immediately runs `PRAGMA integrity_check` on the new database.

`.jwt-secret` is not included in the backup by default. It is only a signing secret and contains no user data; the only consequence is that all logged-in users must log in again after restore. If this matters to you, use `INCLUDE_SECRET=1`.

**Restore steps** (the full version is in the header comments of the script):

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

After restoring, be sure to open the site and confirm: the home page has content, login works, and attachment images display correctly. Only after confirming everything is correct should you delete `data.before-restore`.

> **A backup on the same disk is no backup at all.** In production, point `BACKUP_DIR` to another disk or mounted remote storage (NFS, object storage mounts, etc.).

## Operational Scripts

### Clean Up Orphaned Attachments

When a note is deleted (or an image's Markdown syntax is removed from the body), the files in `uploads/` do not disappear with it — the body only stores a Markdown link, and the server cannot determine whether the image is still referenced elsewhere. Over time the attachment directory fills up with useless images and backup size grows accordingly.

```bash
# Dry run first: preview what will be deleted (no files are removed)
sudo -u notes node /opt/md-notes/scripts/clean-orphan-uploads.js

# Delete for real once you have confirmed it is correct
sudo -u notes node /opt/md-notes/scripts/clean-orphan-uploads.js --apply

# Only delete files unreferenced for 30+ days, leaving a grace period for "just uploaded but not yet inserted into the body"
sudo -u notes node /opt/md-notes/scripts/clean-orphan-uploads.js --apply --days 30
```

The script scans the body text of **all** notes (including the trash), collecting references in the form `/api/uploads/<owner>/<file>` as a whitelist; files on disk not in the whitelist are orphans. Notes in the trash also count as references, so images still exist after being restored. It can be run monthly after the backup cron.

With Docker deployment the script is not in the image (`scripts/` is excluded by `.dockerignore`); copy it in with `cp`:

```bash
docker compose cp scripts/clean-orphan-uploads.js md-notes:/tmp/clean.js
docker compose exec md-notes node /tmp/clean.js            # Dry run (preview)
docker compose exec md-notes node /tmp/clean.js --apply    # Delete for real
```

### Reset Password

If you forget your password there is no need to reinstall or hand-craft SQL. The project ships with a password reset script that reads the same database directly:

```bash
cd /opt/md-notes
sudo -u notes node scripts/reset-password.js --list                       # List accounts
sudo -u notes node scripts/reset-password.js coustea 'new password, at least 6 characters'      # Change password
# Or: sudo -u notes npm run reset-password -- coustea 'new password'
```

With Docker deployment it also needs to be copied in with `cp`:

```bash
docker compose cp scripts/reset-password.js md-notes:/tmp/reset.js
docker compose exec md-notes node /tmp/reset.js --list
docker compose exec md-notes node /tmp/reset.js coustea 'new password, at least 6 characters'
```

Old tokens remain valid after a password change. To immediately kick other devices offline, change `JWT_SECRET` at the same time and restart the service.

## Testing

Uses Node's built-in test framework `node:test`, requires Node 20+.

```bash
npm test
```

Includes two integration suites: `tests/api.test.js` (main flow APIs) and `tests/extra.test.js` (daily learning / trash / user isolation). AI-related cases are intercepted by `tests/mock-ai-fetch.js`, which mocks four kinds of upstream — OpenAI, Spark, Spark error codes, and DeepSeek — without depending on real keys.

## FAQ

**Port in use: `Error: listen EADDRINUSE: address already in use 0.0.0.0:3001`**

```bash
sudo ss -ltnp | grep 3001        # Find the process occupying the port
sudo systemctl stop md-notes     # If it is this service itself
# Or change the port: set PORT=3002 in .env and update nginx's proxy_pass accordingly
```

Common causes are the service having been started twice, or the previous `npm run dev` still being running.

**Forgot your password and cannot log in**

Use the [password reset script](#reset-password); no reinstall is needed.

**better-sqlite3 fails to compile**

Usually `node-gyp` cannot find python / make / g++, or there is a `NODE_MODULE_VERSION` mismatch.

```bash
sudo apt-get install -y python3 make g++
sudo npm rebuild better-sqlite3        # Must be run after switching to a different Node major version
# Or do a full reinstall: sudo rm -rf node_modules && sudo npm ci
```

A `NODE_MODULE_VERSION` mismatch means the `.node` files in `node_modules` were compiled for a different major Node version. The build image and the run image must both be Node 20; after changing the Node version on bare metal you must run `npm rebuild better-sqlite3`, and likewise after switching versions with nvm.

**Links in RSS / sitemap are http after reverse proxying**

Check in order:

1. `SITE_URL` is not set in `.env`. Set it to `https://your-domain` to fix it completely, without relying on request-header inference.
2. nginx is not passing `X-Forwarded-Proto`. Confirm that `proxy_set_header X-Forwarded-Proto $scheme;` is still present in `deploy/nginx.conf`.
3. `TRUST_PROXY` is set to `false`. In this case Express ignores `X-Forwarded-*` and `req.protocol` is always `http`.

Verify:

```bash
curl -s https://your-domain/rss.xml | head -20
curl -s https://your-domain/robots.txt
```

**Upload returns 413**

413 means nginx rejected the request before the application, indicating the limit of `client_max_body_size` was exceeded. The current configuration is `25m`, enough for 10MB attachments (about 13.3MB after base64) and 20MB folder imports. Increase it only when there is a genuine need:

```nginx
client_max_body_size 50m;
sudo nginx -t && sudo systemctl reload nginx
```

If nginx did not intercept it (direct connection to 3001 or a larger reverse-proxy limit), the application itself also returns 413 with the message "request body too large, 24MB limit per request" — this is the limit of `express.json({ limit: '24mb' })` and must be raised as well. If the application returns 400 with the message "file cannot exceed 10MB", that is a hard limit on the application side and the file can only be compressed; the upload API only accepts PNG / JPEG / GIF / WebP / PDF.

**Request returns 400 "request body is not valid JSON"**

The application failed to parse the request body; usually the body sent by a script or third-party tool is not valid JSON (trailing commas, missing quotes, or form data sent as JSON). Normal operations in the browser will not trigger this.

**Rate limit triggered**

- Login: at most 20 attempts per IP within 10 minutes; beyond that, returns `too many attempts, please try again later`.
- Upload: at most 120 attempts per IP within 1 hour.

If, after reverse proxying, everyone is treated as the same IP, either nginx is not passing the real IP or `TRUST_PROXY` is misconfigured: for the former, check `X-Real-IP` / `X-Forwarded-For`; for the latter, confirm the number of layers matches the topology. When connected directly to the public internet, `TRUST_PROXY` must be `false`, otherwise rate limiting can be bypassed with forged request headers.

**Pages 404 but the API works**

`dist/` does not exist or has not been built. The server only hosts the frontend when `dist/index.html` exists; otherwise it only serves the API (a hint is printed in the production startup log).

```bash
npm run build
ls -l dist/index.html
sudo systemctl restart md-notes
```

**Container keeps being unhealthy**

```bash
docker compose logs md-notes
docker inspect --format '{{json .State.Health}}' md-notes
```

Common causes are incorrect `data/` permissions (the container runs as the `node` user, uid 1000), or the database file being owned by root so it cannot be opened. Named volumes usually do not have this problem; for a bind mount you need `sudo chown -R 1000:1000 ./data`.

**Data directory permission error: `SQLITE_CANTOPEN` / `EACCES`**

The service runs as `notes` (bare metal) or `node` (container); `data/` must be writable by the corresponding user:

```bash
sudo chown -R notes:notes /opt/md-notes/data    # Bare metal
sudo chown -R 1000:1000 ./data                  # Docker bind mount
```

## License

This project is a self-hosted personal knowledge base with no open-source license specified. Do not use it for commercial purposes or distribute it publicly without authorization.
