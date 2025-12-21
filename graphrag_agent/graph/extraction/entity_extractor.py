"""
实体关系提取器（最终合并版）
= production 抽取质量 + Schema-aware（GraphConfig/Domain 路由）=

保留/增强：
- JSON 输出解析（safe_json_loads）
- 实体三板斧：normalize + type 白名单 + frequency >= 2 + similarity 去重
- 关系白名单 + source/target 存在校验 + 去重
- 兼容旧 GraphWriter 的输出协议（_build_compatible_result）
- 并发 + cache + retry

新增：
- 若 extractor_factory 走"动态配置模式"，会在 extractor 上挂：
  - extractor.is_dynamic = True
  - extractor.prompt_builder = DynamicPromptBuilder(config)
- 本文件会优先使用 prompt_builder.config 做 Domain routing
- 每个文件选定 domain 后：
  - entity_types / relationship_types 会收敛到该 domain schema
  - 抽取/后处理都严格使用该 domain 白名单

注意：
- 如果没有动态配置（传统模式），则退化为使用传入的 entity_types / relationship_types
"""

import os
import time
import pickle
import json
import re
import concurrent.futures
from typing import List, Tuple, Optional, Dict, Any
from collections import Counter
from difflib import SequenceMatcher

from langchain.prompts import (
    ChatPromptTemplate,
    HumanMessagePromptTemplate,
    MessagesPlaceholder,
    SystemMessagePromptTemplate,
)

from graphrag_agent.graph.core import retry, generate_hash
from graphrag_agent.config.settings import MAX_WORKERS as DEFAULT_MAX_WORKERS, BATCH_SIZE as DEFAULT_BATCH_SIZE


# =========================
# 生产级默认约束（传统模式兜底）
# =========================

DEFAULT_ALLOWED_ENTITY_TYPES = {
    "POLICY",       # 制度、政策、办法、条例
    "PROCESS",      # 流程、步骤、阶段
    "CONDITION",    # 条件、资格、标准
    "ORGANIZATION", # 组织、机构、部门
    "DOCUMENT"      # 正式文件名称
}

DEFAULT_ALLOWED_RELATION_TYPES = {
    "HAS_CONDITION",
    "HAS_STEP",
    "ISSUED_BY",
    "APPLIES_TO",
    "PART_OF",
    "REQUIRES"
}

DEFAULT_MIN_ENTITY_FREQUENCY = 2
DEFAULT_NAME_SIMILARITY_THRESHOLD = 0.85


# =========================
# 工具函数（生产级）
# =========================

def normalize_entity_name(name: str) -> str:
    if not name:
        return ""
    return (
        name.strip()
        .replace(" ", "")
        .replace("（", "(")
        .replace("）", ")")
        .replace("【", "[")
        .replace("】", "]")
    )

def is_similar(a: str, b: str, threshold: float) -> bool:
    return SequenceMatcher(None, a, b).ratio() >= threshold

def _extract_json_dict(text: str) -> Optional[Dict[str, Any]]:
    """
    从 LLM 输出中提取 JSON dict。兼容 ```json fence、前后解释文字。

    尝试策略：
    1. 去除 ```json ... ``` fence
    2. 截取第一个 {...}，避免前后有解释
    3. 解析为 dict
    """
    if not text:
        return None

    t = text.strip()

    # 去掉 ```json ... ``` / ``` ... ```
    t = re.sub(r"^\s*```(?:json)?\s*", "", t, flags=re.IGNORECASE)
    t = re.sub(r"\s*```\s*$", "", t)

    # 截取第一个 {...}，避免前后有解释
    m = re.search(r"\{.*\}", t, flags=re.DOTALL)
    if not m:
        return None
    t = m.group(0)

    try:
        obj = json.loads(t)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


# =========================
# 后处理核心逻辑（production + 可注入白名单）
# =========================

def post_process_entities(
    raw_entities: List[Dict[str, Any]],
    allowed_entity_types: set,
    min_freq: int,
    similarity_threshold: float
) -> List[Dict[str, Any]]:
    if not raw_entities:
        return []

    # normalize
    for e in raw_entities:
        if "name" in e:
            e["name"] = normalize_entity_name(e.get("name", ""))

    # type filter
    entities = [
        e for e in raw_entities
        if e.get("type") in allowed_entity_types and e.get("name")
    ]

    # frequency filter
    freq = Counter(e["name"] for e in entities)
    entities = [e for e in entities if freq[e["name"]] >= min_freq]

    # similarity dedup
    deduped = []
    for e in entities:
        if not any(is_similar(e["name"], u["name"], similarity_threshold) for u in deduped):
            deduped.append(e)

    return deduped


