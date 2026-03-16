# GCPTest Agentic 实现方案

## 一、整体架构设计

### 1.1 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                        Web Layer                             │
│                   (Flask App - app.py)                       │
└───────────────────────────┬─────────────────────────────────┘
                            │
                            ▼
┌─────────────────────────────────────────────────────────────┐
│                  Agentic Orchestrator                        │
│              (AgenticTestGenerator)                          │
│                                                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Workflow State Manager                   │  │
│  │  - 管理Agent间的状态传递                              │  │
│  │  - 跟踪迭代进度和覆盖率                               │  │
│  │  - 控制循环终止条件                                   │  │
│  └──────────────────────────────────────────────────────┘  │
└───────────────────────────┬─────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        │                   │                   │
        ▼                   ▼                   ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│Code Analyzer │   │Test Generator│   │Test Executor │
│    Agent     │   │    Agent     │   │    Agent     │
├──────────────┤   ├──────────────┤   ├──────────────┤
│- AST解析     │   │- 初始测试    │   │- 运行pytest  │
│- 复杂度分析  │   │- 补充测试    │   │- 覆盖率收集  │
│- 路径识别    │   │- 质量检查    │   │- 错误分析    │
└──────────────┘   └──────────────┘   └──────────────┘
        │                   │                   │
        └───────────────────┼───────────────────┘
                            │
                            ▼
                  ┌──────────────────┐
                  │Coverage Analyzer │
                  │     Agent        │
                  ├──────────────────┤
                  │- 缺口识别        │
                  │- 路径分析        │
                  │- 优化建议        │
                  └──────────────────┘
```

### 1.2 核心组件

#### Agent定义
1. **CodeAnalyzerAgent**: 代码分析专家
2. **TestGeneratorAgent**: 测试生成专家
3. **TestExecutorAgent**: 测试执行专家
4. **CoverageAnalyzerAgent**: 覆盖率分析专家

#### 状态管理
```python
class TestGenerationState:
    code: str                    # 源代码
    code_analysis: dict          # 代码分析结果
    test_code: str              # 生成的测试代码
    coverage_report: dict        # 覆盖率报告
    coverage_gaps: list          # 覆盖率缺口
    iteration: int               # 当前迭代次数
    messages: list               # Agent通信消息
    is_complete: bool            # 是否完成
```

## 二、项目结构

```
GCPTest/
├── app.py                          # Flask主应用（需修改）
├── GLMService.py                   # AI服务（保留）
├── agents/                         # 新增：Agent模块
│   ├── __init__.py
│   ├── base_agent.py              # Agent基类
│   ├── code_analyzer_agent.py     # 代码分析Agent
│   ├── test_generator_agent.py    # 测试生成Agent
│   ├── test_executor_agent.py     # 测试执行Agent
│   └── coverage_analyzer_agent.py # 覆盖率分析Agent
├── workflow/                       # 新增：工作流模块
│   ├── __init__.py
│   ├── state.py                   # 状态定义
│   ├── orchestrator.py            # 工作流编排器
│   └── prompts.py                 # Prompt模板
├── utils/                          # 新增：工具模块
│   ├── __init__.py
│   ├── code_parser.py             # 代码解析工具
│   ├── coverage_parser.py         # 覆盖率解析工具
│   └── test_runner.py             # 测试运行工具
├── config.py                       # 新增：配置文件
└── requirements.txt                # 依赖（需更新）
```

## 三、详细实现方案

### 3.1 状态定义 (workflow/state.py)

```python
from typing import TypedDict, List, Dict, Optional
from dataclasses import dataclass, field

@dataclass
class CodeAnalysis:
    """代码分析结果"""
    functions: List[Dict]           # 函数列表
    classes: List[Dict]              # 类列表
    branches: List[Dict]             # 分支列表
    complexity: Dict[str, int]       # 复杂度
    edge_cases: List[str]            # 边界条件
    exceptions: List[str]            # 异常类型

@dataclass
class CoverageGap:
    """覆盖率缺口"""
    uncovered_lines: List[int]
    uncovered_branches: List[str]
    uncovered_functions: List[str]
    suggestions: List[str]

