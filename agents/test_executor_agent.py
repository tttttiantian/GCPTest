"""
测试执行Agent - 负责运行测试并收集覆盖率
"""

import os
import tempfile
from .base_agent import BaseAgent
from workflow.state import TestGenerationState, TestQualityMetrics


class TestExecutorAgent(BaseAgent):
    """测试执行Agent"""

    def __init__(self, glm_service, upload_folder: str):
        """
        初始化TestExecutorAgent

        Args:
            glm_service: GLM服务实例
            upload_folder: 上传文件夹路径
        """
        super().__init__(glm_service, "TestExecutor")
        self.upload_folder = upload_folder

    def execute(self, state: TestGenerationState) -> TestGenerationState:
        """
        执行测试并收集覆盖率

        Args:
            state: 当前状态

        Returns:
            更新后的状态
        """
        self.log(state, "执行测试用例")

        if not state.test_code:
            error_msg = "缺少测试代码，无法执行测试"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)
            return state

        try:
            # 1. 保存源文件和测试文件
            source_file_path = self._save_source_file(state)
            test_file_path = self._save_test_file(state)

            self.log(state, f"文件保存成功", {
                'source_file': os.path.basename(source_file_path),
                'test_file': os.path.basename(test_file_path)
            })

            # 2. 运行pytest并收集覆盖率
            coverage_report, pytest_output = self._run_pytest_with_coverage(
                test_file_path,
                source_file_path,
                state.module_name
            )

            state.coverage_report = coverage_report
            state.pytest_output = pytest_output  # 保存pytest输出

            # 3. 提取当前覆盖率
            current_coverage = state.get_current_coverage()

            # 3.5 新增: 解析质量指标
            quality_metrics = self._parse_test_results(pytest_output)
            state.quality_metrics = quality_metrics
            pass_rate = quality_metrics.pass_rate

            self.log(state, f"测试执行完成", {
                'coverage': f"{current_coverage:.1f}%",
                'pass_rate': f"{pass_rate:.1f}%",  # 新增
                'passed': quality_metrics.passed_tests,  # 新增
                'failed': quality_metrics.failed_tests,  # 新增
                'line_rate': coverage_report.get('summary', {}).get('line_rate', 'N/A'),
                'function_rate': coverage_report.get('summary', {}).get('function_rate', 'N/A')
            })

            # 4. 修改: 同时检查覆盖率和通过率
            if current_coverage >= state.target_coverage and pass_rate >= 99.0:
                state.is_complete = True
                self.log(state, f"✓ 达到目标: 覆盖率{current_coverage:.1f}%, 通过率{pass_rate:.1f}%")
            elif current_coverage >= state.target_coverage:
                self.log(state, f"覆盖率达标但有{quality_metrics.failed_tests}个失败测试, 继续优化")

        except Exception as e:
            self.log_error(state, e)

        return state

    def _save_source_file(self, state: TestGenerationState) -> str:
        """
        保存源代码文件

        Args:
            state: 当前状态

        Returns:
            源文件路径
        """
        source_filename = f'{state.module_name}.py'
        source_file_path = os.path.join(self.upload_folder, source_filename)

        with open(source_file_path, 'w', encoding='utf-8') as f:
            f.write(state.source_code)

        self.logger.info(f"源文件已保存: {source_file_path}")
        return source_file_path

    def _save_test_file(self, state: TestGenerationState) -> str:
        """
        保存测试文件

        Args:
            state: 当前状态

        Returns:
            测试文件路径
        """
        test_filename = f'test_{state.module_name}.py'
        test_file_path = os.path.join(self.upload_folder, test_filename)

        with open(test_file_path, 'w', encoding='utf-8') as f:
            f.write(state.test_code)

        self.logger.info(f"测试文件已保存: {test_file_path}")
        return test_file_path

    def _run_pytest_with_coverage(
        self,
        test_file_path: str,
        source_file_path: str,
        module_name: str
    ) -> tuple:
        """
        运行pytest并收集覆盖率

        Args:
            test_file_path: 测试文件路径
            source_file_path: 源文件路径
            module_name: 模块名

        Returns:
            (覆盖率报告字典, pytest输出)
        """
        # 导入app.py中的函数（延迟导入避免循环依赖）
        try:
            # 由于我们在GCPTest目录下，可以直接导入
            import sys
            import os

            # 确保app.py可以被导入
            current_dir = os.path.dirname(os.path.abspath(__file__))
            parent_dir = os.path.dirname(current_dir)
            if parent_dir not in sys.path:
                sys.path.insert(0, parent_dir)

            # 导入app.py中的函数
            from app import run_pytest_and_generate_coverage

            # 调用现有的函数
            coverage_reports, test_output = run_pytest_and_generate_coverage(test_file_path)

            self.logger.info("pytest执行成功")
            if test_output:
                self.logger.debug(f"测试输出: {test_output[:200]}...")

            return coverage_reports, test_output

        except ImportError as e:
            # 如果无法导入app.py，使用简化版本
            self.logger.warning(f"无法导入app.py: {e}，使用简化版本")
            return self._run_pytest_simplified(test_file_path, source_file_path)

        except Exception as e:
            self.logger.error(f"运行pytest失败: {e}")
            raise

    def _run_pytest_simplified(self, test_file_path: str, source_file_path: str) -> tuple:
        """
        简化版的pytest运行（用于测试环境）

        Args:
            test_file_path: 测试文件路径
            source_file_path: 源文件路径

        Returns:
            (简化的覆盖率报告, pytest输出)
        """
        import subprocess
        import re

        try:
            # 运行pytest with coverage
            result = subprocess.run(
                ['coverage', 'run', '--source', os.path.dirname(source_file_path),
                 '-m', 'pytest', test_file_path, '-v'],
                cwd=os.path.dirname(test_file_path),
                capture_output=True,
                text=True,
                timeout=60
            )

            # 获取覆盖率报告
            coverage_result = subprocess.run(
                ['coverage', 'report'],
                cwd=os.path.dirname(test_file_path),
                capture_output=True,
                text=True
            )

            # 解析覆盖率
            coverage_text = coverage_result.stdout

            # 提取行覆盖率（简单解析）
            line_coverage = 0.0
            for line in coverage_text.split('\n'):
                if '.py' in line and 'test_' not in line:
                    # 尝试提取百分比
                    match = re.search(r'(\d+)%', line)
                    if match:
                        line_coverage = float(match.group(1))
                        break

            # 组合pytest输出
            pytest_output = result.stdout + '\n' + result.stderr

            return {
                'summary': {
                    'line_rate': f'{line_coverage}%',
                    'branch_rate': 'N/A',
                    'function_rate': 'N/A'
                },
                'line': coverage_text,
                'function': 'Function coverage not available in simplified mode'
            }, pytest_output

        except subprocess.TimeoutExpired:
            raise Exception("测试执行超时")
        except Exception as e:
            raise Exception(f"简化版pytest执行失败: {e}")

    def _parse_test_results(self, pytest_output: str) -> TestQualityMetrics:
        """
        解析pytest输出, 提取质量指标

        Args:
            pytest_output: pytest执行输出

        Returns:
            质量指标对象
        """
        import re

        metrics = TestQualityMetrics()

        # 解析测试统计
        # 格式1: "3 failed, 16 passed in 0.05s"
        match = re.search(r'(\d+)\s+failed.*?(\d+)\s+passed', pytest_output)
        if match:
            metrics.failed_tests = int(match.group(1))
            metrics.passed_tests = int(match.group(2))
        else:
            # 格式2: "19 passed in 0.05s" (全部通过)
            match = re.search(r'(\d+)\s+passed', pytest_output)
            if match:
                metrics.passed_tests = int(match.group(1))
                metrics.failed_tests = 0

        metrics.total_tests = metrics.passed_tests + metrics.failed_tests

        if metrics.total_tests > 0:
            metrics.pass_rate = (metrics.passed_tests / metrics.total_tests) * 100.0
        else:
            metrics.pass_rate = 0.0

        self.logger.info(
            f"测试统计: {metrics.passed_tests}通过, "
            f"{metrics.failed_tests}失败, "
            f"通过率{metrics.pass_rate:.1f}%"
        )

        return metrics
