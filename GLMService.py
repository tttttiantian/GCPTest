# app.py
from flask import Flask, request, render_template, jsonify, send_file, url_for, session, Response
import os
from werkzeug.utils import secure_filename
import subprocess
import traceback
from GLMService import GLMService
from workflow.orchestrator import AgenticTestGenerator
from services.session_manager import SessionManager
import uuid
import secrets
import ast
import logging
import json
import queue
import threading
import time

# 设置日志记录
logging.basicConfig(level=logging.INFO,  # 设置日志级别为 INFO
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
    logging.StreamHandler()  # 输出日志到控制台
    ])

app = Flask(__name__)

# 使用环境变量或生成随机密钥（更安全）
app.secret_key = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Session配置 - 确保session cookie正确设置
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SECURE'] = False  # 本地开发设为False
app.config['PERMANENT_SESSION_LIFETIME'] = 3600  # 1小时

# 创建一个全局的 GLMService 实例，这样可以在所有请求之间共享会话历史
glm_service = GLMService()

# 配置上传文件夹
app.config['UPLOAD_FOLDER'] = '/app/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'py'}

# 初始化会话管理器
session_manager = SessionManager(app.config['UPLOAD_FOLDER'])

# 确保 uploads 文件夹存在
if not os.path.exists(app.config['UPLOAD_FOLDER']):
    os.makedirs(app.config['UPLOAD_FOLDER'])

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']