@dataclass
class TestGenerationState:
    """测试生成状态"""
    # 输入
    source_code: str
    test_requirements: str
    module_name: str
    target_coverage: float = 90.0

    # 处理过程
    code_analysis: Optional[CodeAnalysis] = None
    test_code: str = ""
    coverage_report: Dict = field(default_factory=dict)
    coverage_gaps: Optional[CoverageGap] = None

    # 控制
    iteration: int = 0
    max_iterations: int = 3
    is_complete: bool = False

    # 日志
    agent_messages: List[Dict] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)

    def add_message(self, agent: str, message: str, data: dict = None):
        """添加Agent消息"""
        self.agent_messages.append({
            'agent': agent,
            'iteration': self.iteration,
            'message': message,
            'data': data or {}
        })

    def get_current_coverage(self) -> float:
        """获取当前覆盖率"""
        if not self.coverage_report or 'summary' not in self.coverage_report:
            return 0.0
        return float(self.coverage_report['summary'].get('line_rate', '0%').rstrip('%'))
```

### 3.2 Agent基类 (agents/base_agent.py)

```python
from abc import ABC, abstractmethod
from GLMService import GLMService
import logging

class BaseAgent(ABC):
    """Agent基类"""

    def __init__(self, glm_service: GLMService, name: str):
        self.glm_service = glm_service
        self.name = name
        self.logger = logging.getLogger(f"Agent.{name}")

    @abstractmethod
    def execute(self, state: 'TestGenerationState') -> 'TestGenerationState':
        """
        执行Agent任务

        Args:
            state: 当前状态

        Returns:
            更新后的状态
        """
        pass

    def _call_llm(self, prompt: str, temperature: float = 0.7) -> str:
        """调用LLM"""
        try:
            # 使用临时会话ID，避免影响聊天功能
            response = self.glm_service.chat(prompt, f"agent_{self.name}")
            return response
        except Exception as e:
            self.logger.error(f"LLM调用失败: {str(e)}")
            raise

    def log(self, state: 'TestGenerationState', message: str, data: dict = None):
        """记录日志"""
        self.logger.info(f"[Iteration {state.iteration}] {message}")
        state.add_message(self.name, message, data)
```

### 3.3 代码分析Agent (agents/code_analyzer_agent.py)

```python
import ast
from typing import List, Dict
from .base_agent import BaseAgent
from workflow.state import TestGenerationState, CodeAnalysis

