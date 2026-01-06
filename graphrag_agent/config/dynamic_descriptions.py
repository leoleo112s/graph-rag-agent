"""
动态工具描述生成器
根据活动的 GraphConfig 自动生成适配的工具描述和示例问题
"""

from typing import Dict, List, Optional


def get_dynamic_descriptions() -> Dict[str, str]:
    """
    根据当前激活的 GraphConfig 生成动态工具描述

    Returns:
        Dict[str, str]: 包含 lc_description, gl_description, naive_description 的字典
    """
    # 尝试获取活动配置
    try:
        from graphrag_agent.config.graph_config_storage import get_storage

        storage = get_storage()
        config = storage.load()

        if config:
            project_name = config.project_name
            industry = config.industry or "领域"

            # 根据行业生成更精确的描述
            industry_context = _get_industry_context(industry)

            return {
                "lc_description": (
                    f"用于需要具体细节的查询。检索{project_name}中的具体规定、条款、流程等详细内容。"
                    f"适用于'{industry_context['detail_examples']}'等问题。"
                ),
                "gl_description": (
                    f"用于需要总结归纳的查询。分析{project_name}的整体框架、{industry_context['framework_aspect']}等宏观内容。"
                    f"适用于'{industry_context['framework_examples']}'等需要系统性分析的问题。"
                ),
                "naive_description": (
                    f"基础检索工具，直接查找与问题最相关的文本片段，不做复杂分析。快速获取{project_name}相关{industry_context['content_type']}，返回最匹配的原文段落。"
                ),
            }
    except Exception as e:
        print(f"[DynamicDescriptions] 无法加载 GraphConfig，使用默认描述: {e}")

    # 回退到默认描述（华东理工大学学生管理）
    return {
        "lc_description": (
            "用于需要具体细节的查询。检索华东理工大学学生管理文件中的具体规定、条款、流程等详细内容。"
            "适用于'某个具体规定是什么'、'处理流程如何'等问题。"
        ),
        "gl_description": (
            "用于需要总结归纳的查询。分析华东理工大学学生管理体系的整体框架、管理原则、学生权利义务等宏观内容。"
            "适用于'学校的学生管理总体思路'、'学生权益保护机制'等需要系统性分析的问题。"
        ),
        "naive_description": (
            "基础检索工具，直接查找与问题最相关的文本片段，不做复杂分析。快速获取华东理工大学相关政策，返回最匹配的原文段落。"
        ),
    }


def _get_industry_context(industry: str) -> Dict[str, str]:
    """
    根据行业类型返回适配的上下文术语

    Args:
        industry: 行业类型 (legal, medical, ecommerce, education, finance, etc.)

    Returns:
        Dict[str, str]: 包含行业特定术语的字典
    """
    industry_lower = industry.lower() if industry else ""

    # 行业特定上下文映射
    industry_map = {
        "legal": {
            "detail_examples": "某条法律条款的具体内容、案件处理流程",
            "framework_aspect": "法律体系、司法原则、权利义务框架",
            "framework_examples": "法律体系的整体架构、司法理念",
            "content_type": "法律法规",
        },
        "medical": {
            "detail_examples": "某种疾病的治疗方案、药物使用说明",
            "framework_aspect": "医疗体系、诊疗原则、患者权益",
            "framework_examples": "医疗体系的组织架构、诊疗规范",
            "content_type": "医疗知识",
        },
        "ecommerce": {
            "detail_examples": "商品详细信息、交易流程、退换货规则",
            "framework_aspect": "平台规则、用户权益、服务标准",
            "framework_examples": "电商平台的运营框架、服务体系",
            "content_type": "商品和服务信息",
        },
        "education": {
            "detail_examples": "某个具体规定是什么、处理流程如何",
            "framework_aspect": "管理原则、学生权利义务",
            "framework_examples": "学校的管理总体思路、学生权益保护机制",
            "content_type": "政策",
        },
        "finance": {
            "detail_examples": "金融产品的具体条款、操作流程",
            "framework_aspect": "金融体系、监管原则、风险控制",
            "framework_examples": "金融体系的整体架构、监管框架",
            "content_type": "金融产品和服务",
        },
        "government": {
            "detail_examples": "政策具体条款、办事流程",
            "framework_aspect": "政策体系、服务原则、公民权益",
            "framework_examples": "政务体系的整体架构、服务框架",
            "content_type": "政策文件",
        },
    }

    # 匹配行业（支持中英文）
    for key, context in industry_map.items():
        if key in industry_lower:
            return context

    # 中文行业名称映射
    chinese_map = {
        "法律": industry_map["legal"],
        "医疗": industry_map["medical"],
        "电商": industry_map["ecommerce"],
        "教育": industry_map["education"],
        "金融": industry_map["finance"],
        "政务": industry_map["government"],
    }

    for key, context in chinese_map.items():
        if key in industry:
            return context

    # 默认通用上下文
    return {
        "detail_examples": "某个具体内容、处理流程",
        "framework_aspect": "整体框架、核心原则",
        "framework_examples": "系统的整体架构、核心理念",
        "content_type": "内容",
    }


