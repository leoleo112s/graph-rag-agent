"""
指标监控仪表盘

显示构建任务和问答查询的性能指标与趋势分析。
"""

from datetime import datetime, timedelta
from typing import Any, Dict, List

import pandas as pd
import requests
import streamlit as st

# API 基础 URL
API_URL = "http://localhost:8000"


def render_metrics_dashboard():
    """渲染指标监控仪表盘"""
    st.title("📊 指标监控仪表盘")

    # 时间范围选择器
    col1, col2 = st.columns(2)
    with col1:
        days_ago = st.selectbox(
            "时间范围", options=[1, 7, 30, 90], format_func=lambda x: f"最近 {x} 天", index=1  # 默认7天
        )

    # 计算时间范围
    end_time = datetime.now()
    start_time = end_time - timedelta(days=days_ago)

    st.divider()

    # 系统总览
    render_system_overview()

    st.divider()

    # 两列布局
    tab1, tab2 = st.tabs(["🏗️ 构建任务监控", "💬 问答查询监控"])

    with tab1:
        render_build_metrics(start_time.isoformat(), end_time.isoformat())

    with tab2:
        render_qa_metrics(start_time.isoformat(), end_time.isoformat())


def render_system_overview():
    """渲染系统总览"""
    st.subheader("🌐 系统总览")

    try:
        response = requests.get(f"{API_URL}/admin/stats/overview")
        if response.status_code == 200:
            data = response.json()

            col1, col2, col3, col4 = st.columns(4)

            # 构建指标
            with col1:
                st.metric("总构建次数", data["build"]["total_builds"], help="最近7天的总构建次数")

            with col2:
                st.metric("构建成功率", f"{data['build']['success_rate']}%", help="最近7天的构建成功率")

            # 问答指标
            with col3:
                st.metric("总查询次数", data["qa"]["total_queries"], help="最近7天的总查询次数")

            with col4:
                st.metric("平均响应时间", f"{data['qa']['avg_response_time']:.2f}s", help="最近7天的平均响应时间")

            # 第二行指标
            col5, col6, col7, col8 = st.columns(4)

            with col5:
                st.metric("平均构建耗时", f"{data['build']['avg_duration']:.1f}分钟", help="完成构建的平均耗时")

            with col6:
                st.metric("缓存命中率", f"{data['qa']['cache_hit_rate']:.1f}%", help="问答查询的缓存命中率")

            with col7:
                st.metric("用户满意度", f"{data['qa']['positive_feedback_rate']:.1f}%", help="正面反馈率")

        else:
            st.error(f"获取系统总览失败: {response.text}")

    except Exception as e:
        st.error(f"获取系统总览失败: {e}")


def render_build_metrics(start_time: str, end_time: str):
    """渲染构建任务监控"""
    st.subheader("🏗️ 构建任务统计")

    try:
        response = requests.get(f"{API_URL}/admin/stats/build", params={"start_time": start_time, "end_time": end_time})

        if response.status_code == 200:
            data = response.json()

            # 核心KPI
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("总构建次数", data["total_builds"])

            with col2:
                st.metric("成功率", f"{data['success_rate']}%")

            with col3:
                st.metric("平均耗时", f"{data['avg_duration_seconds']:.1f}s")

            with col4:
                st.metric("失败次数", data["failed_builds"], delta_color="inverse")

            st.divider()

            # 数据处理KPI
            col5, col6, col7 = st.columns(3)

            with col5:
                st.metric("总文本块数", f"{data['total_chunks']:,}", help="所有构建任务处理的文本块总数")

            with col6:
                st.metric("总实体数", f"{data['total_nodes']:,}", help="所有构建任务提取的实体总数")

            with col7:
                st.metric("平均实体/构建", f"{data['avg_nodes_per_build']:.0f}", help="每次构建平均提取的实体数")

            st.divider()

            # 每日统计表格
            if data.get("daily_stats"):
                st.subheader("📅 每日构建统计")

                # 转换为DataFrame
                daily_data = []
                for date, stats in sorted(data["daily_stats"].items(), reverse=True):
                    daily_data.append(
                        {
                            "日期": date,
                            "总数": stats["total"],
                            "成功": stats["successful"],
                            "失败": stats["failed"],
                            "成功率": f"{stats['success_rate']:.1f}%",
                            "平均耗时(秒)": f"{stats['avg_duration']:.1f}",
                        }
                    )

                if daily_data:
                    df = pd.DataFrame(daily_data)
                    st.dataframe(df, use_container_width=True)

                    # 可视化趋势
                    st.subheader("📈 构建趋势")

                    # 准备图表数据
                    chart_data = pd.DataFrame([{"日期": d["日期"], "总数": d["总数"]} for d in daily_data])
                    chart_data = chart_data.sort_values("日期")
                    st.line_chart(chart_data.set_index("日期"))

            # 类型分布
            if data.get("type_distribution"):
                st.subheader("📊 构建类型分布")
                type_df = pd.DataFrame([{"类型": k, "数量": v} for k, v in data["type_distribution"].items()])
                st.bar_chart(type_df.set_index("类型"))

        else:
            st.error(f"获取构建统计失败: {response.text}")

    except Exception as e:
        st.error(f"获取构建统计失败: {e}")