class CodeAnalyzerAgent(BaseAgent):
    """代码分析Agent - 使用AST分析代码结构"""

    def __init__(self, glm_service):
        super().__init__(glm_service, "CodeAnalyzer")

    def execute(self, state: TestGenerationState) -> TestGenerationState:
        """分析代码结构"""
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
                'branches_count': len(branches)
            })

        except Exception as e:
            error_msg = f"代码分析失败: {str(e)}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)

        return state

    def _extract_functions(self, tree: ast.AST) -> List[Dict]:
        """提取所有函数定义"""
        functions = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                functions.append({
                    'name': node.name,
                    'lineno': node.lineno,
                    'args': [arg.arg for arg in node.args.args],
                    'returns': ast.unparse(node.returns) if node.returns else None,
                    'decorators': [ast.unparse(d) for d in node.decorator_list],
                    'is_async': isinstance(node, ast.AsyncFunctionDef)
                })
        return functions

    def _extract_classes(self, tree: ast.AST) -> List[Dict]:
        """提取所有类定义"""
        classes = []
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                methods = [
                    n.name for n in node.body
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                ]
                classes.append({
                    'name': node.name,
                    'lineno': node.lineno,
                    'bases': [ast.unparse(base) for base in node.bases],
                    'methods': methods
                })
        return classes

    def _extract_branches(self, tree: ast.AST) -> List[Dict]:
        """提取分支语句"""
        branches = []
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                branches.append({
                    'type': 'if',
                    'lineno': node.lineno,
                    'condition': ast.unparse(node.test),
                    'has_else': len(node.orelse) > 0
                })
            elif isinstance(node, (ast.For, ast.While)):
                branches.append({
                    'type': 'loop',
                    'lineno': node.lineno,
                    'condition': ast.unparse(node.test) if isinstance(node, ast.While) else ast.unparse(node.iter)
                })
        return branches

    def _calculate_complexity(self, tree: ast.AST) -> Dict[str, int]:
        """计算圈复杂度"""
        complexity = {'total': 1}  # 基础复杂度为1

        for node in ast.walk(tree):
            if isinstance(node, (ast.If, ast.For, ast.While, ast.ExceptHandler)):
                complexity['total'] += 1
            elif isinstance(node, ast.BoolOp):
                complexity['total'] += len(node.values) - 1

        return complexity

    def _identify_edge_cases_with_llm(self, code: str, functions: List, classes: List) -> tuple:
        """使用LLM识别边界条件和异常类型"""
        prompt = f"""
请分析以下Python代码，识别需要测试的边界条件和可能抛出的异常：

代码：
{code}

请以JSON格式返回：
{{
    "edge_cases": ["边界条件1", "边界条件2", ...],
    "exceptions": ["异常类型1", "异常类型2", ...]
}}

示例：
{{
    "edge_cases": ["空列表", "负数输入", "None值", "超大数值"],
    "exceptions": ["ValueError", "TypeError", "IndexError"]
}}
"""

        try:
            response = self._call_llm(prompt, temperature=0.3)
            # 简单解析（实际应该更robust）
            import json
            # 提取JSON部分
            start = response.find('{')
            end = response.rfind('}') + 1
            if start != -1 and end > start:
                result = json.loads(response[start:end])
                return result.get('edge_cases', []), result.get('exceptions', [])
        except Exception as e:
            self.logger.warning(f"LLM识别边界条件失败: {e}")

        # 默认返回
        return ["空值", "边界值", "异常值"], ["ValueError", "TypeError"]
```

### 3.4 测试生成Agent (agents/test_generator_agent.py)

```python
from .base_agent import BaseAgent
from workflow.state import TestGenerationState
from workflow.prompts import INITIAL_TEST_PROMPT,补充_TEST_PROMPT