def post_process_relations(
    raw_relations: List[Dict[str, Any]],
    entities: List[Dict[str, Any]],
    allowed_relation_types: set,
    similarity_threshold: float
) -> List[Dict[str, Any]]:
    if not raw_relations or not entities:
        return []

    entity_names = {normalize_entity_name(e["name"]) for e in entities}
    cleaned = []
    seen = set()

    for r in raw_relations:
        src = normalize_entity_name(r.get("source", ""))
        tgt = normalize_entity_name(r.get("target", ""))
        r_type = r.get("type")

        if (
            src in entity_names and
            tgt in entity_names and
            r_type in allowed_relation_types
        ):
            key = (src, tgt, r_type)
            if key not in seen:
                cleaned.append({
                    "source": src,
                    "target": tgt,
                    "type": r_type
                })
                seen.add(key)

    return cleaned


# =========================
# Domain routing（Schema-aware）
# =========================

DOMAIN_ROUTER_SYSTEM = """
你是一个文档分域分类器。给你多个候选领域，每个领域有 trigger_condition（自然语言规则）。
请判断该文档最符合哪个领域。只输出领域名 domain_name，不要解释。
如果都不符合，输出 NONE。
"""

DOMAIN_ROUTER_HUMAN = """
候选领域：
{candidates}

文档内容（可能很长，已截断）：
{doc_preview}
"""


