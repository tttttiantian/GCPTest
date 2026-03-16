"""
Agent基类 - 所有Agent的父类
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from workflow.state import TestGenerationState
    from GLMService import GLMService


class BaseAgent(ABC):
    """Agent基类"""

    def __init__(self, glm_service: 'GLMService', name: str):
        """
        初始化Agent

        Args:
            glm_service: GLM服务实例
            name: Agent名称
        """
        self.glm_service = glm_service
        self.name = name
        self.logger = logging.getLogger(f"Agent.{name}")

    @abstractmethod
    def execute(self, state: 'TestGenerationState') -> 'TestGenerationState':
        """
        执行Agent任务（子类必须实现）

        Args:
            state: 当前状态

        Returns:
            更新后的状态
        """
        pass

    def _call_llm(self, prompt: str, temperature: float = 0.7, max_tokens: int = 2000) -> str:
        """
        调用LLM（无历史，适合Agent）

        Args:
            prompt: 提示词
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            LLM响应
        """
        try:
            # 使用chat_once方法，不保留历史
            response = self.glm_service.chat_once(prompt, temperature, max_tokens)
            return response
        except Exception as e:
            self.logger.error(f"LLM调用失败: {str(e)}")
            raise

    def log(self, state: 'TestGenerationState', message: str, data: dict = None):
        """
        记录日志

        Args:
            state: 当前状态
            message: 日志消息
            data: 附加数据
        """
        self.logger.info(f"[Iteration {state.iteration}] {message}")
        state.add_message(self.name, message, data)

    def log_error(self, state: 'TestGenerationState', error: Exception):
        """
        记录错误

        Args:
            state: 当前状态
            error: 异常对象
        """
        error_msg = f"{self.name} 执行失败: {str(error)}"
        self.logger.error(error_msg, exc_info=True)
        state.error_messages.append(error_msg)