class TestGeneratorAgent(BaseAgent):
    """测试生成Agent"""

    def __init__(self, glm_service):
        super().__init__(glm_service, "TestGenerator")

    def execute(self, state: TestGenerationState) -> TestGenerationState:
        """生成测试用例"""

        if state.iteration == 0:
            # 初始生成
            return self._generate_initial_tests(state)
        else:
            # 补充生成
            return self._generate_gap_filling_tests(state)

    def _generate_initial_tests(self, state: TestGenerationState) -> TestGenerationState:
        """生成初始测试用例"""
        self.log(state, "生成初始测试用例")

        # 构建Prompt
        prompt = self._build_initial_prompt(state)

        try:
            # 调用LLM
            response = self._call_llm(prompt, temperature=0.7)

            # 清理代码
            test_code = self._clean_generated_code(response, state.module_name)

            state.test_code = test_code
            self.log(state, "初始测试用例生成完成", {
                'test_lines': len(test_code.split('\n'))
            })

        except Exception as e:
            error_msg = f"测试生成失败: {str(e)}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)

        return state

    def _generate_gap_filling_tests(self, state: TestGenerationState) -> TestGenerationState:
        """生成补充测试用例（填补覆盖率缺口）"""
        self.log(state, f"生成补充测试用例 (迭代 {state.iteration})")

        if not state.coverage_gaps:
            self.log(state, "无覆盖率缺口，跳过补充生成")
            return state

        # 构建Prompt
        prompt = self._build_gap_filling_prompt(state)

        try:
            # 调用LLM
            response = self._call_llm(prompt, temperature=0.7)

            # 清理并合并代码
            additional_tests = self._clean_generated_code(response, state.module_name)

            # 智能合并（避免重复导入）
            state.test_code = self._merge_test_code(state.test_code, additional_tests)

            self.log(state, "补充测试用例生成完成", {
                'additional_lines': len(additional_tests.split('\n'))
            })

        except Exception as e:
            error_msg = f"补充测试生成失败: {str(e)}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)

        return state

    def _build_initial_prompt(self, state: TestGenerationState) -> str:
        """构建初始测试Prompt"""
        analysis = state.code_analysis

        prompt = f"""你是Python测试专家。请为以下代码生成完整的pytest测试用例。

## 代码分析结果

**函数列表**：
{self._format_functions(analysis.functions)}

**类列表**：
{self._format_classes(analysis.classes)}

**分支语句**：{len(analysis.branches)}个分支需要覆盖

**边界条件**：{', '.join(analysis.edge_cases)}

**可能的异常**：{', '.join(analysis.exceptions)}

**代码复杂度**：{analysis.complexity.get('total', 0)}

## 源代码

```python
{state.source_code}
```

## 测试需求

{state.test_requirements}

## 生成要求

1. **必须覆盖所有函数**：为每个函数生成至少1个测试
2. **必须覆盖所有分支**：确保if/else、循环等所有路径都被测试
3. **使用pytest.mark.parametrize**：对于多场景测试
4. **测试边界条件**：{', '.join(analysis.edge_cases[:3])}
5. **测试异常情况**：使用pytest.raises测试异常
6. **使用fixture**：避免重复的初始化代码

## 输出格式

只输出可执行的Python测试代码，不要包含任何解释文字。代码格式：

```python
import pytest
from {state.module_name} import <需要导入的类/函数>

@pytest.fixture
def instance():
    return ClassName()

def test_function_name(instance):
    # Arrange
    ...
    # Act
    result = instance.method()
    # Assert
    assert result == expected

@pytest.mark.parametrize("input,expected", [...])
def test_function_parametrize(instance, input, expected):
    assert instance.method(input) == expected
```

请生成测试代码：
"""
        return prompt

    def _build_gap_filling_prompt(self, state: TestGenerationState) -> str:
        """构建补充测试Prompt"""
        gaps = state.coverage_gaps
        current_coverage = state.get_current_coverage()

        prompt = f"""你是Python测试专家。当前测试覆盖率为 {current_coverage:.1f}%，需要生成补充测试来提高覆盖率。

## 当前覆盖率缺口

**未覆盖的代码行**：{gaps.uncovered_lines}

**未覆盖的分支**：
{self._format_list(gaps.uncovered_branches)}

**未覆盖的函数**：
{self._format_list(gaps.uncovered_functions)}

**优化建议**：
{self._format_list(gaps.suggestions)}

## 源代码

```python
{state.source_code}
```

## 已有测试代码

```python
{state.test_code}
```

## 任务

请生成**补充测试用例**来覆盖上述缺口。要求：

1. **只生成新的测试函数**，不要重复已有测试
2. **针对性覆盖**未覆盖的代码行和分支
3. **确保测试独立性**，可以与现有测试一起运行
4. **使用相同的fixture**（如果已定义）

只输出补充的测试函数代码，不要包含import语句和fixture（除非需要新的）。
"""
        return prompt

    def _clean_generated_code(self, response: str, module_name: str) -> str:
        """清理生成的代码"""
        # 移除markdown标记
        code = response.replace('```python', '').replace('```', '').strip()

        # 确保有正确的导入
        if 'import pytest' not in code:
            code = 'import pytest\n' + code

        # 确保有模块导入（简单处理，实际应该更智能）
        if f'from {module_name} import' not in code:
            # 尝试从代码分析中提取需要导入的内容
            code = f'import pytest\n# TODO: 添加必要的导入\n' + code

        return code

    def _merge_test_code(self, existing: str, additional: str) -> str:
        """合并测试代码，避免重复导入"""
        # 分离导入语句和测试代码
        existing_lines = existing.split('\n')
        additional_lines = additional.split('\n')

        # 提取现有的导入
        imports = [line for line in existing_lines if line.startswith('import') or line.startswith('from')]

        # 提取补充代码中的新导入
        new_imports = [
            line for line in additional_lines
            if (line.startswith('import') or line.startswith('from')) and line not in imports
        ]

        # 提取补充的测试函数
        test_functions = [
            line for line in additional_lines
            if not (line.startswith('import') or line.startswith('from') or line.strip() == '')
        ]

        # 合并
        merged = existing + '\n\n# === 补充测试（迭代优化） ===\n' + '\n'.join(test_functions)

        return merged

    def _format_functions(self, functions: list) -> str:
        """格式化函数列表"""
        if not functions:
            return "无"
        return '\n'.join([f"  - {f['name']}({', '.join(f['args'])})" for f in functions])

    def _format_classes(self, classes: list) -> str:
        """格式化类列表"""
        if not classes:
            return "无"
        return '\n'.join([f"  - {c['name']} (方法: {', '.join(c['methods'])})" for c in classes])

    def _format_list(self, items: list) -> str:
        """格式化列表"""
        if not items:
            return "无"
        return '\n'.join([f"  - {item}" for item in items])
