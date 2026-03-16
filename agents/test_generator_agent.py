"""
测试生成Agent - 负责生成和优化测试用例
"""

from typing import List, Dict, Optional, Tuple, Any
from .base_agent import BaseAgent
from .helpers.code_cleaner import CodeCleaner
from workflow.state import TestGenerationState
from config import AgenticConfig


class TestGeneratorAgent(BaseAgent):
    """测试生成Agent"""

    # 配置常量
    class Config:
        """TestGenerator专用配置常量"""
        # Prompt相关
        MAX_SOURCE_CODE_LENGTH = 3000  # prompt中源代码的最大长度
        SIMPLIFIED_CODE_LENGTH = 1500  # 精简代码的阈值
        MAX_FUNCTIONS_IN_PROMPT = 10  # prompt中显示的最大函数数量
        MAX_CLASSES_IN_PROMPT = 5  # prompt中显示的最大类数量

        # 显示限制
        MAX_UNCOVERED_LINES_DISPLAY = 8  # 显示的未覆盖行数上限
        MAX_UNCOVERED_CONTEXT_LINES = 5  # 未覆盖代码上下文的最大行数
        MAX_FAILED_TESTS_DISPLAY = 3  # 显示的失败测试数量上限
        MAX_EXISTING_TESTS_DISPLAY = 15  # 显示的已有测试数量上限
        MAX_SUGGESTIONS_DISPLAY = 3  # 显示的优化建议数量上限
        MAX_EDGE_CASES_DISPLAY = 3  # 显示的边界条件数量上限
        MAX_EXCEPTIONS_DISPLAY = 3  # 显示的异常数量上限

        # 上下文窗口
        CONTEXT_BEFORE_LINE = 3  # 未覆盖行之前的上下文行数
        CONTEXT_AFTER_LINE = 2  # 未覆盖行之后的上下文行数

        # 字段提取
        MIN_FIELD_OCCURRENCE = 2  # 字段被认为是"必需"的最小出现次数

        # 错误分析
        MAX_ERROR_CONTEXT_LINES = 20  # 错误详情查找的最大行数

        # LLM配置
        LLM_ANALYSIS_TEMPERATURE = 0.3  # 失败分析时的temperature
        LLM_ANALYSIS_MAX_TOKENS = 2000  # 失败分析的最大token数
        LLM_MAX_RETRIES = 3  # LLM调用失败的最大重试次数
        LLM_RETRY_INITIAL_DELAY = 1.0  # 初始重试延迟（秒）
        LLM_RETRY_MAX_DELAY = 10.0  # 最大重试延迟（秒）
        LLM_RETRY_BACKOFF_FACTOR = 2.0  # 指数退避因子

        # 代码验证
        MAX_CONSECUTIVE_EMPTY_LINES = 2  # 允许的最大连续空行数

        # 文档字符串截断
        MAX_DOCSTRING_LENGTH = 200  # prompt中docstring的最大长度
        MAX_DOCSTRING_IN_ANALYSIS = 150  # 分析中docstring的最大长度
        MAX_DOCSTRING_DISPLAY = 50  # 列表显示中docstring的最大长度

        # 日志
        MAX_LOG_RESPONSE_LENGTH = 500  # 日志中LLM响应的最大显示长度

    # 预编译的正则表达式（提升性能）
    import re as _re

    # 字段提取相关
    RE_FOR_FIELD = _re.compile(r"for\s+\w+\s+in\s*\[([^\]]+)\]")
    RE_FIELD_IN_LIST = _re.compile(r"['\"]([^'\"]+)['\"]")
    RE_NOT_IN_CHECK = _re.compile(r"if\s+['\"](\w+)['\"]\s+not\s+in\s+\w+")
    RE_GET_FIELD = _re.compile(r"\.get\(['\"](\w+)['\"]")

    # unittest转pytest转换相关
    RE_ASSERT_EQUAL = _re.compile(r'self\.assertEqual\((.*?),\s*(.*?)\)')
    RE_ASSERT_TRUE = _re.compile(r'self\.assertTrue\((.*?)\)')
    RE_ASSERT_FALSE = _re.compile(r'self\.assertFalse\((.*?)\)')
    RE_ASSERT_IS_NONE = _re.compile(r'self\.assertIsNone\((.*?)\)')
    RE_ASSERT_IS_NOT_NONE = _re.compile(r'self\.assertIsNotNone\((.*?)\)')
    RE_ASSERT_IN = _re.compile(r'self\.assertIn\((.*?),\s*(.*?)\)')

    # 测试失败解析相关
    RE_FAILED_TEST = _re.compile(r'::([a-zA-Z_]\w+)\s+FAILED')
    RE_NAME_ERROR = _re.compile(r'NameError:\s*(.+)')
    RE_ASSERTION_ERROR = _re.compile(r'assert\s+(.+?)\s+==\s+(.+?)(?:\s|$)')
    RE_ERROR_TYPE = _re.compile(r'(\w+Error):')

    # 代码清理相关
    RE_CHINESE_CHARS = _re.compile(r'[\u4e00-\u9fff]')
    RE_CHINESE_PUNCT = _re.compile(r'[、。，！？；：""''【】《》（）]')

    # 其他
    RE_MISSING_FIELD = _re.compile(r'缺少字段:\s*(\w+)')
    RE_JSON_BLOCK = _re.compile(r'```json\n(.*?)\n```', _re.DOTALL)
    RE_TEST_FUNCTION = _re.compile(r'def (test_\w+)\(')
    RE_DICT_ASSIGN = _re.compile(r"(\w+)\s*=\s*\{")

    def __init__(self, glm_service: Any):
        super().__init__(glm_service, "TestGenerator")
        # 模板缓存
        self._prompt_templates: Dict[str, str] = {}
        # 初始化代码清理器
        self.code_cleaner: CodeCleaner = CodeCleaner(self.Config, self.logger)

    def _load_prompt_template(self, template_name: str) -> str:
        """
        加载prompt模板文件

        Args:
            template_name: 模板文件名（不含.txt后缀）

        Returns:
            模板内容字符串
        """
        # 如果已缓存，直接返回
        if template_name in self._prompt_templates:
            return self._prompt_templates[template_name]

        # 加载模板文件
        import os
        template_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),  # 项目根目录
            'prompts',
            f'{template_name}.txt'
        )

        try:
            with open(template_path, 'r', encoding='utf-8') as f:
                template = f.read()
            # 缓存模板
            self._prompt_templates[template_name] = template
            self.logger.debug(f"成功加载prompt模板: {template_name}")
            return template
        except FileNotFoundError:
            self.logger.error(f"找不到prompt模板文件: {template_path}")
            raise
        except PermissionError as e:
            self.logger.error(f"无权限读取prompt模板文件: {template_path} - {e}")
            raise
        except UnicodeDecodeError as e:
            self.logger.error(f"prompt模板文件编码错误: {template_path} - {e}")
            raise
        except (IOError, OSError) as e:
            self.logger.error(f"读取prompt模板文件IO错误: {template_path} - {e}")
            raise

    def _call_llm_with_retry(self, prompt: str, temperature: Optional[float] = None, max_tokens: Optional[int] = None) -> str:
        """
        带重试机制的LLM调用

        Args:
            prompt: 提示词
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            LLM响应字符串

        Raises:
            Exception: 所有重试失败后抛出最后一次的异常
        """
        import time

        last_exception = None
        retry_delay = self.Config.LLM_RETRY_INITIAL_DELAY

        for attempt in range(self.Config.LLM_MAX_RETRIES):
            try:
                # 调用基类的LLM方法
                response = self._call_llm(
                    prompt,
                    temperature=temperature,
                    max_tokens=max_tokens
                )

                # 成功则返回
                if attempt > 0:
                    self.logger.info(f"✓ LLM调用成功（第{attempt + 1}次尝试）")
                return response

            except Exception as e:
                last_exception = e
                error_type = type(e).__name__

                # 判断是否应该重试
                is_retryable = self._is_retryable_error(e)

                if not is_retryable:
                    self.logger.error(f"LLM调用遇到不可重试错误: {error_type} - {str(e)}")
                    raise

                # 最后一次尝试失败，不再重试
                if attempt == self.Config.LLM_MAX_RETRIES - 1:
                    self.logger.error(
                        f"LLM调用失败，已达最大重试次数({self.Config.LLM_MAX_RETRIES}): "
                        f"{error_type} - {str(e)}"
                    )
                    break

                # 记录重试信息
                self.logger.warning(
                    f"LLM调用失败（第{attempt + 1}/{self.Config.LLM_MAX_RETRIES}次），"
                    f"{retry_delay:.1f}秒后重试: {error_type} - {str(e)[:100]}"
                )

                # 等待后重试
                time.sleep(retry_delay)

                # 指数退避：下次延迟加倍，但不超过最大值
                retry_delay = min(
                    retry_delay * self.Config.LLM_RETRY_BACKOFF_FACTOR,
                    self.Config.LLM_RETRY_MAX_DELAY
                )

        # 所有重试都失败，抛出最后的异常
        raise last_exception

    def _is_retryable_error(self, error: Exception) -> bool:
        """
        判断错误是否可重试

        Args:
            error: 异常对象

        Returns:
            True if 可重试, False otherwise
        """
        error_type = type(error).__name__
        error_message = str(error).lower()

        # 可重试的错误类型
        retryable_types = [
            'TimeoutError',
            'ConnectionError',
            'HTTPError',
            'RequestException',
            'APIError',
            'ServiceUnavailable',
            'RateLimitError',
        ]

        # 检查错误类型
        if error_type in retryable_types:
            return True

        # 检查错误消息中的关键词
        retryable_keywords = [
            'timeout',
            'timed out',
            'connection',
            'network',
            'rate limit',
            'too many requests',
            'service unavailable',
            '503',
            '502',
            '504',
            'gateway',
        ]

        for keyword in retryable_keywords:
            if keyword in error_message:
                return True

        # 默认不可重试（例如参数错误、认证错误等）
        return False

    def execute(self, state: TestGenerationState) -> TestGenerationState:
        """
        生成测试用例

        Args:
            state: 当前状态

        Returns:
            更新后的状态
        """
        if state.iteration == 0:
            # 初始生成
            return self._generate_initial_tests(state)
        else:
            # 补充生成
            return self._generate_gap_filling_tests(state)

    def _generate_initial_tests(self, state: TestGenerationState) -> TestGenerationState:
        """
        生成初始测试用例

        Args:
            state: 当前状态

        Returns:
            更新后的状态
        """
        self.log(state, "生成初始测试用例")

        if not state.code_analysis:
            error_msg = "缺少代码分析结果，无法生成测试"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)
            return state

        # 构建Prompt
        prompt = self._build_initial_prompt(state)

        try:
            # 调用LLM（带重试机制）
            response = self._call_llm_with_retry(
                prompt,
                temperature=AgenticConfig.GENERATION_TEMPERATURE,
                max_tokens=AgenticConfig.MAX_TOKENS
            )

            # 清理代码
            test_code = self.code_cleaner.clean_generated_code(response, state.module_name)

            state.test_code = test_code

            # 统计生成的测试函数数量
            test_count = test_code.count('def test_')

            self.log(state, f"初始测试用例生成完成，共{test_count}个测试函数", {
                'test_count': test_count,
                'code_lines': len(test_code.split('\n'))
            })

        except (ConnectionError, TimeoutError) as e:
            # 网络/连接错误（重试后仍失败）
            error_msg = f"LLM连接失败（已重试{self.Config.LLM_MAX_RETRIES}次）: {e}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)
        except SyntaxError as e:
            # 代码生成语法错误
            error_msg = f"生成的测试代码存在语法错误: {e}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)
        except Exception as e:
            # 其他未预期的错误
            error_msg = f"初始测试生成失败: {type(e).__name__} - {e}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)

        return state

    def _generate_gap_filling_tests(self, state: TestGenerationState) -> TestGenerationState:
        """
        生成补充测试用例（增强版：同时修复失败测试和提升覆盖率）

        Args:
            state: 当前状态

        Returns:
            更新后的状态
        """
        self.log(state, f"生成补充测试用例 (迭代 {state.iteration})")

        # 新增: 失败分析
        failure_analysis = self._analyze_test_failures(state)

        # 更新质量指标中的失败分类
        if state.quality_metrics:
            state.quality_metrics.code_bugs = failure_analysis['code_bugs']
            state.quality_metrics.test_bugs = failure_analysis['test_bugs']

        # 决定生成策略
        has_test_bugs = len(failure_analysis['test_bugs']) > 0
        has_code_bugs = len(failure_analysis['code_bugs']) > 0
        needs_coverage = (
            state.coverage_gaps and
            (state.coverage_gaps.uncovered_lines or
             state.coverage_gaps.uncovered_functions)
        )

        if has_code_bugs:
            self.logger.warning(
                f"检测到{len(failure_analysis['code_bugs'])}个代码问题, "
                "建议修复源代码后重新运行"
            )

        if has_test_bugs:
            self.logger.info(
                f"检测到{len(failure_analysis['test_bugs'])}个测试脚本错误, 将生成修复版本"
            )

        if not needs_coverage and not has_test_bugs:
            self.log(state, "无覆盖率缺口且无测试问题, 跳过补充生成")
            return state

        # 构建增强的prompt (包含失败反馈)
        prompt = self._build_gap_filling_prompt_v2(state, failure_analysis)

        try:
            # 调用LLM（带重试机制）
            response = self._call_llm_with_retry(
                prompt,
                temperature=AgenticConfig.GENERATION_TEMPERATURE,
                max_tokens=AgenticConfig.MAX_TOKENS
            )

            # 清理代码
            additional_tests = self.code_cleaner.clean_generated_code(response, state.module_name)

            # 自动修正常见错误
            additional_tests = self._auto_fix_common_errors(additional_tests, state)

            # 构建需要替换的测试函数集合
            replacement_test_names = set()
            if has_test_bugs:
                replacement_test_names = {bug['test_name'] for bug in failure_analysis['test_bugs'] if 'test_name' in bug}
                if replacement_test_names:
                    self.logger.info(f"标记 {len(replacement_test_names)} 个测试函数需要替换: {replacement_test_names}")

            # 智能合并代码（支持替换失败的测试）
            state.test_code = self._merge_test_code(state.test_code, additional_tests, replacement_test_names)

            # 统计新增的测试函数
            new_test_count = additional_tests.count('def test_')

            self.log(state, f"补充测试用例生成完成，新增{new_test_count}个测试函数", {
                'new_test_count': new_test_count,
                'total_tests': state.test_code.count('def test_')
            })

        except (ConnectionError, TimeoutError) as e:
            # 网络/连接错误（重试后仍失败）
            error_msg = f"LLM连接失败（已重试{self.Config.LLM_MAX_RETRIES}次）: {e}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)
        except SyntaxError as e:
            # 代码生成语法错误
            error_msg = f"补充测试代码存在语法错误: {e}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)
        except Exception as e:
            # 其他未预期的错误
            error_msg = f"补充测试生成失败: {type(e).__name__} - {e}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)

        return state

    def _truncate_source_code(self, source_code: str, max_length: Optional[int] = None) -> str:
        """
        截断源代码到指定长度

        Args:
            source_code: 原始源代码
            max_length: 最大长度（默认使用Config中的值）

        Returns:
            截断后的代码
        """
        if max_length is None:
            max_length = self.Config.MAX_SOURCE_CODE_LENGTH

        if len(source_code) <= max_length:
            return source_code
        else:
            return source_code[:max_length] + f'\n# ... (代码已截断，仅显示前{max_length}字符)'

    def _has_requirements(self, state: TestGenerationState) -> bool:
        """检查是否有原始需求"""
        return bool(state.original_requirements and state.original_requirements.strip())

    def _build_functions_section(self, analysis: Any) -> str:
        """
        构建需要测试的函数详情section

        Args:
            analysis: 代码分析结果

        Returns:
            函数详情的文本section
        """
        if not analysis or not hasattr(analysis, 'functions') or not analysis.functions:
            return ""

        functions_section = "\n## 需要测试的函数\n\n**必须为以下每个公开函数生成测试用例：**\n\n"

        for func in analysis.functions:
            if func.get('is_public', True):
                args_str = ', '.join(func.get('args', []))
                func_name = func.get('name', 'unknown')
                functions_section += f"### {func_name}({args_str})\n"

                # 添加函数位置信息
                start_line = func.get('lineno', '?')
                end_line = func.get('end_lineno', '?')
                functions_section += f"- 位置：第{start_line}-{end_line}行\n"

                # 添加文档字符串说明
                if func.get('docstring'):
                    docstring = func['docstring'][:self.Config.MAX_DOCSTRING_LENGTH]
                    functions_section += f"- 说明：{docstring}\n"

                # 明确要求
                functions_section += f"- **要求：必须生成至少3个测试用例**\n\n"

        return functions_section

    def _build_classes_section(self, analysis: 'CodeAnalysis') -> str:
        """
        构建类的详细信息section

        类似_build_functions_section()，为每个类提供：
        - 类名
        - 构造函数参数
        - 所有方法的签名
        - 方法的文档字符串

        Args:
            analysis: 代码分析结果

        Returns:
            格式化的类详情字符串
        """
        if not analysis.classes:
            return "  无类定义"

        lines = []
        for cls_info in analysis.classes[:self.Config.MAX_CLASSES_IN_PROMPT]:
            lines.append(f"\n类: {cls_info['name']}")
            lines.append(f"  位置: 第{cls_info.get('line_start', 'N/A')}-{cls_info.get('line_end', 'N/A')}行")

            # 添加方法列表
            if cls_info.get('methods'):
                lines.append("  方法:")
                for method in cls_info['methods'][:10]:  # 限制每个类最多10个方法
                    params_list = method.get('params', [])
                    # 过滤掉self参数
                    params_filtered = [p for p in params_list if p != 'self']
                    params = ', '.join(params_filtered)
                    lines.append(f"    - {method['name']}({params})")
                    if method.get('docstring'):
                        doc = method['docstring'][:100]  # 截断到100字符
                        lines.append(f"      描述: {doc}")
            else:
                lines.append("  方法: 无public方法")

            lines.append(f"  **要求: 为此类的所有方法生成测试，确保覆盖所有public方法**")

        return '\n'.join(lines)

    def _build_initial_prompt(self, state: TestGenerationState) -> str:
        """
        构建初始测试Prompt（优先基于原始需求）

        Args:
            state: 当前状态

        Returns:
            Prompt字符串
        """
        analysis = state.code_analysis

        # 格式化函数列表（只保留关键信息）
        functions_list = [f['name'] for f in analysis.functions[:self.Config.MAX_FUNCTIONS_IN_PROMPT]]
        classes_list = [c['name'] for c in analysis.classes[:self.Config.MAX_CLASSES_IN_PROMPT]]

        # 简化源代码片段
        source_code_snippet = self._truncate_source_code(state.source_code)

        # 根据是否有原始需求选择不同的prompt策略
        if self._has_requirements(state):
            self.logger.info("使用基于需求的测试生成策略（优先保证正确性）")
            return self._build_requirements_based_prompt(state, source_code_snippet, functions_list, analysis)
        else:
            self.logger.warning("未提供原始需求，使用基于代码的测试生成策略（可能无法发现逻辑错误）")
            return self._build_code_based_prompt(state, source_code_snippet, functions_list, analysis)

    def _build_requirements_based_prompt(self, state: TestGenerationState, source_code_snippet: str,
                                        functions_list: List[str], analysis: 'CodeAnalysis') -> str:
        """
        基于原始需求生成测试的Prompt（保证正确性 + 覆盖率）

        Args:
            state: 当前状态
            source_code_snippet: 代码片段
            functions_list: 函数列表
            analysis: 代码分析结果

        Returns:
            Prompt字符串
        """
        # 从需求中提取明确的值和规则
        requirements_values = self._extract_requirements_values(state.original_requirements)

        # 构建需要测试的函数详情
        functions_section = self._build_functions_section(analysis)

        # 构建类的详细信息（包含方法）
        classes_section = self._build_classes_section(analysis)

        prompt = f"""生成pytest测试代码。基于需求生成断言，确保高覆盖率。

## 原始需求（断言的唯一依据）

{state.original_requirements}

{requirements_values}
{functions_section}
{classes_section}

## 代码信息
- 模块: {state.module_name}
- 函数总数: {len(functions_list)}
- 类总数: {len(analysis.classes) if analysis.classes else 0}
- 分支数: {len(analysis.branches)}

```python
{source_code_snippet}
```

## 测试生成规则（必须严格遵守！）

### 关键：仔细阅读源代码
**在生成任何测试前，必须先分析源代码找出：**

1. **必需字段**：
   - 查找代码中的字段检查，如：
     * `for field in ['a', 'b', 'c']` → 说明a, b, c都是必需字段
     * `if 'key' not in data` → 说明key是必需字段
   - **所有测试的基础数据必须包含所有必需字段！**
   - 只有测试"缺少字段"时才故意省略某个字段

   示例：如果代码中有 `for field in ['order_id', 'items', 'customer_id']`
   → 所有测试必须包含这3个字段：`{{'order_id': '...', 'items': [...], 'customer_id': '...'}}`

2. **数值边界**：
   - 查找数值比较，如：
     * `if value >= 99` → 边界是99
     * 测试运费/折扣/其他逻辑时，要用触发该逻辑的值（<99或>=99）
     * 注意计算顺序：如果先打折再判断，要用折扣后的值

   示例：如果代码中有 `if is_vip or total >= 99: return 0.0`
   → 测试非0运费：is_vip=False **且** total<99（如50、80、98）

3. **特殊值集合**：
   - 查找 in 操作，如：
     * `if code in {{'A': 0.1, 'B': 0.2}}` → 'A'和'B'是有效值
     * `if province in ['X', 'Y']` → 'X'和'Y'是特殊省份

   示例：如果代码中有 `discounts = {{'SAVE10': 0.1, 'SAVE20': 0.2}}`
   → 测试有效折扣：'SAVE10' 或 'SAVE20'
   → 测试无效折扣：'INVALID'（不在字典中）

4. **验证顺序**：
   - 代码通常按顺序验证：先检查字段存在 → 再检查字段值
   - 如果要测试后面的逻辑，必须先通过前面的验证

   示例：如果代码先检查 `if 'items' not in data`，再检查 `if not data['items']`
   → 测试"缺少items字段"：`{{'order_id': '...'}}`（不包含items）
   → 测试"items为空"：`{{'order_id': '...', 'items': []}}`（包含items但为空）

### 规则1：断言值必须来自需求
**只测试需求中明确提到的功能和值，不要自己推测或添加需求外的内容！**

✅ 正确示例：
- 需求说"SAVE10折扣10%(×0.9)，100元→90元"
- 测试：assert apply_discount(100, 'SAVE10') == 90.0

❌ 错误示例：
- 需求只说SAVE10和SAVE20
- 测试却包含：assert apply_discount(100, 'SAVE30') == 70.0  # SAVE30不在需求中！

### 规则2：计算必须正确（极其重要！）
**必须根据测试数据逐步计算，绝不假设或猜测中间值！**

✅ 正确做法：
```python
# 示例：data = [{{'price': a, 'quantity': b}}, {{'price': c, 'quantity': d}}]
# 步骤1：a × b = result1
# 步骤2：c × d = result2
# 步骤3：result1 + result2 = total
# 步骤4（如有处理）：total × rate = final_result
# 每一步都要验证计算正确
assert function(data) == final_result  # 基于逐步计算的准确值
```

❌ 致命错误（必须避免！）：
- **假设中间结果**：不看输入数据具体值，凭感觉猜测结果
- **跳过计算步骤**：直接写期望值而不验证来源
- **忽视数据类型**：整数、浮点数、字符串混淆

### 规则2.1：理解条件优先级和短路逻辑
**多个条件组合时，要理解执行顺序。优先条件满足时，后续条件不会执行（短路）。**

通用原则：
```python
# 条件判断顺序很重要
if condition_A or condition_B:
    # 如果A为True，B不会被检查
    return result_1
elif condition_C:
    return result_2
else:
    return result_3
```

✅ 正确的测试思路：
1. **识别条件优先级**：哪个条件先判断？
2. **理解短路行为**：前面的条件为True时，后面的条件不执行
3. **构造测试场景**：
   - 测试第一个条件为True → 验证返回result_1（不管后续条件）
   - 测试第一个条件为False，第二个为True → 验证返回result_2
   - 测试所有条件为False → 验证返回result_3

❌ 常见错误：
- **忽略短路逻辑**：假设所有条件都会被检查
- **混淆条件顺序**：以为条件B总是影响结果，但实际上A为True时B根本不执行

### 规则3：覆盖所有分支
查看代码，确保每个if-else都有测试：
- 条件为True的测试
- 条件为False的测试
- 边界值测试（如>=N：测试N-1, N, N+1）

必须覆盖的典型分支：
1. **字段验证（两层检查模式）**：
   很多代码先检查字段存在，再检查值有效

   - **第1层-字段存在性**：`if 'key' not in data`
     → 测试：`data = {{}}`（不包含key）→ 触发"缺少字段"

   - **第2层-字段值有效性**：`if not data['key']` 或 `if data['key'] == ''`
     → 测试：`data = {{'key': ''}}`（包含key但为空/None/[]）→ 触发"值无效"

   **关键**：这是两个不同条件，需要不同的测试数据！

2. **数值边界**：
   - 对于条件 `if value >= threshold`：
     - 测试 value < threshold（触发else）
     - 测试 value == threshold（触发if）
     - 测试 value > threshold（触发if）
   - 注意计算顺序：如果有预处理（如折扣），要用处理后的值判断

3. **容器成员检查**：
   - `if key in dict`：测试key存在和不存在两种情况
   - `if item in list`：测试item在列表中和不在列表中

4. **逻辑运算**：
   - `if A or B`：测试A为真、B为真、都为假
   - `if A and B`：测试都为真、A假、B假

### 规则4：正确处理返回类型

**元组返回**：
```python
# ✓ 正确：访问元组元素
result = function()
assert result[0] == expected_first
assert result[1] == expected_second

# ✓ 正确：解包
first, second = function()
assert first == expected_first

# ✗ 错误：直接判断真假（元组总是truthy）
assert not function()  # 即使返回(False, "error")也会失败！
```

**字典返回**：
```python
result = function()
assert result['key'] == expected_value
```

**布尔/值返回**：
```python
assert function() == expected_value
assert function() is True/False
```

### 规则5：不要构造无效的异常测试

**错误做法**：
```python
# ✗ 在测试函数内raise异常无法测试被测代码的异常处理
def test_exception():
    try:
        raise Exception("test")
    except Exception as e:
        result = function(data)  # 这不会捕获内部异常
```

**正确做法**：
```python
# ✓ 构造会导致函数内部产生异常的输入
def test_exception():
    invalid_data = None  # 或其他会触发异常的数据
    result = function(invalid_data)
    assert 'error' in result  # 验证异常被正确处理
```

### 规则6：测试数据构造的逻辑正确性

**关键原则：直接构造目标状态的数据，不要通过操作不存在的数据来构造**

❌ 常见错误：
```python
# 错误：尝试从不包含某字段的字典中删除该字段
data = {{'field_a': 'value1', 'field_b': [...]}}  # 本来就没有field_c
data.pop('field_c')  # KeyError！不能pop不存在的键
```

✅ 正确做法：
```python
# 正确：直接构造缺少目标字段的字典
data = {{'field_a': 'value1', 'field_b': [...]}}  # 直接不包含field_c
result = validate(data)
assert result[0] == False  # 或根据返回类型判断
```

**区分"字段缺失"和"字段值无效"：**
```python
# 场景1：测试字段完全缺失
data = {{'field_a': 'value'}}  # 不包含field_b
# 可能触发："缺少字段"错误

# 场景2：测试字段存在但值无效
data = {{'field_a': 'value', 'field_b': ''}}  # 包含field_b但为空字符串
# 可能触发："字段值无效"错误

# 这是两种不同的验证层次，需要分别测试
```

## 输出格式要求

**⚠️ 绝对禁止使用中文标点符号在代码中！**
- ❌ 禁止：、。，！？；：""''（）【】
- ✓ 只用：. , ! ? ; : "" '' () []

**代码格式：**
```python
import pytest
from {state.module_name} import *

def test_function_description():
    '''Brief description in Chinese is OK in docstring'''
    # Prepare test data
    # Call function
    # Assert based on requirements
    assert result == expected
```

立即生成测试（只测试需求中的内容，确保计算正确，覆盖所有分支）：
"""
        return prompt

    def _extract_requirements_values(self, requirements: str) -> str:
        """
        从需求中提取明确的值和公式

        Args:
            requirements: 原始需求文本

        Returns:
            格式化的需求值说明
        """
        import re

        # 提取所有包含数字和运算符的行
        lines = requirements.split('\n')
        extracted = []

        for line in lines:
            # 查找包含具体数值、折扣、示例的行
            if any(keyword in line for keyword in ['×', '元', '%', ':', '→', '示例']):
                extracted.append(line.strip())

        if extracted:
            return "**需求中的明确值（必须使用这些值）：**\n" + '\n'.join(f"  - {item}" for item in extracted)
        return ""

    def _build_code_based_prompt(self, state: TestGenerationState, source_code_snippet: str,
                                 functions_list: List[str], analysis: 'CodeAnalysis') -> str:
        """
        基于代码逻辑生成测试的Prompt（后备方案）

        当没有原始需求时使用，主要关注覆盖率

        Args:
            state: 当前状态
            source_code_snippet: 代码片段
            functions_list: 函数列表
            analysis: 代码分析结果

        Returns:
            Prompt字符串
        """
        # 构建需要测试的函数详情
        functions_section = self._build_functions_section(analysis)

        # 构建类的详细信息（包含方法）
        classes_section = self._build_classes_section(analysis)

        prompt = f"""生成pytest测试代码。

⚠️ **重要提示**：未提供原始业务需求，将基于代码逻辑推理生成测试。
这种模式下生成的测试主要用于回归测试，可能无法发现业务逻辑错误。
建议用户提供原始需求以提高测试质量。

{functions_section}
{classes_section}

## 代码信息
- 模块: {state.module_name}
- 函数总数: {len(functions_list)}
- 类总数: {len(analysis.classes) if analysis.classes else 0}
- 分支数: {len(analysis.branches)}
- 边界条件: {', '.join(analysis.edge_cases[:self.Config.MAX_EDGE_CASES_DISPLAY])}
- 异常: {', '.join(analysis.exceptions[:self.Config.MAX_EXCEPTIONS_DISPLAY])}

## 源代码
```python
{source_code_snippet}
```

## 关键要求（非常重要！）

### 1. 分支覆盖要点
- **数值比较边界**：对于 `if total >= 99`，测试total=98（不满足）和total=99/100（满足）
- **字典键检查**：区分"键不存在"、"键存在但值为None"、"键存在但值为空容器"
  * 示例：`items`键缺失 vs `{{'items': None}}` vs `{{'items': []}}`
- **else分支**：确保if-else的两个分支都测试到
  * 示例：折扣码在字典中 vs 折扣码不在字典中（无效码）

### 2. 必需字段验证（关键！避免常见错误）

**理解验证层次：**
代码通常有两层验证：
1. 第一层：检查字段是否存在（`if 'items' not in data`）
2. 第二层：检查字段值是否有效（`if not data['items']` 或 `if len(data['items']) == 0`）

**测试设计原则：**
- **测试"字段缺失"**：专门的测试用例，测试第一层验证
  - 示例：`data = {{'order_id': '123', 'customer_id': '456'}}`（不包含items）
  - 期望：返回 "缺少字段: items" 或类似错误

- **测试"字段值无效"**：必须包含所有必需字段，只是值为空/None/[]
  - 示例：`data = {{'order_id': '123', 'items': [], 'customer_id': '456'}}`（包含items但为空）
  - 期望：返回 "无商品" 或类似业务错误

**常见错误（必须避免！）：**
❌ 错误：想测试"无商品"错误，但缺少items字段
   → `data = {{'order_id': '123', 'customer_id': '456'}}`（缺少items）
   → 实际会在第一层验证失败，返回"缺少字段"而不是"无商品"

✓ 正确：想测试"无商品"错误，应该包含items但值为空
   → `data = {{'order_id': '123', 'items': [], 'customer_id': '456'}}`（items存在但为空）
   → 会通过第一层验证，在第二层返回"无商品"错误

**测试顺序建议：**
1. 先测试字段缺失（每个必需字段一个测试）
2. 再测试字段值无效（空值、None、空列表等）
3. 最后测试正常业务逻辑

### 3. 条件优先级
- 注意代码中条件的执行顺序
- 示例：`if is_vip or total >= 99` - 两个条件都要分别测试

## 输出格式要求（极其重要！）

**代码格式规范：**
1. **缩进**: 使用4个空格缩进（不要使用Tab）
2. **顶层代码**: import语句和函数定义必须从行首开始（0缩进）
3. **函数体**: 函数内代码缩进4个空格
4. **嵌套代码**: 每层嵌套增加4个空格
5. **不要添加额外的整体缩进**: 确保所有代码可以直接作为Python文件运行

**必需内容：**
- import pytest
- from {state.module_name} import 需要的类/函数
- 测试函数 (def test_xxx)

**示例格式：**
```python
import pytest
from {state.module_name} import calculate

def test_calculate_positive():
    result = calculate(5)
    assert result == 10
```

立即生成符合格式规范的测试代码：
"""
        return prompt

    def _build_gap_filling_prompt(self, state: TestGenerationState, failed_test_feedback: str = "") -> str:
        """
        构建补充测试Prompt（优化版：保留必要上下文，适度精简）

        Args:
            state: 当前状态
            failed_test_feedback: 失败测试的反馈信息

        Returns:
            Prompt字符串
        """
        gaps = state.coverage_gaps
        current_coverage = state.get_current_coverage()

        # 格式化缺口信息
        uncovered_lines_str = ', '.join(map(str, gaps.uncovered_lines[:self.Config.MAX_UNCOVERED_LINES_DISPLAY])) if gaps.uncovered_lines else "无"
        suggestions_str = '\n'.join([f"  {s}" for s in gaps.suggestions[:self.Config.MAX_SUGGESTIONS_DISPLAY]]) if gaps.suggestions else "  无"

        # 获取未覆盖行的代码上下文（带更多上下文）
        uncovered_context = self._get_detailed_uncovered_context(state.source_code, gaps.uncovered_lines[:self.Config.MAX_UNCOVERED_CONTEXT_LINES])

        # 检查是否有原始需求
        requirements_section = ""
        if self._has_requirements(state):
            requirements_section = f"""
## 原始业务需求（断言值必须基于此）

{state.original_requirements}
"""

        # 添加失败测试反馈（如果有）
        feedback_section = ""
        if failed_test_feedback:
            feedback_section = f"""
## ⚠️ 上一轮测试中的错误（必须避免重复！）

{failed_test_feedback}

**重要提醒**：
- 检查所有必需字段是否包含
- 验证计算过程的每一步
- 确保测试数据能触发目标代码行
"""

        # 获取已有测试的函数名和简要信息
        existing_test_info = self._extract_existing_test_info(state.test_code)

        # 精简源代码：只保留函数签名和关键逻辑
        simplified_code = self._simplify_source_code(state.source_code)

        # 自动提取必需字段
        required_fields = self._extract_required_fields(state.source_code)
        required_fields_section = ""
        if required_fields:
            required_fields_section = f"""
## 📋 源代码中的必需字段（自动提取）

必需字段: {', '.join(required_fields)}

**所有测试数据都必须包含这些字段**（除非专门测试"缺少字段"的情况）
"""

        prompt = f"""当前覆盖率 {current_coverage:.1f}%，目标 {state.target_coverage}%。生成补充测试覆盖第 {uncovered_lines_str} 行。
{feedback_section}{required_fields_section}
{requirements_section}
## 源代码（关键部分）

```python
{simplified_code}
```

## 未覆盖代码上下文

{uncovered_context}

## 优化建议
{suggestions_str}

## 已有测试（避免重复）
{existing_test_info}

## 核心规则（必须严格遵守！）

### 🔥 规则0：条件优先级和短路逻辑（极其重要！）

**很多测试失败的原因：不理解条件执行的先后顺序**

#### 通用原则：
```python
if condition_A or condition_B:
    return result_1  # 如果A为True，B根本不会被检查（短路）
elif condition_C:
    return result_2
else:
    return result_3
```

#### 正确的测试策略：

**场景1：测试result_1的路径**
- 方法1：让condition_A为True（不管B是什么）
- 方法2：让condition_A为False，condition_B为True

**场景2：测试result_2的路径**
- condition_A必须为False
- condition_B必须为False（这样才不会进入第一个if）
- condition_C必须为True

**场景3：测试result_3的路径**
- 所有条件都必须为False

#### ❌ 常见致命错误：

```python
# 源代码示例：
if flag_X or value >= threshold:
    return special_value
if other_condition:
    return other_value
return default_value
```

**错误测试**：
```python
# 想测试other_value，但value=threshold+1
test_data = create_data(value=threshold+1)  # value >= threshold为True!
assert function(test_data) == other_value  # ❌ 失败！实际返回special_value
```

**正确测试**：
```python
# 想测试other_value，必须让前面的if为False
test_data = create_data(
    flag_X=False,  # 第一个条件为False
    value=threshold-1,  # 第二个条件为False
    other_condition=True  # 这个条件才为True
)
assert function(test_data) == other_value  # ✓ 正确
```

### 关键：仔细阅读源代码和未覆盖行的上下文
**在生成补充测试前，必须：**

1. **找出所有必需字段**：
   - 查看源代码中的字段验证逻辑
   - 如：`for field in ['a', 'b', 'c']` → a, b, c都必须包含
   - **所有测试数据必须包含所有必需字段**（除非专门测试"缺少字段"）

2. **理解未覆盖行的触发条件**：
   - **先找出前面所有的if条件**（从函数开始到目标行）
   - **分析哪些条件会阻止执行到目标行**
   - **构造数据让所有前置条件都"放行"，只有目标条件被触发**
   - 注意先决条件：要执行到某行，必须先通过前面的所有验证

3. **识别数值边界**：
   - 如代码有 `if value >= threshold`
   - 测试threshold的else分支，要用value < threshold的值

4. **注意or/and条件的短路行为**：
   - `if A or B`：A为True时，B不执行；要测试else，A和B都必须为False
   - `if A and B`：A为False时，B不执行；要测试True，A和B都必须为True

### 1. 两层验证模式
很多代码有两层验证，必须区分：
- **第1层-字段存在性**：`if 'key' not in data` → 测试时不包含key
- **第2层-字段值有效性**：`if not data['key']` 或 `if data['key'] == ''` → 测试时包含key但值为空/None/[]

**常见错误**：
❌ 混淆两层，导致触发错误的验证层
✓ 正确识别未覆盖行属于哪一层，构造相应数据

### 2. 数值边界条件
- 对于 `if value >= threshold`：
  - 触发if分支：value >= threshold
  - 触发else分支：value < threshold
- 注意计算顺序：如果有预处理（折扣、税费等），边界判断用的是处理**后**的值

### 3. 函数名和导入必须正确
- 只使用源代码中实际存在的函数
- 不要臆造函数名或类名
- 确保从正确的模块导入：`from {state.module_name} import actual_function`

### 4. 计算必须准确
- 手动逐步计算，写出计算过程
- 不要跳过步骤或猜测结果
- 验证算术运算（加减乘除、百分比等）

### 5. 返回类型处理
- **元组**：使用`result[0]`或解包，不要直接`assert not function()`
- **字典**：访问具体键`result['key']`
- **布尔**：明确比较`assert result == True`

### 6. 异常测试
- 不要在测试函数内手动raise异常
- 构造会导致被测函数内部产生异常的输入数据

## 输出格式要求

**⚠️ 绝对禁止在代码中使用中文标点符号！**
- ❌ 禁止：、。，！？；：""''（）【】
- ✓ 只用：. , ! ? ; : "" '' () []
- 注释和文档字符串中的中文可以用中文标点

**代码格式：**
```python
def test_cover_line_X():
    '''Target line X test description'''
    data = {{'key': 'value'}}
    result = correct_function_name(data)
    assert result == expected  # Calculate based on requirements
```

立即生成2-4个补充测试：
"""
        return prompt

    def _get_detailed_uncovered_context(self, source_code: str, line_numbers: List[int]) -> str:
        """
        获取未覆盖行的详细上下文

        Args:
            source_code: 源代码
            line_numbers: 未覆盖的行号列表

        Returns:
            格式化的代码上下文
        """
        if not line_numbers:
            return "无未覆盖行"

        lines = source_code.split('\n')
        context_parts = []

        for line_no in sorted(line_numbers[:self.Config.MAX_UNCOVERED_CONTEXT_LINES]):
            if 1 <= line_no <= len(lines):
                # 显示目标行和前后各N行
                start = max(0, line_no - self.Config.CONTEXT_BEFORE_LINE)
                end = min(len(lines), line_no + self.Config.CONTEXT_AFTER_LINE)

                context_lines = []
                for i in range(start, end):
                    prefix = "→" if i == line_no - 1 else " "
                    context_lines.append(f"{prefix} L{i+1}: {lines[i]}")

                context_parts.append('\n'.join(context_lines))

        return '\n\n'.join(context_parts)

    def _extract_existing_test_info(self, test_code: str) -> str:
        """
        提取已有测试的简要信息

        Args:
            test_code: 测试代码

        Returns:
            格式化的测试信息
        """
        test_names = []
        lines = test_code.split('\n')

        for line in lines:
            stripped = line.strip()
            if stripped.startswith('def test_'):
                test_name = stripped.split('(')[0].replace('def ', '')
                test_names.append(test_name)

        if not test_names:
            return "无"

        return ', '.join(test_names[:self.Config.MAX_EXISTING_TESTS_DISPLAY]) + (f" 等{len(test_names)}个测试" if len(test_names) > self.Config.MAX_EXISTING_TESTS_DISPLAY else "")

    def _simplify_source_code(self, source_code: str) -> str:
        """
        精简源代码，只保留函数签名和关键逻辑

        Args:
            source_code: 完整源代码

        Returns:
            精简后的代码
        """
        # 如果代码不长，直接返回
        if len(source_code) <= self.Config.SIMPLIFIED_CODE_LENGTH:
            return source_code

        # 保留import、函数定义、if/else关键行
        lines = source_code.split('\n')
        simplified = []
        in_function = False
        indent_level = 0

        for line in lines:
            stripped = line.strip()

            # 保留import、from、函数定义、类定义
            if any(stripped.startswith(kw) for kw in ['import ', 'from ', 'def ', 'class ']):
                simplified.append(line)
                if stripped.startswith('def ') or stripped.startswith('class '):
                    in_function = True
                    indent_level = len(line) - len(line.lstrip())
                continue

            # 在函数内，保留if/elif/else、return、重要逻辑
            if in_function:
                if any(kw in stripped for kw in ['if ', 'elif ', 'else:', 'return ', 'for ', 'while ']):
                    simplified.append(line)
                elif stripped and not stripped.startswith('#'):
                    # 保留关键赋值和调用（缩减显示）
                    if '=' in stripped or '(' in stripped:
                        simplified.append(line)

                # 函数结束检测
                if stripped and len(line) - len(line.lstrip()) <= indent_level and not stripped.startswith(('if ', 'elif ', 'else:', 'for ', 'while ')):
                    in_function = False

        result = '\n'.join(simplified)
        return result if result.strip() else source_code  # 如果精简失败，返回原代码

    def _clean_generated_code(self, response: str, module_name: str) -> str:
        """委托到CodeCleaner（已重构）"""
        return self.code_cleaner.clean_generated_code(response, module_name)

    def _merge_test_code(self, existing: str, additional: str, replacement_tests: set = None) -> str:
        """
        合并测试代码，避免重复导入和重复测试

        Args:
            existing: 现有测试代码
            additional: 补充测试代码
            replacement_tests: 需要替换的测试函数名集合（用于修复失败测试）

        Returns:
            合并后的代码
        """
        if replacement_tests is None:
            replacement_tests = set()

        existing_lines = existing.split('\n')
        additional_lines = additional.split('\n')

        # 提取现有的导入语句、fixtures和测试函数
        existing_imports = set()
        existing_fixtures = set()
        existing_test_names = set()  # 新增：记录已有的测试函数名
        existing_tests_start = 0

        for i, line in enumerate(existing_lines):
            stripped = line.strip()
            if stripped.startswith(('import ', 'from ')):
                existing_imports.add(line)
            elif stripped.startswith('@pytest.fixture'):
                # 记录fixture位置
                if i + 1 < len(existing_lines):
                    func_line = existing_lines[i + 1].strip()
                    if func_line.startswith('def '):
                        fixture_name = func_line.split('(')[0].replace('def ', '')
                        existing_fixtures.add(fixture_name)
            elif stripped.startswith('def test_'):
                # 记录测试函数名
                test_name = stripped.split('(')[0].replace('def ', '')
                existing_test_names.add(test_name)
                if existing_tests_start == 0:
                    existing_tests_start = i

        # 提取补充代码中的新导入、fixtures和测试函数
        new_imports = []
        new_fixtures = []
        new_tests = []
        in_fixture = False
        in_test = False
        current_func = []
        current_test_name = None

        for i, line in enumerate(additional_lines):
            stripped = line.strip()

            if stripped.startswith(('import ', 'from ')):
                if line not in existing_imports:
                    new_imports.append(line)
            elif stripped.startswith('@pytest.fixture'):
                in_fixture = True
                current_func = [line]
            elif in_fixture:
                current_func.append(line)
                if stripped and not stripped.startswith((' ', '\t', '#')) and i > 0:
                    # fixture定义结束
                    in_fixture = False
                    # 检查是否是新的fixture
                    func_line = current_func[1] if len(current_func) > 1 else ''
                    if 'def ' in func_line:
                        fixture_name = func_line.strip().split('(')[0].replace('def ', '')
                        if fixture_name not in existing_fixtures:
                            new_fixtures.extend(current_func)
                            new_fixtures.append('')  # 空行
                    current_func = []
            elif stripped.startswith('def test_'):
                # 提取测试函数名
                test_name = stripped.split('(')[0].replace('def ', '')

                # 检查是否重复或需要替换
                if test_name in existing_test_names:
                    # 检查是否是修复模式（需要替换失败测试）
                    if test_name in replacement_tests:
                        self.logger.info(f"替换失败测试函数: {test_name}")
                        in_test = True
                        current_test_name = test_name
                        current_func = [line]
                        # 不添加到existing_test_names，因为它会在合并时被删除
                    else:
                        self.logger.debug(f"跳过重复的测试函数: {test_name}")
                        in_test = False  # 标记为跳过
                        current_test_name = None
                else:
                    in_test = True
                    current_test_name = test_name
                    existing_test_names.add(test_name)  # 记录新测试
                    current_func = [line]
            elif in_test and current_test_name:
                current_func.append(line)
                # 检测函数结束（下一个函数开始或文件结束）
                if (i + 1 >= len(additional_lines) or
                    (additional_lines[i + 1].strip() and
                     not additional_lines[i + 1].startswith((' ', '\t', '#')))):
                    in_test = False
                    new_tests.extend(current_func)
                    new_tests.append('')  # 空行
                    current_func = []
                    current_test_name = None
            elif in_test and not current_test_name:
                # 跳过重复测试的函数体
                if (i + 1 >= len(additional_lines) or
                    (additional_lines[i + 1].strip() and
                     not additional_lines[i + 1].startswith((' ', '\t', '#')))):
                    in_test = False

        # 合并代码
        result_lines = []

        # 1. 添加所有导入
        result_lines.extend(existing_lines[:existing_tests_start])
        if new_imports:
            result_lines.extend(new_imports)
            result_lines.append('')

        # 2. 添加新的fixtures
        if new_fixtures:
            result_lines.extend(new_fixtures)

        # 3. 添加现有测试（过滤掉需要替换的）
        if replacement_tests:
            self.logger.info(f"过滤掉 {len(replacement_tests)} 个需要替换的测试函数")
            filtered_tests = []
            in_replacement_func = False
            for line in existing_lines[existing_tests_start:]:
                stripped = line.strip()
                # 检测是否进入需要替换的测试函数
                if stripped.startswith('def test_'):
                    test_name = stripped.split('(')[0].replace('def ', '')
                    if test_name in replacement_tests:
                        in_replacement_func = True
                        self.logger.debug(f"跳过需要替换的测试: {test_name}")
                        continue
                    else:
                        in_replacement_func = False

                # 如果不在替换函数中，添加这一行
                if not in_replacement_func:
                    filtered_tests.append(line)
                # 如果在替换函数中，检测是否到达函数结尾
                elif stripped and not stripped.startswith((' ', '\t', '#')):
                    in_replacement_func = False
                    # 这一行可能是下一个函数的开始，需要添加
                    if stripped.startswith('def '):
                        test_name = stripped.split('(')[0].replace('def ', '')
                        if test_name not in replacement_tests:
                            filtered_tests.append(line)
                            in_replacement_func = False

            result_lines.extend(filtered_tests)
        else:
            result_lines.extend(existing_lines[existing_tests_start:])

        # 4. 添加补充测试
        if new_tests:
            self.logger.info(f"新增 {new_tests.count('def test_')} 个不重复的测试函数")
            result_lines.append('')
            result_lines.append('# ===== 补充测试（迭代优化） =====')
            result_lines.append('')
            result_lines.extend(new_tests)
        else:
            self.logger.warning("补充测试全部重复，未添加新测试")

        return '\n'.join(result_lines)

    def _format_functions(self, functions: List[Dict[str, Any]]) -> str:
        """格式化函数列表"""
        if not functions:
            return "  无"
        result = []
        for func in functions:
            args_str = ', '.join(func['args'])
            result.append(f"  - {func['name']}({args_str})")
            if func.get('docstring'):
                result.append(f"    文档: {func['docstring'][:self.Config.MAX_DOCSTRING_DISPLAY]}...")
        return '\n'.join(result)

    def _format_classes(self, classes: List[Dict[str, Any]]) -> str:
        """格式化类列表"""
        if not classes:
            return "  无"
        result = []
        for cls in classes:
            method_names = [m['name'] for m in cls['methods']]
            result.append(f"  - {cls['name']}")
            result.append(f"    方法: {', '.join(method_names)}")
            if cls.get('docstring'):
                result.append(f"    文档: {cls['docstring'][:self.Config.MAX_DOCSTRING_DISPLAY]}...")
        return '\n'.join(result)

    def _normalize_indentation(self, code: str) -> str:
        """委托到CodeCleaner（已重构）"""
        return self.code_cleaner.normalize_indentation(code)

    def _remove_chinese_punctuation(self, code: str) -> str:
        """委托到CodeCleaner（已重构）"""
        return self.code_cleaner.remove_chinese_punctuation(code)

    def _validate_and_fix_syntax(self, code: str, module_name: str) -> str:
        """委托到CodeCleaner（已重构）"""
        return self.code_cleaner.validate_and_fix_syntax(code, module_name)

    def _extract_required_fields(self, source_code: str) -> List[str]:
        """
        从源代码中自动提取必需字段

        Args:
            source_code: 源代码

        Returns:
            必需字段列表
        """
        import ast
        import re

        required_fields = []

        try:
            # 方法1: 查找 for field in [...] 模式
            matches = self.RE_FOR_FIELD.findall(source_code)
            for match in matches:
                # 提取列表中的字符串
                fields = self.RE_FIELD_IN_LIST.findall(match)
                required_fields.extend(fields)

            # 方法2: 查找 if 'field' not in data 模式
            matches = self.RE_NOT_IN_CHECK.findall(source_code)
            required_fields.extend(matches)

            # 方法3: 查找 data.get('field') 或 data['field'] 模式（常用字段）
            matches = self.RE_GET_FIELD.findall(source_code)
            # 只取出现频率高的字段（至少N次）
            from collections import Counter
            field_counts = Counter(matches)
            frequent_fields = [field for field, count in field_counts.items() if count >= self.Config.MIN_FIELD_OCCURRENCE]
            required_fields.extend(frequent_fields)

            # 去重并保持顺序
            seen = set()
            unique_fields = []
            for field in required_fields:
                if field not in seen:
                    seen.add(field)
                    unique_fields.append(field)

            if unique_fields:
                self.logger.info(f"自动提取到必需字段: {unique_fields}")

            return unique_fields

        except re.error as e:
            # 正则表达式错误
            self.logger.warning(f"正则表达式错误，提取必需字段失败: {e}")
            return []
        except (AttributeError, TypeError) as e:
            # 数据类型错误
            self.logger.warning(f"数据类型错误，提取必需字段失败: {e}")
            return []
        except Exception as e:
            # 其他未预期错误
            self.logger.warning(f"提取必需字段失败: {type(e).__name__} - {e}")
            return []

    def _extract_test_failures(self, state: TestGenerationState) -> str:
        """
        从测试执行结果中提取失败信息

        Args:
            state: 当前状态

        Returns:
            格式化的失败信息
        """
        import re

        if not state.pytest_output:
            return ""

        feedback_lines = []
        output_lines = state.pytest_output.split('\n')

        # 查找FAILED行
        failed_tests = []
        for line in output_lines:
            if 'FAILED' in line:
                failed_tests.append(line.strip())

        if not failed_tests:
            return ""

        feedback_lines.append(f"**{len(failed_tests)}个测试失败，常见错误：**")
        feedback_lines.append("")

        # 分析错误类型
        error_types = {
            'missing_field': 0,
            'calculation': 0,
            'assertion': 0,
            'type_error': 0,
        }

        missing_fields = set()

        for line in output_lines:
            if '缺少字段' in line or 'missing' in line.lower():
                error_types['missing_field'] += 1
                # 提取缺少的字段名
                match = self.RE_MISSING_FIELD.search(line)
                if match:
                    missing_fields.add(match.group(1))
            elif 'assert' in line.lower() and '==' in line:
                error_types['assertion'] += 1
            elif 'TypeError' in line:
                error_types['type_error'] += 1
            elif 'AssertionError' in line:
                error_types['calculation'] += 1

        # 生成具体的反馈
        if error_types['missing_field'] > 0:
            fields_str = ', '.join(missing_fields) if missing_fields else "某些字段"
            feedback_lines.append(f"1. **缺少必需字段** ({error_types['missing_field']}次): 测试数据缺少 {fields_str}")
            feedback_lines.append(f"   → 修正：所有测试都必须包含这些字段（除非专门测试字段缺失）")
            feedback_lines.append("")

        if error_types['calculation'] > 0:
            feedback_lines.append(f"2. **计算错误** ({error_types['calculation']}次): 断言值计算不正确")
            feedback_lines.append(f"   → 修正：手动逐步计算，验证每一步的结果")
            feedback_lines.append("")

        if error_types['type_error'] > 0:
            feedback_lines.append(f"3. **类型错误** ({error_types['type_error']}次): 使用了错误的数据类型")
            feedback_lines.append(f"   → 修正：检查函数期望的参数类型")
            feedback_lines.append("")

        # 提取具体的失败示例（最多N个）
        feedback_lines.append("**失败示例：**")
        for i, failed_line in enumerate(failed_tests[:self.Config.MAX_FAILED_TESTS_DISPLAY], 1):
            feedback_lines.append(f"{i}. {failed_line}")

        return '\n'.join(feedback_lines)

    def _convert_unittest_to_pytest(self, code: str) -> str:
        """委托到CodeCleaner（已重构）"""
        return self.code_cleaner.convert_unittest_to_pytest(code)

    def _auto_fix_common_errors(self, test_code: str, state: TestGenerationState) -> str:
        """
        自动修正测试代码中的常见错误

        Args:
            test_code: 生成的测试代码
            state: 当前状态

        Returns:
            修正后的测试代码
        """
        import ast
        import re

        # 首先修复unittest格式到pytest格式
        test_code = self.code_cleaner.convert_unittest_to_pytest(test_code)

        # 提取必需字段
        required_fields = self._extract_required_fields(state.source_code)

        if not required_fields:
            return test_code  # 没有提取到必需字段，跳过修正

        self.logger.debug(f"开始自动修正测试代码，必需字段: {required_fields}")

        try:
            lines = test_code.split('\n')
            fixed_lines = []
            in_test_function = False
            current_indent = ""
            modifications_made = 0

            for i, line in enumerate(lines):
                stripped = line.strip()

                # 检测测试函数开始
                if stripped.startswith('def test_'):
                    in_test_function = True
                    current_indent = line[:len(line) - len(line.lstrip())]
                    fixed_lines.append(line)
                    continue

                # 检测测试函数结束（下一个函数或文件结束）
                if in_test_function and stripped.startswith('def ') and not stripped.startswith('def test_'):
                    in_test_function = False

                if in_test_function and stripped:
                    # 查找字典定义（可能是测试数据）
                    # 模式: data = {...} 或 order_data = {...}
                    match = self.RE_DICT_ASSIGN.match(stripped)

                    if match and '{' in line:
                        var_name = match.group(1)

                        # 检查这是否是多行字典
                        if line.rstrip().endswith('{'):
                            # 多行字典，收集整个字典
                            dict_lines = [line]
                            j = i + 1
                            while j < len(lines) and '}' not in lines[j]:
                                dict_lines.append(lines[j])
                                j += 1
                            if j < len(lines):
                                dict_lines.append(lines[j])  # 包含结束的 }

                            # 解析字典内容
                            dict_str = '\n'.join(dict_lines)

                            # 检查缺少的字段
                            missing_fields = []
                            for field in required_fields:
                                if f"'{field}'" not in dict_str and f'"{field}"' not in dict_str:
                                    missing_fields.append(field)

                            if missing_fields:
                                # 添加缺少的字段
                                self.logger.debug(f"在 {var_name} 中自动添加缺少的字段: {missing_fields}")

                                # 找到字典的最后一行
                                last_line_idx = j
                                last_line = lines[last_line_idx]

                                # 在结束}之前插入字段
                                insert_lines = []
                                for field in missing_fields:
                                    # 根据字段名推测合理的默认值
                                    if 'id' in field.lower():
                                        value = "'test_id'"
                                    elif 'items' in field.lower():
                                        value = "[{'price': 10, 'quantity': 1}]"
                                    elif 'code' in field.lower():
                                        value = "'TEST'"
                                    elif 'is_' in field.lower() or field.startswith('is'):
                                        value = "False"
                                    else:
                                        value = "'test_value'"

                                    field_indent = current_indent + "        "  # 字典内容缩进
                                    insert_lines.append(f"{field_indent}'{field}': {value},")

                                # 重构字典
                                fixed_lines.append(line)  # 添加开始行
                                for k in range(i + 1, last_line_idx):
                                    fixed_lines.append(lines[k])

                                # 插入新字段
                                for insert_line in insert_lines:
                                    fixed_lines.append(insert_line)
                                    modifications_made += 1

                                fixed_lines.append(last_line)  # 添加结束行

                                # 跳过已处理的行
                                for k in range(i, last_line_idx + 1):
                                    lines[k] = None  # 标记为已处理

                                continue

                        else:
                            # 单行字典，尝试解析
                            # 检查缺少的字段
                            missing_fields = []
                            for field in required_fields:
                                if f"'{field}'" not in line and f'"{field}"' not in line:
                                    missing_fields.append(field)

                            if missing_fields:
                                self.logger.debug(f"在单行字典 {var_name} 中发现缺少字段: {missing_fields}")
                                # 对于单行字典，添加注释提示（不自动修改，避免破坏格式）
                                fixed_lines.append(line)
                                comment_indent = current_indent + "    "
                                fixed_lines.append(f"{comment_indent}# TODO: 可能缺少字段: {', '.join(missing_fields)}")
                                continue

                # 保留未标记为None的行
                if line is not None:
                    fixed_lines.append(line)

            if modifications_made > 0:
                self.logger.info(f"✓ 自动修正完成，共修改 {modifications_made} 处")
                return '\n'.join(fixed_lines)
            else:
                return test_code

        except re.error as e:
            # 正则表达式错误
            self.logger.warning(f"正则表达式错误，自动修正失败: {e}")
            return test_code  # 返回原代码
        except (KeyError, IndexError, AttributeError) as e:
            # 数据访问错误
            self.logger.warning(f"数据访问错误，自动修正失败: {e}")
            return test_code
        except Exception as e:
            # 其他未预期错误
            self.logger.warning(f"自动修正失败: {type(e).__name__} - {e}")
            return test_code  # 返回原代码

    def _extract_failed_test_details(self, pytest_output: str) -> List[Dict]:
        """
        从pytest输出中提取失败测试的详细信息（改进版）

        支持解析:
        - NameError
        - AssertionError
        - 其他常见错误类型

        Args:
            pytest_output: pytest执行输出

        Returns:
            失败测试详情列表 [
                {
                    'test_name': 'test_xxx',
                    'error_type': 'NameError',
                    'expected': '',
                    'actual': '',
                    'error_message': 'name \'input_strs\' is not defined',
                    'line': 0
                },
                ...
            ]
        """
        import re

        failed_tests = []
        lines = pytest_output.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i]

            # 匹配失败行：test_xxx.py::test_name FAILED
            if ' FAILED' in line and '::' in line:
                # 更宽松的正则，支持带下划线的测试名
                match = self.RE_FAILED_TEST.search(line)
                if match:
                    test_name = match.group(1)
                    current_test = {
                        'test_name': test_name,
                        'error_type': '',
                        'expected': '',
                        'actual': '',
                        'error_message': '',
                        'line': 0
                    }

                    # 查找后续的错误详情（往后看最多N行）
                    for j in range(i+1, min(i+self.Config.MAX_ERROR_CONTEXT_LINES, len(lines))):
                        error_line = lines[j]

                        # 检测 NameError
                        if 'NameError:' in error_line:
                            current_test['error_type'] = 'NameError'
                            # 提取完整错误信息
                            error_match = self.RE_NAME_ERROR.search(error_line)
                            if error_match:
                                current_test['error_message'] = error_match.group(1).strip()
                            else:
                                current_test['error_message'] = error_line.strip()
                            break

                        # 检测 AssertionError
                        if 'AssertionError' in error_line or ('assert' in error_line and '==' in error_line):
                            current_test['error_type'] = 'AssertionError'

                            # 提取 expected vs actual
                            # 格式: "assert 0.0 == 20.0" 或 "E       AssertionError: assert 0.0 == 20.0"
                            match_assert = self.RE_ASSERTION_ERROR.search(error_line)
                            if match_assert:
                                current_test['actual'] = match_assert.group(1).strip()
                                current_test['expected'] = match_assert.group(2).strip()

                            current_test['error_message'] = error_line.strip()
                            break

                        # 检测其他常见错误
                        if any(err in error_line for err in ['AttributeError:', 'TypeError:', 'ValueError:', 'KeyError:']):
                            error_type_match = self.RE_ERROR_TYPE.search(error_line)
                            if error_type_match:
                                current_test['error_type'] = error_type_match.group(1)
                                current_test['error_message'] = error_line.strip()
                                break

                    # 如果找到了错误信息，添加到结果列表
                    if current_test['error_type']:
                        failed_tests.append(current_test)
                        self.logger.debug(f"提取失败测试: {test_name} - {current_test['error_type']}")

            i += 1

        if failed_tests:
            self.logger.info(f"✓ 成功提取 {len(failed_tests)} 个失败测试的详情")
        else:
            self.logger.warning("未能提取到失败测试详情")

        return failed_tests

    def _extract_test_code_snippets(self, test_code: str, test_names: List[str]) -> str:
        """
        提取指定测试函数的代码片段

        Args:
            test_code: 完整测试代码
            test_names: 需要提取的测试函数名列表

        Returns:
            提取的代码片段
        """
        snippets = []
        lines = test_code.split('\n')

        for test_name in test_names:
            in_test = False
            test_lines = []

            for line in lines:
                if f'def {test_name}' in line:
                    in_test = True

                if in_test:
                    test_lines.append(line)

                    # 检测函数结束 (下一个def或非缩进行)
                    if line.strip() and not line.startswith((' ', '\t')) and len(test_lines) > 1:
                        break

            if test_lines:
                snippets.append('\n'.join(test_lines))

        return '\n\n'.join(snippets)

    def _extract_json_from_response(self, response: str) -> Optional[Dict[str, Any]]:
        """
        从LLM响应中提取JSON

        Args:
            response: LLM响应文本

        Returns:
            解析的JSON字典，失败返回None
        """
        import json
        import re

        try:
            return json.loads(response)
        except json.JSONDecodeError:
            # 提取JSON代码块
            match = self.RE_JSON_BLOCK.search(response)
            if match:
                try:
                    return json.loads(match.group(1))
                except:
                    pass

            # 查找{}包裹的内容
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end > start:
                try:
                    return json.loads(response[start:end])
                except:
                    pass

        return None

    def _analyze_failures_with_llm(
        self,
        state: TestGenerationState,
        failed_tests: List[Dict]
    ) -> Dict:
        """
        使用LLM分析失败原因

        核心判断逻辑:
        - 需求说X, 代码实现了Y → 代码问题
        - 需求说X, 代码正确实现了X, 但测试期望了Z → 测试问题

        Args:
            state: 当前状态
            failed_tests: 失败测试详情列表

        Returns:
            {
                'code_bugs': [{'test': '...', 'reason': '...', 'code_issue': '...'}],
                'test_bugs': [{'test': '...', 'reason': '...', 'fix': '...'}]
            }
        """
        # 构建失败详情字符串
        failures_str = '\n\n'.join([
            f"测试: {f['test_name']}\n"
            f"错误: 期望{f.get('expected', '?')}, 实际{f.get('actual', '?')}"
            for f in failed_tests
        ])

        # 提取相关测试代码
        test_code_snippets = self._extract_test_code_snippets(
            state.test_code,
            [f['test_name'] for f in failed_tests]
        )

        # 判断是否有原始需求
        has_requirements = bool(state.original_requirements and state.original_requirements.strip())

        # 根据是否有需求构建不同的分析指导
        requirements_section = ""
        analysis_guidance = ""

        if has_requirements:
            requirements_section = f"""## 原始需求 (正确行为的唯一依据)
{state.original_requirements}
"""
            analysis_guidance = """## 分析方法
对每个失败测试, 严格按照需求判断:

1. **代码问题**: 代码实现不符合需求
   - 示例: 需求说">=99免运费", 但代码写了">99" (缺少等号)

2. **测试脚本问题**: 测试理解错误, 代码实际是正确的
   - 示例: 需求说"is_vip或total>=99免运费", 代码正确实现了or逻辑
            但测试用total=100期望收费, 违反了>=99免费的规则
   - 常见错误: 未理解短路逻辑、未看到前置条件、计算错误"""
        else:
            requirements_section = """## ⚠️ 注意：无原始需求
没有提供原始需求，需要基于代码逻辑本身来判断。
"""
            analysis_guidance = """## 分析方法（无需求场景）

**判断依据**：
由于没有原始需求，需要查看源代码实现逻辑来判断：

1. **代码问题**：实际输出明显错误（崩溃、异常、逻辑矛盾）
   - 示例：代码抛出未处理的异常
   - 示例：代码返回None但应该返回列表
   - 示例：代码出现明显的逻辑错误（如除零）

2. **测试脚本问题**：代码实际输出是合理的（基于代码逻辑），但测试期望值错误
   - 示例：对于AssertionError，重点分析：
     * 测试的期望值是否合理？是基于什么假设？
     * 代码的实际输出是否符合代码逻辑？
     * 两者谁更合理？优先相信代码实现

**特别提示**：
- 对于字符串处理、排序、分组等逻辑：优先相信代码实现
- 测试的期望值可能是错误的猜测或理解错误
- 如果实际输出符合代码逻辑且无明显错误，通常是测试问题"""

        prompt = f"""分析测试失败原因, 判断是代码问题还是测试脚本问题。

{requirements_section}

## 源代码
{state.source_code}

## 失败的测试
{test_code_snippets}

## 失败详情
{failures_str}

{analysis_guidance}

## 判断标准（必须严格遵守）

### 代码问题的充分条件：
1. 原始需求明确说明了行为X
2. 源代码没有实现X或实现错误
3. 示例：需求说"空栈pop抛出ValueError"，代码只是return

### 测试问题的充分条件：
1. 原始需求没有明确说明该行为
2. 或测试期望与代码实际行为不符
3. 示例：需求未说明空栈行为，测试却期望抛异常

### 如果需求不明确：
- **默认归类为测试问题**
- 因为应该让测试适应代码，而非修改代码
- 只有在需求明确指出代码错误时，才归类为代码问题

**重要：如果拿不准，倾向于归类为test_bug，而非code_bug。**

## 输出格式 (JSON)
{{
  "code_bugs": [
    {{
      "test": "test_name",
      "reason": "具体原因",
      "code_issue": "代码第X行的问题"
    }}
  ],
  "test_bugs": [
    {{
      "test": "test_name",
      "reason": "测试的理解错误",
      "fix": "应该如何修正测试"
    }}
  ]
}}

开始分析:
"""

        try:
            # 调用LLM进行失败分析（带重试机制）
            response = self._call_llm_with_retry(
                prompt,
                temperature=self.Config.LLM_ANALYSIS_TEMPERATURE,
                max_tokens=self.Config.LLM_ANALYSIS_MAX_TOKENS
            )
            result = self._extract_json_from_response(response)

            if result:
                self.logger.info(
                    f"LLM分析完成: {len(result.get('code_bugs', []))}个代码问题, "
                    f"{len(result.get('test_bugs', []))}个测试问题"
                )
                return result
            else:
                self.logger.warning("LLM未返回有效JSON, 使用默认分类")
                return {
                    'code_bugs': [],
                    'test_bugs': [
                        {
                            'test': f['test_name'],
                            'reason': 'LLM分析失败',
                            'fix': '请人工检查'
                        }
                        for f in failed_tests
                    ]
                }

        except (ConnectionError, TimeoutError) as e:
            # 网络/连接错误（重试后仍失败）
            self.logger.error(f"LLM分析失败（网络错误）: {e}")
            return {
                'code_bugs': [],
                'test_bugs': [
                    {
                        'test': f['test_name'],
                        'reason': f'LLM连接失败: {e}',
                        'fix': '请检查网络连接后重试'
                    }
                    for f in failed_tests
                ]
            }
        except (ValueError, KeyError) as e:
            # JSON解析/访问错误
            self.logger.error(f"LLM分析结果解析失败: {e}")
            return {
                'code_bugs': [],
                'test_bugs': [
                    {
                        'test': f['test_name'],
                        'reason': 'LLM返回格式错误',
                        'fix': '请人工检查'
                    }
                    for f in failed_tests
                ]
            }
        except Exception as e:
            # 其他未预期错误
            self.logger.error(f"LLM分析失败: {type(e).__name__} - {e}")
            return {
                'code_bugs': [],
                'test_bugs': [
                    {
                        'test': f['test_name'],
                        'reason': f'分析异常: {type(e).__name__}',
                        'fix': '请人工检查'
                    }
                    for f in failed_tests
                ]
            }

    def _analyze_test_failures(self, state: TestGenerationState) -> Dict:
        """
        智能分析测试失败原因, 分类为代码问题或测试脚本问题

        Args:
            state: 当前状态

        Returns:
            {
                'code_bugs': [{'test': '...', 'reason': '...', 'code_issue': '...'}],
                'test_bugs': [{'test': '...', 'reason': '...', 'fix': '...'}]
            }
        """
        if not state.pytest_output or not state.quality_metrics:
            return {'code_bugs': [], 'test_bugs': []}

        if state.quality_metrics.failed_tests == 0:
            return {'code_bugs': [], 'test_bugs': []}

        # 提取失败信息
        failed_tests = self._extract_failed_test_details(state.pytest_output)

        if not failed_tests:
            self.logger.warning("无法解析失败测试详情")
            return {'code_bugs': [], 'test_bugs': []}

        # 如果有原始需求, 使用LLM判断
        if state.original_requirements and state.original_requirements.strip():
            self.logger.debug(f"使用LLM分析{len(failed_tests)}个失败测试的原因")
            return self._analyze_failures_with_llm(state, failed_tests)
        else:
            # 无需求时, 默认归为测试问题
            self.logger.warning(
                "未提供原始需求, 无法判断代码正确性, "
                f"将{len(failed_tests)}个失败默认归为测试脚本问题"
            )
            return {
                'code_bugs': [],
                'test_bugs': [
                    {
                        'test': f['test_name'],
                        'reason': '无法判断是否代码问题 (缺少需求文档)',
                        'fix': '建议提供原始需求以准确分析'
                    }
                    for f in failed_tests
                ]
            }

    def _build_gap_filling_prompt_v2(
        self,
        state: TestGenerationState,
        failure_analysis: Dict
    ) -> str:
        """
        构建增强的补充测试prompt (包含失败反馈)

        Args:
            state: 当前状态
            failure_analysis: 失败分析结果

        Returns:
            prompt字符串
        """
        gaps = state.coverage_gaps
        current_coverage = state.get_current_coverage()
        analysis = state.code_analysis

        # 失败反馈部分
        failure_feedback = ""
        if failure_analysis['test_bugs']:
            failure_feedback = "## ⚠️ 上一轮测试脚本错误 (必须修复!)\n\n"
            for bug in failure_analysis['test_bugs']:
                failure_feedback += f"**{bug['test']}**:\n"
                failure_feedback += f"- 错误原因: {bug['reason']}\n"
                failure_feedback += f"- 修复方法: {bug['fix']}\n\n"

            failure_feedback += "请生成修复后的测试替换这些错误的测试。\n\n"

        if failure_analysis['code_bugs']:
            failure_feedback += "## 💡 代码问题提示\n\n"
            failure_feedback += "以下失败可能是代码实现问题, 测试预期可能是正确的:\n\n"
            for bug in failure_analysis['code_bugs']:
                failure_feedback += f"- {bug['test']}: {bug['reason']}\n"
            failure_feedback += "\n"

        # 未测试函数部分（最高优先级）
        untested_section = ""
        if gaps and gaps.uncovered_functions:
            untested_section = "## ⚠️ 优先：未测试的函数\n\n"
            untested_section += "以下函数完全未被测试，需要**立即生成测试**：\n\n"

            # 获取每个未测试函数的详细信息
            for func_name in gaps.uncovered_functions:
                # 从code_analysis中查找函数详情
                func_info = None
                if analysis and hasattr(analysis, 'functions'):
                    func_info = next((f for f in analysis.functions if f.get('name') == func_name), None)

                if func_info:
                    args_str = ', '.join(func_info.get('args', []))
                    untested_section += f"### {func_name}({args_str})\n"

                    # 添加位置信息
                    start_line = func_info.get('lineno', '?')
                    end_line = func_info.get('end_lineno', '?')
                    untested_section += f"- 位置：第{start_line}-{end_line}行\n"

                    # 添加文档字符串
                    if func_info.get('docstring'):
                        docstring = func_info['docstring'][:self.Config.MAX_DOCSTRING_IN_ANALYSIS]
                        untested_section += f"- 功能：{docstring}\n"

                    # 明确要求
                    untested_section += f"- **请生成至少3个测试用例**\n\n"
                else:
                    # 如果没有找到详细信息，至少列出函数名
                    untested_section += f"### {func_name}\n"
                    untested_section += f"- **请生成测试用例**\n\n"

        # 覆盖率缺口部分（只有在没有未测试函数时才关注细节覆盖）
        coverage_section = ""
        if gaps and gaps.uncovered_lines and not gaps.uncovered_functions:
            uncovered_str = ', '.join(map(str, gaps.uncovered_lines[:self.Config.MAX_UNCOVERED_LINES_DISPLAY]))
            coverage_section = f"""## 覆盖率缺口

当前覆盖率: {current_coverage:.1f}%
目标覆盖率: {state.target_coverage}%
未覆盖行: {uncovered_str}

请生成新测试覆盖这些未覆盖的行。
"""

        # 已有测试信息
        existing_tests_info = self._extract_existing_test_names(state.test_code)

        # 完整prompt
        prompt = f"""生成补充测试。

{failure_feedback}
{untested_section}
{coverage_section}

## 生成要求

**优先级排序：**
1. **优先级1**：为未测试的函数生成测试（如果有）
2. **优先级2**：修复存在问题的测试（如果有）
3. **优先级3**：补充覆盖率缺口（如果有）

## 已有测试函数
{existing_tests_info}

## 源代码
{state.source_code}

立即生成:
"""

        return prompt

    def _extract_existing_test_names(self, test_code: str) -> str:
        """提取已有测试函数名"""
        matches = self.RE_TEST_FUNCTION.findall(test_code)
        if matches:
            return ', '.join(matches)
        return "无"

