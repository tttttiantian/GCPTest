import requests
import json
import os
from typing import List, Dict
from services.rate_limiter import TokenBucket

class GLMService:
    def __init__(self):
        self.api_url = os.getenv('CODEGEEX_API_URL')
        self.api_key = os.getenv('CODEGEEX_API_KEY')
        self.model_id = os.getenv('MODEL_ID')
        self.conversations: Dict[str, List[Dict]] = {}  # 存储多个会话的历史记录

        # 添加限流器：40 QPS（根据您的API配额调整）
        self.rate_limiter = TokenBucket(rate=40, capacity=80)

        # 添加logger
        import logging
        self.logger = logging.getLogger("GLMService")
        self.logger.setLevel(logging.INFO)

    def chat(self, message: str, conversation_id: str = None, max_tokens: int = 1000) -> str:
        """
        Handle chat messages using GLM model with conversation memory
        Args:
            message (str): User's chat message
            conversation_id (str): Unique identifier for the conversation
            max_tokens (int): Maximum tokens for response
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
            'max_tokens': max_tokens  # 使用传入的max_tokens参数
        }

        try:
            # 等待限流令牌
            if not self.rate_limiter.wait_for_token(timeout=30):
                self.logger.warning("[chat] GLM API rate limit exceeded")
                return "服务繁忙，请稍后再试"

            response = requests.post(self.api_url, headers=headers, json=data, timeout=30)

            # 记录请求详情
            print(f"[DEBUG] API请求详情:")
            print(f"  URL: {self.api_url}")
            print(f"  Model: {self.model_id}")
            print(f"  Max Tokens: {max_tokens}")
            print(f"  Messages Count: {len(data['messages'])}")
            print(f"  Status Code: {response.status_code}")

            response.raise_for_status()
            result = response.json()

            # 检查响应格式
            if 'choices' not in result:
                print(f"[ERROR] API响应格式错误，缺少choices字段")
                print(f"[ERROR] 完整响应: {json.dumps(result, ensure_ascii=False)}")
                return "API response format error: missing 'choices' field"

            if len(result['choices']) == 0:
                print(f"[ERROR] API响应的choices数组为空")
                return "API response error: empty choices array"

            assistant_message = result['choices'][0]['message']['content']

            print(f"[DEBUG] LLM成功返回，内容长度: {len(assistant_message)}")

            # 将助手的回复添加到对话历史
            self.conversations[conversation_id].append({
                "role": "assistant",
                "content": assistant_message
            })

            # 如果对话历史过长，可以进行裁剪
            if len(self.conversations[conversation_id]) > 20:  # 保留最近的20轮对话
                self.conversations[conversation_id] = self.conversations[conversation_id][-20:]

            return assistant_message
        except requests.exceptions.HTTPError as e:
            # HTTP错误（4xx, 5xx）
            print(f"[ERROR] HTTP Error: {e}")
            print(f"[ERROR] Status Code: {e.response.status_code}")
            print(f"[ERROR] Response Body: {e.response.text}")
            return "I apologize, but I'm having trouble processing your message right now. Please try again later."
        except requests.exceptions.Timeout as e:
            print(f"[ERROR] Request Timeout: {e}")
            return "I apologize, but I'm having trouble processing your message right now. Please try again later."
        except requests.exceptions.RequestException as e:
            print(f"[ERROR] Request Exception: {e}")
            return "I apologize, but I'm having trouble processing your message right now. Please try again later."
        except KeyError as e:
            print(f"[ERROR] KeyError accessing response: {e}")
            print(f"[ERROR] Response structure: {json.dumps(result, ensure_ascii=False)[:500]}")
            return "I apologize, but I'm having trouble processing your message right now. Please try again later."
        except Exception as e:
            # 详细记录错误信息
            print(f"[ERROR] Unexpected error in chat: {str(e)}")
            print(f"[ERROR] Error type: {type(e).__name__}")
            import traceback
            print(f"[ERROR] Full traceback:\n{traceback.format_exc()}")
            return "I apologize, but I'm having trouble processing your message right now. Please try again later."

    def chat_once(self, message: str, temperature: float = 0.7, max_tokens: int = 2000) -> str:
        """
        单次对话，不保留历史（适合Agent使用）

        Args:
            message: 用户消息
            temperature: 温度参数
            max_tokens: 最大token数

        Returns:
            模型响应
        """
        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        # 单次对话，不使用历史
        data = {
            'model': self.model_id,
            'messages': [{
                'role': 'user',
                'content': message
            }],
            'temperature': temperature,
            'max_tokens': max_tokens
        }

        # 添加重试机制
        max_retries = 3
        for attempt in range(max_retries):
            try:
                # 等待限流令牌
                if not self.rate_limiter.wait_for_token(timeout=30):
                    self.logger.warning("[chat_once] GLM API rate limit exceeded")
                    raise TimeoutError("GLM API rate limit exceeded, please try again later")

                self.logger.info(f"[chat_once] 开始API请求 (尝试 {attempt + 1}/{max_retries})")
                self.logger.info(f"[chat_once] URL: {self.api_url}")
                self.logger.info(f"[chat_once] Model: {self.model_id}")
                self.logger.info(f"[chat_once] Prompt Length: {len(message)} chars (~{len(message)//4} tokens)")
                self.logger.info(f"[chat_once] Max Tokens: {max_tokens}")

                response = requests.post(self.api_url, headers=headers, json=data, timeout=60)

                self.logger.info(f"[chat_once] Status Code: {response.status_code}")

                response.raise_for_status()
                result = response.json()

                if 'choices' not in result or len(result['choices']) == 0:
                    self.logger.error(f"[chat_once] Invalid API response format")
                    self.logger.error(f"[chat_once] Response: {json.dumps(result, ensure_ascii=False)[:500]}")
                    return "API response error"

                assistant_message = result['choices'][0]['message']['content']
                self.logger.info(f"[chat_once] LLM返回成功，长度: {len(assistant_message)} chars")

                return assistant_message

            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
                self.logger.warning(f"[chat_once] 连接错误 (尝试 {attempt + 1}/{max_retries}): {str(e)}")
                if attempt < max_retries - 1:
                    import time
                    wait_time = 2 ** attempt  # 指数退避: 1s, 2s, 4s
                    self.logger.info(f"[chat_once] 等待 {wait_time}秒后重试...")
                    time.sleep(wait_time)
                    continue
                else:
                    self.logger.error(f"[chat_once] 所有重试均失败")
                    return "API连接失败，请稍后重试"
            except requests.exceptions.HTTPError as e:
                self.logger.error(f"[chat_once] HTTP Error: {e}")
                self.logger.error(f"[chat_once] Status Code: {e.response.status_code}")
                self.logger.error(f"[chat_once] Response: {e.response.text[:1000]}")
                return "API HTTP Error"
            except Exception as e:
                self.logger.error(f"[chat_once] Error: {str(e)}")
                import traceback
                self.logger.error(f"[chat_once] Traceback:\n{traceback.format_exc()}")
                if attempt < max_retries - 1:
                    import time
                    time.sleep(1)
                    continue
                return "API Error"

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
            # 等待限流令牌
            if not self.rate_limiter.wait_for_token(timeout=30):
                raise TimeoutError("GLM API rate limit exceeded, please try again later")

            response = requests.post(self.api_url, headers=headers, json=data)
            response.raise_for_status()

            result = response.json()
            generated_code = result['choices'][0]['message']['content']

            test_cases = self._parse_test_cases(generated_code, module_name)
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

    def _parse_test_cases(self, generated_code, module_name):
        """
        Parse the generated code into a list of test cases, removing explanatory text
        Replace any 'source_code' imports with the actual module name.

        Args:
            generated_code (str): Raw generated code from GLM model
            module_name (str): The name of the module to import in test cases

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
            elif f'from {module_name} import' in line:
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
            # 动态提取类和异常名
            class_and_exception_names = self._extract_class_and_exception_names(code)
            final_lines.append(f'from {module_name} import {", ".join(class_and_exception_names)}')
        
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
        
        # 移除多余的导入
        final_lines = [line for line in final_lines if not line.startswith('from bank_account import')]
        
        # 确保代码的完整性和正确性
        test_code = '\n'.join(final_lines)
        
        return test_code.split('\n')

    def _extract_class_and_exception_names(self, code):
        """
        从生成的代码中提取类和异常名

        Args:
            code (str): 生成的代码

        Returns:
            list: 类和异常名列表
        """
        import re
        pattern = re.compile(r'from \w+ import (\w+(?:, \w+)*)')
        matches = pattern.findall(code)
        if matches:
            return matches[0].split(', ')
        return []