def get_dynamic_examples() -> List[str]:
    """
    根据当前激活的 GraphConfig 生成动态示例问题

    Returns:
        List[str]: 示例问题列表
    """
    try:
        from graphrag_agent.config.graph_config_storage import get_storage

        storage = get_storage()
        config = storage.load()

        if config and config.industry:
            industry = config.industry.lower()

            # 行业特定示例问题
            industry_examples = {
                "legal": [
                    "民事诉讼的流程是什么？",
                    "合同纠纷如何处理？",
                    "法律援助如何申请？",
                    "诉讼时效是多久？",
                ],
                "medical": [
                    "高血压患者的饮食建议是什么？",
                    "常见感冒的治疗方法？",
                    "如何预防糖尿病？",
                    "住院流程是怎样的？",
                ],
                "ecommerce": [
                    "退换货政策是什么？",
                    "如何使用优惠券？",
                    "配送时间多久？",
                    "商品质量问题如何投诉？",
                ],
                "education": [
                    "旷课多少学时会被退学？",
                    "国家奖学金和国家励志奖学金互斥吗？",
                    "优秀学生要怎么申请？",
                    "那上海市奖学金呢？",
                ],
                "finance": [
                    "如何申请贷款？",
                    "理财产品的风险等级是什么？",
                    "信用卡逾期会有什么后果？",
                    "基金赎回需要多久？",
                ],
                "government": [
                    "如何办理居住证？",
                    "医保报销流程是什么？",
                    "公积金提取条件是什么？",
                    "户口迁移需要哪些材料？",
                ],
            }

            # 匹配行业示例
            for key, examples in industry_examples.items():
                if key in industry:
                    return examples

            # 中文行业名称映射
            chinese_examples = {
                "法律": industry_examples["legal"],
                "医疗": industry_examples["medical"],
                "电商": industry_examples["ecommerce"],
                "教育": industry_examples["education"],
                "金融": industry_examples["finance"],
                "政务": industry_examples["government"],
            }

            for key, examples in chinese_examples.items():
                if key in config.industry:
                    return examples

    except Exception as e:
        print(f"[DynamicExamples] 无法加载 GraphConfig，使用默认示例: {e}")

    # 默认示例（教育领域）
    return [
        "旷课多少学时会被退学？",
        "国家奖学金和国家励志奖学金互斥吗？",
        "优秀学生要怎么申请？",
        "那上海市奖学金呢？",
    ]


def get_kb_name() -> str:
    """
    根据当前激活的 GraphConfig 获取知识库名称

    Returns:
        str: 知识库名称
    """
    try:
        from graphrag_agent.config.graph_config_storage import get_storage

        storage = get_storage()
        config = storage.load()

        if config:
            return config.project_name

    except Exception as e:
        print(f"[DynamicKBName] 无法加载 GraphConfig，使用默认名称: {e}")

    # 默认知识库名称
    return "华东理工大学"


def get_theme() -> str:
    """
    根据当前激活的 GraphConfig 获取知识图谱主题

    Returns:
        str: 知识图谱主题
    """
    try:
        from graphrag_agent.config.graph_config_storage import get_storage

        storage = get_storage()
        config = storage.load()

        if config:
            # 组合项目名称和行业作为主题
            if config.industry:
                return f"{config.project_name} - {config.industry}"
            return config.project_name

    except Exception as e:
        print(f"[DynamicTheme] 无法加载 GraphConfig，使用默认主题: {e}")

    # 默认主题
    return "华东理工大学学生管理"
