import traceback
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from models.schemas import (
    EntityData,
    EntityDeleteData,
    EntitySearchFilter,
    EntityUpdateData,
    ReasoningRequest,
    RelationData,
    RelationDeleteData,
    RelationSearchFilter,
    RelationUpdateData,
)
from server_config.database import get_db_manager
from services.kg_service import (
    extract_kg_from_message,
    get_all_paths,
    get_chunks,
    get_common_neighbors,
    get_entity_cycles,
    get_entity_influence,
    get_knowledge_graph,
    get_one_two_hop_paths,
    get_shortest_path,
    get_simplified_community,
)

from server.utils.auth import verify_admin_token  # ✅ 导入管理员权限验证

# 创建路由器
router = APIRouter()


@router.get("/knowledge_graph")
async def knowledge_graph(limit: int = 100, query: Optional[str] = None):
    """
    获取知识图谱数据

    Args:
        limit: 节点数量限制
        query: 查询条件(可选)

    Returns:
        Dict: 知识图谱数据，包含节点和连接
    """
    return get_knowledge_graph(limit, query)


@router.get("/knowledge_graph_from_message")
async def knowledge_graph_from_message(message: Optional[str] = None, query: Optional[str] = None):
    """
    从消息文本中提取知识图谱数据

    Args:
        message: 消息文本
        query: 查询内容(可选)

    Returns:
        Dict: 知识图谱数据，包含节点和连接
    """
    if not message:
        return {"nodes": [], "links": []}

    return extract_kg_from_message(message, query)


@router.get("/chunks")
async def chunks(limit: int = 10, offset: int = 0):
    """
    获取数据库中的文本块

    Args:
        limit: 返回数量限制
        offset: 偏移量

    Returns:
        Dict: 文本块数据和总数
    """
    return get_chunks(limit, offset)


@router.post("/kg_reasoning")
async def knowledge_graph_reasoning(request: ReasoningRequest):
    """
    执行知识图谱推理
    """
    try:
        # 获取数据库连接
        db_manager = get_db_manager()
        driver = db_manager.get_driver()

        # 对参数进行处理，确保安全传递给Neo4j
        reasoning_type = request.reasoning_type
        entity_a = request.entity_a.strip()
        entity_b = request.entity_b.strip() if request.entity_b else None
        max_depth = min(max(1, request.max_depth), 5)  # 确保在1-5的范围内
        algorithm = request.algorithm

        print(
            f"推理请求: 类型={reasoning_type}, 实体A={entity_a}, 实体B={entity_b}, 深度={max_depth}, 算法={algorithm}"
        )

        # 社区检测系统
        if reasoning_type == "entity_community":
            return await process_community_detection(entity_a, max_depth, algorithm)

        # 其他推理类型
        if reasoning_type == "shortest_path":
            if not entity_b:
                return {"error": "最短路径查询需要指定两个实体", "nodes": [], "links": []}
            result = get_shortest_path(driver, entity_a, entity_b, max_depth)
        elif reasoning_type == "one_two_hop":
            if not entity_b:
                return {"error": "一到两跳关系查询需要指定两个实体", "nodes": [], "links": []}
            result = get_one_two_hop_paths(driver, entity_a, entity_b)
        elif reasoning_type == "common_neighbors":
            if not entity_b:
                return {"error": "共同邻居查询需要指定两个实体", "nodes": [], "links": []}
            result = get_common_neighbors(driver, entity_a, entity_b)
        elif reasoning_type == "all_paths":
            if not entity_b:
                return {"error": "关系路径查询需要指定两个实体", "nodes": [], "links": []}
            result = get_all_paths(driver, entity_a, entity_b, max_depth)
        elif reasoning_type == "entity_cycles":
            result = get_entity_cycles(driver, entity_a, max_depth)
        elif reasoning_type == "entity_influence":
            result = get_entity_influence(driver, entity_a, max_depth)
        else:
            return {"error": "未知的推理类型", "nodes": [], "links": []}

        return result
    except Exception as e:
        print(f"推理查询异常: {str(e)}")
        traceback.print_exc()
        return {"error": str(e), "nodes": [], "links": []}