class EntityRelationExtractor:
    """
    最终合并版实体关系提取器
    """

    def __init__(
        self,
        llm,
        system_template: str,
        human_template: str,
        entity_types: List[str],
        relationship_types: List[str],
        cache_dir: str = "./cache/graph",
        max_workers: int = 4,
        batch_size: int = 5
    ):
        self.llm = llm

        # 传统模式传入的类型（作为 fallback）
        self.entity_types = entity_types or []
        self.relationship_types = relationship_types or []

        # 动态模式会由 extractor_factory 赋值：
        # - self.is_dynamic = True
        # - self.prompt_builder = DynamicPromptBuilder(config)
        self.is_dynamic = getattr(self, "is_dynamic", False)
        self.prompt_builder = getattr(self, "prompt_builder", None)

        self.chat_history = []

        # 旧协议分隔符（GraphWriter 兼容）
        self.tuple_delimiter = " : "
        self.record_delimiter = "\n"
        self.completion_delimiter = "\n\n"

        # Prompt chain（抽取）
        system_message_prompt = SystemMessagePromptTemplate.from_template(system_template)
        human_message_prompt = HumanMessagePromptTemplate.from_template(human_template)

        self.chat_prompt = ChatPromptTemplate.from_messages([
            system_message_prompt,
            MessagesPlaceholder("chat_history"),
            human_message_prompt
        ])
        self.chain = self.chat_prompt | self.llm

        # Router chain（按文件挑 domain）
        router_sys = SystemMessagePromptTemplate.from_template(DOMAIN_ROUTER_SYSTEM)
        router_human = HumanMessagePromptTemplate.from_template(DOMAIN_ROUTER_HUMAN)
        self.router_prompt = ChatPromptTemplate.from_messages([router_sys, router_human])
        self.router_chain = self.router_prompt | self.llm

        # cache
        self.cache_dir = cache_dir
        self.enable_cache = True
        os.makedirs(cache_dir, exist_ok=True)

        # concurrency
        self.max_workers = max_workers or DEFAULT_MAX_WORKERS
        self.batch_size = batch_size or DEFAULT_BATCH_SIZE

        # cache stats
        self.cache_hits = 0
        self.cache_misses = 0

    # -------------------------
    # cache helpers
    # -------------------------
    def _generate_cache_key(self, text: str) -> str:
        return generate_hash(text)

    def _cache_path(self, cache_key: str) -> str:
        return os.path.join(self.cache_dir, f"{cache_key}.pkl")

    def _save_to_cache(self, cache_key: str, result: Any) -> None:
        if not self.enable_cache:
            return
        try:
            with open(self._cache_path(cache_key), "wb") as f:
                pickle.dump(result, f)
        except Exception as e:
            print(f"缓存保存错误: {e}")

    def _load_from_cache(self, cache_key: str) -> Optional[Any]:
        if not self.enable_cache:
            return None
        p = self._cache_path(cache_key)
        if os.path.exists(p):
            try:
                with open(p, "rb") as f:
                    self.cache_hits += 1
                    return pickle.load(f)
            except Exception as e:
                print(f"缓存加载错误: {e}")
        self.cache_misses += 1
        return None

    # -------------------------
    # schema helpers
    # -------------------------
    def _get_graph_config(self):
        """
        动态模式下，prompt_builder.config 就是 GraphConfig（你 extractor_factory 已经 load storage 并构建了它）
        """
        if self.prompt_builder is not None and hasattr(self.prompt_builder, "config"):
            return self.prompt_builder.config
        return None

    def _route_domain_for_document(self, filename: str, content: str) -> Optional[str]:
        """
        使用 GraphConfig.domain_definitions 的 trigger_condition 做 domain routing
        """
        config = self._get_graph_config()
        if config is None or not getattr(config, "domain_definitions", None):
            return None

        # cache（按文件+内容预览）
        preview = (content or "")[:2000]
        doc_key = self._generate_cache_key(f"domain::{filename}::{preview}")
        cached = self._load_from_cache(doc_key)
        if cached is not None:
            # cached 可能是 "" 代表 NONE
            return cached or None

        candidates = []
        for d in config.domain_definitions:
            candidates.append(f"- {d.domain_name}: {d.trigger_condition}")

        resp = self.router_chain.invoke({
            "candidates": "\n".join(candidates),
            "doc_preview": preview
        })

        domain = (resp.content or "").strip()
        if not domain or domain.upper() == "NONE":
            domain = None

        self._save_to_cache(doc_key, domain or "")
        return domain

    def _schema_for_domain(self, domain_name: Optional[str]) -> Tuple[set, set]:
        """
        返回 domain 对应的实体/关系白名单
        """
        config = self._get_graph_config()
        default_schema = None
        if config and getattr(config, "domain_definitions", None):
            default_schema = config.domain_definitions[0] if config.domain_definitions else None

        if config is None:
            return (
                set(self.entity_types) or DEFAULT_ALLOWED_ENTITY_TYPES,
                set(self.relationship_types) or DEFAULT_ALLOWED_RELATION_TYPES,
            )

        if not domain_name and default_schema:
            ent = set(default_schema.schema.entities or [])
            rel = set(default_schema.schema.relations or [])
            if not ent:
                ent = DEFAULT_ALLOWED_ENTITY_TYPES
            if not rel:
                rel = DEFAULT_ALLOWED_RELATION_TYPES
            return ent, rel

        for d in config.domain_definitions:
            if d.domain_name == domain_name:
                ent = set(d.schema.entities or [])
                rel = set(d.schema.relations or [])
                # 如果 schema 为空，兜底用默认
                if not ent:
                    ent = DEFAULT_ALLOWED_ENTITY_TYPES
                if not rel:
                    rel = DEFAULT_ALLOWED_RELATION_TYPES
                return ent, rel

        if default_schema:
            ent = set(default_schema.schema.entities or [])
            rel = set(default_schema.schema.relations or [])
            if not ent:
                ent = DEFAULT_ALLOWED_ENTITY_TYPES
            if not rel:
                rel = DEFAULT_ALLOWED_RELATION_TYPES
            return ent, rel

        return (
            set(self.entity_types) or DEFAULT_ALLOWED_ENTITY_TYPES,
            set(self.relationship_types) or DEFAULT_ALLOWED_RELATION_TYPES,
        )

    # -------------------------
    # output builder（兼容 GraphWriter）
    # -------------------------
    def _build_compatible_result(self, entities: List[Dict[str, Any]], relations: List[Dict[str, Any]]) -> str:
        """
        兼容旧格式：
        ("entity" : <name> : <type> : <desc>)
        ("relationship" : <src> : <tgt> : <type> : <desc> : <strength>)
        """
        lines = []

        for e in entities:
            name = e.get("name", "")
            e_type = e.get("type", "")
            desc = e.get("description", name)
            lines.append(f'("entity"{self.tuple_delimiter}{name}{self.tuple_delimiter}{e_type}{self.tuple_delimiter}{desc})')

        for r in relations:
            src = r.get("source", "")
            tgt = r.get("target", "")
            r_type = r.get("type", "")
            desc = r.get("description", f"{src} {r_type} {tgt}")
            strength = r.get("strength", 8)
            lines.append(
                f'("relationship"{self.tuple_delimiter}{src}{self.tuple_delimiter}{tgt}{self.tuple_delimiter}{r_type}'
                f'{self.tuple_delimiter}{desc}{self.tuple_delimiter}{strength})'
            )

        return self.record_delimiter.join(lines) + self.completion_delimiter

    # -------------------------
    # chunk processing
    # -------------------------
    @retry(times=3, exceptions=(Exception,), delay=1.0)
    def _process_single_chunk(
        self,
        input_text: str,
        allowed_entity_types: set,
        allowed_relation_types: set
    ) -> Dict[str, Any]:
        """
        单 chunk 抽取：LLM -> JSON -> 后处理 -> 返回 dict

        Returns:
            Dict: 包含 entities, relations, relationships 等字段的字典
        """
        cache_key = self._generate_cache_key(
            f"{sorted(list(allowed_entity_types))}|{sorted(list(allowed_relation_types))}|{input_text}"
        )
        cached = self._load_from_cache(cache_key)
        if cached:
            # 确保缓存结果是dict
            if isinstance(cached, dict):
                return cached
            # 兼容旧的字符串缓存格式
            print(f"⚠️ 缓存格式为字符串，返回空结果")
            return {"entities": [], "relations": [], "relationships": []}

        # 1) 调用 LLM（注意：system_template/human_template 可能会用到 entity_types/relationship_types 占位符）
        resp = self.chain.invoke({
            "chat_history": self.chat_history,
            "entity_types": list(allowed_entity_types),
            "relationship_types": list(allowed_relation_types),
            "tuple_delimiter": self.tuple_delimiter,
            "record_delimiter": self.record_delimiter,
            "completion_delimiter": self.completion_delimiter,
            "input_text": input_text
        })

        # 从 AIMessage 获取内容
        raw = getattr(resp, "content", resp)  # 兼容 AIMessage / str

        # 初始化默认结果
        result = {
            "entities": [],
            "relations": [],
            "relationships": [],
            "domains": [],
            "bridges": []
        }

        try:
            # 解析 JSON（使用强化版解析器）
            parsed = _extract_json_dict(raw)
            if parsed is None:
                # 打印原始内容前 300 字符用于调试
                print(f"⚠️ JSON parse failed, raw head: {repr(str(raw)[:300])}")
                parsed = {
                    "entities": [],
                    "relations": [],
                    "relationships": [],
                    "domains": [],
                    "bridges": [],
                    "raw": str(raw)
                }

            raw_entities = parsed.get("entities", []) or []
            raw_relations = parsed.get("relations", []) or []
            # 兼容 relationships 字段
            if not raw_relations:
                raw_relations = parsed.get("relationships", []) or []

            # 2) 后处理（白名单来自 domain schema）
            entities = post_process_entities(
                raw_entities,
                allowed_entity_types=allowed_entity_types,
                min_freq=DEFAULT_MIN_ENTITY_FREQUENCY,
                similarity_threshold=DEFAULT_NAME_SIMILARITY_THRESHOLD
            )

            relations = post_process_relations(
                raw_relations,
                entities,
                allowed_relation_types=allowed_relation_types,
                similarity_threshold=DEFAULT_NAME_SIMILARITY_THRESHOLD
            )

            # 3) 构建统一的 dict 结果
            result = {
                "entities": entities,
                "relations": relations,
                "relationships": relations,  # 兼容字段
                "domains": parsed.get("domains", []),
                "bridges": parsed.get("bridges", []),
                "raw": str(raw)  # 保留原始输出用于调试
            }

        except Exception as e:
            print(f"⚠️ 后处理失败，返回空结果: {e}")

        self._save_to_cache(cache_key, result)
        return result

    def process_chunks(self, file_contents: List[Tuple], progress_callback=None) -> List[Tuple]:
        """
        file_contents: [ [filename, content, chunks], ... ]
        append: results list -> file_content[3]
        """
        t0 = time.time()
        chunk_index = 0
        total_chunks = sum(len(fc[2]) for fc in file_contents)

        # 文件级 domain routing & schema 准备
        file_schema_map: Dict[str, Tuple[set, set]] = {}
        for fc in file_contents:
            filename, content = fc[0], fc[1]
            domain = self._route_domain_for_document(filename, content or "")
            ent_types, rel_types = self._schema_for_domain(domain)
            file_schema_map[filename] = (ent_types, rel_types)

        for i, fc in enumerate(file_contents):
            filename = fc[0]
            chunks = fc[2]
            allowed_entity_types, allowed_relation_types = file_schema_map.get(
                filename,
                (set(self.entity_types) or DEFAULT_ALLOWED_ENTITY_TYPES, set(self.relationship_types) or DEFAULT_ALLOWED_RELATION_TYPES)
            )

            # 预检查缓存（按 chunk）
            chunk_texts = [''.join(chunk) for chunk in chunks]
            cache_keys = [
                self._generate_cache_key(
                    f"{sorted(list(allowed_entity_types))}|{sorted(list(allowed_relation_types))}|{txt}"
                )
                for txt in chunk_texts
            ]
            cached_results = {k: self._load_from_cache(k) for k in cache_keys}
            non_cached_indices = [idx for idx, k in enumerate(cache_keys) if cached_results[k] is None]

            if non_cached_indices:
                with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                    futures = {
                        executor.submit(
                            self._process_single_chunk,
                            chunk_texts[idx],
                            allowed_entity_types,
                            allowed_relation_types
                        ): idx
                        for idx in non_cached_indices
                    }

                    for fut in concurrent.futures.as_completed(futures):
                        idx = futures[fut]
                        try:
                            res = fut.result()
                            cached_results[cache_keys[idx]] = res
                            self._save_to_cache(cache_keys[idx], res)
                        except Exception as e:
                            print(f'Chunk {idx} 处理异常: {e}')
                            cached_results[cache_keys[idx]] = "" + self.completion_delimiter

                        if progress_callback:
                            progress_callback(chunk_index)
                        chunk_index += 1

            ordered = [cached_results[k] for k in cache_keys]
            fc.append(ordered)

            cache_ratio = self.cache_hits / (self.cache_hits + self.cache_misses) * 100 if (self.cache_hits + self.cache_misses) else 0
            print(f"文件 {i+1}/{len(file_contents)} 处理完成, domain-schema启用={self._get_graph_config() is not None}, 缓存命中率: {cache_ratio:.1f}%")

        dt = time.time() - t0
        print(f"所有chunks处理完成, 总耗时: {dt:.2f}秒, 平均每chunk: {dt/max(total_chunks,1):.2f}秒")
        return file_contents

    def _extract_one_chunk(self, chunk_text: str, allowed_entity_types: set, allowed_relation_types: set) -> Dict[str, Any]:
        """
        包装单 chunk 抽取逻辑，供 batch 调用。

        Args:
            chunk_text: chunk 文本
            allowed_entity_types: 允许的实体类型集合
            allowed_relation_types: 允许的关系类型集合

        Returns:
            Dict: 包含 entities, relations, relationships 等字段的字典
        """
        return self._process_single_chunk(chunk_text, allowed_entity_types, allowed_relation_types)

    def process_chunks_batch(self, file_contents: List[Tuple], progress_callback=None) -> List[Tuple]:
        """
        Batch 版：保证 chunk 与 LLM 抽取结果严格对齐。

        Args:
            file_contents: [ [filename, content, chunks], ... ]

        Returns:
            [(fname, orig_chunks, proc_chunks), ...]
              - orig_chunks: List[str]  # 每个 chunk 的原文
              - proc_chunks: List[Dict]  # 每个 chunk 的抽取结果
        """

        def _pick_chunks_from_fc(fc):
            """
            从 fc 中提取 filename 和 chunk 文本列表。
            fc 可能是：
              - dict: {"filename": ..., "chunks": [...]}
              - tuple/list: [fname, content, chunks] 或其他变体
            """
            if isinstance(fc, dict):
                fname = fc.get("filename") or fc.get("fname") or fc.get("file") or ""
                chunks = fc.get("chunks") or fc.get("orig_chunks") or []
                return fname, chunks

            fname = fc[0] if len(fc) > 0 else ""

            # ✅ 优先找"像 chunk 列表"的那个字段：list 且元素是 str/list 且每个元素长度明显>1
            for idx in range(1, len(fc)):
                v = fc[idx]
                if isinstance(v, list) and v:
                    # chunk 可能是 str 或 list（带分隔符的）
                    if all(isinstance(x, str) for x in v):
                        avg_len = sum(len(x) for x in v) / max(1, len(v))
                        if avg_len >= 20:   # chunk 一般不会是单字
                            return fname, v
                    elif all(isinstance(x, list) for x in v):
                        # chunks 是 [[text, sep1, sep2], ...] 这种格式
                        # 提取每个 chunk 的文本部分
                        chunk_texts = []
                        for chunk_item in v:
                            if isinstance(chunk_item, list) and len(chunk_item) > 0:
                                # 取第一个元素作为文本，或者拼接所有元素
                                text = ''.join(chunk_item) if all(isinstance(x, str) for x in chunk_item) else str(chunk_item[0])
                                chunk_texts.append(text)
                            else:
                                chunk_texts.append(str(chunk_item))
                        if chunk_texts:
                            return fname, chunk_texts

            # 如果没找到，返回空
            return fname, []

        # 1) 提取每个文件的 chunks
        normalized = []
        for fc in file_contents:
            fname, chunks = _pick_chunks_from_fc(fc)
            normalized.append((fname, chunks))

        bad = [fn for fn, ch in normalized if not ch]
        if bad:
            raise ValueError(f"process_chunks_batch: 未能从输入中解析出 chunk 列表，出问题的文件: {bad[:5]} (共{len(bad)}个)")

        # 2) 准备每个文件的 schema
        file_schema_map: Dict[str, Tuple[set, set]] = {}
        for fc in file_contents:
            filename = fc[0]
            content = fc[1] if len(fc) > 1 else ""
            domain = self._route_domain_for_document(filename, content or "")
            ent_types, rel_types = self._schema_for_domain(domain)
            file_schema_map[filename] = (ent_types, rel_types)

        # 3) 扁平化所有 chunks，记录每个文件的范围
        flat_chunks = []
        flat_schemas = []
        spans = []   # (fname, start, end)
        cursor = 0

        for fname, chunks in normalized:
            start = cursor
            allowed_entity_types, allowed_relation_types = file_schema_map.get(
                fname,
                (set(self.entity_types) or DEFAULT_ALLOWED_ENTITY_TYPES,
                 set(self.relationship_types) or DEFAULT_ALLOWED_RELATION_TYPES)
            )

            for chunk_text in chunks:
                flat_chunks.append(chunk_text)
                flat_schemas.append((allowed_entity_types, allowed_relation_types))

            cursor += len(chunks)
            spans.append((fname, start, cursor))

        # 4) 批量调用 LLM 抽取（使用并发）
        print(f"开始批量抽取 {len(flat_chunks)} 个 chunks...")
        llm_results = [None] * len(flat_chunks)

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(
                    self._extract_one_chunk,
                    flat_chunks[idx],
                    flat_schemas[idx][0],
                    flat_schemas[idx][1]
                ): idx
                for idx in range(len(flat_chunks))
            }

            completed = 0
            for fut in concurrent.futures.as_completed(futures):
                idx = futures[fut]
                try:
                    res = fut.result()
                    llm_results[idx] = res
                except Exception as e:
                    print(f'Chunk {idx} 处理异常: {e}')
                    llm_results[idx] = {
                        "entities": [],
                        "relations": [],
                        "relationships": [],
                        "domains": [],
                        "bridges": [],
                        "raw": ""
                    }

                completed += 1
                if progress_callback:
                    progress_callback(completed)

        if None in llm_results:
            raise ValueError(f"process_chunks_batch: 部分 chunk 抽取失败")

        print(f"批量抽取完成，共 {len(llm_results)} 个结果")

        # 5) 切片回填到每个文件，保证对齐
        processed_file_contents = []
        for fname, start, end in spans:
            orig_chunks = flat_chunks[start:end]
            proc_chunks = llm_results[start:end]
            processed_file_contents.append((fname, orig_chunks, proc_chunks))

        return processed_file_contents