def render_qa_metrics(start_time: str, end_time: str):
    """渲染问答查询监控"""
    st.subheader("💬 问答查询统计")

    try:
        response = requests.get(f"{API_URL}/admin/stats/qa", params={"start_time": start_time, "end_time": end_time})

        if response.status_code == 200:
            data = response.json()

            # 核心KPI
            col1, col2, col3, col4 = st.columns(4)

            with col1:
                st.metric("总查询次数", data["total_queries"])

            with col2:
                st.metric("平均响应时间", f"{data['avg_response_time']:.3f}s")

            with col3:
                st.metric("缓存命中率", f"{data['cache_hit_rate']:.1f}%")

            with col4:
                st.metric("正面反馈率", f"{data['positive_feedback_rate']:.1f}%")

            st.divider()

            # 性能分解
            col5, col6, col7 = st.columns(3)

            with col5:
                st.metric("平均搜索时间", f"{data['avg_search_time']:.3f}s", help="检索阶段平均耗时")

            with col6:
                st.metric("平均LLM时间", f"{data['avg_llm_time']:.3f}s", help="LLM生成阶段平均耗时")

            with col7:
                st.metric("平均Token/查询", f"{data['avg_tokens_per_query']:.0f}", help="每次查询平均消耗的Token数")

            st.divider()

            # 反馈统计
            col8, col9 = st.columns(2)

            with col8:
                st.metric("正面反馈", data["positive_feedback_count"], help="用户点赞数量")

            with col9:
                st.metric("负面反馈", data["negative_feedback_count"], delta_color="inverse", help="用户点踩数量")

            st.divider()

            # 代理类型分布
            if data.get("agent_distribution"):
                st.subheader("🤖 代理类型分布")
                agent_df = pd.DataFrame([{"代理类型": k, "使用次数": v} for k, v in data["agent_distribution"].items()])
                st.bar_chart(agent_df.set_index("代理类型"))

            # 检索器类型分布
            if data.get("retriever_distribution"):
                st.subheader("🔍 检索器类型分布")
                retriever_df = pd.DataFrame(
                    [{"检索器": k, "使用次数": v} for k, v in data["retriever_distribution"].items()]
                )
                st.bar_chart(retriever_df.set_index("检索器"))

            st.divider()

            # 时间序列图表
            st.subheader("📈 响应时间趋势")

            # 选择时间粒度
            interval = st.selectbox(
                "时间粒度",
                options=["hour", "day", "week"],
                format_func=lambda x: {"hour": "小时", "day": "天", "week": "周"}[x],
                index=1,  # 默认按天
            )

            # 获取时间序列数据
            ts_response = requests.get(
                f"{API_URL}/admin/stats/qa/timeseries",
                params={
                    "metric": "response_time",
                    "start_time": start_time,
                    "end_time": end_time,
                    "interval": interval,
                },
            )

            if ts_response.status_code == 200:
                ts_data = ts_response.json()

                if ts_data:
                    # 转换为DataFrame
                    ts_df = pd.DataFrame(ts_data)
                    ts_df["时间"] = ts_df["time"]
                    ts_df["平均响应时间(秒)"] = ts_df["avg"]

                    # 绘制图表
                    st.line_chart(ts_df.set_index("时间")[["平均响应时间(秒)"]])

                    # 详细数据表格
                    with st.expander("查看详细数据"):
                        st.dataframe(
                            ts_df[["时间", "平均响应时间(秒)", "min", "max", "count"]], use_container_width=True
                        )
                else:
                    st.info("暂无时间序列数据")

            # Token消耗趋势
            st.subheader("💰 Token消耗统计")
            col10, col11 = st.columns(2)

            with col10:
                st.metric("总Token消耗", f"{data['total_tokens']:,}", help="时间范围内的总Token消耗")

            with col11:
                estimated_cost = data["total_tokens"] / 1000 * 0.002  # 假设每1K token $0.002
                st.metric("估算成本(USD)", f"${estimated_cost:.2f}", help="基于gpt-4o定价的估算成本")

        else:
            st.error(f"获取问答统计失败: {response.text}")

    except Exception as e:
        st.error(f"获取问答统计失败: {e}")