async def process_community_detection(entity_id: str, max_depth: int, algorithm: str):
    """执行专业社区检测流程"""
    try:
        # 首先检查实体是否已存在于社区中
        community_info = await get_entity_community_from_db(entity_id)
        if community_info and community_info.get("nodes") and community_info.get("links"):
            print(f"实体 {entity_id} 已有社区信息，直接返回")
            return community_info

        # 实体没有社区信息，使用简化版本返回查询结果
        print(f"实体 {entity_id} 没有社区信息，使用简化版本")
        db_manager = get_db_manager()
        driver = db_manager.get_driver()
        return get_simplified_community(driver, entity_id, max_depth)
    except Exception as e:
        print(f"处理社区检测失败: {str(e)}")
        traceback.print_exc()
        return {"error": str(e), "nodes": [], "links": []}


async def get_entity_community_from_db(entity_id: str):
    """从数据库中获取实体的社区信息"""
    try:
        db_manager = get_db_manager()
        graph = db_manager.get_graph()

        # 查询实体所属的社区
        community_result = graph.query(
            """
        MATCH (e:__Entity__ {id: $entity_id})-[:IN_COMMUNITY]->(c:__Community__)
        RETURN c.id AS community_id
        LIMIT 1
        """,
            params={"entity_id": entity_id},
        )

        if not community_result:
            return None

        community_id = community_result[0].get("community_id")
        if not community_id:
            return None

        # 获取该社区的所有节点和关系
        community_data = graph.query(
            """
        // 获取社区中的所有实体
        MATCH (c:__Community__ {id: $community_id})<-[:IN_COMMUNITY]-(e:__Entity__)
        WITH c, collect({
            id: e.id,
            description: e.description,
            labels: labels(e)
        }) AS entities
        
        // 获取社区摘要
        OPTIONAL MATCH (c)
        WHERE c.summary IS NOT NULL
        
        // 获取实体间的关系
        CALL {
            WITH c
            MATCH (c)<-[:IN_COMMUNITY]-(e1:__Entity__)-[r]->(e2:__Entity__)-[:IN_COMMUNITY]->(c)
            RETURN collect({
                source: e1.id,
                target: e2.id,
                type: type(r)
            }) AS relationships
        }
        
        // 返回社区信息
        RETURN 
            c.id AS community_id,
            c.summary AS summary,
            entities,
            relationships
        """,
            params={"community_id": community_id},
        )

        if not community_data:
            return None

        # 构建可视化格式
        nodes = []
        links = []
        community_summary = community_data[0].get("summary", "无社区摘要")

        # 处理节点
        for entity in community_data[0].get("entities", []):
            entity_labels = entity.get("labels", [])
            group = [label for label in entity_labels if label != "__Entity__"]
            group = group[0] if group else "Unknown"

            # 标记中心实体
            if entity.get("id") == entity_id:
                group = "Center"

            nodes.append(
                {
                    "id": entity.get("id"),
                    "label": entity.get("id"),
                    "description": entity.get("description", ""),
                    "group": group,
                }
            )

        # 处理关系
        for rel in community_data[0].get("relationships", []):
            links.append(
                {"source": rel.get("source"), "target": rel.get("target"), "label": rel.get("type"), "weight": 1}
            )

        # 获取社区统计信息
        stats = {
            "id": community_id,
            "entity_count": len(nodes),
            "relation_count": len(links),
            "summary": community_summary,
        }

        return {"nodes": nodes, "links": links, "community_info": stats}

    except Exception as e:
        print(f"获取社区信息失败: {str(e)}")
        return None


@router.get("/entity_types")
def get_entity_types():
    db_manager = get_db_manager()
    try:
        # 查询实体类型
        result = db_manager.execute_query(
            """
        MATCH (e:__Entity__)
        RETURN DISTINCT
        CASE WHEN size(labels(e)) > 1 
             THEN [lbl IN labels(e) WHERE lbl <> '__Entity__'][0] 
             ELSE 'Unknown' 
        END AS entity_type
        ORDER BY entity_type
        """
        )

        # DataFrame处理方式
        entity_types = result["entity_type"].tolist() if "entity_type" in result.columns else []

        return {"entity_types": entity_types}
    except Exception as e:
        print(e)
        traceback.print_exc()  # 打印完整堆栈
        raise HTTPException(status_code=500, detail=f"获取实体类型失败: {str(e)}")


