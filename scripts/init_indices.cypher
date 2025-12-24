// ============================================================================
// Neo4j 索引和约束预创建脚本
// ============================================================================
// 用途：
// - 生产环境部署时，关闭 refresh_schema 以避免启动变慢
// - 使用此脚本手动创建所有必要的索引和约束
// - 提升查询性能和数据完整性
//
// 使用方法：
//   # 方式1: 通过 cypher-shell
//   cat scripts/init_indices.cypher | cypher-shell -u neo4j -p 12345678
//
//   # 方式2: 通过 Neo4j Browser
//   复制粘贴本文件内容到 Neo4j Browser 执行
//
//   # 方式3: 通过 Python 脚本
//   python scripts/init_indices.py
// ============================================================================

// ============================================================================
// 1. 文档块（__Chunk__）约束和索引
// ============================================================================

// 唯一约束：chunk ID 必须唯一
CREATE CONSTRAINT chunk_id_unique IF NOT EXISTS
FOR (c:__Chunk__) REQUIRE c.id IS UNIQUE;

// 向量索引：用于相似度搜索（重要！）
// 注意：向量索引需要指定维度，默认 1536 对应 OpenAI text-embedding-3-large
CREATE VECTOR INDEX chunk_embedding_index IF NOT EXISTS
FOR (c:__Chunk__) ON (c.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 1536,
  `vector.similarity_function`: 'cosine'
}};

// 全文索引：用于文本搜索
CREATE FULLTEXT INDEX chunk_text_index IF NOT EXISTS
FOR (c:__Chunk__) ON EACH [c.text];

// 属性索引：加速按 source_id 查询
CREATE INDEX chunk_source_id_index IF NOT EXISTS
FOR (c:__Chunk__) ON (c.source_id);

// ============================================================================
// 2. 实体（__Entity__）约束和索引
// ============================================================================

// 唯一约束：entity ID 必须唯一
CREATE CONSTRAINT entity_id_unique IF NOT EXISTS
FOR (e:__Entity__) REQUIRE e.id IS UNIQUE;

// 向量索引：用于实体向量相似度搜索
CREATE VECTOR INDEX entity_embedding_index IF NOT EXISTS
FOR (e:__Entity__) ON (e.embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 1536,
  `vector.similarity_function`: 'cosine'
}};

// 属性索引：加速按 name 查询（高频查询）
CREATE INDEX entity_name_index IF NOT EXISTS
FOR (e:__Entity__) ON (e.name);

// 属性索引：加速按 type 查询
CREATE INDEX entity_type_index IF NOT EXISTS
FOR (e:__Entity__) ON (e.type);

// 全文索引：用于实体描述搜索
CREATE FULLTEXT INDEX entity_description_index IF NOT EXISTS
FOR (e:__Entity__) ON EACH [e.description];

// ============================================================================
// 3. 社区（__Community__）约束和索引
// ============================================================================

// 唯一约束：community ID 必须唯一
CREATE CONSTRAINT community_id_unique IF NOT EXISTS
FOR (c:__Community__) REQUIRE c.id IS UNIQUE;

// 属性索引：加速按 level 查询（Leiden 层级）
CREATE INDEX community_level_index IF NOT EXISTS
FOR (c:__Community__) ON (c.level);

// 属性索引：加速按 size 查询（社区大小）
CREATE INDEX community_size_index IF NOT EXISTS
FOR (c:__Community__) ON (c.size);

// 向量索引：用于社区摘要相似度搜索
CREATE VECTOR INDEX community_summary_embedding_index IF NOT EXISTS
FOR (c:__Community__) ON (c.summary_embedding)
OPTIONS {indexConfig: {
  `vector.dimensions`: 1536,
  `vector.similarity_function`: 'cosine'
}};

// ============================================================================
// 4. 文档（__Document__）约束和索引
// ============================================================================

// 唯一约束：document ID 必须唯一
CREATE CONSTRAINT document_id_unique IF NOT EXISTS
FOR (d:__Document__) REQUIRE d.id IS UNIQUE;

// 属性索引：加速按 path 查询
CREATE INDEX document_path_index IF NOT EXISTS
FOR (d:__Document__) ON (d.path);

// 属性索引：加速按 extension 查询
CREATE INDEX document_extension_index IF NOT EXISTS
FOR (d:__Document__) ON (d.extension);

// ============================================================================
// 5. 关系（Relationship）索引
// ============================================================================

// 关系类型索引：加速按关系类型过滤
// 注意：Neo4j 5.x 中关系类型本身就是索引，但可以为关系属性创建索引

// 为 PART_OF 关系的 weight 属性创建索引（如果存在）
// CREATE INDEX rel_part_of_weight IF NOT EXISTS
// FOR ()-[r:PART_OF]-() ON (r.weight);

// 为所有关系的 strength 属性创建索引
// CREATE INDEX rel_strength_index IF NOT EXISTS
// FOR ()-[r]-() ON (r.strength);

// ============================================================================
// 6. 动态实体类型的特殊索引（可选）
// ============================================================================

// 如果系统使用动态实体类型（如 "学生类型", "奖学金类型"），
// 可以为这些类型创建专门的索引：

// 示例：为 "学生类型" 实体创建索引
// CREATE INDEX entity_student_name IF NOT EXISTS
// FOR (e:学生类型) ON (e.name);

// ============================================================================
// 7. 图算法相关索引（GDS）
// ============================================================================

// 如果使用 Graph Data Science 库进行社区检测，
// 可能需要为图投影创建特定的索引：

// 示例：为 PageRank 结果创建索引
// CREATE INDEX entity_pagerank IF NOT EXISTS
// FOR (e:__Entity__) ON (e.pageRank);

// ============================================================================
// 验证索引创建
// ============================================================================

// 查看所有索引和约束（执行完后运行此命令）
// SHOW INDEXES;
// SHOW CONSTRAINTS;

// ============================================================================
// 性能建议
// ============================================================================

// 1. 向量索引：
//    - 维度必须与 embedding 模型匹配
//    - cosine 相似度适用于大多数场景
//    - 如果使用其他模型，修改 vector.dimensions

// 2. 全文索引：
//    - 适用于模糊搜索和关键词搜索
//    - 支持中文分词（取决于 Neo4j 配置）

// 3. 属性索引：
//    - 仅为高频查询字段创建索引
//    - 过多索引会降低写入性能

// 4. 唯一约束：
//    - 自动创建索引
//    - 保证数据完整性

// ============================================================================
// 索引维护
// ============================================================================

// 删除索引（如果需要）
// DROP INDEX chunk_embedding_index IF EXISTS;

// 重建索引（如果损坏）
// DROP INDEX chunk_embedding_index IF EXISTS;
// CREATE VECTOR INDEX chunk_embedding_index ...;

// 查看索引使用情况（需要 APOC）
// CALL apoc.meta.stats() YIELD nodeCount, relCount, labels, relTypesCount;

// ============================================================================
// 完成
// ============================================================================
