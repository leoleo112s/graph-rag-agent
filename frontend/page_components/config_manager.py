"""
配置管理页面
提供实体类型、关系类型等配置管理功能
"""

import streamlit as st
import re
from pathlib import Path
from typing import List, Tuple

# 导入当前配置
try:
    from graphrag_agent.config.settings import (
        entity_types as current_entity_types,
        relationship_types as current_relationship_types,
        theme as current_theme,
        BASE_DIR
    )
except ImportError:
    # 如果导入失败，使用默认值
    current_entity_types = []
    current_relationship_types = []
    current_theme = ""
    BASE_DIR = Path(".")


def read_settings_file() -> str:
    """读取 settings.py 文件内容"""
    settings_path = Path(BASE_DIR) / "config" / "settings.py"
    try:
        with open(settings_path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        st.error(f"读取配置文件失败: {e}")
        return ""


def write_settings_file(content: str) -> bool:
    """写入 settings.py 文件"""
    settings_path = Path(BASE_DIR) / "config" / "settings.py"
    try:
        # 备份原文件
        backup_path = settings_path.with_suffix('.py.bak')
        if settings_path.exists():
            import shutil
            shutil.copy2(settings_path, backup_path)

        with open(settings_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return True
    except Exception as e:
        st.error(f"写入配置文件失败: {e}")
        return False


def update_config_section(content: str, section_name: str, new_values: List[str]) -> str:
    """更新配置文件中的某个列表配置节"""
    # 查找配置节的位置
    pattern = rf'({section_name}\s*=\s*\[)(.*?)(\])'

    # 格式化新的配置值
    formatted_values = ',\n    '.join([f'"{val}"' for val in new_values])
    new_section = f'\\g<1>\n    {formatted_values},\n\\g<3>'

    # 替换配置
    new_content = re.sub(pattern, new_section, content, flags=re.DOTALL)

    return new_content


def update_theme_config(content: str, new_theme: str) -> str:
    """更新主题配置"""
    pattern = r'(theme\s*=\s*)["\'].*?["\']'
    new_content = re.sub(pattern, f'\\g<1>"{new_theme}"', content)
    return new_content


def validate_config_items(items: List[str]) -> Tuple[bool, str]:
    """验证配置项"""
    if not items:
        return False, "配置项不能为空"

    for item in items:
        if not item.strip():
            return False, "配置项不能包含空行"

        # 检查特殊字符
        if any(char in item for char in ['"', "'", '\\']):
            return False, f"配置项 '{item}' 包含非法字符"

    return True, ""


def config_manager_page():
    """配置管理主页面"""
    st.title("⚙️ 配置管理")
    st.markdown("---")

    # 提示信息
    st.info("💡 修改配置后需要重新构建知识图谱才能生效")

    # 创建标签页
    tab1, tab2, tab3 = st.tabs(["📊 实体与关系配置", "🎨 主题配置", "📄 查看完整配置"])

    # ===== 实体与关系配置 =====
    with tab1:
        col1, col2 = st.columns(2)

        with col1:
            st.subheader("📌 实体类型配置")
            st.caption("每行一个实体类型")

            entity_types_text = st.text_area(
                "实体类型",
                value="\n".join(current_entity_types),
                height=300,
                help="输入知识图谱中的实体类型，每行一个",
                label_visibility="collapsed"
            )

            # 显示实体类型数量
            entity_list = [line.strip() for line in entity_types_text.split('\n') if line.strip()]
            st.caption(f"共 {len(entity_list)} 个实体类型")

            # 预设模板
            st.markdown("**快速模板:**")
            template_col1, template_col2 = st.columns(2)
            with template_col1:
                if st.button("📚 学生管理", key="entity_template_1"):
                    st.session_state.entity_template = "学生类型\n奖学金类型\n处分类型\n部门\n学生职责\n管理规定"
            with template_col2:
                if st.button("🏢 企业管理", key="entity_template_2"):
                    st.session_state.entity_template = "员工\n部门\n项目\n客户\n产品\n合同"

            if 'entity_template' in st.session_state:
                entity_types_text = st.session_state.entity_template
                del st.session_state.entity_template
                st.rerun()

        with col2:
            st.subheader("🔗 关系类型配置")
            st.caption("每行一个关系类型")

            relationship_types_text = st.text_area(
                "关系类型",
                value="\n".join(current_relationship_types),
                height=300,
                help="输入知识图谱中的关系类型，每行一个",
                label_visibility="collapsed"
            )

            # 显示关系类型数量
            relationship_list = [line.strip() for line in relationship_types_text.split('\n') if line.strip()]
            st.caption(f"共 {len(relationship_list)} 个关系类型")

            # 预设模板
            st.markdown("**快速模板:**")
            template_col1, template_col2 = st.columns(2)
            with template_col1:
                if st.button("📚 学生管理", key="rel_template_1"):
                    st.session_state.rel_template = "申请\n评选\n违纪\n资助\n申诉\n管理\n权利义务\n互斥"
            with template_col2:
                if st.button("🏢 企业管理", key="rel_template_2"):
                    st.session_state.rel_template = "隶属于\n负责\n参与\n合作\n采购\n销售"

            if 'rel_template' in st.session_state:
                relationship_types_text = st.session_state.rel_template
                del st.session_state.rel_template
                st.rerun()

        # 保存按钮
        st.markdown("---")
        col1, col2, col3 = st.columns([1, 1, 3])

        with col1:
            if st.button("💾 保存配置", type="primary", use_container_width=True):
                # 验证配置
                valid_entity, entity_msg = validate_config_items(entity_list)
                valid_rel, rel_msg = validate_config_items(relationship_list)

                if not valid_entity:
                    st.error(f"实体类型配置错误: {entity_msg}")
                elif not valid_rel:
                    st.error(f"关系类型配置错误: {rel_msg}")
                else:
                    # 读取当前配置文件
                    content = read_settings_file()
                    if content:
                        # 更新配置
                        content = update_config_section(content, "entity_types", entity_list)
                        content = update_config_section(content, "relationship_types", relationship_list)

                        # 写入文件
                        if write_settings_file(content):
                            st.success("✅ 配置已保存成功！")
                            st.info("💡 请前往「构建管理」重新构建知识图谱")
                        else:
                            st.error("❌ 保存失败，请检查文件权限")

        with col2:
            if st.button("🔄 重置为默认", use_container_width=True):
                st.session_state.reset_config = True

        if st.session_state.get('reset_config', False):
            st.warning("⚠️ 确定要重置为当前运行时的配置吗？")
            col1, col2, col3 = st.columns([1, 1, 3])
            with col1:
                if st.button("✅ 确认重置"):
                    st.session_state.reset_config = False
                    st.rerun()
            with col2:
                if st.button("❌ 取消"):
                    st.session_state.reset_config = False
                    st.rerun()

    # ===== 主题配置 =====
    with tab2:
        st.subheader("🎨 知识图谱主题")

        theme_text = st.text_input(
            "主题名称",
            value=current_theme,
            help="知识图谱的主题描述，用于引导 LLM 提取相关实体和关系"
        )

        st.markdown("**示例主题:**")
        example_col1, example_col2, example_col3 = st.columns(3)

        with example_col1:
            if st.button("🎓 学生管理"):
                st.session_state.theme_example = "华东理工大学学生管理"
        with example_col2:
            if st.button("🏥 医疗健康"):
                st.session_state.theme_example = "医疗诊断与治疗方案"
        with example_col3:
            if st.button("⚖️ 法律法规"):
                st.session_state.theme_example = "中国法律法规体系"

        if 'theme_example' in st.session_state:
            theme_text = st.session_state.theme_example
            del st.session_state.theme_example
            st.rerun()

        st.markdown("---")

        if st.button("💾 保存主题配置", type="primary"):
            if not theme_text.strip():
                st.error("主题名称不能为空")
            else:
                content = read_settings_file()
                if content:
                    content = update_theme_config(content, theme_text.strip())
                    if write_settings_file(content):
                        st.success("✅ 主题配置已保存！")
                        st.info("💡 请前往「构建管理」重新构建知识图谱")

    # ===== 查看完整配置 =====
    with tab3:
        st.subheader("📄 完整配置文件 (只读)")

        content = read_settings_file()
        if content:
            # 语法高亮显示
            st.code(content, language='python', line_numbers=True)

            # 下载按钮
            st.download_button(
                label="📥 下载配置文件",
                data=content,
                file_name="settings.py",
                mime="text/x-python"
            )
        else:
            st.error("无法读取配置文件")

    # 帮助信息
    with st.expander("❓ 配置说明"):
        st.markdown("""
        ### 实体类型
        - 定义知识图谱中可以识别的实体类别
        - 例如：学生类型、奖学金类型、部门等
        - LLM 会根据这些类型从文本中提取对应的实体

        ### 关系类型
        - 定义实体之间可能存在的关系
        - 例如：申请、评选、管理等
        - LLM 会根据这些类型识别实体间的关联

        ### 主题
        - 描述知识图谱的整体主题和领域
        - 帮助 LLM 更好地理解上下文
        - 提高实体和关系提取的准确性

        ### 注意事项
        - 修改配置后必须重新构建知识图谱
        - 配置会自动备份为 `.bak` 文件
        - 不要使用特殊字符（引号、反斜杠等）
        """)
