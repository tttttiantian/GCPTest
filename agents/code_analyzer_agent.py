"""
代码分析Agent - 使用AST分析代码结构
"""

import ast
import sys
import json
from typing import List, Dict, Tuple
from .base_agent import BaseAgent
from workflow.state import TestGenerationState, CodeAnalysis
from config import AgenticConfig


def safe_unparse(node):
    """
    兼容不同Python版本的AST节点转字符串函数
    Python 3.9+有ast.unparse(), 更早版本需要替代方案
    """
    if node is None:
        return None

    # Python 3.9+使用原生ast.unparse
    if sys.version_info >= (3, 9):
        return ast.unparse(node)

    # Python 3.8及以下，返回节点类型描述
    if isinstance(node, ast.Name):
        return node.id
    elif isinstance(node, ast.Constant):
        return repr(node.value)
    elif isinstance(node, ast.Attribute):
        value = safe_unparse(node.value)
        return f"{value}.{node.attr}"
    elif isinstance(node, ast.Call):
        func = safe_unparse(node.func)
        return f"{func}(...)"
    elif isinstance(node, ast.List):
        return "[...]"
    elif isinstance(node, ast.Tuple):
        return "(...)"
    elif isinstance(node, ast.Dict):
        return "{...}"
    elif isinstance(node, list):
        # 处理decorators等列表
        return [safe_unparse(item) for item in node]
    else:
        # 其他类型返回节点类名
        return f"<{node.__class__.__name__}>"