@router.get("/relation_types")
def get_relation_types():
    db_manager = get_db_manager()
    try:
        # 查询关系类型
        result = db_manager.execute_query(
            """
        MATCH ()-[r]->()
        RETURN DISTINCT type(r) AS relation_type
        ORDER BY relation_type
        """
        )

        # DataFrame处理方式
        relation_types = result["relation_type"].tolist() if "relation_type" in result.columns else []

        return {"relation_types": relation_types}
    except Exception as e:
        print(e)
        traceback.print_exc()  # 打印完整堆栈
        raise HTTPException(status_code=500, detail=f"获取关系类型失败: {str(e)}")


@router.post("/entities/search")
def search_entities(filters: EntitySearchFilter):
    db_manager = get_db_manager()
    try:
        # 构建查询条件
        conditions = ["e:__Entity__"]
        params = {}

        if filters.type:
            conditions.append(f"e:{filters.type}")

        if filters.term:
            conditions.append("e.id CONTAINS $term")
            params["term"] = filters.term

        # 构建完整查询
        query = f"""
        MATCH (e)
        WHERE {' AND '.join(conditions)}
        RETURN e.id AS id,
               COALESCE(e.id, '') AS name,
               CASE WHEN size(labels(e)) > 1 
                    THEN [lbl IN labels(e) WHERE lbl <> '__Entity__'][0] 
                    ELSE 'Unknown' 
               END AS type,
               COALESCE(e.description, '') AS description
        LIMIT {filters.limit}
        """

        result = db_manager.execute_query(query, params)

        # 检查结果是否为None
        if result is None:
            return {"entities": []}

        # DataFrame处理方式
        entities = []
        if not result.empty:
            for _, row in result.iterrows():
                entity = {
                    "id": row["id"] if "id" in row and row["id"] is not None else "",
                    "name": row["name"] if "name" in row and row["name"] is not None else "",
                    "type": row["type"] if "type" in row and row["type"] is not None else "Unknown",
                    "description": (
                        row["description"] if "description" in row and row["description"] is not None else ""
                    ),
                    "properties": {},
                }
                entities.append(entity)

        return {"entities": entities}
    except Exception as e:
        print(e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"搜索实体失败: {str(e)}")


@router.post("/relations/search")
def search_relations(filters: RelationSearchFilter):
    db_manager = get_db_manager()
    try:
        # 构建查询条件
        conditions = []
        params = {}

        if filters.source:
            conditions.append("e1.id = $source")
            params["source"] = filters.source

        if filters.target:
            conditions.append("e2.id = $target")
            params["target"] = filters.target

        if filters.type:
            conditions.append("type(r) = $relType")
            params["relType"] = filters.type

        # 构建完整查询
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        query = f"""
        MATCH (e1:__Entity__)-[r]->(e2:__Entity__)
        {where_clause}
        RETURN e1.id AS source,
               type(r) AS type,
               e2.id AS target,
               COALESCE(r.description, '') AS description,
               COALESCE(r.weight, 0.5) AS weight
        LIMIT {filters.limit}
        """

        result = db_manager.execute_query(query, params)

        # DataFrame处理方式
        relations = []
        if not result.empty:
            for _, row in result.iterrows():
                relation = {
                    "source": row["source"] if "source" in row else None,
                    "type": row["type"] if "type" in row else None,
                    "target": row["target"] if "target" in row else None,
                    "description": row["description"] if "description" in row else "",
                    "weight": row["weight"] if "weight" in row else 0.5,
                    "properties": {},
                }
                relations.append(relation)

        return {"relations": relations}
    except Exception as e:
        print(e)
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"搜索关系失败: {str(e)}")


@router.post("/entity/create", dependencies=[Depends(verify_admin_token)])
def create_entity(entity_data: EntityData):
    """
    创建实体

    ✅ 改进：需要管理员权限（X-Admin-Token Header）

    Args:
        entity_data: 实体数据

    Returns:
        Dict: 创建结果

    Security:
        - Requires: X-Admin-Token in HTTP Headers
    """
    db_manager = get_db_manager()
    try:
        # 检查实体是否已存在
        check_query = """
        MATCH (e:__Entity__ {id: $id})
        RETURN count(e) AS count
        """

        check_result = db_manager.execute_query(check_query, {"id": entity_data.id})

        if not check_result.empty and check_result.iloc[0]["count"] > 0:
            return {"success": False, "message": f"实体ID '{entity_data.id}' 已存在"}

        # 创建实体，设置基本属性
        create_query = f"""
        CREATE (e:__Entity__:{entity_data.type} {{
            id: $id,
            name: $name,
            description: $description
        }})
        RETURN e.id AS id
        """

        params = {"id": entity_data.id, "name": entity_data.name, "description": entity_data.description}

        result = db_manager.execute_query(create_query, params)

        if not result.empty:
            return {"success": True, "id": result.iloc[0]["id"]}
        else:
            return {"success": False, "message": "创建实体失败: 未能获取返回结果"}
    except Exception as e:
        print(e)
        traceback.print_exc()
        return {"success": False, "message": f"创建实体失败: {str(e)}"}