```

### 3.5 测试执行Agent (agents/test_executor_agent.py)

```python
import os
import subprocess
import tempfile
from .base_agent import BaseAgent
from workflow.state import TestGenerationState

class TestExecutorAgent(BaseAgent):
    """测试执行Agent"""

    def __init__(self, glm_service, upload_folder: str):
        super().__init__(glm_service, "TestExecutor")
        self.upload_folder = upload_folder

    def execute(self, state: TestGenerationState) -> TestGenerationState:
        """执行测试并收集覆盖率"""
        self.log(state, "执行测试用例")

        try:
            # 1. 保存测试文件
            test_file_path = self._save_test_file(state)
            source_file_path = self._save_source_file(state)

            # 2. 运行pytest with coverage
            coverage_report = self._run_pytest_with_coverage(
                test_file_path,
                source_file_path,
                state.module_name
            )

            state.coverage_report = coverage_report

            current_coverage = state.get_current_coverage()
            self.log(state, f"测试执行完成，当前覆盖率: {current_coverage:.1f}%", {
                'line_coverage': coverage_report.get('summary', {}).get('line_rate'),
                'function_coverage': coverage_report.get('summary', {}).get('function_rate')
            })

        except Exception as e:
            error_msg = f"测试执行失败: {str(e)}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)

        return state

    def _save_test_file(self, state: TestGenerationState) -> str:
        """保存测试文件"""
        test_filename = f'test_{state.module_name}.py'
        test_file_path = os.path.join(self.upload_folder, test_filename)

        with open(test_file_path, 'w') as f:
            f.write(state.test_code)

        return test_file_path

    def _save_source_file(self, state: TestGenerationState) -> str:
        """保存源代码文件"""
        source_filename = f'{state.module_name}.py'
        source_file_path = os.path.join(self.upload_folder, source_filename)

        # 如果文件不存在才保存（可能已经上传过了）
        if not os.path.exists(source_file_path):
            with open(source_file_path, 'w') as f:
                f.write(state.source_code)

        return source_file_path

    def _run_pytest_with_coverage(self, test_file: str, source_file: str, module_name: str) -> dict:
        """运行pytest并收集覆盖率"""

        # 这里复用app.py中的run_pytest_and_generate_coverage逻辑
        # 为了简化，直接调用
        from app import run_pytest_and_generate_coverage

        coverage_reports, test_output = run_pytest_and_generate_coverage(test_file)

        return coverage_reports
```

### 3.6 覆盖率分析Agent (agents/coverage_analyzer_agent.py)

```python
import ast
from .base_agent import BaseAgent
from workflow.state import TestGenerationState, CoverageGap

