"""
状态管理模块 - 定义测试生成过程中的状态
"""

from typing import List, Dict, Optional
from dataclasses import dataclass, field
import logging


@dataclass
class TestQualityMetrics:
    """测试质量指标"""
    # 基础指标
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    pass_rate: float = 0.0  # 百分比

    # 失败分类
    code_bugs: List[Dict] = field(default_factory=list)
    # 示例: [{'test': 'test_xxx', 'reason': '代码未实现XX', 'code_issue': '第65行'}]

    test_bugs: List[Dict] = field(default_factory=list)
    # 示例: [{'test': 'test_yyy', 'reason': '测试未理解短路逻辑', 'fix': '使用total<99'}]

    # 需求覆盖 (可选, 仅当有original_requirements时计算)
    requirement_coverage: float = 0.0
    covered_scenarios: List[str] = field(default_factory=list)
    missing_scenarios: List[str] = field(default_factory=list)


@dataclass
class CodeAnalysis:
    """代码分析结果"""
    functions: List[Dict] = field(default_factory=list)      # 函数列表
    classes: List[Dict] = field(default_factory=list)        # 类列表
    branches: List[Dict] = field(default_factory=list)       # 分支列表
    complexity: Dict[str, int] = field(default_factory=dict) # 复杂度
    edge_cases: List[str] = field(default_factory=list)      # 边界条件
    exceptions: List[str] = field(default_factory=list)      # 异常类型


@dataclass
class CoverageGap:
    """覆盖率缺口"""
    uncovered_lines: List[int] = field(default_factory=list)
    uncovered_branches: List[str] = field(default_factory=list)
    uncovered_functions: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)


@dataclass
class TestGenerationState:
    """测试生成状态"""

    # ===== 输入参数 =====
    source_code: str                              # 源代码
    original_requirements: str = ""               # 原始需求（功能规格）- 用于确定正确的断言值
    test_requirements: str = ""                   # 测试策略需求（可选）- 用于定制测试策略
    module_name: str = ""                         # 模块名
    target_coverage: float = 90.0                 # 目标覆盖率

    # ===== 处理过程数据 =====
    code_analysis: Optional[CodeAnalysis] = None  # 代码分析结果
    test_code: str = ""                           # 生成的测试代码
    coverage_report: Dict = field(default_factory=dict)  # 覆盖率报告
    coverage_gaps: Optional[CoverageGap] = None   # 覆盖率缺口
    pytest_output: str = ""                       # pytest执行输出

    # ===== 控制参数 =====
    iteration: int = 0                            # 当前迭代次数
    max_iterations: int = 3                       # 最大迭代次数
    is_complete: bool = False                     # 是否完成

    # ===== 日志和错误 =====
    agent_messages: List[Dict] = field(default_factory=list)  # Agent消息
    error_messages: List[str] = field(default_factory=list)   # 错误消息

    # ===== 新增: 质量指标和历史记录 =====
    quality_metrics: Optional[TestQualityMetrics] = None      # 测试质量指标
    iteration_history: List[Dict] = field(default_factory=list)  # 迭代历史

    def add_message(self, agent: str, message: str, data: dict = None):
        """
        添加Agent消息

        Args:
            agent: Agent名称
            message: 消息内容
            data: 附加数据
        """
        self.agent_messages.append({
            'agent': agent,
            'iteration': self.iteration,
            'message': message,
            'data': data or {}
        })

    def get_current_coverage(self) -> float:
        """
        获取当前总覆盖率（从 pytest-cov 的 Cover 列）

        Returns:
            当前总覆盖率百分比
        """
        if not self.coverage_report or 'summary' not in self.coverage_report:
            return 0.0

        # 从summary中提取总覆盖率（pytest-cov 的 Cover 列，综合了行和分支覆盖）
        total_coverage = self.coverage_report['summary'].get('total_coverage', '0%')

        # 移除百分号并转换为浮点数
        if isinstance(total_coverage, str):
            total_coverage = total_coverage.rstrip('%')

        try:
            return float(total_coverage)
        except (ValueError, TypeError):
            return 0.0

    def get_pass_rate(self) -> float:
        """
        获取测试通过率

        Returns:
            测试通过率百分比
        """
        if not self.quality_metrics or self.quality_metrics.total_tests == 0:
            return 0.0
        return self.quality_metrics.pass_rate

    def _check_quality_target_met(self) -> bool:
        """
        检查质量目标是否达成 (覆盖率 + 通过率)

        Returns:
            是否达成质量目标
        """
        coverage_ok = self.get_current_coverage() >= self.target_coverage
        pass_rate_ok = self.get_pass_rate() >= 99.0  # 允许1%失败
        return coverage_ok and pass_rate_ok

    def _check_no_improvement(self, window: int = 2, threshold: float = 1.0) -> bool:
        """
        检查连续N轮是否无改进

        Args:
            window: 检查窗口 (默认2轮)
            threshold: 改进阈值 (默认1%)

        Returns:
            True表示无改进应停止
        """
        # 修改：只需要 window 条记录，不需要 window + 1
        if len(self.iteration_history) < window:
            return False

        # 获取最近window轮的记录
        recent = self.iteration_history[-window:]

        # 检查是否所有值都相同（无改进）
        if len(recent) < 2:
            return False

        first_coverage = recent[0]['coverage']
        first_pass_rate = recent[0]['pass_rate']

        for record in recent[1:]:
            coverage_delta = abs(record['coverage'] - first_coverage)
            pass_rate_delta = abs(record['pass_rate'] - first_pass_rate)

            if coverage_delta >= threshold or pass_rate_delta >= threshold:
                return False  # 有改进

        return True  # 连续N轮无改进

    def should_continue(self) -> bool:
        """
        判断是否应该继续迭代

        停止条件 (满足任一):
        1. is_complete=True (覆盖率+通过率都达标)
        2. 达到最大迭代次数
        3. 有严重错误
        4. 连续N轮无改进 (新增)

        Returns:
            是否继续
        """
        logger = logging.getLogger("TestGenerationState")

        # 如果已完成，不继续
        if self.is_complete:
            return False

        # 如果达到最大迭代次数，不继续
        if self.iteration >= self.max_iterations:
            return False

        # 如果有严重错误，不继续
        if self.error_messages:
            return False

        # 新增: 检查质量目标 (覆盖率 + 通过率)
        if self._check_quality_target_met():
            self.is_complete = True
            logger.info(
                f"已达到质量目标: 覆盖率{self.get_current_coverage():.1f}%, "
                f"通过率{self.get_pass_rate():.1f}%"
            )
            return False

        # 新增: 检查连续无改进（在至少完成2次迭代后才检查）
        if self.iteration >= 2 and self._check_no_improvement(window=2, threshold=0.5):
            logger.info(f"连续2轮覆盖率和通过率均无明显改进(阈值0.5%), 提前停止 "
                       f"(当前迭代: {self.iteration}, 覆盖率: {self.get_current_coverage():.1f}%)")
            return False

        return True

    def get_summary(self) -> Dict:
        """
        获取状态摘要

        Returns:
            状态摘要字典
        """
        return {
            'iteration': self.iteration,
            'current_coverage': f"{self.get_current_coverage():.1f}%",
            'target_coverage': f"{self.target_coverage}%",
            'is_complete': self.is_complete,
            'has_errors': len(self.error_messages) > 0,
            'functions_count': len(self.code_analysis.functions) if self.code_analysis else 0,
            'test_functions_count': self.test_code.count('def test_') if self.test_code else 0
        }