class CodeAnalyzerAgent(BaseAgent):
    """代码分析Agent - 使用AST分析代码结构"""

    def __init__(self, glm_service):
        super().__init__(glm_service, "CodeAnalyzer")

    def execute(self, state: TestGenerationState) -> TestGenerationState:
        """
        分析代码结构

        Args:
            state: 当前状态

        Returns:
            更新后的状态
        """
        self.log(state, "开始分析代码结构")

        try:
            # 1. AST解析
            tree = ast.parse(state.source_code)

            # 2. 提取函数和类
            functions = self._extract_functions(tree)
            classes = self._extract_classes(tree)

            # 3. 识别分支
            branches = self._extract_branches(tree)

            # 4. 计算复杂度
            complexity = self._calculate_complexity(tree)

            # 5. 使用LLM识别边界条件和异常
            edge_cases, exceptions = self._identify_edge_cases_with_llm(
                state.source_code, functions, classes
            )

            # 6. 构建分析结果
            state.code_analysis = CodeAnalysis(
                functions=functions,
                classes=classes,
                branches=branches,
                complexity=complexity,
                edge_cases=edge_cases,
                exceptions=exceptions
            )

            self.log(state, "代码分析完成", {
                'functions_count': len(functions),
                'classes_count': len(classes),
                'branches_count': len(branches),
                'complexity': complexity.get('total', 0)
            })

        except SyntaxError as e:
            error_msg = f"代码语法错误: {str(e)}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)
        except Exception as e:
            self.log_error(state, e)

        return state

    def _extract_functions(self, tree: ast.AST) -> List[Dict]:
        """
        提取所有函数定义

        Args:
            tree: AST树

        Returns:
            函数列表
        """
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                # 提取函数信息
                func_info = {
                    'name': node.name,
                    'lineno': node.lineno,
                    'end_lineno': node.end_lineno,
                    'args': [arg.arg for arg in node.args.args],
                    'returns': safe_unparse(node.returns) if node.returns else None,
                    'decorators': [safe_unparse(d) for d in node.decorator_list],
                    'is_async': False,
                    'is_public': not node.name.startswith('_'),
                    'docstring': ast.get_docstring(node)
                }
                functions.append(func_info)
            elif isinstance(node, ast.AsyncFunctionDef):
                # 异步函数
                func_info = {
                    'name': node.name,
                    'lineno': node.lineno,
                    'end_lineno': node.end_lineno,
                    'args': [arg.arg for arg in node.args.args],
                    'returns': safe_unparse(node.returns) if node.returns else None,
                    'decorators': [safe_unparse(d) for d in node.decorator_list],
                    'is_async': True,
                    'is_public': not node.name.startswith('_'),
                    'docstring': ast.get_docstring(node)
                }
                functions.append(func_info)

        return functions

    def _extract_classes(self, tree: ast.AST) -> List[Dict]:
        """
        提取所有类定义

        Args:
            tree: AST树

        Returns:
            类列表
        """
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                # 提取方法
                methods = []
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        methods.append({
                            'name': item.name,
                            'lineno': item.lineno,
                            'is_async': isinstance(item, ast.AsyncFunctionDef)
                        })

                class_info = {
                    'name': node.name,
                    'lineno': node.lineno,
                    'bases': [safe_unparse(base) for base in node.bases],
                    'methods': methods,
                    'docstring': ast.get_docstring(node)
                }
                classes.append(class_info)

        return classes

    def _extract_branches(self, tree: ast.AST) -> List[Dict]:
        """
        提取分支语句

        Args:
            tree: AST树

        Returns:
            分支列表
        """
        branches = []

        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                branches.append({
                    'type': 'if',
                    'lineno': node.lineno,
                    'condition': safe_unparse(node.test),
                    'has_else': len(node.orelse) > 0
                })
            elif isinstance(node, ast.For):
                branches.append({
                    'type': 'for',
                    'lineno': node.lineno,
                    'condition': safe_unparse(node.iter)
                })
            elif isinstance(node, ast.While):
                branches.append({
                    'type': 'while',
                    'lineno': node.lineno,
                    'condition': safe_unparse(node.test)
                })
            elif isinstance(node, ast.Try):
                branches.append({
                    'type': 'try',
                    'lineno': node.lineno,
                    'handlers': len(node.handlers)
                })

        return branches

    def _calculate_complexity(self, tree: ast.AST) -> Dict[str, int]:
        """
        计算圈复杂度

        Args:
            tree: AST树

        Returns:
            复杂度字典
        """
        complexity = {'total': 1}  # 基础复杂度为1

        for node in ast.walk(tree):
            # 每个决策点增加复杂度
            if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                complexity['total'] += 1
            elif isinstance(node, ast.BoolOp):
                # 布尔运算符（and/or）
                complexity['total'] += len(node.values) - 1
            elif isinstance(node, (ast.Break, ast.Continue)):
                complexity['total'] += 1

        return complexity

    def _identify_edge_cases_with_llm(
        self,
        code: str,
        functions: List[Dict],
        classes: List[Dict]
    ) -> Tuple[List[str], List[str]]:
        """
        使用LLM识别边界条件和异常类型

        Args:
            code: 源代码
            functions: 函数列表
            classes: 类列表

        Returns:
            (边界条件列表, 异常类型列表)
        """
        # 构建简化的函数签名
        func_signatures = [
            f"{f['name']}({', '.join(f['args'])})" for f in functions
        ]
        class_names = [c['name'] for c in classes]

        prompt = f"""请分析以下Python代码，识别需要测试的边界条件和可能抛出的异常。

代码：
```python
{code}
```

函数签名: {', '.join(func_signatures) if func_signatures else '无'}
类名: {', '.join(class_names) if class_names else '无'}

请以JSON格式返回（只返回JSON，不要其他文字）：
{{
    "edge_cases": ["边界条件1", "边界条件2", ...],
    "exceptions": ["异常类型1", "异常类型2", ...]
}}

边界条件示例：空列表、None值、负数、零、超大数值、空字符串等
异常类型示例：ValueError、TypeError、IndexError、KeyError等
"""

        try:
            response = self._call_llm(
                prompt,
                temperature=AgenticConfig.ANALYSIS_TEMPERATURE
            )

            # 提取JSON部分
            result = self._extract_json_from_response(response)

            if result:
                edge_cases = result.get('edge_cases', [])
                exceptions = result.get('exceptions', [])
                self.logger.info(f"LLM识别到 {len(edge_cases)} 个边界条件和 {len(exceptions)} 个异常类型")
                return edge_cases, exceptions

        except Exception as e:
            self.logger.warning(f"LLM识别边界条件失败: {e}")

        # 默认返回常见的边界条件和异常
        default_edge_cases = ["None值", "空值", "边界值", "异常值"]
        default_exceptions = ["ValueError", "TypeError"]

        return default_edge_cases, default_exceptions

    def _extract_json_from_response(self, response: str) -> dict:
        """
        从LLM响应中提取JSON

        Args:
            response: LLM响应

        Returns:
            解析后的字典，失败返回None
        """
        try:
            # 尝试直接解析
            return json.loads(response)
        except json.JSONDecodeError:
            # 尝试提取JSON代码块
            start = response.find('{')
            end = response.rfind('}') + 1

            if start != -1 and end > start:
                try:
                    json_str = response[start:end]
                    return json.loads(json_str)
                except json.JSONDecodeError:
                    pass

            return None
