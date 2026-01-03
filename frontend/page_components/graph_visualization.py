"""
图可视化页面组件

使用 pyvis 提供交互式知识图谱可视化。
"""

import streamlit as st
import streamlit.components.v1 as components
import requests
from pathlib import Path
import tempfile

# API 基础 URL
API_URL = "http://localhost:8000"


def render_graph_visualization():
    """渲染图可视化主页"""
    st.title("🕸️ 知识图谱可视化")
    st.markdown("使用 PyVis 进行交互式图探索")

    st.divider()

    # 侧边栏配置
    with st.sidebar:
        st.header("可视化配置")

        # 节点数量限制
        node_limit = st.slider("最大节点数", min_value=10, max_value=500, value=100, step=10)

        # 关系类型过滤
        st.subheader("关系类型过滤")
        relationship_types = st.multiselect(
            "选择要显示的关系类型",
            options=["申请", "评选", "违纪", "资助", "申诉", "管理", "权利义务", "互斥"],
            default=["申请", "评选"],
        )

        # 布局算法
        layout = st.selectbox("布局算法", options=["force_atlas", "barnes_hut", "hierarchical"], index=0)

        # 物理引擎
        physics_enabled = st.checkbox("启用物理引擎", value=True)

        # 节点大小
        node_size = st.slider("节点大小", min_value=5, max_value=50, value=20)

    # 主内容区
    tab1, tab2, tab3 = st.tabs(["🌐 全图预览", "🔍 社区探索", "🎯 实体邻居"])

    with tab1:
        render_full_graph(node_limit, relationship_types, layout, physics_enabled, node_size)

    with tab2:
        render_community_graph(node_limit, layout, physics_enabled, node_size)

    with tab3:
        render_entity_neighbors(node_limit, relationship_types, layout, physics_enabled, node_size)


def render_full_graph(
    node_limit: int, relationship_types: list, layout: str, physics_enabled: bool, node_size: int
):
    """渲染全图预览"""
    st.subheader("全图预览")
    st.caption(f"显示前 {node_limit} 个节点及其关系")

    if st.button("生成图可视化", key="generate_full_graph"):
        with st.spinner("正在生成图可视化..."):
            try:
                # 调用后端 API 获取图数据
                response = requests.post(
                    f"{API_URL}/graph/visualize",
                    json={
                        "node_limit": node_limit,
                        "relationship_types": relationship_types if relationship_types else None,
                        "layout": layout,
                    },
                    timeout=60,
                )

                if response.status_code == 200:
                    graph_data = response.json()

                    # 使用 pyvis 生成可视化
                    html_content = create_pyvis_graph(
                        graph_data["nodes"],
                        graph_data["edges"],
                        layout=layout,
                        physics_enabled=physics_enabled,
                        node_size=node_size,
                    )

                    # 显示图
                    components.html(html_content, height=800, scrolling=True)

                    # 显示统计信息
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.metric("节点数", len(graph_data["nodes"]))
                    with col2:
                        st.metric("边数", len(graph_data["edges"]))
                    with col3:
                        st.metric("平均度数", f"{graph_data.get('avg_degree', 0):.2f}")

                else:
                    st.error(f"获取图数据失败: {response.text}")

            except Exception as e:
                st.error(f"生成可视化失败: {e}")


def render_community_graph(node_limit: int, layout: str, physics_enabled: bool, node_size: int):
    """渲染社区图"""
    st.subheader("社区探索")
    st.caption("按社区聚类显示节点")

    community_id = st.text_input("社区ID", placeholder="例如: 0-1", help="留空则显示所有社区")

    if st.button("生成社区可视化", key="generate_community_graph"):
        with st.spinner("正在生成社区可视化..."):
            try:
                response = requests.post(
                    f"{API_URL}/graph/visualize/community",
                    json={"community_id": community_id if community_id else None, "node_limit": node_limit},
                    timeout=60,
                )

                if response.status_code == 200:
                    graph_data = response.json()

                    # 为不同社区着色
                    html_content = create_pyvis_graph(
                        graph_data["nodes"],
                        graph_data["edges"],
                        layout=layout,
                        physics_enabled=physics_enabled,
                        node_size=node_size,
                        color_by_community=True,
                    )

                    components.html(html_content, height=800, scrolling=True)

                    # 社区统计
                    st.metric("社区数", graph_data.get("community_count", 0))

                else:
                    st.error(f"获取社区数据失败: {response.text}")

            except Exception as e:
                st.error(f"生成社区可视化失败: {e}")


