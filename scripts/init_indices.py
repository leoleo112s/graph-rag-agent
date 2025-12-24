#!/usr/bin/env python3
"""
Neo4j 索引和约束初始化脚本

用途：
- 自动创建生产环境所需的所有索引和约束
- 避免在应用启动时执行 refresh_schema（提升启动速度）
- 支持幂等执行（可重复运行）

使用方法：
    # 使用默认配置（从环境变量读取）
    python scripts/init_indices.py

    # 指定连接参数
    python scripts/init_indices.py --uri neo4j://localhost:7687 --user neo4j --password 12345678

    # 仅检查索引（不创建）
    python scripts/init_indices.py --check-only

    # 删除所有索引（危险操作！）
    python scripts/init_indices.py --drop-all
"""

import os
import sys
import argparse
from pathlib import Path
from neo4j import GraphDatabase
from typing import List, Dict, Any

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


class IndexManager:
    """Neo4j 索引管理器"""

    def __init__(self, uri: str, user: str, password: str):
        """
        初始化连接

        Args:
            uri: Neo4j URI (如 neo4j://localhost:7687)
            user: 用户名
            password: 密码
        """
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.vector_dim = int(os.getenv("EMBEDDING_DIM", "1536"))

    def close(self):
        """关闭连接"""
        self.driver.close()

    def execute_query(self, query: str) -> List[Dict[str, Any]]:
        """执行 Cypher 查询"""
        with self.driver.session() as session:
            result = session.run(query)
            return [record.data() for record in result]

    def create_constraints(self):
        """创建约束（自动创建索引）"""
        constraints = [
            # Chunk 唯一约束
            "CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS FOR (c:__Chunk__) REQUIRE c.id IS UNIQUE",

            # Entity 唯一约束
            "CREATE CONSTRAINT entity_id_unique IF NOT EXISTS FOR (e:__Entity__) REQUIRE e.id IS UNIQUE",

            # Community 唯一约束
            "CREATE CONSTRAINT community_id_unique IF NOT EXISTS FOR (c:__Community__) REQUIRE c.id IS UNIQUE",

            # Document 唯一约束
            "CREATE CONSTRAINT document_id_unique IF NOT EXISTS FOR (d:__Document__) REQUIRE d.id IS UNIQUE",
        ]

        print("📋 创建约束...")
        for constraint in constraints:
            try:
                self.execute_query(constraint)
                print(f"  ✅ {constraint.split()[2]}")
            except Exception as e:
                print(f"  ⚠️  {constraint.split()[2]}: {e}")

    def create_vector_indices(self):
        """创建向量索引"""
        vector_indices = [
            # Chunk embedding 索引
            f"""CREATE VECTOR INDEX chunk_embedding_index IF NOT EXISTS
                FOR (c:__Chunk__) ON (c.embedding)
                OPTIONS {{indexConfig: {{
                  `vector.dimensions`: {self.vector_dim},
                  `vector.similarity_function`: 'cosine'
                }}}}""",

            # Entity embedding 索引
            f"""CREATE VECTOR INDEX entity_embedding_index IF NOT EXISTS
                FOR (e:__Entity__) ON (e.embedding)
                OPTIONS {{indexConfig: {{
                  `vector.dimensions`: {self.vector_dim},
                  `vector.similarity_function`: 'cosine'
                }}}}""",

            # Community summary embedding 索引
            f"""CREATE VECTOR INDEX community_summary_embedding_index IF NOT EXISTS
                FOR (c:__Community__) ON (c.summary_embedding)
                OPTIONS {{indexConfig: {{
                  `vector.dimensions`: {self.vector_dim},
                  `vector.similarity_function`: 'cosine'
                }}}}""",
        ]

        print("\n🔍 创建向量索引...")
        for index in vector_indices:
            try:
                self.execute_query(index)
                index_name = index.split()[3]
                print(f"  ✅ {index_name}")
            except Exception as e:
                print(f"  ⚠️  向量索引创建失败: {e}")

    def create_property_indices(self):
        """创建属性索引"""
        property_indices = [
            # Chunk 索引
            "CREATE INDEX chunk_source_id_index IF NOT EXISTS FOR (c:__Chunk__) ON (c.source_id)",

            # Entity 索引
            "CREATE INDEX entity_name_index IF NOT EXISTS FOR (e:__Entity__) ON (e.name)",
            "CREATE INDEX entity_type_index IF NOT EXISTS FOR (e:__Entity__) ON (e.type)",

            # Community 索引
            "CREATE INDEX community_level_index IF NOT EXISTS FOR (c:__Community__) ON (c.level)",
            "CREATE INDEX community_size_index IF NOT EXISTS FOR (c:__Community__) ON (c.size)",

            # Document 索引
            "CREATE INDEX document_path_index IF NOT EXISTS FOR (d:__Document__) ON (d.path)",
            "CREATE INDEX document_extension_index IF NOT EXISTS FOR (d:__Document__) ON (d.extension)",
        ]

        print("\n📊 创建属性索引...")
        for index in property_indices:
            try:
                self.execute_query(index)
                index_name = index.split()[2]
                print(f"  ✅ {index_name}")
            except Exception as e:
                print(f"  ⚠️  {index.split()[2]}: {e}")

    def create_fulltext_indices(self):
        """创建全文索引"""
        fulltext_indices = [
            "CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS FOR (c:__Chunk__) ON EACH [c.text]",
            "CREATE FULLTEXT INDEX entity_description_index IF NOT EXISTS FOR (e:__Entity__) ON EACH [e.description]",
        ]

        print("\n📝 创建全文索引...")
        for index in fulltext_indices:
            try:
                self.execute_query(index)
                index_name = index.split()[3]
                print(f"  ✅ {index_name}")
            except Exception as e:
                print(f"  ⚠️  {index.split()[3]}: {e}")

    def show_indices(self):
        """显示所有索引和约束"""
        print("\n" + "=" * 80)
        print("📋 当前索引和约束")
        print("=" * 80)

        # 显示约束
        constraints = self.execute_query("SHOW CONSTRAINTS")
        print(f"\n约束数量: {len(constraints)}")
        for c in constraints:
            print(f"  - {c.get('name', 'N/A')}: {c.get('type', 'N/A')}")

        # 显示索引
        indices = self.execute_query("SHOW INDEXES")
        print(f"\n索引数量: {len(indices)}")
        for i in indices:
            print(f"  - {i.get('name', 'N/A')}: {i.get('type', 'N/A')} ({i.get('state', 'N/A')})")

    def drop_all_indices(self):
        """删除所有索引和约束（危险操作！）"""
        print("\n⚠️  警告：准备删除所有索引和约束...")
        confirm = input("确定要继续吗？(yes/no): ")
        if confirm.lower() != "yes":
            print("已取消操作")
            return

        # 删除所有索引（除了约束自动创建的）
        indices = self.execute_query("SHOW INDEXES")
        for idx in indices:
            name = idx.get("name")
            if name and not name.endswith("_unique"):
                try:
                    self.execute_query(f"DROP INDEX {name} IF EXISTS")
                    print(f"  ✅ 已删除索引: {name}")
                except Exception as e:
                    print(f"  ⚠️  删除索引失败 {name}: {e}")

        # 删除所有约束
        constraints = self.execute_query("SHOW CONSTRAINTS")
        for c in constraints:
            name = c.get("name")
            if name:
                try:
                    self.execute_query(f"DROP CONSTRAINT {name} IF EXISTS")
                    print(f"  ✅ 已删除约束: {name}")
                except Exception as e:
                    print(f"  ⚠️  删除约束失败 {name}: {e}")

    def create_all(self):
        """创建所有索引和约束"""
        self.create_constraints()
        self.create_vector_indices()
        self.create_property_indices()
        self.create_fulltext_indices()


