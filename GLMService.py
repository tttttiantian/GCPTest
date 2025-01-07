import requests
import json
import os
from typing import List, Dict

class GLMService:
    def __init__(self):
        self.api_url = os.getenv('CODEGEEX_API_URL')
        self.api_key = os.getenv('CODEGEEX_API_KEY')
        self.model_id = os.getenv('MODEL_ID')
        self.conversations: Dict[str, List[Dict]] = {}  # 存储多个会话的历史记录

    def chat(self, message: str, conversation_id: str = None) -> str:
        """
        Handle chat messages using GLM model with conversation memory
        Args:
            message (str): User's chat message
            conversation_id (str): Unique identifier for the conversation
        Returns:
            str: Model's response
        """
        if not conversation_id:
            conversation_id = "default"

        # 初始化或获取现有的对话历史
        if conversation_id not in self.conversations:
            self.conversations[conversation_id] = []

        # 添加用户消息到对话历史
        self.conversations[conversation_id].append({
            "role": "user",
            "content": message
        })

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        # 使用完整的对话历史构建请求
        data = {
            'model': self.model_id,
            'messages': self.conversations[conversation_id],
            'temperature': 0.7,
            'max_tokens': 1000
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=data)
            response.raise_for_status()
            result = response.json()
            assistant_message = result['choices'][0]['message']['content']

            # 将助手的回复添加到对话历史
            self.conversations[conversation_id].append({
                "role": "assistant",
                "content": assistant_message
            })

            # 如果对话历史过长，可以进行裁剪
            if len(self.conversations[conversation_id]) > 20:  # 保留最近的20轮对话
                self.conversations[conversation_id] = self.conversations[conversation_id][-20:]

            return assistant_message
        except Exception as e:
            print(f"Error in chat: {str(e)}")
            return "I apologize, but I'm having trouble processing your message right now. Please try again later."

    def clear_conversation(self, conversation_id: str = None) -> bool:
        """
        Clear the conversation history for a specific conversation
        Args:
            conversation_id (str): Unique identifier for the conversation
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if not conversation_id:
                conversation_id = "default"
            if conversation_id in self.conversations:
                self.conversations[conversation_id] = []
            return True
        except Exception as e:
            print(f"Error clearing conversation: {str(e)}")
            return False


    def generate_test_cases(self, code_content, requirements, module_name):
        """
        Generate test cases using GLM model

        Args:
            code_content (str): Source code content to generate tests for
            requirements (str): Test requirements specified by user
            module_name (str): The name of the module to import in test cases.
            
        Returns:
            list: Generated test cases as a list of strings
        """
        # 从文件路径中提取模块名
        prompt = self._build_prompt(code_content, requirements, module_name)

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        data = {
            'model': self.model_id,
            'messages': [{
                'role': 'user',
                'content': prompt
            }],
            'temperature': 0.7,
            'max_tokens': 2000
        }

        try:
            response = requests.post(self.api_url, headers=headers, json=data)
            response.raise_for_status()

            result = response.json()
            generated_code = result['choices'][0]['message']['content']

            test_cases = self._parse_test_cases(generated_code)
            return test_cases

        except Exception as e:
            print(f"Error calling GLM API: {str(e)}")
            raise

    def _build_prompt(self, code_content, requirements, module_name):
        """
        构建更优化的prompt来生成测试用例
        
        Args:
            code_content (str): 源代码内容
            requirements (str): 测试需求
            module_name (str): 模块名称
        """
        prompt_template = """作为一个Python测试专家，请为以下代码生成高质量的Pytest测试用例。

源代码 ({module_name}.py):
{code_content}

测试需求: {requirements}

请遵循以下严格的测试用例生成规则：

1. 基本结构：
   - 保持测试结构简单，使用函数级测试
   - 必须首先正确导入pytest和被测模块
   - 正确初始化被测试的类实例
   - 确保在每个测试函数开始时都创建新的类实例
   - 每个测试函数必须以test_开头

2. 测试夹具（Fixtures）：
   - 使用pytest fixture来处理重复的实例初始化
   - fixture应该在测试模块级别定义
   - 确保fixture的作用域正确（通常使用 scope="function"）

3. 测试覆盖要求：
   - 每个类方法都必须有独立的测试函数
   - 使用参数化测试来测试不同的输入组合
   - 确保测试条件分支覆盖率
   - 确保异常处理覆盖率

请生成符合上述要求的Pytest测试用例。确保：
1. 生成的测试用例能被pytest直接执行
2. 能达到100%的函数覆盖率
3. 能达到较高的分支覆盖率
4. 所有测试用例都是独立的且可重复执行的

生成的测试代码示例格式：

import pytest
from {module_name} import ClassName

@pytest.fixture
def instance():
    return ClassName()

def test_method(instance):
    result = instance.method(param1, param2)
    assert result == expected_value

@pytest.mark.parametrize("param1,param2,expected", [
    (value1, value2, expected1),
    (value3, value4, expected2),
])
def test_method_parametrize(instance, param1, param2, expected):
    result = instance.method(param1, param2)
    assert result == expected

def test_method_error(instance):
    with pytest.raises(ExceptionType):
        instance.method(invalid_param)


请直接生成可执行的测试代码，不要包含任何解释性文本。"""
        
        return prompt_template.format(
            module_name=module_name,
            code_content=code_content,
            requirements=requirements
        )

    def _parse_test_cases(self, generated_code):
        """
        Parse the generated code into a list of test cases, removing explanatory text
        Replace any 'source_code' imports with the actual module name.

        Args:
            generated_code (str): Raw generated code from GLM model

        Returns:
            list: Clean test case code lines
        """
        # 移除markdown代码块标记
        code = generated_code.replace('```python', '').replace('```', '').strip()
        
        # 分割代码行
        lines = code.split('\n')
        cleaned_lines = []
        
        # 确保必要的导入
        has_pytest_import = False
        has_module_import = False
        has_fixture = False
        
        # 处理每一行代码
        for line in lines:
            line = line.rstrip()
            
            # 检查是否已包含必要的导入和fixture
            if line.startswith('import pytest'):
                has_pytest_import = True
            elif 'from calculator import' in line:
                has_module_import = True
            elif '@pytest.fixture' in line:
                has_fixture = True
                
            # 跳过注释和空行
            if not line or line.strip().startswith('#'):
                continue
                
            # 保留有效的测试代码
            if (not line.startswith('"""') and 
                not line.startswith("'''") and
                not line.startswith('Here') and 
                not line.startswith('Note')):
                cleaned_lines.append(line)
                
        # 如果缺少必要的导入和fixture，添加它们
        final_lines = []
        if not has_pytest_import:
            final_lines.append('import pytest')
        if not has_module_import:
            final_lines.append('from calculator import Calculator')
        
        if not has_fixture:
            final_lines.extend([
                '',
                '@pytest.fixture(scope="function")',
                'def calculator():',
                '    return Calculator()',
                ''
            ])
        
        # 添加其余的测试代码
        final_lines.extend(cleaned_lines)
        
        # 确保代码的完整性和正确性
        test_code = '\n'.join(final_lines)
        
        return test_code.split('\n')