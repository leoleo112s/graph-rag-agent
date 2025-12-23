#!/usr/bin/env python3
"""
缓存迁移脚本 - 将旧格式的实体抽取缓存转换为新格式

用途：
- 遍历所有缓存文件（session cache 和 global cache）
- 检测旧格式（字符串 / 元组）
- 转换为新格式（JSON Dict - ExtractionResult）
- 重新保存

使用方法：
    python scripts/migrate_extraction_cache.py
    python scripts/migrate_extraction_cache.py --dry-run  # 仅检测，不修改
    python scripts/migrate_extraction_cache.py --backup   # 迁移前备份
"""

import os
import sys
import json
import shutil
import argparse
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

# 添加项目根目录到路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from server.models.schemas import ExtractionResult, EntityItem, RelationItem

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class CacheMigrator:
    """缓存迁移工具"""

    def __init__(self, cache_dirs: List[str], dry_run: bool = False, backup: bool = False):
        """
        初始化迁移器

        Args:
            cache_dirs: 缓存目录列表
            dry_run: 是否仅检测不修改
            backup: 是否在迁移前备份
        """
        self.cache_dirs = cache_dirs
        self.dry_run = dry_run
        self.backup = backup

        self.stats = {
            'total_files': 0,
            'migrated': 0,
            'skipped': 0,
            'failed': 0,
            'already_new_format': 0
        }

    def parse_old_string_format(self, content: str) -> Optional[Dict[str, Any]]:
        """
        解析旧的字符串格式

        旧格式示例：
        ("entity"<|>学生<|>学生类型<|>在校学生)<record>
        ("relationship"<|>学生<|>奖学金<|>申请<|>学生可以申请奖学金<|>0.8)<record>
        <|complete|>

        Returns:
            解析后的字典（ExtractionResult 格式），如果解析失败返回 None
        """
        try:
            entities = []
            relations = []

            # 分割记录
            records = content.split('<record>')

            for record in records:
                record = record.strip()
                if not record or record == '<|complete|>':
                    continue

                # 解析实体
                entity_match = re.match(r'\("entity"<\|>([^<]+)<\|>([^<]+)<\|>([^)]*)\)', record)
                if entity_match:
                    entities.append(EntityItem(
                        name=entity_match.group(1).strip(),
                        type=entity_match.group(2).strip(),
                        description=entity_match.group(3).strip()
                    ))
                    continue

                # 解析关系
                relation_match = re.match(
                    r'\("relationship"<\|>([^<]+)<\|>([^<]+)<\|>([^<]+)<\|>([^<]*)<\|>([^)]*)\)',
                    record
                )
                if relation_match:
                    try:
                        weight = float(relation_match.group(5).strip())
                    except:
                        weight = 0.5

                    relations.append(RelationItem(
                        source=relation_match.group(1).strip(),
                        target=relation_match.group(2).strip(),
                        type=relation_match.group(3).strip(),
                        description=relation_match.group(4).strip(),
                        weight=weight
                    ))

            if entities or relations:
                result = ExtractionResult(
                    entities=entities,
                    relations=relations
                )
                return result.dict()

            return None

        except Exception as e:
            logger.warning(f"解析旧格式失败: {e}")
            return None

    def detect_format(self, content: Any) -> str:
        """
        检测缓存内容格式

        Returns:
            'new' (已是新格式), 'old_string' (旧字符串格式), 'old_tuple' (旧元组格式), 'unknown'
        """
        if isinstance(content, dict):
            # 检查是否包含 ExtractionResult 的关键字段
            if 'entities' in content and 'relations' in content:
                return 'new'
            return 'unknown'

        elif isinstance(content, str):
            # 检查是否是旧的字符串格式
            if '<|complete|>' in content or '("entity"' in content or '("relationship"' in content:
                return 'old_string'
            return 'unknown'

        elif isinstance(content, (tuple, list)):
            # 旧的元组格式：(entities_list, relations_list, ...)
            return 'old_tuple'

        return 'unknown'

    def migrate_file(self, file_path: Path) -> bool:
        """
        迁移单个缓存文件

        Returns:
            是否成功迁移
        """
        try:
            # 读取缓存文件
            with open(file_path, 'r', encoding='utf-8') as f:
                content = json.load(f)

            # 如果缓存是字典且包含 'value' 键（标准缓存格式）
            cache_value = content.get('value') if isinstance(content, dict) else content

            # 检测格式
            format_type = self.detect_format(cache_value)

            if format_type == 'new':
                self.stats['already_new_format'] += 1
                logger.debug(f"✓ 已是新格式: {file_path.name}")
                return True

            elif format_type == 'old_string':
                logger.info(f"📝 发现旧字符串格式: {file_path.name}")

                # 解析旧格式
                new_value = self.parse_old_string_format(cache_value)
                if not new_value:
                    logger.warning(f"⚠️  解析失败，跳过: {file_path.name}")
                    self.stats['failed'] += 1
                    return False

                # 更新缓存值
                if isinstance(content, dict) and 'value' in content:
                    content['value'] = new_value
                else:
                    content = new_value

                # 保存
                if not self.dry_run:
                    if self.backup:
                        backup_path = file_path.with_suffix(file_path.suffix + '.backup')
                        shutil.copy2(file_path, backup_path)
                        logger.debug(f"  备份: {backup_path.name}")

                    with open(file_path, 'w', encoding='utf-8') as f:
                        json.dump(content, f, ensure_ascii=False, indent=2)

                    logger.info(f"✅ 迁移成功: {file_path.name}")
                else:
                    logger.info(f"🔍 [DRY RUN] 将迁移: {file_path.name}")

                self.stats['migrated'] += 1
                return True

            elif format_type == 'old_tuple':
                logger.info(f"📝 发现旧元组格式: {file_path.name}")
                # 元组格式较复杂，暂时跳过
                logger.warning(f"⚠️  旧元组格式需要手动处理，跳过: {file_path.name}")
                self.stats['skipped'] += 1
                return False

            else:
                logger.debug(f"➖ 未知格式，跳过: {file_path.name}")
                self.stats['skipped'] += 1
                return False

        except Exception as e:
            logger.error(f"❌ 处理文件失败 {file_path.name}: {e}")
            self.stats['failed'] += 1
            return False

    def migrate_all(self):
        """迁移所有缓存文件"""
        logger.info("=" * 80)
        logger.info("开始缓存迁移")
        logger.info(f"缓存目录: {self.cache_dirs}")
        logger.info(f"Dry Run: {self.dry_run}")
        logger.info(f"Backup: {self.backup}")
        logger.info("=" * 80)

        for cache_dir in self.cache_dirs:
            cache_path = Path(cache_dir)
            if not cache_path.exists():
                logger.warning(f"⚠️  缓存目录不存在: {cache_dir}")
                continue

            logger.info(f"\n📂 扫描目录: {cache_dir}")

            # 遍历所有 JSON 文件
            for file_path in cache_path.rglob('*.json'):
                self.stats['total_files'] += 1
                self.migrate_file(file_path)

        # 打印统计
        logger.info("\n" + "=" * 80)
        logger.info("迁移完成统计")
        logger.info("=" * 80)
        logger.info(f"总文件数: {self.stats['total_files']}")
        logger.info(f"✅ 迁移成功: {self.stats['migrated']}")
        logger.info(f"✓  已是新格式: {self.stats['already_new_format']}")
        logger.info(f"➖ 跳过: {self.stats['skipped']}")
        logger.info(f"❌ 失败: {self.stats['failed']}")
        logger.info("=" * 80)


def main():
    parser = argparse.ArgumentParser(description='缓存格式迁移工具')
    parser.add_argument('--dry-run', action='store_true', help='仅检测，不修改文件')
    parser.add_argument('--backup', action='store_true', help='迁移前备份原文件')
    parser.add_argument('--cache-dirs', nargs='+', default=['./cache', './cache/global'],
                        help='缓存目录列表（默认: ./cache ./cache/global）')
    parser.add_argument('--verbose', action='store_true', help='显示详细日志')

    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # 创建迁移器并执行
    migrator = CacheMigrator(
        cache_dirs=args.cache_dirs,
        dry_run=args.dry_run,
        backup=args.backup
    )

    migrator.migrate_all()


if __name__ == "__main__":
    main()
