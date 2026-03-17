"""
工作流编排器 - 协调所有Agent完成测试生成任务
"""

import logging
from typing import Optional, Callable, TYPE_CHECKING

if TYPE_CHECKING:
    from GLMService import GLMService

from workflow.state import TestGenerationState
from agents.code_analyzer_agent import CodeAnalyzerAgent
from agents.test_generator_agent import TestGeneratorAgent
from agents.test_executor_agent import TestExecutorAgent
from agents.coverage_analyzer_agent import CoverageAnalyzerAgent


class AgenticTestGenerator:
    """Agentic测试生成编排器"""

    def __init__(self, glm_service: 'GLMService', upload_folder: str):
        """
        初始化编排器

        Args:
            glm_service: GLM服务实例
            upload_folder: 文件上传目录
        """
        self.logger = logging.getLogger("AgenticTestGenerator")

        # 初始化所有Agent
        self.code_analyzer = CodeAnalyzerAgent(glm_service)
        self.test_generator = TestGeneratorAgent(glm_service)
        self.test_executor = TestExecutorAgent(glm_service, upload_folder)
        self.coverage_analyzer = CoverageAnalyzerAgent(glm_service)

        # 状态回调函数，用于实时通知迭代进度
        self.status_callback: Optional[Callable[[dict], None]] = None

        # 存储session_id用于生成下载URL
        self.session_id: str = ""

        self.logger.info("AgenticTestGenerator 初始化完成")

    def set_status_callback(self, callback: Callable[[dict], None]):
        """
        设置状态回调函数

        Args:
            callback: 回调函数，接收状态字典
        """
        self.status_callback = callback

    def _emit_status(self, event_type: str, data: dict):
        """
        发送状态更新

        Args:
            event_type: 事件类型
            data: 事件数据
        """
        if self.status_callback:
            status = {
                'event': event_type,
                **data
            }
            self.logger.debug(f"发送事件: {event_type}")
            try:
                self.status_callback(status)
                self.logger.debug(f"事件 {event_type} 已传递给回调函数")
            except Exception as e:
                self.logger.error(f"发送事件 {event_type} 时出错: {str(e)}", exc_info=True)

    def generate_tests(
        self,
        source_code: str,
        original_requirements: str = "",
        test_requirements: str = "",
        module_name: str = "",
        target_coverage: float = 90.0,
        max_iterations: int = 3,
        session_id: str = ""
    ) -> TestGenerationState:
        """
        执行完整的测试生成工作流

        Args:
            source_code: 源代码
            original_requirements: 原始业务需求（功能规格）
            test_requirements: 测试策略需求（可选）
            module_name: 模块名
            target_coverage: 目标覆盖率
            max_iterations: 最大迭代次数

        Returns:
            最终状态
        """
        # 存储session_id
        self.session_id = session_id

        # 初始化状态
        state = TestGenerationState(
            source_code=source_code,
            original_requirements=original_requirements,
            test_requirements=test_requirements,
            module_name=module_name,
            target_coverage=target_coverage,
            max_iterations=max_iterations
        )

        self._log_header("开始Agentic测试生成流程")
        self.logger.info(f"模块: {module_name}")
        self.logger.info(f"目标覆盖率: {target_coverage}%")
        self.logger.info(f"最大迭代次数: {max_iterations}")
        self._log_separator()

        # 发送开始事件
        self._emit_status('start', {
            'module_name': module_name,
            'target_coverage': target_coverage,
            'max_iterations': max_iterations
        })

        try:
            # ===== 阶段1: 代码分析（只执行一次）=====
            self._log_phase(1, "代码分析")
            self._emit_status('phase', {
                'iteration': 0,
                'phase': 'code_analysis',
                'phase_name': '代码分析',
                'status': 'running'
            })

            state = self.code_analyzer.execute(state)

            if state.error_messages:
                self.logger.error("代码分析阶段出错，终止流程")
                self._emit_status('error', {'message': state.error_messages[-1]})
                return state

            self._log_phase_result(state)
            self._emit_status('phase', {
                'iteration': 0,
                'phase': 'code_analysis',
                'phase_name': '代码分析',
                'status': 'completed',
                'data': {
                    'functions_count': len(state.code_analysis.functions) if state.code_analysis else 0,
                    'classes_count': len(state.code_analysis.classes) if state.code_analysis else 0,
                    'branches_count': len(state.code_analysis.branches) if state.code_analysis else 0
                }
            })

            # ===== 迭代循环 =====
            while state.should_continue() and state.iteration < state.max_iterations:
                iteration_num = state.iteration + 1
                self._log_iteration_header(iteration_num)

                # 发送迭代开始事件
                self._emit_status('iteration_start', {
                    'iteration': iteration_num,
                    'current_coverage': state.get_current_coverage()
                })

                # 阶段2: 生成测试
                self._log_phase(2, "生成测试用例")
                self._emit_status('phase', {
                    'iteration': iteration_num,
                    'phase': 'test_generation',
                    'phase_name': '生成测试用例',
                    'status': 'running'
                })

                state = self.test_generator.execute(state)

                if state.error_messages:
                    self.logger.warning(f"测试生成出错: {state.error_messages[-1]}")
                    self._emit_status('error', {'message': state.error_messages[-1]})
                    break

                self._log_phase_result(state)
                test_count = state.test_code.count('def test_') if state.test_code else 0
                self._emit_status('phase', {
                    'iteration': iteration_num,
                    'phase': 'test_generation',
                    'phase_name': '生成测试用例',
                    'status': 'completed',
                    'data': {'test_count': test_count}
                })

                # 阶段3: 执行测试
                self._log_phase(3, "执行测试")
                self._emit_status('phase', {
                    'iteration': iteration_num,
                    'phase': 'test_execution',
                    'phase_name': '执行测试',
                    'status': 'running'
                })

                state = self.test_executor.execute(state)

                if state.error_messages:
                    self.logger.warning(f"测试执行出错: {state.error_messages[-1]}")
                    self._emit_status('error', {'message': state.error_messages[-1]})
                    break

                current_coverage = state.get_current_coverage()
                pass_rate = state.get_pass_rate()  # 新增: 获取通过率

                self.logger.info(
                    f"✓ 测试执行完成, 覆盖率: {current_coverage:.1f}%, "
                    f"通过率: {pass_rate:.1f}%"  # 新增: 显示通过率
                )

                # 获取分支覆盖率
                branch_rate = '0%'
                if state.coverage_report and 'summary' in state.coverage_report:
                    branch_rate = state.coverage_report['summary'].get('branch_rate', '0%')

                self._emit_status('phase', {
                    'iteration': iteration_num,
                    'phase': 'test_execution',
                    'phase_name': '执行测试',
                    'status': 'completed',
                    'data': {
                        'line_coverage': current_coverage,
                        'branch_coverage': branch_rate,
                        'pass_rate': pass_rate  # 新增: 发送通过率
                    }
                })

                # 阶段4: 分析覆盖率
                self._log_phase(4, "分析覆盖率")
                self._emit_status('phase', {
                    'iteration': iteration_num,
                    'phase': 'coverage_analysis',
                    'phase_name': '分析覆盖率',
                    'status': 'running'
                })

                state = self.coverage_analyzer.execute(state)

                if state.error_messages:
                    self.logger.warning(f"覆盖率分析出错: {state.error_messages[-1]}")
                    self._emit_status('error', {'message': state.error_messages[-1]})
                    break

                self._emit_status('phase', {
                    'iteration': iteration_num,
                    'phase': 'coverage_analysis',
                    'phase_name': '分析覆盖率',
                    'status': 'completed',
                    'data': {
                        'uncovered_lines': len(state.coverage_gaps.uncovered_lines) if state.coverage_gaps else 0,
                        'suggestions': len(state.coverage_gaps.suggestions) if state.coverage_gaps else 0
                    }
                })

                # 发送迭代完成事件
                self._emit_status('iteration_end', {
                    'iteration': iteration_num,
                    'current_coverage': state.get_current_coverage(),
                    'pass_rate': state.get_pass_rate(),  # 新增: 发送通过率
                    'target_reached': state.is_complete
                })

                # 新增: 记录迭代历史
                state.iteration_history.append({
                    'iteration': iteration_num,
                    'coverage': current_coverage,
                    'pass_rate': pass_rate
                })

                # 检查是否完成 (should_continue()已包含新的质量目标检查)
                if state.is_complete:
                    self.logger.info("✓ 已达到质量目标!")
                    break

                # 检查覆盖率提升
                if iteration_num > 1:
                    # 检查是否有进步（简单检查）
                    self.logger.info(f"准备下一轮迭代，生成补充测试...")

                # 准备下一轮迭代
                state.iteration += 1

                self._log_separator()

            # ===== 完成 =====
            self._log_completion(state)

            # 发送完成事件（包含所有结果数据）
            self.logger.info("准备发送complete事件...")
            summary = self.get_summary(state)

            # 准备结果数据
            test_filename = f'test_{state.module_name}.py'
            download_url = f'/download/{test_filename}?session_id={self.session_id}'

            # 安全地构建覆盖率报告
            safe_coverage_report = {
                'summary': state.coverage_report.get('summary', {}) if state.coverage_report else {},
                'line': str(state.coverage_report.get('line', '')) if state.coverage_report else '',
                'function': str(state.coverage_report.get('function', '')) if state.coverage_report else '',
                'branch': str(state.coverage_report.get('branch', '')) if state.coverage_report else ''
            }

            self.logger.info(f"Complete事件数据准备完成: iterations={summary['iterations']}, "
                           f"final_coverage={summary['final_coverage']:.1f}%, "
                           f"test_count={summary['test_functions_count']}")

            self._emit_status('complete', {
                'success': summary['success'],
                'iterations': summary['iterations'],
                'final_coverage': summary['final_coverage'],
                'target_coverage': summary['target_coverage'],
                'test_count': summary['test_functions_count'],
                # 添加结果数据
                'coverage_report': safe_coverage_report,
                'test_output': state.pytest_output or 'Tests completed',
                'download_url': download_url,
                'test_code': state.test_code or '',
                'source_filename': f'{state.module_name}.py'  # 添加源文件名
            })

            self.logger.info("Complete事件已发送到回调队列")

        except Exception as e:
            self.logger.error(f"工作流执行异常: {str(e)}", exc_info=True)
            state.error_messages.append(f"工作流异常: {str(e)}")

            # 即使出错，也发送complete事件（包含部分结果）
            try:
                summary = self.get_summary(state)
                test_filename = f'test_{state.module_name}.py'
                download_url = f'/download/{test_filename}?session_id={self.session_id}'

                safe_coverage_report = {
                    'summary': state.coverage_report.get('summary', {}) if state.coverage_report else {},
                    'line': str(state.coverage_report.get('line', '')) if state.coverage_report else '',
                    'function': str(state.coverage_report.get('function', '')) if state.coverage_report else '',
                    'branch': str(state.coverage_report.get('branch', '')) if state.coverage_report else ''
                }

                self._emit_status('complete', {
                    'success': False,
                    'iterations': summary['iterations'],
                    'final_coverage': summary['final_coverage'],
                    'target_coverage': summary['target_coverage'],
                    'test_count': summary['test_functions_count'],
                    'coverage_report': safe_coverage_report,
                    'test_output': state.pytest_output or 'Tests partially completed',
                    'download_url': download_url,
                    'test_code': state.test_code or '',
                    'source_filename': f'{state.module_name}.py',  # 添加源文件名
                    'error_occurred': True,
                    'error_message': str(e)
                })
            except Exception as emit_error:
                self.logger.error(f"Failed to emit complete event after error: {emit_error}")

        return state

    def get_execution_log(self, state: TestGenerationState) -> list:
        """
        获取执行日志

        Args:
            state: 状态对象

        Returns:
            Agent消息列表
        """
        return state.agent_messages

    def get_summary(self, state: TestGenerationState) -> dict:
        """
        获取执行摘要

        Args:
            state: 状态对象

        Returns:
            摘要字典
        """
        return {
            'success': not bool(state.error_messages),
            'iterations': len(state.iteration_history),  # 修复: 使用历史记录长度，准确反映已完成的迭代次数
            'final_coverage': state.get_current_coverage(),
            'target_coverage': state.target_coverage,
            'is_complete': state.is_complete,
            'test_functions_count': state.test_code.count('def test_') if state.test_code else 0,
            'error_count': len(state.error_messages),
            'agent_messages_count': len(state.agent_messages)
        }

    # ===== 日志辅助方法 =====

    def _log_header(self, message: str):
        """打印头部日志"""
        self.logger.info("=" * 60)
        self.logger.info(message)
        self.logger.info("=" * 60)

    def _log_separator(self):
        """打印分隔线"""
        self.logger.info("-" * 60)

    def _log_iteration_header(self, iteration: int):
        """打印迭代头部"""
        self.logger.info("")
        self.logger.info("=" * 60)
        self.logger.info(f"迭代 {iteration}")
        self.logger.info("=" * 60)

    def _log_phase(self, phase_num: int, phase_name: str):
        """打印阶段信息"""
        self.logger.info(f"\n[阶段 {phase_num}] {phase_name}")

    def _log_phase_result(self, state: TestGenerationState):
        """打印阶段结果"""
        if state.agent_messages:
            last_msg = state.agent_messages[-1]
            data = last_msg.get('data', {})
            if data:
                for key, value in data.items():
                    self.logger.info(f"  {key}: {value}")

    def _log_completion(self, state: TestGenerationState):
        """打印完成信息"""
        self.logger.info("")
        self._log_header("测试生成流程完成")

        summary = self.get_summary(state)

        self.logger.info(f"总迭代次数: {summary['iterations']}")
        self.logger.info(f"最终覆盖率: {summary['final_coverage']:.1f}%")
        self.logger.info(f"目标覆盖率: {summary['target_coverage']}%")
        self.logger.info(f"是否达标: {'是' if summary['is_complete'] else '否'}")
        self.logger.info(f"生成测试函数: {summary['test_functions_count']}个")

        if state.error_messages:
            self.logger.warning(f"错误数量: {len(state.error_messages)}")
            for i, error in enumerate(state.error_messages, 1):
                self.logger.warning(f"  错误{i}: {error}")
        else:
            self.logger.info("无错误")

        self._log_separator()

        # 打印覆盖率摘要
        if state.coverage_report and 'summary' in state.coverage_report:
            summary_data = state.coverage_report['summary']
            self.logger.info("覆盖率详情:")
            self.logger.info(f"  行覆盖率: {summary_data.get('line_rate', 'N/A')}")
            self.logger.info(f"  函数覆盖率: {summary_data.get('function_rate', 'N/A')}")
            if 'branch_rate' in summary_data:
                self.logger.info(f"  分支覆盖率: {summary_data.get('branch_rate', 'N/A')}")

        self._log_header("流程结束")
