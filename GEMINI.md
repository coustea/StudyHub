# GEMINI.md — FrameForge 开发规范

本文档定义 **FrameForge** 项目的编码原则、代码风格与开发约束。所有新增或修改的代码均须严格遵守。

---

## 1. 核心设计原则：简洁明了，禁止过度封装

- **直接优先（KISS / YAGNI）**：优先使用最直观、扁平的函数与模块结构，拒绝为了“扩展性”提前制造抽象层、基类体系、泛型工厂或空壳包装类。
- **避免无意义封装**：
  - 仅调用一次或几行即可写清的逻辑，不要强行拆成多层 `Manager` / `Handler` / `Wrapper` / `Adapter`。
  - 服务层函数（`app/services/*.py`）直接编写清晰的异步函数即可，不要引入无必要的 `Service` 类或抽象接口（`Protocol` / `ABC`）。
  - 不要把简单的配置、异常或 SQLModel 查询包装成复杂的 DSL 或元编程框架。
- **控制抽象时机**：只有当相同逻辑在多处（3 处及以上）重复出现，或确需隔离外部系统边界（如文件系统沙箱、受限 Shell 执行、第三方 API 客户端）时，才抽取公共函数或轻量类。
- **浅层嵌套与早返回**：优先使用 `if ...: return / raise` 早返回，减少 `else` 嵌套，保持函数短小、职责单一。

---

## 2. Google Python 代码规范

全项目后端代码统一遵循 **Google Python Style Guide**（结合 Python 3.12+ 与 FastAPI 约定）：

### 2.1 命名规范
- **模块与包名**：全小写加下划线（`snake_case`），例如 `jwt_auth.py`、`auth.py`；`models/` 与 `services/` 目录下的文件命名禁止使用 `_model`、`_service` 后缀（应直接使用 `models/user.py`、`services/auth.py`）。
- **类名与异常类**：大驼峰（`CapWords`），例如 `User`、`JWTAuthMiddleware`、`AuthenticationError`。
- **函数、方法与变量**：全小写加下划线（`snake_case`），例如 `register_user`、`decode_access_token`。
- **常量**：全大写加下划线（`CAPS_WITH_UNDER`），例如 `BACKEND_DIR`、`ALEMBIC_INI_PATH`。
- **内部/私有成员**：单下划线前缀，例如 `_build_token`、`_is_exempt`。

### 2.2 格式与排版
- **缩进**：统一使用 4 个空格，禁止使用 Tab。
- **行宽**：每行不超过 100 字符（与 `pyproject.toml` 中 `[tool.ruff]` 对齐）。
- **空行**：顶级函数与类定义之间空 2 行；类内方法之间空 1 行；函数内逻辑分段可适当空 1 行。
- **引号**：字符串优先使用双引号 `"`，文档字符串统一使用三双引号 `"""`。

### 2.3 导入规范（Imports）
- 仅导入包或模块内具体的符号，避免使用 `from x import *`。
- 按标准库、第三方库、项目内部模块的顺序分组，每组之间空 1 行，组内按字母序排列（由 `ruff` 的 `I` 规则自动校验）。
- 禁止未使用的导入。

### 2.4 类型注解（Type Annotations）
- 所有函数参数与返回值均须显式标注类型（Python 3.12+ 原生语法：`list[str]`、`dict[str, Any]`、`str | None`，不使用旧式 `List`、`Optional`）。
- 避免使用 `Any`，仅在确实无法静态确定结构时使用。

### 2.5 语法与错误处理规范
- **禁止裸异常捕获**：禁止 `except:` 或吞掉异常；只捕获明确的可预期异常，保留原始异常链（`raise ... from exc`）。
- **禁止可变默认参数**：不要使用 `def fn(items: list[str] = [])`，改用 `None` 或 `Field(default_factory=...)`。
- **资源安全**：文件、数据库连接等上下文资源统一使用 `with` / `async with` 管理。
- **列表推导式与表达式**：仅在简洁清晰时使用推导式，嵌套超过两层时改写为普通 `for` 循环。

---

## 3. 中文注释与 Google 风格文档字符串（Docstring）

**全项目的所有代码注释与文档字符串必须使用中文编写**，并采用 Google Python Style 格式：

- **模块/类/函数 Docstring**：说明“做什么”，清晰简洁；参数较多或有返回值、异常抛出的函数需包含 `Args:`、`Returns:`、`Raises:`。
- **行内注释（`#`）**：解释**为什么这样写（Why）**或关键约束，不重复代码表面字面含义（What）。
- **示例**：

```python
def create_access_token(
    *,
    subject: str,
    role: str,
    settings: Settings,
) -> tuple[str, int]:
    """签发用于接口鉴权的 JWT 访问令牌。

    Args:
        subject: 令牌主体标识（通常为用户 ID 字符串）。
        role: 用户角色名称。
        settings: 应用配置实例。

    Returns:
        由签名后的 JWT 字符串与有效时长（秒）组成的二元组。
    """
    ...
```

---

## 4. FastAPI 与数据库开发约定

除遵守上述 Google Python 规范外，同时配合 `.agents/skills/fastapi/SKILL.md` 与 `AGENTS.md` 执行：
1. **依赖注入**：使用 `Annotated[Type, Depends(...)]` 并在 `app/api/deps.py` 定义可复用别名；Pydantic 模型与路径/查询参数禁止使用 `...`（Ellipsis）与 `RootModel`。
2. **路由组织**：在 `APIRouter(...)` 自身声明 `prefix`、`tags` 与公共 `dependencies`，每个接口函数只处理单一 HTTP 方法，并声明明确的返回类型。
3. **数据访问与迁移**：统一使用 `SQLModel` + 异步 `AsyncSession`；表结构变更通过 `uv run alembic revision --autogenerate` 生成迁移脚本，应用启动时自动执行 `alembic upgrade head`。
4. **工程工具**：使用 `uv` 管理依赖，提交前须通过 `uv run ruff check .` 与 `uv run pytest -v`。
