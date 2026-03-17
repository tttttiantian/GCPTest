"""
Agentic配置文件
"""

import os


class AgenticConfig:
    """Agentic系统配置"""

    # ===== 覆盖率目标 =====
    DEFAULT_TARGET_COVERAGE = 90.0  # 默认目标覆盖率
    MIN_COVERAGE_IMPROVEMENT = 5.0  # 最小覆盖率提升（每次迭代）

    # ===== 迭代控制 =====
    MAX_ITERATIONS = 3              # 最大迭代次数
    MIN_ITERATIONS = 1              # 最小迭代次数

    # ===== LLM参数 =====
    ANALYSIS_TEMPERATURE = 0.3      # 代码分析温度（低温度更精确）
    GENERATION_TEMPERATURE = 0.7    # 测试生成温度（中等温度更创造）
    MAX_TOKENS = 4000               # 最大token数（智谱GLM的限制，prompt约1500 + output 4000 = 5500 < 8192）

    # ===== Agent超时设置 =====
    AGENT_TIMEOUT = 60              # Agent执行超时（秒）
    LLM_TIMEOUT = 30                # LLM调用超时（秒）

    # ===== 日志配置 =====
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'

    # ===== 测试配置 =====
    TEST_TIMEOUT = 60               # 测试执行超时（秒）
    COVERAGE_THRESHOLD = 0.90       # 覆盖率阈值

    # ===== Prompt模板路径 =====
    PROMPTS_DIR = os.path.join(os.path.dirname(__file__), 'workflow', 'prompts')

    # ===== 新增: 质量控制配置 =====
    MIN_PASS_RATE = 90.0                      # 最小通过率 (%)
    ENABLE_FAILURE_ANALYSIS = True            # 启用失败分析
    ENABLE_REQUIREMENT_COVERAGE = True        # 启用需求覆盖检查

    # ===== 新增: 早停控制 =====
    NO_IMPROVEMENT_WINDOW = 2                 # 无改进检测窗口(轮数)
    IMPROVEMENT_THRESHOLD = 1.0               # 改进阈值 (%)

    @classmethod
    def get_config_dict(cls) -> dict:
        """获取配置字典"""
        return {
            'target_coverage': cls.DEFAULT_TARGET_COVERAGE,
            'max_iterations': cls.MAX_ITERATIONS,
            'analysis_temperature': cls.ANALYSIS_TEMPERATURE,
            'generation_temperature': cls.GENERATION_TEMPERATURE,
            'log_level': cls.LOG_LEVEL
        }
