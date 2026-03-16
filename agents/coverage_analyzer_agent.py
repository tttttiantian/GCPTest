"""
覆盖率分析Agent - 负责分析覆盖率缺口并生成优化建议
"""

import ast
import re
from typing import List
from .base_agent import BaseAgent
from workflow.state import TestGenerationState, CoverageGap
from config import AgenticConfig


class CoverageAnalyzerAgent(BaseAgent):
    """覆盖率分析Agent"""

    def __init__(self, glm_service):
        super().__init__(glm_service, "CoverageAnalyzer")

    def execute(self, state: TestGenerationState) -> TestGenerationState:
        """
        分析覆盖率缺口

        Args:
            state: 当前状态

        Returns:
            更新后的状态
        """
        self.log(state, "分析覆盖率缺口")

        # 检查当前覆盖率
        current_coverage = state.get_current_coverage()

        # 如果已达到目标，标记为完成
        if current_coverage >= state.target_coverage:
            self.log(state, f"已达到目标覆盖率 {state.target_coverage}%")
            state.is_complete = True
            return state

        # 如果没有覆盖率报告，无法分析
        if not state.coverage_report:
            error_msg = "缺少覆盖率报告，无法分析缺口"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)
            return state

        try:
            # 1. 解析覆盖率报告，提取缺口
            gaps = self._analyze_coverage_gaps(state)

            # 2. 使用LLM生成优化建议
            if gaps.uncovered_lines or gaps.uncovered_functions or gaps.uncovered_branches:
                suggestions = self._generate_suggestions_with_llm(state, gaps)
                gaps.suggestions = suggestions
            else:
                gaps.suggestions = []

            state.coverage_gaps = gaps

            self.log(state, "覆盖率缺口分析完成", {
                'uncovered_lines_count': len(gaps.uncovered_lines),
                'uncovered_functions_count': len(gaps.uncovered_functions),
                'uncovered_branches_count': len(gaps.uncovered_branches),
                'suggestions_count': len(gaps.suggestions)
            })

        except Exception as e:
            self.log_error(state, e)

        return state

    def _analyze_coverage_gaps(self, state: TestGenerationState) -> CoverageGap:
        """
        分析覆盖率缺口

        Args:
            state: 当前状态

        Returns:
            覆盖率缺口对象
        """
        coverage_report = state.coverage_report

        # 解析未覆盖的行
        uncovered_lines = self._parse_uncovered_lines(coverage_report)

        # 解析未覆盖的分支
        uncovered_branches = self._parse_uncovered_branches(coverage_report)

        # 解析未覆盖的函数
        uncovered_functions = self._parse_uncovered_functions(
            state.source_code,
            coverage_report,
            state.code_analysis
        )

        return CoverageGap(
            uncovered_lines=uncovered_lines,
            uncovered_branches=uncovered_branches,
            uncovered_functions=uncovered_functions,
            suggestions=[]  # 将在后续填充
        )

    def _parse_uncovered_lines(self, coverage_report: dict) -> List[int]:
        """
        解析未覆盖的代码行

        Args:
            coverage_report: 覆盖率报告

        Returns:
            未覆盖的行号列表
        """
        uncovered_lines = []

        # 从line报告中提取
        line_report = coverage_report.get('line', '')

        if not line_report:
            return uncovered_lines

        # 查找包含源代码文件的行（排除测试文件）
        # 格式示例: "calculator.py    10      8     65%   10-12, 18"
        for line in line_report.split('\n'):
            # 跳过表头和分隔线
            if 'Name' in line or '---' in line or 'TOTAL' in line:
                continue

            # 只处理源代码文件（不包含test_）
            if '.py' in line and 'test_' not in line:
                # 检查是否有"Missing"列
                if 'Missing' in line_report:
                    # 格式: "calculator.py  15  5  65%  10-12, 18"
                    # Missing列可能包含多个部分（被空格分隔）
                    parts = line.split()
                    if len(parts) >= 5:
                        # 从第5个元素开始，都可能是Missing的行号
                        # 找到百分比后面的所有部分
                        percent_index = -1
                        for i, part in enumerate(parts):
                            if '%' in part:
                                percent_index = i
                                break

                        if percent_index >= 0 and percent_index < len(parts) - 1:
                            # 百分比后面的所有部分都是Missing行号
                            for missing_part in parts[percent_index + 1:]:
                                if re.search(r'\d', missing_part):
                                    # 移除可能的逗号
                                    missing_part = missing_part.rstrip(',')
                                    line_numbers = self._parse_line_ranges(missing_part)
                                    uncovered_lines.extend(line_numbers)
                else:
                    # 没有显式的"Missing"列头，尝试查找最后的非百分比部分
                    parts = line.split()
                    if len(parts) >= 5:
                        # 从后往前找所有包含数字但不是百分比的部分
                        for part in reversed(parts):
                            if '%' in part:
                                break  # 遇到百分比就停止
                            if re.search(r'\d', part):
                                part = part.rstrip(',')
                                line_numbers = self._parse_line_ranges(part)
                                uncovered_lines.extend(line_numbers)

        return sorted(list(set(uncovered_lines)))

    def _parse_line_ranges(self, range_str: str) -> List[int]:
        """
        解析行号范围字符串

        Args:
            range_str: 行号范围字符串，如 "5-6, 10-12, 15"

        Returns:
            行号列表
        """
        line_numbers = []

        # 分割逗号
        parts = range_str.split(',')

        for part in parts:
            part = part.strip()

            if '-' in part:
                # 范围，如 "5-6"
                try:
                    start, end = part.split('-')
                    start = int(start)
                    end = int(end)
                    line_numbers.extend(range(start, end + 1))
                except ValueError:
                    continue
            else:
                # 单个行号
                try:
                    line_numbers.append(int(part))
                except ValueError:
                    continue

        return line_numbers

    def _parse_uncovered_branches(self, coverage_report: dict) -> List[str]:
        """
        解析未覆盖的分支

        Args:
            coverage_report: 覆盖率报告

        Returns:
            未覆盖分支的描述列表
        """
        uncovered_branches = []

        branch_report = coverage_report.get('branch', '')

        if not branch_report:
            return uncovered_branches

        # 查找分支覆盖率不是100%的行
        # 格式可能包含 "Missing branches" 信息
        for line in branch_report.split('\n'):
            if 'Missing' in line and 'branch' in line.lower():
                # 提取分支信息
                # 这里简化处理，实际可能需要更复杂的解析
                uncovered_branches.append(line.strip())

        return uncovered_branches

    def _parse_uncovered_functions(
        self,
        source_code: str,
        coverage_report: dict,
        code_analysis
    ) -> List[str]:
        """
        基于行号范围识别未测试的函数（通用方法）

        策略：
        1. 从coverage report解析uncovered_lines
        2. 对每个函数，检查其行号范围是否完全在uncovered_lines中
        3. 如果函数的所有行都未覆盖 → 该函数未被测试

        Args:
            source_code: 源代码
            coverage_report: 覆盖率报告
            code_analysis: 代码分析结果

        Returns:
            未覆盖函数名列表
        """
        uncovered_functions = []

        try:
            # 步骤1：解析未覆盖的行号
            uncovered_lines = set()
            line_report = coverage_report.get('line', '')

            if not line_report:
                return uncovered_functions

            # 从报告中提取Missing列（例如："67-79, 93-103"）
            for line in line_report.split('\n'):
                # 跳过表头、分隔线和TOTAL行
                if 'Name' in line or '---' in line or 'TOTAL' in line:
                    continue

                # 只处理源代码文件（不包含test_）
                if '.py' in line and 'test_' not in line:
                    parts = line.split()

                    # 找到百分比列
                    percent_index = -1
                    for i, part in enumerate(parts):
                        if '%' in part:
                            percent_index = i
                            break

                    # 百分比后面的所有部分都是Missing行号
                    if percent_index >= 0 and percent_index < len(parts) - 1:
                        for missing_part in parts[percent_index + 1:]:
                            if re.search(r'\d', missing_part):
                                # 移除可能的逗号
                                missing_part = missing_part.rstrip(',')
                                # 使用已有的_parse_line_ranges方法
                                line_numbers = self._parse_line_ranges(missing_part)
                                uncovered_lines.update(line_numbers)

            # 步骤2：检查每个公开函数是否被覆盖
            if code_analysis and hasattr(code_analysis, 'functions'):
                for func in code_analysis.functions:
                    # 只检查公开函数（无下划线前缀）
                    if func.get('is_public', True):
                        func_start = func.get('lineno')
                        func_end = func.get('end_lineno', func_start)

                        if func_start and func_end:
                            # 函数的所有行号
                            func_lines = set(range(func_start, func_end + 1))

                            # 计算未覆盖比例
                            if len(func_lines) > 0:
                                uncovered_in_func = func_lines & uncovered_lines
                                uncovered_ratio = len(uncovered_in_func) / len(func_lines)

                                # 如果函数的至少80%的行都未覆盖 → 认为该函数未被测试
                                if uncovered_ratio >= 0.8:
                                    uncovered_functions.append(func['name'])
                                    self.logger.info(
                                        f"识别到未测试函数: {func['name']} "
                                        f"(第{func_start}-{func_end}行, "
                                        f"未覆盖率{uncovered_ratio*100:.0f}%)"
                                    )

            return uncovered_functions

        except Exception as e:
            self.logger.warning(f"解析未覆盖函数失败: {e}")
            return []

    def _generate_suggestions_with_llm(
        self,
        state: TestGenerationState,
        gaps: CoverageGap
    ) -> List[str]:
        """
        使用LLM生成优化建议

        Args:
            state: 当前状态
            gaps: 覆盖率缺口

        Returns:
            建议列表
        """
        # 如果没有实际缺口，返回空
        if (not gaps.uncovered_lines and
            not gaps.uncovered_functions and
            not gaps.uncovered_branches):
            return []

        # 构建Prompt
        prompt = self._build_suggestion_prompt(state, gaps)

        try:
            # 调用LLM
            response = self._call_llm(
                prompt,
                temperature=AgenticConfig.ANALYSIS_TEMPERATURE
            )

            # 解析建议
            suggestions = self._parse_suggestions(response)

            return suggestions[:5]  # 最多返回5条建议

        except Exception as e:
            self.logger.warning(f"生成建议失败: {e}")
            # 返回默认建议
            return self._get_default_suggestions(gaps)

    def _build_suggestion_prompt(
        self,
        state: TestGenerationState,
        gaps: CoverageGap
    ) -> str:
        """
        构建建议生成Prompt

        Args:
            state: 当前状态
            gaps: 覆盖率缺口

        Returns:
            Prompt字符串
        """
        current_coverage = state.get_current_coverage()

        # 格式化缺口信息
        uncovered_lines_str = ', '.join(map(str, gaps.uncovered_lines[:10])) if gaps.uncovered_lines else "无"

        # 获取未覆盖行的代码上下文
        uncovered_code_context = self._get_uncovered_lines_context(
            state.source_code,
            gaps.uncovered_lines[:10]
        )

        prompt = f"""分析覆盖率缺口，给出3-5条具体的测试建议。

## 当前覆盖率
- 当前: {current_coverage:.1f}%
- 目标: {state.target_coverage}%
- 未覆盖行: {uncovered_lines_str}

## 未覆盖代码（需要覆盖的具体行）

{uncovered_code_context}

## 任务

分析每个未覆盖的行，给出具体的测试建议：
1. **这行代码在什么条件下执行？**（查看if条件、函数参数等）
2. **如何构造测试数据让它执行？**（具体的参数值、数据结构）
3. **注意区分两层验证**：
   - 如果是 `if 'key' not in data` → 测试时不包含key
   - 如果是 `if not data['key']` 或 `if data['key'] == ''` → 测试时包含key但值为空/None/[]
4. **注意数值条件**：
   - `if x >= 99` 的else → 需要 x < 99
   - 注意折扣：99×0.9=89.1 < 99（不满足>=99）

输出格式（每行一条建议）：
- 第X行：条件[...] → 测试数据[...]
- 第Y行：函数Z的else分支 → 使用无效参数[...]

给出建议：
"""
        return prompt

    def _get_uncovered_lines_context(self, source_code: str, line_numbers: List[int]) -> str:
        """
        获取未覆盖行的代码上下文

        Args:
            source_code: 源代码
            line_numbers: 未覆盖的行号列表

        Returns:
            格式化的代码上下文字符串
        """
        if not line_numbers:
            return "无未覆盖行"

        lines = source_code.split('\n')
        context_parts = []

        for line_no in sorted(line_numbers):
            if 1 <= line_no <= len(lines):
                # 获取上下文（前后各1行）
                start = max(0, line_no - 2)
                end = min(len(lines), line_no + 1)

                context_lines = []
                for i in range(start, end):
                    prefix = "→" if i == line_no - 1 else " "
                    context_lines.append(f"  {prefix} {i+1}: {lines[i]}")

                context_parts.append('\n'.join(context_lines))

        return '\n\n'.join(context_parts[:5])  # 最多显示5个上下文

    def _parse_suggestions(self, response: str) -> List[str]:
        """
        解析LLM响应中的建议

        Args:
            response: LLM响应

        Returns:
            建议列表
        """
        suggestions = []

        # 按行分割
        lines = response.split('\n')

        for line in lines:
            line = line.strip()

            # 查找以 "- " 或数字开头的建议
            if line.startswith('-') or line.startswith('•'):
                # 移除前缀
                suggestion = line.lstrip('-•').strip()
                if suggestion and len(suggestion) > 10:  # 确保不是空建议
                    suggestions.append(suggestion)
            elif re.match(r'^\d+[.、)]', line):
                # 匹配 "1. " 或 "1、" 或 "1)" 格式
                suggestion = re.sub(r'^\d+[.、)]', '', line).strip()
                if suggestion and len(suggestion) > 10:
                    suggestions.append(suggestion)

        return suggestions

    def _get_default_suggestions(self, gaps: CoverageGap) -> List[str]:
        """
        获取默认建议

        Args:
            gaps: 覆盖率缺口

        Returns:
            默认建议列表
        """
        suggestions = []

        if gaps.uncovered_functions:
            suggestions.append(
                f"为未覆盖的函数 {', '.join(gaps.uncovered_functions[:3])} 增加测试用例"
            )

        if gaps.uncovered_lines:
            suggestions.append(
                f"针对未覆盖的代码行（第 {', '.join(map(str, gaps.uncovered_lines[:5]))} 行）增加测试"
            )

        if gaps.uncovered_branches:
            suggestions.append(
                "增加分支覆盖测试，确保所有if/else路径都被执行"
            )

        if not suggestions:
            suggestions.append("增加边界条件和异常情况的测试")

        return suggestions
