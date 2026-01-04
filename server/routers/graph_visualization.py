"""
图可视化 API

提供图数据接口for PyVis 可视化。
"""

import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from graphrag_agent.config.settings import NEO4J_CONFIG
from langchain_community.graphs import Neo4jGraph

router = APIRouter(prefix="/graph", tags=["graph_visualization"])
logger = logging.getLogger(__name__)


class VisualizeRequest(BaseModel):
    """图可视化请求"""

    node_limit: int = 100
    relationship_types: Optional[List[str]] = None
    layout: str = "force_atlas"


class CommunityVisualizeRequest(BaseModel):
    """社区可视化请求"""

    community_id: Optional[str] = None
    node_limit: int = 100


class EntityNeighborsRequest(BaseModel):
    """实体邻居可视化请求"""

    entity_name: str
    hop_count: int = 2
    relationship_types: Optional[List[str]] = None


def get_neo4j_graph() -> Neo4jGraph:
    """获取 Neo4j 图实例"""
    try:
        return Neo4jGraph(
            url=NEO4J_CONFIG["uri"],
            username=NEO4J_CONFIG["username"],
            password=NEO4J_CONFIG["password"],
        )
    except Exception as e:
        logger.error(f"Failed to connect to Neo4j: {e}")
        raise HTTPException(status_code=500, detail="无法连接到 Neo4j 数据库")


@router.post("/visualize")
async def visualize_graph(request: VisualizeRequest) -> Dict[str, Any]:
    """
    获取图数据用于可视化

    Args:
        request: 可视化请求

    Returns:
        图数据 (nodes, edges, metadata)
    """
    try:
        graph = get_neo4j_graph()

        # 构建关系类型过滤
        relationship_filter = ""
        if request.relationship_types:
            relationship_filter = "WHERE type(r) IN $relationship_types"

        # 查询节点和边
        query = f"""
        MATCH (n:`__Entity__`)-[r]->(m:`__Entity__`)
        {relationship_filter}
        WITH n, r, m
        LIMIT {request.node_limit}
        RETURN
            collect(DISTINCT {{id: id(n), label: n.id, name: n.id}}) AS nodes_source,
            collect(DISTINCT {{id: id(m), label: m.id, name: m.id}}) AS nodes_target,
            collect({{source: id(n), target: id(m), label: type(r)}}) AS edges
        """

        result = graph.query(
            query,
            params={"relationship_types": request.relationship_types} if request.relationship_types else {},
        )

        if not result:
            return {"nodes": [], "edges": [], "avg_degree": 0}

        # 合并节点
        nodes_source = result[0].get("nodes_source", [])
        nodes_target = result[0].get("nodes_target", [])
        edges = result[0].get("edges", [])

        # 去重节点
        nodes_dict = {}
        for node in nodes_source + nodes_target:
            nodes_dict[node["id"]] = node

        nodes = list(nodes_dict.values())

        # 计算平均度数
        avg_degree = len(edges) / len(nodes) if nodes else 0

        return {"nodes": nodes, "edges": edges, "avg_degree": avg_degree}

    except Exception as e:
        logger.error(f"Failed to visualize graph: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/visualize/community")
async def visualize_community(request: CommunityVisualizeRequest) -> Dict[str, Any]:
    """
    按社区可视化图

    Args:
        request: 社区可视化请求

    Returns:
        图数据 (nodes with community info, edges)
    """
    try:
        graph = get_neo4j_graph()

        # 构建社区过滤
        community_filter = ""
        if request.community_id:
            community_filter = f"WHERE c.id = '{request.community_id}'"

        # 查询社区节点
        query = f"""
        MATCH (n:`__Entity__`)-[:IN_COMMUNITY]->(c:`__Community__`)
        {community_filter}
        WITH n, c.id AS community_id
        LIMIT {request.node_limit}

        MATCH (n)-[r]->(m)
        WHERE m:`__Entity__`

        RETURN
            collect(DISTINCT {{
                id: id(n),
                label: n.id,
                name: n.id,
                community: toInteger(split(community_id, '-')[1])
            }}) AS nodes_source,
            collect(DISTINCT {{
                id: id(m),
                label: m.id,
                name: m.id
            }}) AS nodes_target,
            collect({{source: id(n), target: id(m), label: type(r)}}) AS edges,
            count(DISTINCT community_id) AS community_count
        """

        result = graph.query(query)

        if not result:
            return {"nodes": [], "edges": [], "community_count": 0}

        # 合并节点
        nodes_source = result[0].get("nodes_source", [])
        nodes_target = result[0].get("nodes_target", [])
        edges = result[0].get("edges", [])
        community_count = result[0].get("community_count", 0)

        # 去重节点
        nodes_dict = {}
        for node in nodes_source + nodes_target:
            nodes_dict[node["id"]] = node

        nodes = list(nodes_dict.values())

        return {"nodes": nodes, "edges": edges, "community_count": community_count}

    except Exception as e:
        logger.error(f"Failed to visualize community: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/visualize/entity_neighbors")