@router.post("/entity/update", dependencies=[Depends(verify_admin_token)])
def update_entity(entity_data: EntityUpdateData):
    """
    更新实体

    ✅ 改进：需要管理员权限（X-Admin-Token Header）

    Args:
        entity_data: 实体更新数据

    Returns:
        Dict: 更新结果

    Security:
        - Requires: X-Admin-Token in HTTP Headers
    """
    db_manager = get_db_manager()
    try:
        # 检查实体是否存在
        check_query = """
        MATCH (e:__Entity__ {id: $id})
        RETURN count(e) AS count
        """

        check_result = db_manager.execute_query(check_query, {"id": entity_data.id})

        if check_result.empty or check_result.iloc[0]["count"] == 0:
            return {"success": False, "message": f"实体ID '{entity_data.id}' 不存在"}

        # 构建更新参数
        params = {"id": entity_data.id}
        set_clauses = []

        if entity_data.name is not None:
            set_clauses.append("e.name = $name")
            params["name"] = entity_data.name

        if entity_data.description is not None:
            set_clauses.append("e.description = $description")
            params["description"] = entity_data.description

        # 如果需要更新类型，需要先移除旧标签，再添加新标签
        if entity_data.type is not None:
            # 获取当前实体的标签
            labels_query = """
            MATCH (e:__Entity__ {id: $id})
            RETURN labels(e) AS labels
            """

            labels_result = db_manager.execute_query(labels_query, {"id": entity_data.id})

            if not labels_result.empty:
                current_labels = labels_result.iloc[0]["labels"]

                # 移除非__Entity__的标签
                remove_labels = [label for label in current_labels if label != "__Entity__"]

                # 执行更新
                update_type_query = f"""
                MATCH (e:__Entity__ {{id: $id}})
                {' '.join(f'REMOVE e:{label}' for label in remove_labels)}
                SET e:{entity_data.type}
                RETURN e.id as id
                """

                db_manager.execute_query(update_type_query, {"id": entity_data.id})

        # 执行更新
        if set_clauses:
            update_query = f"""
            MATCH (e:__Entity__ {{id: $id}})
            SET {', '.join(set_clauses)}
            RETURN e.id as id
            """

            db_manager.execute_query(update_query, params)

        return {"success": True}
    except Exception as e:
        print(e)
        traceback.print_exc()
        return {"success": False, "message": f"更新实体失败: {str(e)}"}


@router.post("/entity/delete", dependencies=[Depends(verify_admin_token)])
def delete_entity(entity_data: EntityDeleteData):
    """
    删除实体

    ✅ 改进：需要管理员权限（X-Admin-Token Header）

    Args:
        entity_data: 实体删除数据

    Returns:
        Dict: 删除结果

    Security:
        - Requires: X-Admin-Token in HTTP Headers
    """
    db_manager = get_db_manager()
    try:
        # 检查实体是否存在
        check_query = """
        MATCH (e:__Entity__ {id: $id})
        RETURN count(e) AS count
        """

        check_result = db_manager.execute_query(check_query, {"id": entity_data.id})

        # 检查结果是否为None
        if check_result is None:
            return {"success": False, "message": "检查实体存在性失败: 查询返回为空"}

        # 检查是否存在计数结果
        if check_result.empty:
            return {"success": False, "message": f"实体ID '{entity_data.id}' 不存在: 查询结果为空"}

        # 安全地访问count值
        count_value = 0
        if "count" in check_result.columns:
            count_value = check_result.iloc[0]["count"]

        if count_value == 0:
            return {"success": False, "message": f"实体ID '{entity_data.id}' 不存在"}

        # 删除实体的所有关系
        delete_rels_query = """
        MATCH (e:__Entity__ {id: $id})-[r]-()
        DELETE r
        """

        db_manager.execute_query(delete_rels_query, {"id": entity_data.id})

        # 删除实体
        delete_query = """
        MATCH (e:__Entity__ {id: $id})
        DELETE e
        """

        db_manager.execute_query(delete_query, {"id": entity_data.id})

        return {"success": True}
    except Exception as e:
        print(e)
        traceback.print_exc()
        return {"success": False, "message": f"删除实体失败: {str(e)}"}


