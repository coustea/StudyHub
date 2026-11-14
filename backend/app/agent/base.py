
"""
Deep Agent 基础构建模块。

统一初始化：
- LLM 模型
- Tavily 联网搜索
- Skills 技能加载
- 文件系统与工作目录
- Shell 命令执行
"""

from pathlib import Path

from deepagents import FilesystemPermission, create_deep_agent
from deepagents.backends import CompositeBackend, FilesystemBackend, StateBackend
from langchain.agents.middleware import HostExecutionPolicy, ShellToolMiddleware
from langchain_openai import ChatOpenAI
from langchain_tavily import TavilySearch
from langgraph.graph.state import CompiledStateGraph

from app.config.config import get_settings


def build_agent(
    system_prompt: str,
    workspace_dir: Path | str | None = None,
) -> CompiledStateGraph:
    """根据 Prompt 和工作目录构建 Deep Agent。"""

    settings = get_settings()

    # 1. 初始化大模型
    llm = settings.agent.llm
    model = ChatOpenAI(
        model=llm.model,
        api_key=llm.api_key,
        base_url=llm.base_url,
        temperature=llm.temperature,
        max_tokens=llm.max_tokens,
        timeout=llm.timeout,
        max_retries=llm.max_retries,
    )

    # 2. 注册联网搜索工具
    tools = []
    if settings.agent.tavily:
        tools.append(
            TavilySearch(
                max_results=5,
                tavily_api_key=settings.agent.tavily,
            )
        )

    # 3. 挂载 Skills 目录
    # Agent 通过 /skills/ 访问真实技能目录
    skills_path = Path(settings.agent.skills_dir).resolve()

    routes = {
        "/skills/": FilesystemBackend(
            root_dir=skills_path,
            virtual_mode=True,
        ),
    }

    # 4. 配置文件权限
    # 禁止通过 Deep Agents 文件工具修改共享 Skills
    permissions = [
        FilesystemPermission(
            operations=["write"],
            paths=["/skills/**"],
            mode="deny",
        ),
    ]

    # 5. 配置 Shell 工具及工作目录
    middleware = []

    if workspace_dir is not None:
        ws_path = Path(workspace_dir).resolve()
        ws_path.mkdir(parents=True, exist_ok=True)

        # 将 /workspace/ 映射到真实工作目录
        routes["/workspace/"] = FilesystemBackend(
            root_dir=ws_path,
            virtual_mode=True,
        )

        # LangChain 自动向 Agent 注册 shell 工具
        # Shell 命令默认在当前工作目录执行
        middleware.append(
            ShellToolMiddleware(
                workspace_root=ws_path,
                execution_policy=HostExecutionPolicy(
                    command_timeout=120.0,
                    max_output_lines=200,
                ),
            )
        )

    # 6. 构建虚拟文件系统
    # /skills/ 和 /workspace/ 使用真实文件系统
    # 其他未匹配路径使用 StateBackend
    backend = CompositeBackend(
        default=StateBackend(),
        routes=routes,
    )

    # 7. 创建并返回 Agent
    return create_deep_agent(
        model=model,
        system_prompt=system_prompt,
        tools=tools,
        backend=backend,
        skills=["/skills/"],
        permissions=permissions,
        middleware=middleware,
    )