def main():
    parser = argparse.ArgumentParser(description="Neo4j 索引和约束管理工具")
    parser.add_argument("--uri", default=os.getenv("NEO4J_URI", "neo4j://localhost:7687"),
                        help="Neo4j URI (默认: neo4j://localhost:7687)")
    parser.add_argument("--user", default=os.getenv("NEO4J_USERNAME", "neo4j"),
                        help="Neo4j 用户名 (默认: neo4j)")
    parser.add_argument("--password", default=os.getenv("NEO4J_PASSWORD", "12345678"),
                        help="Neo4j 密码 (默认: 12345678)")
    parser.add_argument("--check-only", action="store_true",
                        help="仅检查现有索引，不创建")
    parser.add_argument("--drop-all", action="store_true",
                        help="删除所有索引和约束（危险操作！）")

    args = parser.parse_args()

    print("=" * 80)
    print("Neo4j 索引管理工具")
    print("=" * 80)
    print(f"连接: {args.uri}")
    print(f"用户: {args.user}")

    manager = IndexManager(args.uri, args.user, args.password)

    try:
        if args.drop_all:
            manager.drop_all_indices()
        elif args.check_only:
            manager.show_indices()
        else:
            manager.create_all()
            manager.show_indices()

        print("\n✅ 完成！")

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        sys.exit(1)

    finally:
        manager.close()


if __name__ == "__main__":
    main()
