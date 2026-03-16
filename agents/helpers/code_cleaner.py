"""代码清理和修复辅助类"""

import re as _re
import ast
from typing import Any
import logging


class CodeCleaner:
    """负责测试代码的清理、验证和修复"""

    # 预编译的正则表达式
    RE_CHINESE_CHARS = _re.compile(r'[\u4e00-\u9fff]')
    RE_CHINESE_PUNCT = _re.compile(r'[、。，！？；：""''【】《》（）]')

    # unittest转pytest转换相关
    RE_ASSERT_EQUAL = _re.compile(r'self\.assertEqual\((.*?),\s*(.*?)\)')
    RE_ASSERT_TRUE = _re.compile(r'self\.assertTrue\((.*?)\)')
    RE_ASSERT_FALSE = _re.compile(r'self\.assertFalse\((.*?)\)')
    RE_ASSERT_IS_NONE = _re.compile(r'self\.assertIsNone\((.*?)\)')
    RE_ASSERT_IS_NOT_NONE = _re.compile(r'self\.assertIsNotNone\((.*?)\)')
    RE_ASSERT_IN = _re.compile(r'self\.assertIn\((.*?),\s*(.*?)\)')

    def __init__(self, config: Any, logger: logging.Logger):
        """
        初始化CodeCleaner

        Args:
            config: 配置对象（包含MAX_LOG_RESPONSE_LENGTH等常量）
            logger: 日志记录器
        """
        self.config = config
        self.logger = logger

    def clean_generated_code(self, response: str, module_name: str) -> str:
        """
        清理生成的代码

        Args:
            response: LLM响应
            module_name: 模块名

        Returns:
            清理后的代码
        """
        # 调试：输出原始响应的前N字符
        self.logger.debug(f"LLM原始响应（前{self.config.MAX_LOG_RESPONSE_LENGTH}字符）: {response[:self.config.MAX_LOG_RESPONSE_LENGTH]}")
        self.logger.debug(f"LLM响应总长度: {len(response)}")

        # 移除markdown标记
        code = response.replace('```python', '').replace('```', '').strip()

        # 如果响应为空或太短，返回基础导入
        if len(code.strip()) < 10:
            self.logger.warning(f"LLM响应太短或为空，长度: {len(code)}")
            return f"import pytest\nfrom {module_name} import *\n"

        # 移除开头的解释性文字（如果有）
        lines = code.split('\n')
        clean_lines = []
        code_started = False

        self.logger.debug(f"开始清理代码，共{len(lines)}行")

        for i, line in enumerate(lines):
            # 跳过纯文本说明
            if not code_started:
                if line.strip().startswith(('import', 'from', '@', 'def', 'class')):
                    code_started = True
                    self.logger.debug(f"在第{i+1}行找到代码开始标记: {line[:50]}")
                else:
                    continue

            if code_started:
                clean_lines.append(line)

        self.logger.debug(f"清理后保留{len(clean_lines)}行代码")
        if clean_lines:
            self.logger.debug(f"清理后的前3行: {clean_lines[:3]}")

        code = '\n'.join(clean_lines)

        # 规范化缩进（核心改进）
        code = self.normalize_indentation(code)

        # 主动移除中文标点符号（在语法验证前）
        code = self.remove_chinese_punctuation(code)

        # 确保有pytest导入
        if 'import pytest' not in code:
            code = 'import pytest\n' + code

        # 确保有模块导入（如果代码中没有）
        if f'from {module_name} import' not in code and f'import {module_name}' not in code:
            # 自动添加导入语句
            self.logger.warning(f"生成的代码缺少模块导入，自动添加 'from {module_name} import *'")

            # 在pytest导入后添加模块导入
            lines = code.split('\n')
            import_added = False
            new_lines = []

            for line in lines:
                new_lines.append(line)
                if 'import pytest' in line and not import_added:
                    new_lines.append(f'from {module_name} import *')
                    import_added = True

            code = '\n'.join(new_lines)

        # 验证语法
        code = self.validate_and_fix_syntax(code, module_name)

        return code

    def normalize_indentation(self, code: str) -> str:
        """
        规范化代码缩进，修复常见的缩进问题

        Args:
            code: 原始代码

        Returns:
            规范化后的代码
        """
        import textwrap

        # 1. 将所有tab转换为4个空格
        code = code.replace('\t', '    ')

        # 2. 移除每行末尾的空白字符
        lines = [line.rstrip() for line in code.split('\n')]

        # 3. 找到所有顶层定义（import, from, def, class）的最小缩进
        # 这些语句应该在顶层（缩进为0）
        min_top_level_indent = float('inf')
        for line in lines:
            if line.strip():  # 非空行
                stripped = line.lstrip()
                # 检查是否是顶层语句
                if stripped.startswith(('import ', 'from ', 'def ', 'class ', '@')):
                    indent = len(line) - len(stripped)
                    min_top_level_indent = min(min_top_level_indent, indent)

        # 如果没有找到顶层语句，使用第一个非空行的缩进
        if min_top_level_indent == float('inf'):
            for line in lines:
                if line.strip():
                    min_top_level_indent = len(line) - len(line.lstrip())
                    break

        # 确保最小缩进是有限值
        if min_top_level_indent == float('inf'):
            min_top_level_indent = 0

        # 4. 移除多余的基础缩进
        if min_top_level_indent > 0:
            normalized_lines = []
            for line in lines:
                if line.strip():  # 非空行
                    # 移除基础缩进
                    current_indent = len(line) - len(line.lstrip())
                    if current_indent >= min_top_level_indent:
                        # 减去基础缩进
                        new_indent = current_indent - min_top_level_indent
                        normalized_lines.append(' ' * new_indent + line.lstrip())
                    else:
                        # 保持原样（缩进小于基础缩进的情况，虽然不太可能）
                        normalized_lines.append(line)
                else:
                    normalized_lines.append('')  # 保留空行
            lines = normalized_lines

        # 5. 移除连续的多个空行，最多保留N个
        result_lines = []
        empty_count = 0
        max_consecutive_empty_lines = getattr(self.config, 'MAX_CONSECUTIVE_EMPTY_LINES', 2)
        for line in lines:
            if not line.strip():
                empty_count += 1
                if empty_count <= max_consecutive_empty_lines:
                    result_lines.append(line)
            else:
                empty_count = 0
                result_lines.append(line)

        # 6. 移除开头和结尾的空行
        while result_lines and not result_lines[0].strip():
            result_lines.pop(0)
        while result_lines and not result_lines[-1].strip():
            result_lines.pop()

        # 7. 新增：检查顶层测试函数定义的缩进
        final_lines = []
        for i, line in enumerate(result_lines):
            stripped = line.lstrip()

            # 检测以def test_开头的行（顶层测试函数）
            if stripped.startswith('def test_'):
                # 顶层测试函数不应该有缩进
                if line != stripped:
                    self.logger.warning(f"行{i+1}: 检测到顶层测试函数有缩进，已移除 -> {stripped[:50]}")
                    final_lines.append(stripped)
                else:
                    final_lines.append(line)
            else:
                final_lines.append(line)

        normalized_code = '\n'.join(final_lines)

        self.logger.debug(f"缩进规范化完成，处理了 {len(lines)} 行代码")

        return normalized_code

    def remove_chinese_punctuation(self, code: str) -> str:
        """
        改进版：只替换中文标点为英文标点，不删除代码行

        对于代码语句（赋值、函数定义等），将全角标点替换为半角标点
        对于纯注释，如果包含纯中文标点则移除

        Args:
            code: 原始代码

        Returns:
            清理后的代码
        """
        lines = code.split('\n')
        fixed_lines = []
        removed_count = 0
        replaced_count = 0

        for line in lines:
            stripped = line.strip()

            # 跳过空行
            if not stripped:
                fixed_lines.append(line)
                continue

            # 保留注释（但检查是否有纯中文标点）
            if stripped.startswith('#'):
                # 对注释，检测纯中文标点（不包括全角引号）
                chinese_only_punct = '、。！？；《》'
                if any(p in line for p in chinese_only_punct):
                    self.logger.warning(f"移除包含中文标点的注释: {stripped[:50]}")
                    removed_count += 1
                else:
                    fixed_lines.append(line)
                continue

            # 保留文档字符串（三引号）
            if stripped.startswith(('"""', "'''")):
                fixed_lines.append(line)
                continue

            # 检测是否为代码语句（包含赋值、函数调用等）
            is_code_statement = (
                '=' in line or
                'def ' in line or
                'class ' in line or
                'import ' in line or
                'from ' in line or
                'assert ' in line or
                'return ' in line or
                'if ' in line or
                'for ' in line or
                'while ' in line
            )

            if is_code_statement:
                # 对代码语句，只替换全角标点为半角，不删除
                fixed_line = line
                original_line = line

                # 全角 → 半角替换
                fixed_line = fixed_line.replace('"', '"').replace('"', '"')
                fixed_line = fixed_line.replace(''', "'").replace(''', "'")
                fixed_line = fixed_line.replace('，', ',')
                fixed_line = fixed_line.replace('：', ':')
                fixed_line = fixed_line.replace('（', '(').replace('）', ')')
                fixed_line = fixed_line.replace('【', '[').replace('】', ']')

                if fixed_line != original_line:
                    self.logger.debug(f"替换全角标点: {original_line.strip()[:50]}...")
                    replaced_count += 1

                fixed_lines.append(fixed_line)
            else:
                # 非代码语句，保留原样
                fixed_lines.append(line)

        if removed_count > 0:
            self.logger.info(f"✓ 移除了 {removed_count} 行中文标点注释")

        if replaced_count > 0:
            self.logger.info(f"✓ 替换了 {replaced_count} 行全角标点为半角标点")

        return '\n'.join(fixed_lines)

    def validate_and_fix_syntax(self, code: str, module_name: str) -> str:
        """
        验证Python语法并尝试修复常见错误

        Args:
            code: 代码字符串
            module_name: 模块名

        Returns:
            验证/修复后的代码
        """
        try:
            # 尝试编译代码检查语法
            ast.parse(code)
            self.logger.info("✓ 代码语法验证通过")
            return code

        except SyntaxError as e:
            self.logger.warning(f"检测到语法错误: {e}")

            # 尝试一些常见的修复

            # 修复1: 检查是否有未闭合的括号/引号
            # 计算括号平衡
            open_parens = code.count('(') - code.count(')')
            open_brackets = code.count('[') - code.count(']')
            open_braces = code.count('{') - code.count('}')

            if open_parens > 0:
                self.logger.info(f"检测到 {open_parens} 个未闭合的圆括号，尝试修复")
                code += ')' * open_parens
            if open_brackets > 0:
                self.logger.info(f"检测到 {open_brackets} 个未闭合的方括号，尝试修复")
                code += ']' * open_brackets
            if open_braces > 0:
                self.logger.info(f"检测到 {open_braces} 个未闭合的花括号，尝试修复")
                code += '}' * open_braces

            # 修复2: 移除明显错误的行（非字符串/注释中的中文标点等）
            lines = code.split('\n')
            fixed_lines = []
            for i, line in enumerate(lines, 1):
                stripped = line.strip()

                # 保留注释和文档字符串
                if stripped.startswith('#') or stripped.startswith(('"""', "'''")):
                    fixed_lines.append(line)
                    continue

                # 检查是否在字符串字面量内（简单检查：引号数量成对）
                single_quotes = stripped.count("'")
                double_quotes = stripped.count('"')

                # 如果包含assert且有中文，很可能是合法的中文断言，保留
                if 'assert' in stripped and self.RE_CHINESE_CHARS.search(stripped):
                    # 检查中文是否在引号内（粗略检查）
                    if (single_quotes >= 2 or double_quotes >= 2):
                        # 中文很可能在字符串内，保留
                        fixed_lines.append(line)
                        continue

                # 检查是否有中文标点符号在代码部分（不在字符串中）
                # 中文标点：、。，！？；：""''【】《》（）
                has_chinese_punct = bool(self.RE_CHINESE_PUNCT.search(stripped))

                if has_chinese_punct and not stripped.startswith(('#', '"""', "'''")):
                    # 检查是否确实在字符串外
                    # 简单策略：如果引号不成对，或者中文标点在引号前，则可能是错误
                    if (single_quotes % 2 == 1) or (double_quotes % 2 == 1):
                        # 引号不成对，这行可能有问题，但先保留
                        fixed_lines.append(line)
                    elif not ('in' in stripped and 'assert' in stripped):
                        # 如果不是断言语句，且有中文标点，可能是解释性文字
                        self.logger.warning(f"行 {i} 包含疑似错误的中文标点，已移除: {line[:50]}")
                        continue
                    else:
                        fixed_lines.append(line)
                else:
                    fixed_lines.append(line)

            code = '\n'.join(fixed_lines)

            # 再次验证
            try:
                ast.parse(code)
                self.logger.info("✓ 语法修复成功")
                return code
            except SyntaxError as e2:
                self.logger.error(f"语法修复失败: {e2}")
                self.logger.warning("返回基础测试模板")

                # 返回一个基础的可工作模板
                return f"""import pytest
from {module_name} import *

def test_basic():
    '''基础测试 - 由于生成的代码存在语法错误，使用此占位测试'''
    assert True  # 占位测试
"""

        except RecursionError as e:
            # AST解析递归深度超限
            self.logger.error(f"代码验证失败（代码嵌套过深）: {e}")
            return code
        except MemoryError as e:
            # 内存不足
            self.logger.error(f"代码验证失败（内存不足）: {e}")
            return code
        except Exception as e:
            # 其他验证异常
            self.logger.error(f"代码验证过程出错: {type(e).__name__} - {e}")
            # 如果验证过程本身出错，返回原代码
            return code

    def convert_unittest_to_pytest(self, code: str) -> str:
        """
        将unittest格式的测试转换为pytest格式

        Args:
            code: 原始测试代码

        Returns:
            转换后的代码
        """
        lines = code.split('\n')
        converted_lines = []

        for line in lines:
            stripped = line.strip()
            indent = line[:len(line) - len(stripped)]

            # 1. 移除测试函数的self参数
            # def test_something(self): -> def test_something():
            if stripped.startswith('def test_') and '(self)' in stripped:
                line = line.replace('(self)', '()')
                self.logger.debug(f"修复unittest格式: 移除self参数 -> {stripped}")

            # 2. 转换self.assertEqual -> assert
            # self.assertEqual(a, b) -> assert a == b
            if 'self.assertEqual(' in stripped:
                match = self.RE_ASSERT_EQUAL.search(stripped)
                if match:
                    arg1, arg2 = match.group(1), match.group(2)
                    line = indent + f'assert {arg1} == {arg2}'
                    self.logger.debug(f"修复unittest格式: self.assertEqual -> assert")

            # 3. 转换self.assertTrue -> assert
            # self.assertTrue(x) -> assert x
            elif 'self.assertTrue(' in stripped:
                match = self.RE_ASSERT_TRUE.search(stripped)
                if match:
                    arg = match.group(1)
                    line = indent + f'assert {arg}'
                    self.logger.debug(f"修复unittest格式: self.assertTrue -> assert")

            # 4. 转换self.assertFalse -> assert not
            # self.assertFalse(x) -> assert not x
            elif 'self.assertFalse(' in stripped:
                match = self.RE_ASSERT_FALSE.search(stripped)
                if match:
                    arg = match.group(1)
                    line = indent + f'assert not {arg}'
                    self.logger.debug(f"修复unittest格式: self.assertFalse -> assert not")

            # 5. 转换self.assertIsNone -> assert is None
            # self.assertIsNone(x) -> assert x is None
            elif 'self.assertIsNone(' in stripped:
                match = self.RE_ASSERT_IS_NONE.search(stripped)
                if match:
                    arg = match.group(1)
                    line = indent + f'assert {arg} is None'
                    self.logger.debug(f"修复unittest格式: self.assertIsNone -> assert is None")

            # 6. 转换self.assertIsNotNone -> assert is not None
            elif 'self.assertIsNotNone(' in stripped:
                match = self.RE_ASSERT_IS_NOT_NONE.search(stripped)
                if match:
                    arg = match.group(1)
                    line = indent + f'assert {arg} is not None'
                    self.logger.debug(f"修复unittest格式: self.assertIsNotNone -> assert is not None")

            # 7. 转换self.assertIn -> assert in
            # self.assertIn(a, b) -> assert a in b
            elif 'self.assertIn(' in stripped:
                match = self.RE_ASSERT_IN.search(stripped)
                if match:
                    arg1, arg2 = match.group(1), match.group(2)
                    line = indent + f'assert {arg1} in {arg2}'
                    self.logger.debug(f"修复unittest格式: self.assertIn -> assert in")

            converted_lines.append(line)

        return '\n'.join(converted_lines)