async def visualize_entity_neighbors(request: EntityNeighborsRequest) -> Dict[str, Any]:
    """
    可视化实体的N跳邻居

    Args:
        request: 实体邻居请求

    Returns:
        图数据 (nodes, edges)
    """
    try:
        graph = get_neo4j_graph()

        # 构建关系类型过滤
        relationship_filter = ""
        if request.relationship_types:
            rel_types = "|".join([f":{rt}" for rt in request.relationship_types])
            relationship_filter = rel_types
        else:
            relationship_filter = ""

        # 查询N跳邻居
        if relationship_filter:
            query = f"""
            MATCH path = (start:`__Entity__` {{id: $entity_name}})
                         -[{relationship_filter}*1..{request.hop_count}]-
                         (neighbor:`__Entity__`)
            WITH start, neighbor, relationships(path) AS rels
            LIMIT 200

            RETURN
                collect(DISTINCT {{id: id(start), label: start.id, name: start.id}}) AS start_nodes,
                collect(DISTINCT {{id: id(neighbor), label: neighbor.id, name: neighbor.id}}) AS neighbor_nodes,
                collect({{
                    source: id(startNode(rels[0])),
                    target: id(endNode(rels[0])),
                    label: type(rels[0])
                }}) AS edges
            """
        else:
            query = f"""
            MATCH path = (start:`__Entity__` {{id: $entity_name}})
                         -[*1..{request.hop_count}]-
                         (neighbor:`__Entity__`)
            WITH start, neighbor, relationships(path) AS rels
            LIMIT 200

            UNWIND rels AS r
            WITH DISTINCT r, start, neighbor

            RETURN
                collect(DISTINCT {{id: id(start), label: start.id, name: start.id}}) AS start_nodes,
                collect(DISTINCT {{id: id(startNode(r)), label: startNode(r).id, name: startNode(r).id}}) AS source_nodes,
                collect(DISTINCT {{id: id(endNode(r)), label: endNode(r).id, name: endNode(r).id}}) AS target_nodes,
                collect({{source: id(startNode(r)), target: id(endNode(r)), label: type(r)}}) AS edges
            """

        result = graph.query(query, params={"entity_name": request.entity_name})

        if not result:
            return {"nodes": [], "edges": []}

        # 合并节点
        if relationship_filter:
            start_nodes = result[0].get("start_nodes", [])
            neighbor_nodes = result[0].get("neighbor_nodes", [])
            all_nodes = start_nodes + neighbor_nodes
        else:
            start_nodes = result[0].get("start_nodes", [])
            source_nodes = result[0].get("source_nodes", [])
            target_nodes = result[0].get("target_nodes", [])
            all_nodes = start_nodes + source_nodes + target_nodes

        edges = result[0].get("edges", [])

        # 去重节点
        nodes_dict = {}
        for node in all_nodes:
            nodes_dict[node["id"]] = node

        nodes = list(nodes_dict.values())

        return {"nodes": nodes, "edges": edges}

    except Exception as e:
        logger.error(f"Failed to visualize entity neighbors: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_graph_stats() -> Dict[str, Any]:
    """
    获取图统计信息

    Returns:
        图统计数据
    """
    try:
        graph = get_neo4j_graph()

        # 统计节点、边、社区
        stats_query = """
        MATCH (n:`__Entity__`)
        WITH count(n) AS entity_count

        MATCH ()-[r]->()
        WITH entity_count, count(r) AS relationship_count

        MATCH (c:`__Community__`)
        RETURN entity_count, relationship_count, count(c) AS community_count
        """

        result = graph.query(stats_query)

        if result:
            return result[0]
        else:
            return {"entity_count": 0, "relationship_count": 0, "community_count": 0}

    except Exception as e:
        logger.error(f"Failed to get graph stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
