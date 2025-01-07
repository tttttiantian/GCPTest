# app.py
from flask import Flask, request, render_template, jsonify, send_file, url_for, session
import os
from werkzeug.utils import secure_filename
import subprocess
import traceback
from GLMService import GLMService 
import uuid
import secrets
import ast
import logging

# 设置日志记录
logging.basicConfig(level=logging.INFO,  # 设置日志级别为 INFO
                    format='%(asctime)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.StreamHandler()  # 输出日志到控制台
                    ])

app = Flask(__name__)

# 生成一个随机的32字节密钥
app.secret_key = secrets.token_bytes(32)

# 创建一个全局的 GLMService 实例，这样可以在所有请求之间共享会话历史
glm_service = GLMService()

# 配置上传文件夹
app.config['UPLOAD_FOLDER'] = '/app/uploads'
app.config['ALLOWED_EXTENSIONS'] = {'py'}

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

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        try:
            test_requirements = request.form.get('test_requirements')
            if 'code_file' not in request.files:
                return jsonify({'error': 'No file uploaded'}), 400
                
            code_file = request.files['code_file']
            if not code_file or not allowed_file(code_file.filename):
                return jsonify({'error': 'Invalid file type'}), 400

            filename = secure_filename(code_file.filename)
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            code_file.save(file_path)
            
            module_name = os.path.splitext(filename)[0]

            # 生成测试用例文件
            test_cases = generate_test_cases(test_requirements, file_path, module_name)
            test_case_file_path = create_test_case_file(test_cases, file_path)

            # 运行测试并获取结果
            coverage_reports, test_output = run_pytest_and_generate_coverage(test_case_file_path)
            
            # 准备响应数据
            download_url = url_for('download_test_cases', filename=os.path.basename(test_case_file_path))
            return render_template('index.html', 
                                coverage_report=coverage_reports,
                                test_output=test_output,
                                download_url=download_url)

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
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        if not os.path.exists(file_path):
            return jsonify({'error': 'File not found'}), 404
        return send_file(file_path, as_attachment=True)
    except Exception as e:
        return jsonify({'error': 'Error downloading file', 'message': str(e)}), 500

def generate_test_cases(test_requirements, file_path, module_name):
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

        # 修正 coverage 配置格式
        coverage_config = '''[run]
branch = true
source = {}
data_file = {}


[report]
exclude_lines =
    pragma: no cover
    def __repr__
    if __name__ == .__main__.:
    raise NotImplementedError
    pass
# 新增分支覆盖相关配置
show_missing = true
skip_covered = false
'''.format(
            app.config['UPLOAD_FOLDER'],
            os.path.join(app.config['UPLOAD_FOLDER'], '.coverage')
        )

        config_path = os.path.join(app.config['UPLOAD_FOLDER'], '.coveragerc')
        with open(config_path, 'w') as f:
            f.write(coverage_config)

        # 清理之前的覆盖率数据
        subprocess.run(['coverage', 'erase'], cwd=app.config['UPLOAD_FOLDER'])

        # 运行测试并收集覆盖率数据
        test_result = subprocess.run([
            'coverage', 'run',
            '--branch',  # 显式启用分支覆盖率
            '--source', app.config['UPLOAD_FOLDER'],
            '-m', 'pytest',
            test_case_file_path,
            '-v'
        ], cwd=app.config['UPLOAD_FOLDER'], capture_output=True, text=True)

        # 运行完成后立即生成覆盖率报告
        subprocess.run(['coverage', 'report'], cwd=app.config['UPLOAD_FOLDER'])
        
        coverage_reports = {}

        # 收集行覆盖率报告，修改解析方式
        line_report = subprocess.run(
            ['coverage', 'report', '--include', f'*{module_name}.py'],
            cwd=app.config['UPLOAD_FOLDER'],
            capture_output=True,
            text=True
        )
        coverage_reports['line'] = line_report.stdout if line_report.stdout else "No line coverage report generated"

        # 解析行覆盖率
        line_coverage = 0
        if line_report.stdout:
            try:
                # 查找最后一行的覆盖率数字
                lines = line_report.stdout.strip().split('\n')
                if lines:
                    last_line = lines[-1]
                    coverage_str = last_line.split()[-1].rstrip('%')
                    line_coverage = float(coverage_str)
            except (IndexError, ValueError):
                line_coverage = 0

        # 收集分支覆盖率报告
        branch_report = subprocess.run(
            ['coverage', 'report', '--include', f'*{module_name}.py', '--show-missing', '--branch'],
            cwd=app.config['UPLOAD_FOLDER'],
            capture_output=True,
            text=True
        )
        coverage_reports['branch'] = branch_report.stdout if branch_report.stdout else "No branch coverage report generated"

        # 解析分支覆盖率
         # 改进分支覆盖率解析
        branch_coverage = 0
        if branch_report.stdout:
            try:
                lines = branch_report.stdout.strip().split('\n')
                for line in lines:
                    if module_name in line:
                        parts = line.split()
                        # 分支覆盖率通常在倒数第三列
                        if len(parts) >= 4:
                            branch_str = parts[-3].rstrip('%')  # 调整索引位置
                            if branch_str.replace('.', '', 1).isdigit():  # 确保是有效的数字
                                branch_coverage = float(branch_str)
                                break
            except (IndexError, ValueError) as e:
                logging.error(f"Error parsing branch coverage: {e}")  # 错误记录
                branch_coverage = 0

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
                covered_lines = file_data.lines(source_file)
                
                functions = {}
                class FunctionVisitor(ast.NodeVisitor):
                    def visit_FunctionDef(self, node):
                        # 获取函数体的实际起始行（跳过装饰器和函数定义行）
                        body_start = min(stmt.lineno for stmt in node.body)
                        body_end = max(stmt.end_lineno for stmt in node.body)
                        
                        # 检查函数体是否被覆盖
                        body_lines = set(range(body_start, body_end + 1))
                        required_lines = {line for line in body_lines 
                                        if not isinstance(node.body[0], ast.Pass)}  # 排除只有pass的函数
                        
                        functions[node.name] = {
                            'name': node.name,
                            'start_line': node.lineno,
                            'end_line': node.end_lineno,
                            'body_start': body_start,
                            'body_end': body_end,
                            'covered': any(line in covered_lines for line in required_lines)
                        }
                
                visitor = FunctionVisitor()
                visitor.visit(tree)
                
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
                'line_rate': f"{line_coverage:.2f}%",
                'branch_rate': f"{branch_coverage:.2f}%",
                'function_rate': f"{function_coverage_results['coverage_rate']:.2f}%"
            }
            app.logger.info(f"Branch coverage: {branch_coverage}%")
            app.logger.info(f"Line coverage: {line_coverage}%")
            app.logger.info(f"Function coverage: {function_coverage_results['coverage_rate']}%")

        except Exception as e:
            app.logger.error(f"Error generating function coverage: {str(e)}\n{traceback.format_exc()}")
            coverage_reports['function'] = f"Error generating function coverage report: {str(e)}"
            coverage_reports['summary'] = {
                'line_rate': f"{line_coverage:.2f}%",
                'branch_rate': f"{branch_coverage:.2f}%",
                'function_rate': "0%"
            }

        return coverage_reports, test_result.stderr if test_result.stderr else "Tests completed successfully"

    except Exception as e:
        app.logger.error(f"Error running tests: {str(e)}\n{traceback.format_exc()}")
        raise

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=6007)