@router.post("/relation/create", dependencies=[Depends(verify_admin_token)])
def create_relation(relation_data: RelationData):
    """
    创建关系

    ✅ 改进：需要管理员权限（X-Admin-Token Header）

    Args:
        relation_data: 关系数据

    Returns:
        Dict: 创建结果

    Security:
        - Requires: X-Admin-Token in HTTP Headers
    """
    db_manager = get_db_manager()
    try:
        # 检查源实体和目标实体是否存在
        check_query = """
        MATCH (e1:__Entity__ {id: $source})
        MATCH (e2:__Entity__ {id: $target})
        RETURN count(e1) AS source_count, count(e2) AS target_count
        """

        check_result = db_manager.execute_query(
            check_query, {"source": relation_data.source, "target": relation_data.target}
        )

        if not check_result.empty:
            if check_result.iloc[0]["source_count"] == 0:
                return {"success": False, "message": f"源实体 '{relation_data.source}' 不存在"}

            if check_result.iloc[0]["target_count"] == 0:
                return {"success": False, "message": f"目标实体 '{relation_data.target}' 不存在"}
        else:
            return {"success": False, "message": "无法验证实体存在性"}

        # 检查关系是否已存在
        rel_check_query = """
        MATCH (e1:__Entity__ {id: $source})-[r]->(e2:__Entity__ {id: $target})
        WHERE type(r) = $relType
        RETURN count(r) AS rel_count
        """

        rel_check_result = db_manager.execute_query(
            rel_check_query,
            {"source": relation_data.source, "target": relation_data.target, "relType": relation_data.type},
        )

        if not rel_check_result.empty and rel_check_result.iloc[0]["rel_count"] > 0:
            return {
                "success": False,
                "message": f"关系 '{relation_data.source} -[{relation_data.type}]-> {relation_data.target}' 已存在",
            }

        # 创建关系，只使用基本属性
        create_query = f"""
        MATCH (e1:__Entity__ {{id: $source}})
        MATCH (e2:__Entity__ {{id: $target}})
        CREATE (e1)-[r:{relation_data.type} {{
            description: $description,
            weight: $weight
        }}]->(e2)
        RETURN type(r) AS type
        """

        params = {
            "source": relation_data.source,
            "target": relation_data.target,
            "description": relation_data.description,
            "weight": relation_data.weight,
        }

        result = db_manager.execute_query(create_query, params)

        if not result.empty:
            return {"success": True, "type": result.iloc[0]["type"]}
        else:
            return {"success": False, "message": "创建关系失败: 未能获取返回结果"}
    except Exception as e:
        print(e)
        traceback.print_exc()
        return {"success": False, "message": f"创建关系失败: {str(e)}"}


