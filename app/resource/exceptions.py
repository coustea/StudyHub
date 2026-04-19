"""
资源生成模块专用异常类

定义了多智能体资源生成系统中可能出现的各种异常情况，
提供清晰的错误类型和上下文信息。
"""


class ResourceAgentError(Exception):
    """资源生成 Agent 基础异常类"""

    def __init__(self, message: str, agent_name: str = "", context: dict | None = None):
        # 把 agent 名直接嵌进错误文本，日志里一眼就能知道是哪一层抛出来的。
        self.agent_name = agent_name
        self.context = context or {}
        super().__init__(f"[{agent_name}] {message}" if agent_name else message)


class PlanningError(ResourceAgentError):
    """任务规划阶段异常

    当 Planner 无法解析需求、生成非法 JSON 或规划失败时抛出。
    """

    def __init__(self, message: str, raw_output: str = ""):
        super().__init__(message, agent_name="Coordinator")
        # 原始输出保留给后续排查 Planner 非法 JSON 或 prompt 漂移问题。
        self.raw_output = raw_output


class KnowledgeBaseError(ResourceAgentError):
    """知识库检索异常

    当知识库服务不可用、检索失败或返回无效结果时抛出。
    """

    def __init__(self, message: str, query: str = ""):
        super().__init__(message, agent_name="KnowledgeBase")
        self.query = query


class AgentExecutionError(ResourceAgentError):
    """Agent 执行异常

    当子 Agent 工作流执行失败、超时或返回无效结果时抛出。
    """

    def __init__(self, message: str, agent_name: str, phase: str = ""):
        super().__init__(message, agent_name=agent_name)
        # phase 能帮助区分是初始化、生成还是校验阶段挂掉。
        self.phase = phase


class ValidationError(ResourceAgentError):
    """输出校验异常

    当 Agent 生成的资源未通过校验规则时抛出。
    """

    def __init__(self, message: str, agent_name: str, validation_details: dict | None = None):
        super().__init__(message, agent_name=agent_name)
        self.validation_details = validation_details or {}


class RetryExhaustedError(ResourceAgentError):
    """重试次数耗尽异常

    当 Agent 达到最大重试次数仍未生成有效结果时抛出。
    """

    def __init__(self, message: str, agent_name: str, retry_count: int = 0):
        super().__init__(message, agent_name=agent_name)
        self.retry_count = retry_count
