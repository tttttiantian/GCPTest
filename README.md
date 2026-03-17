# GCPTest - AI-Powered Agentic Test Case Generator

一个基于 **Agentic 架构**的 AI 驱动 Python 测试用例自动生成平台，支持智能迭代测试生成、实时覆盖率分析和可视化进度展示。

---

## 项目简介

GCPTest 是一个利用大语言模型（GLM-4）和多 Agent 协作架构自动生成高质量 Python 测试用例的 Web 应用。系统采用**迭代式生成策略**，通过多轮分析-生成-执行-优化循环，自动提升测试覆盖率和测试代码正确率直至达到目标。

### 核心特性

- **智能化测试生成**：基于智谱AI GLM-4-flash微调大模型，深度理解代码语义和业务逻辑
- **Agentic多Agent协作**：4个专业Agent分工协作，完成代码分析、测试生成、执行和优化
- **迭代式优化**：自动进行多轮测试生成和优化，直至达到90%覆盖率目标
- **实时进度反馈**：通过SSE流式推送，实时展示测试生成进度和覆盖率变化
- **在线编辑运行**：集成CodeMirror编辑器，支持在线修改测试代码并立即运行
- **多用户支持**：会话隔离机制，支持多用户并发访问，互不干扰
- **完整覆盖率分析**：提供行覆盖率、分支覆盖率、函数覆盖率的详细报告

### 技术架构

```
┌─────────────────────────────────────────────────────┐
│              Web界面 (Flask + CodeMirror)            │
├─────────────────────────────────────────────────────┤
│                  Agent编排层                         │
│  ┌─────────────────────────────────────────────┐   │
│  │  CodeAnalyzerAgent     (代码分析)           │   │
│  │          ↓                                   │   │
│  │  TestGeneratorAgent    (测试生成)           │   │
│  │          ↓                                   │   │
│  │  TestExecutorAgent     (执行测试)           │   │
│  │          ↓                                   │   │
│  │  CoverageAnalyzerAgent (覆盖率分析)         │   │
│  └─────────────────────────────────────────────┘   │
├─────────────────────────────────────────────────────┤
│              GLM-4 LLM服务层                        │
└─────────────────────────────────────────────────────┘
```

---

## 核心亮点

### 1. 智能Agentic架构

采用多Agent协作模式，每个Agent专注于特定任务：

- **CodeAnalyzerAgent**：使用AST精确解析代码结构，提取函数、类、分支、复杂度等信息
- **TestGeneratorAgent**：基于代码分析结果和覆盖率缺口，智能生成针对性测试用例
- **TestExecutorAgent**：运行pytest并收集覆盖率数据，生成质量指标
- **CoverageAnalyzerAgent**：深度分析覆盖率缺口，提供优化建议

### 2. 迭代式智能优化

系统通过多轮迭代自动优化测试质量：

1. **初始生成**：基于代码结构分析生成全面的初始测试集
2. **执行分析**：运行测试并收集覆盖率数据，识别未覆盖代码
3. **针对性优化**：根据覆盖率缺口生成补充测试，替换失败测试
4. **智能停止**：达到目标覆盖率或检测到无改进时自动停止

**停止条件**：
- 覆盖率达到目标（默认90%）且通过率≥99%
- 达到最大迭代次数（默认3次）
- 连续2轮改进幅度<0.5%（早停优化）

### 3. 实时可视化反馈

采用Server-Sent Events（SSE）技术实现实时进度推送：

- 迭代进度实时显示
- 覆盖率变化动态更新
- 测试执行结果即时反馈
- 失败测试详情展示
- 优化建议实时呈现

### 4. 在线编辑与调试

集成CodeMirror专业代码编辑器：

- **语法高亮**：Python代码语法高亮显示（Monokai主题）
- **智能缩进**：自动缩进、括号匹配
- **在线运行**：修改后立即运行，无需下载上传
- **快捷操作**：支持Ctrl/Cmd + Enter快捷键运行测试
- **即时反馈**：运行结果、覆盖率报告实时更新

### 5. 企业级部署能力

- **Docker容器化**：一键部署，环境隔离
- **Gunicorn多Worker**：支持高并发访问
- **会话管理**：基于UUID的会话隔离，支持多用户并发
- **限流保护**：TokenBucket算法限制LLM API调用频率（40 QPS）
- **错误恢复**：完善的异常处理和日志记录

### 6. 完整的质量保障

- **语法验证**：运行前使用AST验证代码语法
- **失败分类**：区分代码bug和测试bug，自动替换失败测试
- **缩进检查**：CodeCleaner工具精确验证和修复代码缩进
- **质量指标**：提供测试通过率、失败分类、需求覆盖等多维度指标

---

## 使用教程

### 前置要求