class CoverageAnalyzerAgent(BaseAgent):
    """覆盖率分析Agent"""

    def __init__(self, glm_service):
        super().__init__(glm_service, "CoverageAnalyzer")

    def execute(self, state: TestGenerationState) -> TestGenerationState:
        """分析覆盖率缺口"""
        self.log(state, "分析覆盖率缺口")

        current_coverage = state.get_current_coverage()

        if current_coverage >= state.target_coverage:
            self.log(state, f"已达到目标覆盖率 {state.target_coverage}%")
            state.is_complete = True
            return state

        try:
            # 1. 解析覆盖率报告
            gaps = self._analyze_coverage_gaps(state)

            # 2. 使用LLM生成优化建议
            suggestions = self._generate_suggestions_with_llm(state, gaps)
            gaps.suggestions = suggestions

            state.coverage_gaps = gaps

            self.log(state, "覆盖率缺口分析完成", {
                'uncovered_lines': len(gaps.uncovered_lines),
                'uncovered_functions': len(gaps.uncovered_functions)
            })

        except Exception as e:
            error_msg = f"覆盖率分析失败: {str(e)}"
            self.logger.error(error_msg)
            state.error_messages.append(error_msg)

        return state

    def _analyze_coverage_gaps(self, state: TestGenerationState) -> CoverageGap:
        """分析覆盖率缺口"""

        # 从覆盖率报告中提取信息
        coverage_report = state.coverage_report

        # 解析未覆盖的行
        uncovered_lines = self._parse_uncovered_lines(coverage_report)

        # 解析未覆盖的分支
        uncovered_branches = self._parse_uncovered_branches(coverage_report)

        # 解析未覆盖的函数
        uncovered_functions = self._parse_uncovered_functions(
            state.source_code,
            coverage_report
        )

        return CoverageGap(
            uncovered_lines=uncovered_lines,
            uncovered_branches=uncovered_branches,
            uncovered_functions=uncovered_functions,
            suggestions=[]
        )

    def _parse_uncovered_lines(self, coverage_report: dict) -> list:
        """解析未覆盖的代码行"""
        # 从coverage report中提取
        # 这里简化处理，实际需要解析coverage的详细输出
        line_report = coverage_report.get('line', '')

        # 提取类似 "Missing lines: 10-15, 20" 的信息
        uncovered = []
        if 'Missing' in line_report:
            # 简单解析（实际应该更robust）
            # TODO: 实现详细解析逻辑
            pass

        return uncovered

    def _parse_uncovered_branches(self, coverage_report: dict) -> list:
        """解析未覆盖的分支"""
        branch_report = coverage_report.get('branch', '')

        # 解析分支覆盖率报告
        uncovered_branches = []

        # TODO: 实现详细解析逻辑

        return uncovered_branches

    def _parse_uncovered_functions(self, source_code: str, coverage_report: dict) -> list:
        """解析未覆盖的函数"""

        # 使用AST获取所有函数
        tree = ast.parse(source_code)
        all_functions = [
            node.name for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
        ]

        # 从function coverage report中提取已覆盖的函数
        function_report = coverage_report.get('function', '')

        # 找出未覆盖的函数
        # TODO: 实现详细解析逻辑
        uncovered_functions = []

        return uncovered_functions

    def _generate_suggestions_with_llm(self, state: TestGenerationState, gaps: CoverageGap) -> list:
        """使用LLM生成优化建议"""

        if not gaps.uncovered_lines and not gaps.uncovered_functions:
            return []

        prompt = f"""你是测试专家。请分析以下代码覆盖率缺口，给出具体的测试建议。

## 源代码
```python
{state.source_code}
```

## 覆盖率缺口
- 未覆盖的代码行：{gaps.uncovered_lines}
- 未覆盖的函数：{gaps.uncovered_functions}
- 未覆盖的分支：{gaps.uncovered_branches}

## 已有测试
```python
{state.test_code}
```

请给出3-5条具体的测试建议，每条建议说明：
1. 需要测试的具体场景
2. 如何构造测试数据
3. 预期的测试效果

格式：
- 建议1: ...
- 建议2: ...
"""

        try:
            response = self._call_llm(prompt, temperature=0.3)
            # 简单解析建议列表
            suggestions = [
                line.strip() for line in response.split('\n')
                if line.strip().startswith('-') or line.strip().startswith('•')
            ]
            return suggestions[:5]  # 最多5条
        except Exception as e:
            self.logger.warning(f"生成建议失败: {e}")
            return ["增加边界条件测试", "增加异常处理测试", "增加分支覆盖测试"]
```

### 3.7 工作流编排器 (workflow/orchestrator.py)

```python
import logging
from typing import Optional
from GLMService import GLMService
from workflow.state import TestGenerationState
from agents.code_analyzer_agent import CodeAnalyzerAgent
from agents.test_generator_agent import TestGeneratorAgent
from agents.test_executor_agent import TestExecutorAgent
from agents.coverage_analyzer_agent import CoverageAnalyzerAgent