@router.post("/relation/update", dependencies=[Depends(verify_admin_token)])
def update_relation(relation_data: RelationUpdateData):
    """
    更新关系

    ✅ 改进：需要管理员权限（X-Admin-Token Header）

    Args:
        relation_data: 关系更新数据

    Returns:
        Dict: 更新结果

    Security:
        - Requires: X-Admin-Token in HTTP Headers
    """
    db_manager = get_db_manager()
    try:
        # 检查关系是否存在
        check_query = """
        MATCH (e1:__Entity__ {id: $source})-[r]->(e2:__Entity__ {id: $target})
        WHERE type(r) = $relType
        RETURN count(r) AS count
        """

        check_result = db_manager.execute_query(
            check_query,
            {"source": relation_data.source, "target": relation_data.target, "relType": relation_data.original_type},
        )

        if check_result.empty or check_result.iloc[0]["count"] == 0:
            return {
                "success": False,
                "message": f"关系 '{relation_data.source} -[{relation_data.original_type}]-> {relation_data.target}' 不存在",
            }

        # 如果需要更改关系类型，需要删除旧关系，创建新关系
        if relation_data.new_type and relation_data.new_type != relation_data.original_type:
            # 获取当前关系的所有属性
            get_props_query = """
            MATCH (e1:__Entity__ {id: $source})-[r]->(e2:__Entity__ {id: $target})
            WHERE type(r) = $relType
            RETURN r.description AS description,
                   r.weight AS weight
            """

            props_result = db_manager.execute_query(
                get_props_query,
                {
                    "source": relation_data.source,
                    "target": relation_data.target,
                    "relType": relation_data.original_type,
                },
            )

            # 删除旧关系
            delete_query = """
            MATCH (e1:__Entity__ {id: $source})-[r]->(e2:__Entity__ {id: $target})
            WHERE type(r) = $relType
            DELETE r
            """

            db_manager.execute_query(
                delete_query,
                {
                    "source": relation_data.source,
                    "target": relation_data.target,
                    "relType": relation_data.original_type,
                },
            )

            # 准备新关系属性
            if not props_result.empty:
                props = props_result.iloc[0]

                description = (
                    relation_data.description
                    if relation_data.description is not None
                    else props["description"] if "description" in props else ""
                )
                weight = (
                    relation_data.weight
                    if relation_data.weight is not None
                    else props["weight"] if "weight" in props else 0.5
                )

                # 创建新关系
                create_query = f"""
                MATCH (e1:__Entity__ {{id: $source}})
                MATCH (e2:__Entity__ {{id: $target}})
                CREATE (e1)-[r:{relation_data.new_type} {{
                    description: $description,
                    weight: $weight
                }}]->(e2)
                RETURN type(r) AS type
                """

                db_manager.execute_query(
                    create_query,
                    {
                        "source": relation_data.source,
                        "target": relation_data.target,
                        "description": description,
                        "weight": weight,
                    },
                )
            else:
                # 如果没有获取到原属性，使用默认值
                create_query = f"""
                MATCH (e1:__Entity__ {{id: $source}})
                MATCH (e2:__Entity__ {{id: $target}})
                CREATE (e1)-[r:{relation_data.new_type} {{
                    description: $description,
                    weight: $weight
                }}]->(e2)
                RETURN type(r) AS type
                """

                db_manager.execute_query(
                    create_query,
                    {
                        "source": relation_data.source,
                        "target": relation_data.target,
                        "description": relation_data.description or "",
                        "weight": relation_data.weight or 0.5,
                    },
                )
        else:
            # 构建更新参数
            params = {
                "source": relation_data.source,
                "target": relation_data.target,
                "relType": relation_data.original_type,
            }
            set_clauses = []

            if relation_data.description is not None:
                set_clauses.append("r.description = $description")
                params["description"] = relation_data.description

            if relation_data.weight is not None:
                set_clauses.append("r.weight = $weight")
                params["weight"] = relation_data.weight

            # 执行更新
            if set_clauses:
                update_query = f"""
                MATCH (e1:__Entity__ {{id: $source}})-[r]->(e2:__Entity__ {{id: $target}})
                WHERE type(r) = $relType
                SET {', '.join(set_clauses)}
                RETURN type(r) as type
                """

                db_manager.execute_query(update_query, params)

        return {"success": True}
    except Exception as e:
        print(e)
        traceback.print_exc()
        return {"success": False, "message": f"更新关系失败: {str(e)}"}


@router.post("/relation/delete", dependencies=[Depends(verify_admin_token)])
def delete_relation(relation_data: RelationDeleteData):
    """
    删除关系

    ✅ 改进：需要管理员权限（X-Admin-Token Header）

    Args:
        relation_data: 关系删除数据

    Returns:
        Dict: 删除结果

    Security:
        - Requires: X-Admin-Token in HTTP Headers
    """
    db_manager = get_db_manager()
    try:
        # 检查关系是否存在
        check_query = """
        MATCH (e1:__Entity__ {id: $source})-[r]->(e2:__Entity__ {id: $target})
        WHERE type(r) = $relType
        RETURN count(r) AS count
        """

        check_result = db_manager.execute_query(
            check_query, {"source": relation_data.source, "target": relation_data.target, "relType": relation_data.type}
        )

        if check_result.empty or check_result.iloc[0]["count"] == 0:
            return {
                "success": False,
                "message": f"关系 '{relation_data.source} -[{relation_data.type}]-> {relation_data.target}' 不存在",
            }

        # 删除关系
        delete_query = """
        MATCH (e1:__Entity__ {id: $source})-[r]->(e2:__Entity__ {id: $target})
        WHERE type(r) = $relType
        DELETE r
        """

        db_manager.execute_query(
            delete_query,
            {"source": relation_data.source, "target": relation_data.target, "relType": relation_data.type},
        )

        return {"success": True}
    except Exception as e:
        print(e)
        traceback.print_exc()
        return {"success": False, "message": f"删除关系失败: {str(e)}"}


