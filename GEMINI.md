# AI Learning Platform Backend - Project Guide

## Project Overview
This is a sophisticated AI-powered multi-agent backend for a personalized learning platform. It leverages **FastAPI**, **LangChain**, and **LangGraph** to provide features like intelligent tutoring, user profiling, and automated learning resource generation.

### Key Technologies
- **Python 3.13+** with **uv** for dependency management.
- **FastAPI**: Web framework for API and SSE (Server-Sent Events) streaming.
- **LangChain & LangGraph**: Orchestration of multi-agent workflows and stateful LLM interactions.
- **SQLModel / SQLAlchemy Async**: Database abstraction layer for MySQL.
- **MySQL**: Relational database for persistent storage.
- **Tavily / DuckDuckGo**: Tools for web search.
- **Loguru**: Structured logging.

### Architecture
The project follows a modular architecture where each feature is self-contained:
- **`app/auth`**: User registration, JWT-based authentication, and security.
- **`app/chat`**: Real-time interaction with a `TutorAgent` using LangGraph for multi-step reasoning. Supports file uploads and vision (GLM-4V/Spark).
- **`app/profile`**: Builds an 8-dimensional user profile based on interactions and extracts long-term facts.
- **`app/resource`**: A DAG-based multi-agent system (`CoordinatorAgent`) that generates structured learning materials (mindmaps, PPTs, quizzes, code, reading lists).
- **`app/memory`**: Manages short-term chat history and long-term memory with automatic compression and fact extraction.
- **`app/avatar`**: Integration with digital human services for interactive experiences via WebSockets.
- **`app/infra`**: Core infrastructure including DB sessions, LLM client factories, and global logging setup.

---

## Building and Running

### Prerequisites
- Python 3.13 or higher.
- MySQL 8.0+.
- `uv` installed (`curl -LsSf https://astral.sh/uv/install.sh | sh`).
- Node.js (for certain skills like mindmap generation).

### Installation
```bash
uv sync
```

### Environment Configuration
Copy `.env.example` to `.env` and configure the following:
- `DB_PASSWORD`: Your MySQL password.
- `OPENAI_API_KEY` & `OPENAI_API_BASE`: Primary LLM configuration.
- `JWT_SECRET_KEY`: Secret for signing tokens.

### Running the Application
**Development Mode (Hot Reload):**
```bash
uv run fastapi dev app/main.py
```

**Production Mode:**
```bash
uv run python app/main.py
```

### Testing
```bash
uv run pytest
```

---

## Development Conventions

### Module Structure
Each module in `app/` should generally contain:
- `api.py`: FastAPI routes and dependency injections.
- `service.py`: Business logic and service runtimes.
- `schemas.py`: Pydantic models for request/response validation.

### API Responses
All endpoints should return the unified `HttpResponse` format found in `app/shared/response.py`:
```json
{
  "code": 200,
  "message": "success",
  "data": { ... }
}
```

### Database Usage
- Use **SQLModel** for defining tables in `app/infra/models.py`.
- Prefer async database operations using `get_session` dependency.
- Define new tables in `models.py` to ensure they are initialized by `init_db()`.

### LLM Integration
- Use `app.infra.llm.get_llm()` to retrieve the primary LLM client.
- For lightweight tasks (classification, simple extraction), use `get_fast_llm()`.

### Error Handling
- Use the global exception handler in `app/main.py`.
- Define module-specific exceptions (e.g., `ResourceAgentError`) to maintain clear error hierarchies.

---

## Key Files
- `app/main.py`: Entry point and route registration.
- `app/config.py`: Centralized configuration management using `python-dotenv`.
- `app/infra/models.py`: Database schema definitions.
- `langgraph.json`: Configuration for LangGraph integration.
- `pyproject.toml`: Dependency and project metadata.