class AgenticTestGenerator:
    """Agentic测试生成编排器"""

    def __init__(self, glm_service: GLMService, upload_folder: str):
        self.logger = logging.getLogger("AgenticTestGenerator")

        # 初始化所有Agent
        self.code_analyzer = CodeAnalyzerAgent(glm_service)
        self.test_generator = TestGeneratorAgent(glm_service)
        self.test_executor = TestExecutorAgent(glm_service, upload_folder)
        self.coverage_analyzer = CoverageAnalyzerAgent(glm_service)

    def generate_tests(
        self,
        source_code: str,
        test_requirements: str,
        module_name: str,
        target_coverage: float = 90.0,
        max_iterations: int = 3
    ) -> TestGenerationState:
        """
        执行完整的测试生成工作流

        Args:
            source_code: 源代码
            test_requirements: 测试需求
            module_name: 模块名
            target_coverage: 目标覆盖率
            max_iterations: 最大迭代次数

        Returns:
            最终状态
        """
        # 初始化状态
        state = TestGenerationState(
            source_code=source_code,
            test_requirements=test_requirements,
            module_name=module_name,
            target_coverage=target_coverage,
            max_iterations=max_iterations
        )

        self.logger.info("="*60)
        self.logger.info("开始Agentic测试生成流程")
        self.logger.info(f"目标覆盖率: {target_coverage}%")
        self.logger.info(f"最大迭代次数: {max_iterations}")
        self.logger.info("="*60)

        try:
            # === 阶段1: 代码分析 ===
            self.logger.info("\n[阶段1] 代码分析")
            state = self.code_analyzer.execute(state)

            if state.error_messages:
                self.logger.error("代码分析阶段出错，终止流程")
                return state

            # === 迭代循环 ===
            while state.iteration < state.max_iterations and not state.is_complete:
                self.logger.info(f"\n{'='*60}")
                self.logger.info(f"[迭代 {state.iteration + 1}]")
                self.logger.info(f"{'='*60}")

                # 阶段2: 生成测试
                self.logger.info("[阶段2] 生成测试用例")
                state = self.test_generator.execute(state)

                if state.error_messages:
                    self.logger.warning(f"测试生成出错: {state.error_messages[-1]}")
                    break

                # 阶段3: 执行测试
                self.logger.info("[阶段3] 执行测试")
                state = self.test_executor.execute(state)

                if state.error_messages:
                    self.logger.warning(f"测试执行出错: {state.error_messages[-1]}")
                    break

                # 阶段4: 分析覆盖率
                self.logger.info("[阶段4] 分析覆盖率")
                state = self.coverage_analyzer.execute(state)

                current_coverage = state.get_current_coverage()
                self.logger.info(f"\n当前覆盖率: {current_coverage:.1f}%")

                # 检查是否完成
                if state.is_complete:
                    self.logger.info("✓ 已达到目标覆盖率！")
                    break

                if state.iteration >= state.max_iterations - 1:
                    self.logger.info("✗ 已达到最大迭代次数")
                    break

                state.iteration += 1

            # === 完成 ===
            self.logger.info("\n" + "="*60)
            self.logger.info("测试生成流程完成")
            self.logger.info(f"最终覆盖率: {state.get_current_coverage():.1f}%")
            self.logger.info(f"总迭代次数: {state.iteration + 1}")
            self.logger.info("="*60)

        except Exception as e:
            self.logger.error(f"工作流执行异常: {str(e)}", exc_info=True)
            state.error_messages.append(f"工作流异常: {str(e)}")

        return state

    def get_execution_log(self, state: TestGenerationState) -> list:
        """获取执行日志"""
        return state.agent_messages
```

## 四、集成到现有系统

### 4.1 修改 app.py

```python
# 在app.py中添加
from workflow.orchestrator import AgenticTestGenerator

# 创建全局实例
agentic_generator = AgenticTestGenerator(glm_service, app.config['UPLOAD_FOLDER'])