def render_entity_neighbors(
    node_limit: int, relationship_types: list, layout: str, physics_enabled: bool, node_size: int
):
    """渲染实体邻居"""
    st.subheader("实体邻居探索")
    st.caption("以某个实体为中心，探索其邻居节点")

    entity_name = st.text_input("实体名称", placeholder="例如: 学生", help="输入实体名称")

    hop_count = st.slider("跳数", min_value=1, max_value=3, value=2, help="探索的图深度")

    if entity_name and st.button("生成邻居可视化", key="generate_entity_neighbors"):
        with st.spinner(f"正在探索 '{entity_name}' 的 {hop_count} 跳邻居..."):
            try:
                response = requests.post(
                    f"{API_URL}/graph/visualize/entity_neighbors",
                    json={
                        "entity_name": entity_name,
                        "hop_count": hop_count,
                        "relationship_types": relationship_types if relationship_types else None,
                    },
                    timeout=60,
                )

                if response.status_code == 200:
                    graph_data = response.json()

                    if not graph_data["nodes"]:
                        st.warning(f"未找到实体 '{entity_name}' 或其邻居")
                        return

                    # 中心节点高亮
                    html_content = create_pyvis_graph(
                        graph_data["nodes"],
                        graph_data["edges"],
                        layout=layout,
                        physics_enabled=physics_enabled,
                        node_size=node_size,
                        highlight_node=entity_name,
                    )

                    components.html(html_content, height=800, scrolling=True)

                    # 邻居统计
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric("邻居节点数", len(graph_data["nodes"]) - 1)
                    with col2:
                        st.metric("连接边数", len(graph_data["edges"]))

                else:
                    st.error(f"获取邻居数据失败: {response.text}")

            except Exception as e:
                st.error(f"生成邻居可视化失败: {e}")


def create_pyvis_graph(
    nodes: list,
    edges: list,
    layout: str = "force_atlas",
    physics_enabled: bool = True,
    node_size: int = 20,
    color_by_community: bool = False,
    highlight_node: str = None,
) -> str:
    """
    使用 PyVis 创建图可视化

    Args:
        nodes: 节点列表 [{"id": "node1", "label": "Node 1", "community": 0}, ...]
        edges: 边列表 [{"source": "node1", "target": "node2", "label": "REL"}, ...]
        layout: 布局算法
        physics_enabled: 是否启用物理引擎
        node_size: 节点大小
        color_by_community: 是否按社区着色
        highlight_node: 高亮的节点名称

    Returns:
        HTML 字符串
    """
    try:
        from pyvis.network import Network
    except ImportError:
        return "<html><body><h3>PyVis 未安装，请运行: pip install pyvis</h3></body></html>"

    # 创建网络
    net = Network(height="750px", width="100%", bgcolor="#ffffff", font_color="#000000")

    # 社区颜色映射
    community_colors = [
        "#FF6B6B",
        "#4ECDC4",
        "#45B7D1",
        "#96CEB4",
        "#FFEAA7",
        "#DFE6E9",
        "#A29BFE",
        "#FD79A8",
        "#FDCB6E",
        "#6C5CE7",
    ]

    # 添加节点
    for node in nodes:
        node_id = node["id"]
        label = node.get("label", node_id)

        # 节点颜色
        if highlight_node and label == highlight_node:
            color = "#FF0000"  # 高亮节点为红色
            size = node_size * 1.5
        elif color_by_community and "community" in node:
            color = community_colors[node["community"] % len(community_colors)]
            size = node_size
        else:
            color = "#4ECDC4"
            size = node_size

        # 节点标题（鼠标悬停时显示）
        title = f"<b>{label}</b><br>ID: {node_id}"
        if "community" in node:
            title += f"<br>社区: {node['community']}"

        net.add_node(node_id, label=label, color=color, size=size, title=title)

    # 添加边
    for edge in edges:
        edge_label = edge.get("label", "")
        net.add_edge(edge["source"], edge["target"], title=edge_label, label=edge_label)

    # 设置物理引擎
    if physics_enabled:
        if layout == "force_atlas":
            net.force_atlas_2based()
        elif layout == "barnes_hut":
            net.barnes_hut()
        elif layout == "hierarchical":
            net.set_options(
                """
            {
                "layout": {
                    "hierarchical": {
                        "enabled": true,
                        "direction": "UD",
                        "sortMethod": "directed"
                    }
                }
            }
            """
            )
    else:
        net.toggle_physics(False)

    # 生成HTML
    with tempfile.NamedTemporaryFile(mode="w", suffix=".html", delete=False) as f:
        net.save_graph(f.name)
        with open(f.name, "r", encoding="utf-8") as html_file:
            html_content = html_file.read()

    return html_content
