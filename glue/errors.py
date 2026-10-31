"""可预期错误的类型层级；异常消息面向最终用户，统一使用中文。"""

from __future__ import annotations


class WorkstationError(Exception):
    """所有可预期错误的基类，调用方可统一捕获后展示给用户。"""


class ToolNotFoundError(WorkstationError):
    """注册表中不存在该 tool_id。"""


class ToolNotWrappedError(WorkstationError):
    """Bioconda 条目尚未自动封装，暂不能实例化为节点。"""


class InvalidToolDefinitionError(WorkstationError):
    """工具定义（如 LLM 生成的 meta.yaml）未通过校验。"""


class CompileError(WorkstationError):
    """画布无法编译为 Snakefile；uid 指向出错的节点（可为空）。"""

    def __init__(self, message: str, uid: str | None = None) -> None:
        super().__init__(message)
        self.uid = uid


class SessionConflictError(WorkstationError):
    """保存时发现 session.json 已被其他进程修改（revision 不一致）。"""


class RunBusyError(WorkstationError):
    """同一工作区已有运行中的任务。"""


class RunNotFoundError(WorkstationError):
    """不存在该 run_id。"""


class PathNotAllowedError(WorkstationError):
    """路径不在工作区或 allowed_input_roots 白名单内。"""