- Docker 和 Docker Compose
- 智谱AI API Key（访问 [https://open.bigmodel.cn/](https://open.bigmodel.cn/) 获取）
- Python 3.10+（仅本地运行需要）

### 快速开始

#### 1. 克隆项目

```bash
git clone <repository-url>
cd GCPTest
```

#### 2. 配置环境变量

编辑 [docker-compose.yml](docker-compose.yml) 文件，设置你的API配置：

```yaml
environment:
  - CODEGEEX_API_URL=https://open.bigmodel.cn/api/paas/v4/chat/completions/
  - CODEGEEX_API_KEY=your_api_key_here  # 替换为你的API Key
  - MODEL_ID=glm-4-flash:your_model_id  # 替换为你的模型ID
```

#### 3. 启动服务

使用Docker Compose一键启动：

```bash
docker-compose up --build
```

服务将在 `http://localhost:6007` 启动。

#### 4. 访问Web界面

打开浏览器访问 [http://localhost:6007](http://localhost:6007)

### 使用流程

#### 步骤1：上传待测代码

1. 在Web界面点击"选择文件"或拖拽文件到上传区域
2. 支持上传 `.py` Python源代码文件
3. 系统会自动读取文件内容

#### 步骤2：配置生成参数

1. **功能规格**：输入代码的功能描述，帮助AI理解业务逻辑
   - 示例：`这是一个用户认证模块，包含登录、注册和密码验证功能`

2. **测试策略（可选）**：自定义测试生成策略
   - 示例：`按照白盒测试中判定/条件覆盖的原则生成测试用例`

3. **目标覆盖率**：设置期望的代码覆盖率（默认90%）
   - 范围：0-100
   - 建议：80-95之间平衡质量和时间

#### 步骤3：生成测试

1. 点击"开始生成测试"按钮
2. 系统自动执行以下流程：
   ```
   代码分析 → 生成测试 → 执行测试 → 分析覆盖率 → 优化迭代
   ```
3. 实时进度展示：
   - 当前迭代次数
   - 各阶段执行状态
   - 覆盖率变化趋势
   - 测试通过/失败统计

#### 步骤4：查看结果

生成完成后，可以查看：

1. **覆盖率报告**
   - 行覆盖率：代码行的执行比例
   - 分支覆盖率：条件分支的覆盖情况
   - 函数覆盖率：函数的调用覆盖率
   - 详细的覆盖率明细（按函数和分支）

2. **测试代码**
   - 在CodeMirror编辑器中显示生成的测试代码
   - 支持语法高亮和代码折叠

3. **执行日志**
   - pytest运行的详细输出
   - 测试通过/失败详情
   - 错误堆栈信息

#### 步骤5：在线编辑和调试（可选）

1. **编辑测试代码**
   - 直接在CodeMirror编辑器中修改测试代码
   - 支持行号显示、自动缩进、括号匹配

2. **运行测试**
   - 点击"Run Tests"按钮
   - 或使用快捷键 `Ctrl+Enter`（Windows/Linux）或 `Cmd+Enter`（Mac）

3. **查看更新结果**
   - 覆盖率报告自动刷新
   - pytest执行日志更新
   - 下载链接指向最新版本

4. **迭代优化**
   - 根据覆盖率报告识别未覆盖代码
   - 补充或修改测试用例
   - 重新运行直到满意

#### 步骤6：下载测试文件

1. 点击"复制代码"按钮复制测试代码到剪贴板
2. 或点击下载链接获取 `test_<module_name>.py` 文件
3. 将测试文件集成到你的项目中

### 常见问题

#### Q1: 生成的测试覆盖率未达到目标怎么办？

**原因**：
- 代码逻辑复杂，难以生成完整测试
- 达到最大迭代次数限制
- 存在难以触发的边界条件
- API请求超时

**解决方案**：
1. 使用在线编辑功能，手动补充测试用例
2. 在"测试策略"中明确指出需要重点测试的部分

#### Q2: 生成的测试有语法错误或运行失败

**原因**：
- LLM生成的代码可能存在缩进或语法问题
- 代码依赖外部模块或资源

**解决方案**：
1. 系统会自动进行语法验证和缩进修复
2. 在后续迭代中自动替换失败的测试
3. 使用在线编辑功能手动修复问题
4. 确保待测代码的依赖已在环境中安装

#### Q3: 测试生成时间过长

**原因**：
- 代码规模大，需要多轮迭代
- LLM API响应较慢
- 网络延迟

**解决方案**：
1. 降低目标覆盖率（如80%）减少迭代次数
2. 检查网络连接和API配额
3. 调整 `MAX_ITERATIONS` 限制迭代次数

#### Q4: 如何查看详细日志？

```bash
# 查看Docker容器日志
docker-compose logs -f web

# 查看应用日志
docker exec -it <container_id> tail -f /tmp/*.log
```

### 本地开发运行

如果不使用Docker，可以本地运行：

#### 1. 安装依赖

```bash
pip install -r requirements.txt
```

#### 2. 设置环境变量

```bash
export CODEGEEX_API_URL="https://open.bigmodel.cn/api/paas/v4/chat/completions/"
export CODEGEEX_API_KEY="your_api_key"
export MODEL_ID="glm-4-flash:your_model_id"
```

#### 3. 运行应用

```bash
# 开发模式（Flask内置服务器）
python app.py

# 生产模式（Gunicorn）
gunicorn -c gunicorn_config.py app:app
```

### 项目结构

```
GCPTest/
├── app.py                   # Flask应用主程序
├── config.py                # Agentic系统配置
├── GLMService.py            # LLM服务模块
├── agents/                  # Agent模块目录
│   ├── base_agent.py        # Agent基类
│   ├── code_analyzer_agent.py
│   ├── test_generator_agent.py
│   ├── test_executor_agent.py
│   ├── coverage_analyzer_agent.py
│   └── helpers/
│       └── code_cleaner.py  # 代码清理工具
├── workflow/                # 工作流编排
│   ├── orchestrator.py      # Agent编排器
│   └── state.py             # 状态管理
├── services/                # 支持服务
│   ├── session_manager.py   # 会话管理
│   └── rate_limiter.py      # 限流器
├── templates/
│   └── index.html           # Web界面
├── static/
│   └── style.css            # 样式文件
├── doc/                     # 项目文档
├── Dockerfile               # Docker镜像定义
├── docker-compose.yml       # 容器编排
├── gunicorn_config.py       # Gunicorn配置
└── requirements.txt         # Python依赖
```

---