# 修改原有的generate_test_cases函数
def generate_test_cases_agentic(source_code, test_requirements, module_name):
    """使用Agentic工作流生成测试用例"""
    try:
        # 执行Agentic工作流
        state = agentic_generator.generate_tests(
            source_code=source_code,
            test_requirements=test_requirements,
            module_name=module_name,
            target_coverage=90.0,  # 可以从请求参数获取
            max_iterations=3
        )

        if state.error_messages:
            raise ValueError(f"生成失败: {'; '.join(state.error_messages)}")

        # 返回生成的测试代码（已经是字符串）
        return state.test_code.split('\n')

    except Exception as e:
        app.logger.error(f"Agentic测试生成失败: {str(e)}")
        raise

# 在index路由中使用
@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            # ... 文件上传处理 ...

            # 使用Agentic生成
            test_cases = generate_test_cases_agentic(
                code_content,
                test_requirements,
                module_name
            )

            # 后续流程保持不变
            # ...
```

### 4.2 更新 requirements.txt

```txt
Flask
requests
pytest
pytest-cov
coverage
werkzeug
```

## 五、配置文件 (config.py)

```python
import os

class AgenticConfig:
    """Agentic配置"""

    # 覆盖率目标
    DEFAULT_TARGET_COVERAGE = 90.0

    # 最大迭代次数
    MAX_ITERATIONS = 3

    # LLM温度参数
    ANALYSIS_TEMPERATURE = 0.3  # 代码分析用低温度
    GENERATION_TEMPERATURE = 0.7  # 测试生成用中等温度

    # Agent超时设置
    AGENT_TIMEOUT = 60  # 秒

    # 日志级别
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
```

## 六、测试方案

### 6.1 单元测试

为每个Agent编写单元测试：

```python
# tests/test_code_analyzer_agent.py
import pytest
from agents.code_analyzer_agent import CodeAnalyzerAgent

def test_extract_functions():
    code = """
def add(a, b):
    return a + b

def subtract(a, b):
    return a - b
"""
    agent = CodeAnalyzerAgent(mock_glm_service)
    state = TestGenerationState(source_code=code, ...)

    result = agent.execute(state)

    assert len(result.code_analysis.functions) == 2
    assert result.code_analysis.functions[0]['name'] == 'add'
```

### 6.2 集成测试

测试完整的工作流：

```python
# tests/test_orchestrator.py
def test_full_workflow():
    orchestrator = AgenticTestGenerator(glm_service, '/tmp')

    source_code = """
class Calculator:
    def add(self, a, b):
        return a + b
"""

    state = orchestrator.generate_tests(
        source_code=source_code,
        test_requirements="测试所有方法",
        module_name="calculator"
    )

    assert state.get_current_coverage() > 50
    assert 'def test_' in state.test_code
```

## 七、预期效果

### 性能指标
- **覆盖率提升**: 从当前70% → 85%+
- **迭代成功率**: >80%的案例在3次迭代内达标
- **生成时间**: 初始生成<30s，每次迭代<20s

### 用户体验
- 自动迭代优化，无需人工干预
- 显示详细的Agent执行日志
- 透明的决策过程

## 八、风险和应对

### 风险1: LLM调用成本高
**应对**:
- 设置最大迭代次数
- 缓存代码分析结果
- 使用更小的模型处理简单任务

### 风险2: 迭代不收敛
**应对**:
- 设置覆盖率增长阈值（如每次至少提升5%）
- 如果连续2次没有提升，提前终止
- 提供降级方案（回退到单次生成）

### 风险3: 生成的测试有语法错误
**应对**:
- 在TestExecutorAgent中增加语法检查
- 如果失败，将错误信息反馈给TestGeneratorAgent重新生成
- 最多重试2次

## 十、后续扩展

1. **Agent专业化**: 增加SecurityTestAgent、PerformanceTestAgent
2. **并行执行**: 多个Agent并行工作
3. **用户反馈循环**: 学习用户修改的测试
4. **RAG增强**: 添加知识库检索
5. **可视化**: Agent执行过程可视化展示