@app.route('/chat', methods=['POST'])
def chat():
    try:
        data = request.json
        message = data.get('message')
        
        if not message:
            return jsonify({'error': 'No message provided'}), 400

        # 获取或创建会话ID
        conversation_id = session.get('conversation_id')
        if not conversation_id:
            conversation_id = str(uuid.uuid4())
            session['conversation_id'] = conversation_id
            app.logger.info(f"Created new conversation with ID: {conversation_id}")
        
        # 使用全局 GLMService 实例处理聊天消息
        response = glm_service.chat(message, conversation_id)
        
        return jsonify({
            'response': response,
            'conversation_id': conversation_id
        })
    except Exception as e:
        app.logger.error(f"Error in chat endpoint: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': 'An error occurred processing your message'}), 500

@app.route('/clear-chat', methods=['POST'])
def clear_chat():
    try:
        conversation_id = session.get('conversation_id')
        if conversation_id:
            success = glm_service.clear_conversation(conversation_id)
            if success:
                return jsonify({'message': 'Conversation cleared successfully'})
        return jsonify({'error': 'Unable to clear conversation'}), 400
    except Exception as e:
        app.logger.error(f"Error clearing chat: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': 'An error occurred clearing the conversation'}), 500

@app.route('/clear-session', methods=['POST'])
def clear_session():
    """清理当前会话"""
    try:
        session_id = session.get('session_id')
        if session_id:
            session_manager.cleanup_session(session_id)
            session.pop('session_id', None)
            return jsonify({'message': 'Session cleared successfully'})
        return jsonify({'error': 'No active session'}), 400
    except Exception as e:
        app.logger.error(f"Error clearing session: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': 'An error occurred clearing the session'}), 500

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            # 获取原始需求（新增 - 功能规格）
            original_requirements = request.form.get('original_requirements', '')
            # 获取测试策略（可选）
            test_requirements = request.form.get('test_requirements', '')
            # 获取目标覆盖率参数（可选，默认90%）
            target_coverage = float(request.form.get('target_coverage', 90.0))

            if 'code_file' not in request.files:
                return jsonify({'error': 'No file uploaded'}), 400

            code_file = request.files['code_file']
            if not code_file or not allowed_file(code_file.filename):
                return jsonify({'error': 'Invalid file type'}), 400

            filename = secure_filename(code_file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            code_file.save(file_path)

            module_name = os.path.splitext(filename)[0]

            # 根据配置选择使用Agentic模式或原有模式
            if USE_AGENTIC:
                app.logger.info("使用Agentic模式生成测试用例")
                test_cases = generate_test_cases_agentic(
                    original_requirements,
                    test_requirements,
                    file_path,
                    module_name,
                    target_coverage=target_coverage
                )
            else:
                app.logger.info("使用传统模式生成测试用例")
                test_cases = generate_test_cases(original_requirements, test_requirements, file_path, module_name)

            test_case_file_path = create_test_case_file(test_cases, file_path)

            # 运行测试并获取结果
            coverage_reports, test_output = run_pytest_and_generate_coverage(test_case_file_path)
            
            # 准备响应数据
            download_url = url_for('download_test_cases', filename=os.path.basename(test_case_file_path))
            test_code = '\n'.join(test_cases)
            return render_template('index.html', 
                                coverage_report=coverage_reports,
                                test_output=test_output,
                                download_url=download_url,
                                test_code=test_code)

        except Exception as e:
            error_trace = traceback.format_exc()
            app.logger.error(f"Error processing request: {error_trace}")
            return jsonify({
                'error': 'An error occurred while processing your request',
                'message': str(e),
                'details': error_trace
            }), 500

    return render_template('index.html')

@app.route('/download/<filename>')
def download_test_cases(filename):
    try:
        session_id = request.args.get('session_id')

        if session_id:
            # 从session目录查找文件
            session = session_manager.get_session(session_id)
            if not session:
                return jsonify({'error': 'Session not found'}), 404
            file_path = os.path.join(session['session_folder'], filename)
        else:
            # 兼容旧逻辑：从根目录查找
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)

        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({'error': 'Error downloading file', 'message': str(e)}), 500


# SSE流式生成端点
@app.route('/generate-stream', methods=['POST'])
def generate_stream():
    """
    流式生成测试用例，通过SSE实时返回迭代进度
    """
    try:
        # 获取或创建会话
        session_id = session.get('session_id')
        if not session_id:
            session_info = session_manager.create_session()
            session_id = session_info['session_id']
            session['session_id'] = session_id
            session.permanent = True  # 标记为permanent session
            app.logger.info(f"创建新会话: {session_id}")
            app.logger.info(f"会话信息: {session_info}")
            app.logger.info(f"Session Manager中的所有会话: {list(session_manager.sessions.keys())}")
        else:
            session_info = session_manager.get_session(session_id)
            if not session_info:
                # 会话过期，创建新的
                session_info = session_manager.create_session()
                session_id = session_info['session_id']
                session['session_id'] = session_id
                session.permanent = True  # 标记为permanent session
                app.logger.info(f"会话过期，创建新会话: {session_id}")
                app.logger.info(f"Session Manager中的所有会话: {list(session_manager.sessions.keys())}")
            else:
                session.permanent = True  # 确保session持久化
                app.logger.info(f"使用现有会话: {session_id}")
                app.logger.info(f"Session Manager中的所有会话: {list(session_manager.sessions.keys())}")

        # 获取原始需求（功能规格）
        original_requirements = request.form.get('original_requirements', '')
        # 获取测试策略（可选）
        test_requirements = request.form.get('test_requirements', '')
        target_coverage = float(request.form.get('target_coverage', 90.0))

        if 'code_file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400

        code_file = request.files['code_file']
        if not code_file or not allowed_file(code_file.filename):
            return jsonify({'error': 'Invalid file type'}), 400

        filename = secure_filename(code_file.filename)
        # 使用会话独立的文件夹
        file_path = os.path.join(session_info['session_folder'], filename)
        code_file.save(file_path)

        module_name = os.path.splitext(filename)[0]

        # 读取源代码
        with open(file_path, 'r') as f:
            code_content = f.read()

        # 使用会话独立的上传目录
        upload_folder = session_info['session_folder']

        def generate():
            """SSE事件生成器"""
            event_queue = queue.Queue()
            result_holder = {'state': None, 'error': None}

            def status_callback(status):
                """状态回调函数"""
                event_type = status.get('event', 'unknown')
                app.logger.info(f"[SSE] 接收到事件: {event_type}")
                event_queue.put(status)
                app.logger.debug(f"[SSE] 事件 {event_type} 已放入队列")

            def run_generation():
                """在后台线程运行生成任务"""
                try:
                    # 创建新的generator实例以支持回调
                    generator = AgenticTestGenerator(glm_service, upload_folder)
                    generator.set_status_callback(status_callback)

                    state = generator.generate_tests(
                        source_code=code_content,
                        original_requirements=original_requirements,
                        test_requirements=test_requirements,
                        module_name=module_name,
                        target_coverage=target_coverage,
                        max_iterations=3,
                        session_id=session_id
                    )
                    result_holder['state'] = state
                    # complete事件已由orchestrator发送，包含所有结果数据

                except Exception as e:
                    import traceback as tb
                    app.logger.error(f"Generation error: {str(e)}\n{tb.format_exc()}")
                    result_holder['error'] = str(e)
                    # 发送错误事件
                    event_queue.put({'event': 'error', 'message': str(e)})
                finally:
                    # 增加延迟时间，确保complete事件被消费后再发送结束信号
                    app.logger.info("后台线程即将结束，等待2秒确保所有事件都被发送...")
                    time.sleep(2.0)  # 从0.5秒增加到2秒
                    app.logger.info("发送结束信号到事件队列")
                    event_queue.put(None)  # 发送结束信号

            # 启动后台线程
            thread = threading.Thread(target=run_generation)
            thread.start()

            # 从队列中读取事件并发送
            while True:
                try:
                    event = event_queue.get(timeout=180)  # 3分钟超时
                    if event is None:
                        break

                    # 如果是complete事件，注入session_id
                    if event.get('event') == 'complete':
                        event['session_id'] = session_id
                        app.logger.info(f"[SSE] 向complete事件注入session_id: {session_id}")

                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
                except queue.Empty:
                    yield f"data: {json.dumps({'event': 'timeout'})}\n\n"
                    break

            # 等待线程结束
            thread.join(timeout=10)

        return Response(
            generate(),
            mimetype='text/event-stream',
            headers={
                'Cache-Control': 'no-cache',
                'Connection': 'keep-alive',
                'X-Accel-Buffering': 'no'
            }
        )

    except Exception as e:
        app.logger.error(f"Stream generation error: {str(e)}\n{traceback.format_exc()}")
        return jsonify({'error': str(e)}), 500


# 重新运行编辑后的测试
@app.route('/rerun-tests', methods=['POST'])
def rerun_tests():
    """
    重新运行编辑后的测试代码
    """
    try:
        data = request.get_json()

        # 验证参数
        test_code = data.get('test_code')
        source_filename = data.get('source_filename')
        session_id_from_body = data.get('session_id')  # 从请求体获取session_id

        if not test_code or not source_filename:
            return jsonify({
                'success': False,
                'error': 'Missing required parameters: test_code and source_filename'
            }), 400

        # 获取会话信息 - 优先使用请求体中的session_id，其次使用Flask session
        session_id = session_id_from_body or session.get('session_id')
        app.logger.info(f"[RERUN] Session ID from request body: {session_id_from_body}")
        app.logger.info(f"[RERUN] Session ID from Flask session: {session.get('session_id')}")
        app.logger.info(f"[RERUN] Using session ID: {session_id}")

        # 调试：查看session_manager中所有的session
        app.logger.info(f"[RERUN] All sessions in manager: {list(session_manager.sessions.keys())}")

        if not session_id:
            # 尝试从所有活动会话中找到最近的一个（临时解决方案）
            all_sessions = session_manager.sessions
            if all_sessions:
                # 获取最近创建的会话
                latest_session = max(all_sessions.items(), key=lambda x: x[1]['created_at'])
                session_id = latest_session[0]
                session['session_id'] = session_id  # 重新设置session
                app.logger.info(f"[RERUN] Using latest session: {session_id}")
            else:
                app.logger.error("[RERUN] No active session found and no sessions available")
                return jsonify({
                    'success': False,
                    'error': 'No active session found. Please regenerate tests first.'
                }), 401

        session_info = session_manager.get_session(session_id)
        if not session_info:
            app.logger.error(f"[RERUN] Session not found even after filesystem recovery: {session_id}")
            return jsonify({
                'success': False,
                'error': 'Session expired or invalid'
            }), 404

        app.logger.info(f"[RERUN] Session recovered successfully: {session_info['folder_name']}")
        session_dir = session_info['session_folder']
        app.logger.info(f"[RERUN] Rerunning tests in directory: {session_dir}")

        # 代码语法验证（可选）
        syntax_validation = validate_python_code(test_code)
        if not syntax_validation['valid']:
            return jsonify({
                'success': False,
                'error': f"Syntax error at line {syntax_validation['line']}: {syntax_validation['error']}"
            }), 400

        # 保存编辑后的测试代码
        test_filename = f"test_{source_filename}"
        test_file_path = os.path.join(session_dir, test_filename)

        with open(test_file_path, 'w', encoding='utf-8') as f:
            f.write(test_code)

        app.logger.info(f"Test file updated: {test_file_path}")

        # 更新会话历史（可选）
        session_manager.update_test_file(session_id, test_code)

        # 运行pytest并生成覆盖率报告
        coverage_reports, test_output = run_pytest_and_generate_coverage(test_file_path)

        # 更新下载URL
        download_url = url_for('download_test_cases', filename=test_filename, session_id=session_id)

        return jsonify({
            'success': True,
            'coverage_report': coverage_reports,
            'test_output': test_output,
            'test_code': test_code,
            'download_url': download_url
        })

    except Exception as e:
        app.logger.error(f"Error in rerun_tests: {str(e)}", exc_info=True)
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


# 验证Python代码语法
def validate_python_code(code: str) -> dict:
    """
    验证Python代码语法

    Args:
        code: Python代码字符串

    Returns:
        {
            'valid': bool,
            'error': str or None,
            'line': int or None
        }
    """
    import ast
    try:
        ast.parse(code)
        return {'valid': True, 'error': None, 'line': None}
    except SyntaxError as e:
        return {
            'valid': False,
            'error': str(e.msg),
            'line': e.lineno
        }
    except Exception as e:
        return {
            'valid': False,
            'error': str(e),
            'line': None
        }


# 配置：是否使用Agentic模式（可通过环境变量控制）
USE_AGENTIC = os.getenv('USE_AGENTIC', 'true').lower() == 'true'

def generate_test_cases_agentic(original_requirements, test_requirements, file_path, module_name, target_coverage=90.0):
    """
    使用Agentic工作流生成测试用例

    Args:
        original_requirements: 原始业务需求（功能规格）
        test_requirements: 测试策略需求（可选）
        file_path: 源代码文件路径
        module_name: 模块名
        target_coverage: 目标覆盖率（默认90%）

    Returns:
        测试用例列表（字符串列表）
    """
    try:
        # 读取源代码
        with open(file_path, 'r') as f:
            code_content = f.read()

        app.logger.info(f"开始Agentic测试生成: 模块={module_name}, 目标覆盖率={target_coverage}%")
        if original_requirements:
            app.logger.info(f"使用原始需求生成测试（基于需求的正确性验证）")
        else:
            app.logger.info(f"未提供原始需求，将基于代码逻辑推理生成测试")

        # 执行Agentic工作流
        state = agentic_generator.generate_tests(
            source_code=code_content,
            original_requirements=original_requirements,
            test_requirements=test_requirements,
            module_name=module_name,
            target_coverage=target_coverage,
            max_iterations=3
        )

        # 检查是否有错误
        if state.error_messages:
            raise ValueError(f"生成失败: {'; '.join(state.error_messages)}")

        # 记录执行摘要
        summary = agentic_generator.get_summary(state)
        app.logger.info(f"Agentic生成完成: 迭代{summary['iterations']}次, "
                       f"覆盖率{summary['final_coverage']}%, "
                       f"生成{summary['test_functions_count']}个测试")

        # 返回生成的测试代码（分割成行）
        return state.test_code.split('\n')

    except Exception as e:
        app.logger.error(f"Agentic测试生成失败: {str(e)}")
        raise

def generate_test_cases(test_requirements, file_path, module_name):
    """原有的单次LLM调用测试生成（备用）"""
    try:
        with open(file_path, 'r') as f:
            code_content = f.read()

        test_cases = glm_service.generate_test_cases(code_content, test_requirements, module_name)

        if not test_cases:
            raise ValueError("No test cases were generated")

        return test_cases
    except Exception as e:
        app.logger.error(f"Error generating test cases: {str(e)}")
        raise

def create_test_case_file(test_cases, file_path):
    try:
        test_case_file_name = 'test_' + os.path.basename(file_path)
        test_case_file_path = os.path.join(app.config['UPLOAD_FOLDER'], test_case_file_name)
        
        with open(test_case_file_path, 'w') as file:
            file.write('\n'.join(test_cases))
        
        app.logger.info(f"Generated test case file: {test_case_file_path}")
        return test_case_file_path
    except Exception as e:
        app.logger.error(f"Error creating test case file: {str(e)}")
        raise

# app.py 中的 run_pytest_and_generate_coverage 函数更新

def run_pytest_and_generate_coverage(test_case_file_path):
    try:
        # 确保源代码文件和测试文件在同一目录
        source_file = test_case_file_path.replace('test_', '')
        module_name = os.path.splitext(os.path.basename(source_file))[0]
        
        if not os.path.exists(source_file):
            raise FileNotFoundError(f"Source file not found: {source_file}")

        # 修正 coverage 配置格式 - 使用相对路径
        coverage_config = '''[run]
branch = true
source = .
data_file = .coverage
relative_files = true

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    if __name__ == .__main__.:
    raise NotImplementedError
    pass
show_missing = true
skip_covered = false
'''

        config_path = os.path.join(app.config['UPLOAD_FOLDER'], '.coveragerc')
        with open(config_path, 'w') as f:
            f.write(coverage_config)

        # 清理之前的覆盖率数据
        coverage_data_file = os.path.join(app.config['UPLOAD_FOLDER'], '.coverage')
        if os.path.exists(coverage_data_file):
            os.remove(coverage_data_file)
            app.logger.info("已清理旧的覆盖率数据")

        # 运行测试并收集覆盖率数据 - 只分析当前源文件
        # 使用相对路径来确保coverage能正确跟踪
        source_basename = os.path.basename(source_file)

        test_result = subprocess.run([
            'coverage', 'run',
            '--branch',  # 显式启用分支覆盖率
            '--source', '.',  # 跟踪当前目录下的所有文件
            '-m', 'pytest',
            test_case_file_path,
            '-v'
        ], cwd=app.config['UPLOAD_FOLDER'], capture_output=True, text=True)

        # 记录pytest输出用于调试（显示更多内容）
        app.logger.info(f"pytest stdout (first 1000 chars): {test_result.stdout[:1000] if test_result.stdout else 'None'}")
        app.logger.info(f"pytest stderr (first 1000 chars): {test_result.stderr[:1000] if test_result.stderr else 'None'}")
        app.logger.info(f"pytest return code: {test_result.returncode}")
        app.logger.info(f"pytest stdout length: {len(test_result.stdout) if test_result.stdout else 0}")

        # 运行完成后立即生成覆盖率报告 - 只显示源文件
        subprocess.run(['coverage', 'report', '--include', source_basename], cwd=app.config['UPLOAD_FOLDER'])

        coverage_reports = {}

        # 收集行覆盖率报告 - 只包含源文件（使用相对路径）
        line_report = subprocess.run(
            ['coverage', 'report', '--include', source_basename],
            cwd=app.config['UPLOAD_FOLDER'],
            capture_output=True,
            text=True
        )
        coverage_reports['line'] = line_report.stdout if line_report.stdout else "No line coverage report generated"

        # 解析行覆盖率和分支覆盖率 - 从同一个报告中提取
        # 报告格式: Name  Stmts  Miss  Branch  BrPart  Cover  Missing
        line_coverage = 0
        branch_coverage = 0
        total_branches = 0
        partial_branches = 0

        if line_report.stdout:
            try:
                lines = line_report.stdout.strip().split('\n')
                app.logger.info(f"覆盖率报告内容:\n{line_report.stdout}")

                # 查找包含源文件名的行
                for line in lines:
                    if module_name + '.py' in line and 'test_' not in line:
                        parts = line.split()
                        app.logger.info(f"找到源文件行: {line}")
                        app.logger.info(f"分割后的parts: {parts}, 长度: {len(parts)}")

                        # 格式: filename.py  Stmts  Miss  Branch  BrPart  Cover  Missing
                        # 索引:     0          1      2      3       4       5      6+
                        if len(parts) >= 6:
                            try:
                                # 提取语句数据 - Stmts列是索引1，Miss列是索引2
                                total_stmts = int(parts[1])
                                missed_stmts = int(parts[2])

                                # 提取分支数据 - Branch列是索引3，BrPart列是索引4
                                total_branches = int(parts[3])
                                partial_branches = int(parts[4])

                                # 从 Cover 列提取总覆盖率（这是 pytest-cov 计算的综合覆盖率）
                                total_coverage = 0.0
                                for part in parts[5:]:  # Cover 列在索引5之后
                                    if '%' in part:
                                        cover_str = part.rstrip('%')
                                        total_coverage = float(cover_str)
                                        app.logger.info(f"从 Cover 列提取总覆盖率: {total_coverage}%")
                                        break

                                # 计算行覆盖率（仅用于显示）：(Stmts - Miss) / Stmts * 100
                                if total_stmts > 0:
                                    line_coverage = ((total_stmts - missed_stmts) / total_stmts) * 100.0
                                    app.logger.info(f"行覆盖率计算: ({total_stmts} - {missed_stmts}) / {total_stmts} = {line_coverage:.1f}%")
                                else:
                                    line_coverage = 0.0
                                    app.logger.info("代码中没有语句，行覆盖率设为0%")

                                # 计算分支覆盖率（仅用于显示）：(Branch - BrPart) / Branch * 100
                                # BrPart=部分覆盖的分支数，Branch-BrPart=完全覆盖的分支数
                                if total_stmts > 0 and missed_stmts == total_stmts:
                                    # 如果所有语句都未执行，分支覆盖率也应该是0%
                                    branch_coverage = 0.0
                                    app.logger.info(f"所有代码未执行，分支覆盖率设为0%")
                                elif total_branches > 0:
                                    fully_covered_branches = total_branches - partial_branches
                                    branch_coverage = (fully_covered_branches / total_branches) * 100.0
                                    app.logger.info(f"分支覆盖率计算: ({total_branches} - {partial_branches})(完全覆盖) / {total_branches}(总分支) = {branch_coverage:.1f}%")
                                else:
                                    branch_coverage = 100.0  # 没有分支则认为100%覆盖
                                    app.logger.info("代码中没有分支，分支覆盖率设为100%")

                            except (ValueError, IndexError) as e:
                                app.logger.warning(f"解析覆盖率数据失败: {e}, parts={parts}")
                        else:
                            # 可能是没有分支的情况，格式: filename.py  Stmts  Miss  Cover  Missing
                            app.logger.info(f"报告格式可能不包含分支信息，parts长度: {len(parts)}")
                            try:
                                # 提取语句数据
                                total_stmts = int(parts[1])
                                missed_stmts = int(parts[2])

                                # 从 Cover 列提取总覆盖率
                                total_coverage = 0.0
                                for part in parts[3:]:  # 简化格式中 Cover 列在索引3之后
                                    if '%' in part:
                                        cover_str = part.rstrip('%')
                                        total_coverage = float(cover_str)
                                        break

                                # 计算行覆盖率（仅用于显示）：(Stmts - Miss) / Stmts * 100
                                if total_stmts > 0:
                                    line_coverage = ((total_stmts - missed_stmts) / total_stmts) * 100.0
                                else:
                                    line_coverage = 0.0

                                branch_coverage = 100.0  # 没有分支列，认为100%
                                app.logger.info(f"从 Cover 列提取总覆盖率: {total_coverage}%, 行覆盖率: {line_coverage:.1f}%, 无分支信息")
                            except (ValueError, IndexError) as e:
                                app.logger.warning(f"解析简化格式覆盖率失败: {e}, parts={parts}")
                                total_coverage = 0.0
                                line_coverage = 0
                                branch_coverage = 100.0
                        break

            except (IndexError, ValueError) as e:
                app.logger.warning(f"解析覆盖率失败: {e}")
                line_coverage = 0
                branch_coverage = 0

        # 分支覆盖率报告使用相同的数据
        coverage_reports['branch'] = line_report.stdout if line_report.stdout else "No branch coverage report generated"

        # 分析函数覆盖率
        try:
            # 首先定义新的分析函数（把我之前发送的 analyze_function_coverage 函数完整粘贴到这里）
            def analyze_function_coverage(source_file, coverage_data_file):
                """
                Improved function coverage analysis
                """
                import coverage
                import ast
                
                # 创建coverage对象
                cov = coverage.Coverage(data_file=coverage_data_file)
                cov.load()
                
                # 获取源代码分析结果
                with open(source_file, 'r') as f:
                    source_code = f.read()
                    tree = ast.parse(source_code)
                
                # 获取文件的覆盖数据
                file_data = cov.get_data()

                # 尝试多种路径格式来匹配coverage数据
                covered_lines = None
                source_basename = os.path.basename(source_file)

                # 尝试不同的路径格式
                for possible_path in [source_file, source_basename, os.path.abspath(source_file)]:
                    covered_lines = file_data.lines(possible_path)
                    if covered_lines is not None:
                        app.logger.info(f"Found coverage data for path: {possible_path}")
                        break

                # 如果还是None，列出所有可用的文件
                if covered_lines is None:
                    available_files = list(file_data.measured_files())
                    app.logger.warning(f"Could not find coverage for {source_file}. Available files: {available_files}")
                    # 尝试使用第一个可用文件（如果有的话）
                    if available_files:
                        covered_lines = file_data.lines(available_files[0])
                        app.logger.info(f"Using coverage from: {available_files[0]}")

                # 如果还是None，使用空集合
                if covered_lines is None:
                    app.logger.warning(f"No coverage data found, using empty set")
                    covered_lines = set()
                
                functions = {}
                class FunctionVisitor(ast.NodeVisitor):
                    def __init__(self):
                        self.functions = {}
                        self.current_class = None

                    def visit_ClassDef(self, node):
                        """访问类定义，记录类名并继续遍历"""
                        old_class = self.current_class
                        self.current_class = node.name
                        self.generic_visit(node)  # 继续遍历类中的方法
                        self.current_class = old_class

                    def visit_FunctionDef(self, node):
                        """访问函数定义（包括类方法）"""
                        self._process_function(node)
                        self.generic_visit(node)  # 处理嵌套函数

                    def visit_AsyncFunctionDef(self, node):
                        """访问异步函数定义"""
                        self._process_function(node)
                        self.generic_visit(node)

                    def _process_function(self, node):
                        """处理函数或方法"""
                        try:
                            if not node.body:
                                return

                            # 获取函数体的实际起始行
                            body_start = min(stmt.lineno for stmt in node.body if hasattr(stmt, 'lineno'))
                            body_end = max(stmt.end_lineno for stmt in node.body if hasattr(stmt, 'end_lineno'))

                            # 检查函数体是否被覆盖
                            body_lines = set(range(body_start, body_end + 1))
                            required_lines = {line for line in body_lines
                                            if not isinstance(node.body[0], ast.Pass)}

                            # 构建函数键名
                            if self.current_class:
                                func_key = f"{self.current_class}.{node.name}"
                            else:
                                func_key = node.name

                            self.functions[func_key] = {
                                'name': node.name,
                                'class': self.current_class,
                                'start_line': node.lineno,
                                'end_line': node.end_lineno,
                                'body_start': body_start,
                                'body_end': body_end,
                                'covered': any(line in covered_lines for line in required_lines)
                            }
                        except (AttributeError, ValueError) as e:
                            app.logger.warning(f"处理函数 {node.name} 时出错: {e}")

                visitor = FunctionVisitor()
                visitor.visit(tree)
                functions = visitor.functions  # 从visitor中获取结果
                
                # 生成报告
                report_lines = ["Function Coverage Report:", "=" * 40]
                total_functions = len(functions)
                covered_functions = sum(1 for func in functions.values() if func['covered'])
                
                for func_name, func_info in functions.items():
                    status = "Covered" if func_info['covered'] else "Not covered"
                    report_lines.append(
                        f"Function: {func_name} "
                        f"(lines {func_info['start_line']}-{func_info['end_line']}) - {status}"
                    )
                
                coverage_rate = (covered_functions / total_functions * 100) if total_functions > 0 else 0
                report_lines.append(f"\nOverall function coverage: {coverage_rate:.2f}%")
                
                return {
                    'functions': functions,
                    'report': '\n'.join(report_lines),
                    'coverage_rate': coverage_rate
                }

            # 调用新的分析函数
            coverage_data_file = os.path.join(app.config['UPLOAD_FOLDER'], '.coverage')
            function_coverage_results = analyze_function_coverage(source_file, coverage_data_file)
            
            # 更新报告
            coverage_reports['function'] = function_coverage_results['report']
            coverage_reports['summary'] = {
                'total_coverage': f"{total_coverage:.2f}%",  # pytest-cov 的总覆盖率（用于迭代判断）
                'line_rate': f"{line_coverage:.2f}%",
                'branch_rate': f"{branch_coverage:.2f}%",
                'function_rate': f"{function_coverage_results['coverage_rate']:.2f}%"
            }
            app.logger.info(f"Total coverage (from Cover column): {total_coverage}%")
            app.logger.info(f"Branch coverage: {branch_coverage}%")
            app.logger.info(f"Line coverage: {line_coverage}%")
            app.logger.info(f"Function coverage: {function_coverage_results['coverage_rate']}%")

        except Exception as e:
            app.logger.error(f"Error generating function coverage: {str(e)}\n{traceback.format_exc()}")
            coverage_reports['function'] = f"Error generating function coverage report: {str(e)}"
            coverage_reports['summary'] = {
                'total_coverage': f"{total_coverage:.2f}%",
                'line_rate': f"{line_coverage:.2f}%",
                'branch_rate': f"{branch_coverage:.2f}%",
                'function_rate': "0%"
            }

        # 组合完整的pytest输出（stdout + stderr）
        pytest_output = ""
        if test_result.stdout:
            pytest_output += test_result.stdout
        if test_result.stderr:
            if pytest_output:
                pytest_output += "\n\n=== STDERR ===\n"
            pytest_output += test_result.stderr

        if not pytest_output:
            pytest_output = "Tests completed successfully"

        return coverage_reports, pytest_output

    except Exception as e:
        app.logger.error(f"Error running tests: {str(e)}\n{traceback.format_exc()}")
        raise

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6007)
