"""
缓存监控仪表板

提供缓存性能指标的实时监控和可视化。
"""

import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta

# API 基础 URL
from frontend_config.settings import API_URL


def render_cache_dashboard():
    """渲染缓存监控仪表板"""
    st.title("📊 缓存监控仪表板")
    st.markdown("实时监控缓存性能和使用情况")

    st.divider()

    # 刷新按钮
    col1, col2 = st.columns([4, 1])
    with col2:
        if st.button("🔄 刷新数据", use_container_width=True):
            st.rerun()

    # 获取缓存指标
    try:
        response = requests.get(f"{API_URL}/cache/metrics", timeout=10)
        if response.status_code == 200:
            metrics = response.json()
            render_metrics_overview(metrics)
            render_performance_charts(metrics)
            render_cache_details(metrics)
        else:
            st.error(f"获取缓存指标失败: {response.text}")
    except Exception as e:
        st.error(f"获取缓存指标失败: {e}")
        # 显示示例数据
        st.info("显示示例数据（实际需要实现 `/cache/metrics` API）")
        render_sample_dashboard()


def render_metrics_overview(metrics: dict):
    """渲染指标概览"""
    st.subheader("📈 性能概览")

    # 计算命中率
    total_queries = metrics.get("total_queries", 0)
    exact_hits = metrics.get("exact_hits", 0)
    vector_hits = metrics.get("vector_hits", 0)
    misses = metrics.get("misses", 0)

    hit_rate = (exact_hits + vector_hits) / total_queries * 100 if total_queries > 0 else 0

    # 显示关键指标
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        st.metric(
            "缓存命中率",
            f"{hit_rate:.1f}%",
            delta=None,
            help="精确匹配 + 向量匹配的总命中率",
        )

    with col2:
        st.metric("总查询数", f"{total_queries:,}", delta=None)

    with col3:
        st.metric("缓存大小", f"{metrics.get('cache_size', 0):,} 项", delta=None)

    with col4:
        avg_latency = metrics.get("avg_latency_ms", 0)
        st.metric("平均响应时间", f"{avg_latency:.2f}ms", delta=None)

    st.divider()


def render_performance_charts(metrics: dict):
    """渲染性能图表"""
    st.subheader("📊 性能分析")

    col1, col2 = st.columns(2)

    with col1:
        # 命中类型分布饼图
        exact_hits = metrics.get("exact_hits", 0)
        vector_hits = metrics.get("vector_hits", 0)
        misses = metrics.get("misses", 0)

        fig_pie = go.Figure(
            data=[
                go.Pie(
                    labels=["精确命中", "向量命中", "未命中"],
                    values=[exact_hits, vector_hits, misses],
                    marker=dict(colors=["#00CC96", "#636EFA", "#EF553B"]),
                    hole=0.4,
                )
            ]
        )

        fig_pie.update_layout(title="命中类型分布", height=400)

        st.plotly_chart(fig_pie, use_container_width=True)

    with col2:
        # 响应时间分布柱状图
        latency_distribution = metrics.get(
            "latency_distribution",
            {"<10ms": 20, "10-50ms": 45, "50-100ms": 25, "100-500ms": 8, ">500ms": 2},
        )

        fig_bar = go.Figure(
            data=[
                go.Bar(
                    x=list(latency_distribution.keys()),
                    y=list(latency_distribution.values()),
                    marker_color="#636EFA",
                )
            ]
        )

        fig_bar.update_layout(title="响应时间分布", xaxis_title="响应时间", yaxis_title="查询数", height=400)

        st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()


def render_cache_details(metrics: dict):
    """渲染缓存详情"""
    st.subheader("🔍 缓存详情")

    # 缓存类型统计
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("**会话缓存 (Session Cache)**")
        session_cache = metrics.get("session_cache", {})
        st.metric("缓存项数", session_cache.get("size", 0))
        st.metric("命中率", f"{session_cache.get('hit_rate', 0):.1f}%")
        st.metric("内存占用", f"{session_cache.get('memory_mb', 0):.2f} MB")

    with col2:
        st.markdown("**全局缓存 (Global Cache)**")
        global_cache = metrics.get("global_cache", {})
        st.metric("缓存项数", global_cache.get("size", 0))
        st.metric("命中率", f"{global_cache.get('hit_rate', 0):.1f}%")
        st.metric("磁盘占用", f"{global_cache.get('disk_mb', 0):.2f} MB")

    st.divider()

    # 热点查询
    st.subheader("🔥 热点查询 Top 10")

    hot_queries = metrics.get(
        "hot_queries",
        [
            {"query": "旷课多少学时会被退学？", "count": 45},
            {"query": "如何申请奖学金？", "count": 32},
            {"query": "学分不足会怎样？", "count": 28},
        ],
    )

    if hot_queries:
        df = pd.DataFrame(hot_queries)
        st.dataframe(df, use_container_width=True, hide_index=True)
    else:
        st.info("暂无热点查询数据")

    st.divider()

    # 缓存管理操作
    st.subheader("🛠️ 缓存管理")

    col1, col2, col3 = st.columns(3)

    with col1:
        if st.button("🗑️ 清空会话缓存", use_container_width=True):
            clear_cache("session")

    with col2:
        if st.button("🗑️ 清空全局缓存", use_container_width=True):
            clear_cache("global")

    with col3:
        if st.button("🗑️ 清空全部缓存", use_container_width=True):
            clear_cache("all")


def render_sample_dashboard():
    """渲染示例仪表板（用于演示）"""
    sample_metrics = {
        "total_queries": 1250,
        "exact_hits": 450,
        "vector_hits": 320,
        "misses": 480,
        "cache_size": 856,
        "avg_latency_ms": 35.6,
        "latency_distribution": {"<10ms": 250, "10-50ms": 580, "50-100ms": 310, "100-500ms": 95, ">500ms": 15},
        "session_cache": {"size": 234, "hit_rate": 62.3, "memory_mb": 12.4},
        "global_cache": {"size": 622, "hit_rate": 58.7, "disk_mb": 245.6},
        "hot_queries": [
            {"query": "旷课多少学时会被退学？", "count": 45},
            {"query": "如何申请奖学金？", "count": 32},
            {"query": "学分不足会怎样？", "count": 28},
            {"query": "违纪处分有哪些类型？", "count": 25},
            {"query": "如何申诉处分？", "count": 21},
        ],
    }

    render_metrics_overview(sample_metrics)
    render_performance_charts(sample_metrics)
    render_cache_details(sample_metrics)


def clear_cache(cache_type: str):
    """清空缓存"""
    try:
        response = requests.post(f"{API_URL}/cache/clear", json={"cache_type": cache_type}, timeout=10)

        if response.status_code == 200:
            st.success(f"✅ 缓存已清空: {cache_type}")
            st.rerun()
        else:
            st.error(f"清空缓存失败: {response.text}")

    except Exception as e:
        st.error(f"清空缓存失败: {e}")


# 趋势图（可选功能）
def render_trend_chart():
    """渲染缓存趋势图（需要持续收集数据）"""
    st.subheader("📈 缓存趋势")

    # 模拟时间序列数据
    dates = pd.date_range(end=datetime.now(), periods=30, freq="D")
    hit_rates = [55 + i % 20 for i in range(30)]

    df_trend = pd.DataFrame({"日期": dates, "命中率(%)": hit_rates})

    fig_trend = px.line(df_trend, x="日期", y="命中率(%)", title="30天缓存命中率趋势")

    st.plotly_chart(fig_trend, use_container_width=True)