@router.get("/communities")
async def list_communities(limit: int = 50, offset: int = 0, min_entities: int = 0):
    """
    获取所有社区列表（按重要性排序）

    Args:
        limit: 返回数量限制
        offset: 偏移量
        min_entities: 最小实体数过滤

    Returns:
        Dict: 社区列表和总数
    """
    try:
        db_manager = get_db_manager()
        driver = db_manager.get_driver()

        # 查询所有社区及统计信息
        query = """
        MATCH (c:__Community__)
        OPTIONAL MATCH (c)<-[:IN_COMMUNITY]-(e:__Entity__)
        WITH c, count(DISTINCT e) AS entity_count
        WHERE entity_count >= $min_entities

        // 获取社区内的关系数量
        OPTIONAL MATCH (c)<-[:IN_COMMUNITY]-(e1:__Entity__)-[r]-(e2:__Entity__)-[:IN_COMMUNITY]->(c)
        WITH c, entity_count, count(DISTINCT r) AS relation_count

        RETURN c.id AS id,
               c.title AS title,
               c.summary AS summary,
               c.rating AS rating,
               entity_count,
               relation_count
        ORDER BY c.rating DESC
        SKIP $offset
        LIMIT $limit
        """

        with driver.session() as session:
            result = session.run(query, min_entities=min_entities, offset=offset, limit=limit)
            communities = []

            for record in result:
                communities.append(
                    {
                        "id": record["id"],
                        "title": record["title"],
                        "summary": record["summary"],
                        "rating": record["rating"] if record["rating"] else 0,
                        "entity_count": record["entity_count"],
                        "relation_count": record["relation_count"],
                    }
                )

        # 获取总数
        count_query = """
        MATCH (c:__Community__)
        OPTIONAL MATCH (c)<-[:IN_COMMUNITY]-(e:__Entity__)
        WITH c, count(DISTINCT e) AS entity_count
        WHERE entity_count >= $min_entities
        RETURN count(c) AS total
        """

        with driver.session() as session:
            result = session.run(count_query, min_entities=min_entities)
            total = result.single()["total"] if result.single() else 0

        return {"communities": communities, "total": total, "limit": limit, "offset": offset}

    except Exception as e:
        print(f"Failed to list communities: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/community/{community_id}/members")
async def get_community_members(community_id: str):
    """
    获取社区成员（实体和关系）

    Args:
        community_id: 社区ID

    Returns:
        Dict: 社区详情、实体列表、关系列表
    """
    try:
        db_manager = get_db_manager()
        driver = db_manager.get_driver()

        # 查询社区信息
        community_query = """
        MATCH (c:__Community__ {id: $community_id})
        RETURN c.id AS id,
               c.title AS title,
               c.summary AS summary,
               c.rating AS rating
        """

        with driver.session() as session:
            result = session.run(community_query, community_id=community_id)
            community_record = result.single()

            if not community_record:
                raise HTTPException(status_code=404, detail="Community not found")

            community = {
                "id": community_record["id"],
                "title": community_record["title"],
                "summary": community_record["summary"],
                "rating": community_record["rating"] if community_record["rating"] else 0,
            }

        # 查询社区实体
        entities_query = """
        MATCH (c:__Community__ {id: $community_id})<-[:IN_COMMUNITY]-(e:__Entity__)
        RETURN e.id AS id,
               e.name AS name,
               e.type AS type,
               e.description AS description
        ORDER BY e.name
        """

        with driver.session() as session:
            result = session.run(entities_query, community_id=community_id)
            entities = []

            for record in result:
                entities.append(
                    {
                        "id": record["id"],
                        "name": record["name"],
                        "type": record["type"],
                        "description": record["description"] if record["description"] else "",
                    }
                )

        # 查询社区内的关系
        relations_query = """
        MATCH (c:__Community__ {id: $community_id})<-[:IN_COMMUNITY]-(e1:__Entity__)-[r]-(e2:__Entity__)-[:IN_COMMUNITY]->(c)
        RETURN DISTINCT e1.id AS source,
               e2.id AS target,
               type(r) AS type,
               r.description AS description,
               r.weight AS weight
        ORDER BY r.weight DESC
        """

        with driver.session() as session:
            result = session.run(relations_query, community_id=community_id)
            relationships = []

            for record in result:
                relationships.append(
                    {
                        "source": record["source"],
                        "target": record["target"],
                        "type": record["type"],
                        "description": record["description"] if record["description"] else "",
                        "weight": record["weight"] if record["weight"] else 0.5,
                    }
                )

        return {
            "community": community,
            "entities": entities,
            "relationships": relationships,
            "entity_count": len(entities),
            "relation_count": len(relationships),
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Failed to get community members: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/entity/{entity_id}/detail")
async def get_entity_detail(entity_id: str):
    """
    获取实体详情（聚合信息）

    返回：
    - 实体基本信息
    - 一跳邻居节点和关系
    - 关联的文本块
    - 所属社区

    Args:
        entity_id: 实体ID

    Returns:
        Dict: 实体详情
    """
    try:
        db_manager = get_db_manager()
        driver = db_manager.get_driver()

        # 查询实体基本信息
        entity_query = """
        MATCH (e:__Entity__ {id: $entity_id})
        RETURN e.id AS id,
               e.name AS name,
               e.type AS type,
               e.description AS description
        """

        with driver.session() as session:
            result = session.run(entity_query, entity_id=entity_id)
            entity_record = result.single()

            if not entity_record:
                raise HTTPException(status_code=404, detail="Entity not found")

            entity = {
                "id": entity_record["id"],
                "name": entity_record["name"],
                "type": entity_record["type"],
                "description": entity_record["description"] if entity_record["description"] else "",
            }

        # 查询一跳邻居和关系
        neighbors_query = """
        MATCH (e:__Entity__ {id: $entity_id})
        OPTIONAL MATCH (e)-[r]-(neighbor:__Entity__)
        RETURN DISTINCT neighbor.id AS neighbor_id,
               neighbor.name AS neighbor_name,
               neighbor.type AS neighbor_type,
               type(r) AS relation_type,
               CASE
                   WHEN startNode(r) = e THEN 'outgoing'
                   ELSE 'incoming'
               END AS direction,
               r.weight AS weight
        ORDER BY r.weight DESC
        """

        with driver.session() as session:
            result = session.run(neighbors_query, entity_id=entity_id)
            neighbors = []

            for record in result:
                if record["neighbor_id"]:  # 排除无邻居的情况
                    neighbors.append(
                        {
                            "id": record["neighbor_id"],
                            "name": record["neighbor_name"],
                            "type": record["neighbor_type"],
                            "relation": record["relation_type"],
                            "direction": record["direction"],
                            "weight": record["weight"] if record["weight"] else 0.5,
                        }
                    )

        # 查询关联的文本块
        chunks_query = """
        MATCH (e:__Entity__ {id: $entity_id})
        OPTIONAL MATCH (e)<-[:MENTIONS]-(c:__Chunk__)
        RETURN c.id AS chunk_id,
               c.fileName AS file_name,
               c.text AS text
        LIMIT 10
        """

        with driver.session() as session:
            result = session.run(chunks_query, entity_id=entity_id)
            chunks = []

            for record in result:
                if record["chunk_id"]:  # 排除无文本块的情况
                    chunks.append(
                        {
                            "chunk_id": record["chunk_id"],
                            "file_name": record["file_name"] if record["file_name"] else "Unknown",
                            "text": record["text"][:200] + "..." if len(record["text"]) > 200 else record["text"],
                        }
                    )

        # 查询所属社区
        community_query = """
        MATCH (e:__Entity__ {id: $entity_id})
        OPTIONAL MATCH (e)-[:IN_COMMUNITY]->(c:__Community__)
        RETURN c.id AS community_id,
               c.title AS community_title,
               c.summary AS community_summary
        """

        with driver.session() as session:
            result = session.run(community_query, entity_id=entity_id)
            community_record = result.single()

            community = None
            if community_record and community_record["community_id"]:
                community = {
                    "id": community_record["community_id"],
                    "title": community_record["community_title"],
                    "summary": community_record["community_summary"],
                }

        return {
            "entity": entity,
            "neighbors": neighbors,
            "chunks": chunks,
            "community": community,
            "neighbor_count": len(neighbors),
            "chunk_count": len(chunks),
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"Failed to get entity detail: {e}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))
