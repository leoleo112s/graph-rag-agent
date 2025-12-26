# 认证与配置校验改进文档

> **改进时间**: 2025-12-24
> **改进目标**: 解决知识图谱 CRUD 权限缺失和 GraphConfig 配置校验不足的问题

---

## 📋 目录

1. [问题分析](#问题分析)
2. [改进方案](#改进方案)
3. [代码实现](#代码实现)
4. [配置说明](#配置说明)
5. [测试验证](#测试验证)
6. [安全建议](#安全建议)

---

## 问题分析

### 问题 1: 知识图谱 CRUD 权限缺失 🚨

#### 问题描述

`server/routers/knowledge_graph.py` 中的所有写操作端点**完全没有身份验证**，任何人只要知道后端 IP 就可以：

- 删除整个知识图谱
- 修改任意实体和关系
-创建虚假数据

#### 受影响的端点

| 端点 | 位置 | 风险等级 |
|------|------|----------|
| `POST /entity/create` | line 405 | 🔴 高危 |
| `POST /entity/update` | line 448 | 🔴 高危 |
| `POST /entity/delete` | line 518 | 🔴 高危 |
| `POST /relation/create` | line 569 | 🔴 高危 |
| `POST /relation/update` | line 640 | 🔴 高危 |
| `POST /relation/delete` | line 766 | 🔴 高危 |

#### 攻击示例

```bash
# ❌ 攻击者可以直接删除实体（无需任何凭证）
curl -X POST http://your-backend-ip:8000/api/knowledge_graph/entity/delete \
  -H "Content-Type: application/json" \
  -d '{"entity_id": "重要实体ID"}'

# ❌ 批量删除知识图谱
for id in $(seq 1 1000); do
  curl -X POST http://your-backend-ip:8000/api/knowledge_graph/entity/delete \
    -H "Content-Type: application/json" \
    -d "{\"entity_id\": \"$id\"}"
done
```

---

### 问题 2: GraphConfig 配置校验不足 ⚠️

#### 问题描述

`graphrag_agent/config/graph_config_model.py` 的 `GraphConfig` 类**只有 Pydantic 类型校验**，缺乏业务逻辑校验：

1. **Bridge Key 可重复** → 导致配置歧义，无法确定引用哪个桥接点
2. **Domain Name 可重复** → 导致领域冲突，路由无法正确匹配
3. **Bridge Mapping 引用不校验** → 引用不存在的 `bridge_key` 不报错，运行时才发现

#### 错误示例（当前不会报错）

```python
# ❌ 重复的 Bridge Key（当前不报错，但会导致歧义）
GraphConfig(
    bridge_definitions=[
        BridgeDefinition(name="问题类型", key="bridge_issue"),
        BridgeDefinition(name="问题分类", key="bridge_issue")  # 重复！
    ],
    ...
)

# ❌ 重复的 Domain Name（当前不报错，但会导致路由冲突）
GraphConfig(
    domain_definitions=[
        DomainDefinition(domain_name="规则库", ...),
        DomainDefinition(domain_name="规则库", ...)  # 重复！
    ],
    ...
)

# ❌ 引用不存在的 Bridge Key（当前不报错，运行时才崩溃）
GraphConfig(
    bridge_definitions=[
        BridgeDefinition(key="bridge_issue", ...)
    ],
    domain_definitions=[
        DomainDefinition(
            bridge_mappings=[
                BridgeMapping(bridge_key="bridge_non_exist")  # 不存在！
            ]
        )
    ]
)
```

---

## 改进方案

### 方案 1: 知识图谱 CRUD 权限控制

#### 架构设计

```
FastAPI Dependency Injection
    ↓
server/utils/auth.py
    ↓
verify_admin_token(x_admin_token: Header)
    ↓
    ├─ AUTH_ENABLED=false → 开发模式，直接通过
    ├─ 未提供 token → 401 Unauthorized
    ├─ token 无效 → 403 Forbidden
    └─ token 有效 → 放行
```

#### 认证模式

支持三种认证模式：

1. **开发模式** (AUTH_ENABLED=false): 跳过所有检查
2. **默认密钥模式**: 使用内置默认密钥（仅测试用）
3. **生产模式**: 从环境变量读取自定义 ADMIN_API_KEY

#### 权限级别

| 权限函数 | 用途 | Header | 适用端点 |
|---------|------|--------|----------|
| `verify_admin_token()` | 管理员权限 | X-Admin-Token | 写操作（CRUD） |
| `verify_read_token()` | 读权限（可选） | X-API-Key | 查询操作 |
| `get_current_user()` | 获取用户信息（可扩展为 JWT） | - | 需要用户上下文的场景 |

---

### 方案 2: GraphConfig 配置强校验

#### 校验策略

使用 Pydantic 的 `@model_validator(mode='after')` 在模型创建时自动校验：

```python
@model_validator(mode='after')
def validate_integrity(self):
    # 1. Bridge Key 唯一性检查
    # 2. Domain Name 唯一性检查
    # 3. Bridge Mapping 引用完整性检查
    return self
```

#### 校验时机

```
API 接收请求 → Pydantic 解析 JSON → @model_validator 校验 → 保存到文件
                                        ↓
                                   发现错误立即抛出 ValueError
```

---

## 代码实现

### 实现 1: 身份验证依赖 (`server/utils/auth.py`)

#### 核心代码

```python
"""
身份验证和授权依赖

用途：
- 提供 FastAPI 依赖注入函数，用于保护敏感API端点
- 支持多种认证方式：API Key、JWT Token（可扩展）
- 区分读写权限

安全级别：
- verify_api_key: 基础API Key验证（适合内部服务）
- verify_admin_token: 管理员权限验证（适合知识图谱CRUD）
- verify_jwt_token: JWT Token验证（适合多用户场景，可选）

使用方法：
    from server.utils.auth import verify_admin_token
    from fastapi import Depends

    @router.post("/entity/create", dependencies=[Depends(verify_admin_token)])
    def create_entity(...):
        ...

配置：
    在 .env 中设置：
    ADMIN_API_KEY=your_secret_admin_key_here
    READ_API_KEY=your_read_only_key_here  # 可选，用于只读访问
"""

import os
from fastapi import Header, HTTPException, Depends
from typing import Optional
import logging

logger = logging.getLogger(__name__)

# ============================================================================
# 配置常量
# ============================================================================

# 从环境变量读取API Key（生产环境必须设置）
ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
READ_API_KEY = os.getenv("READ_API_KEY", "")

# 默认密钥警告（仅开发环境使用）
DEFAULT_DEV_KEY = "dev-mode-insecure-key-change-in-production"

# 是否启用认证（默认启用，开发环境可设置为False）
AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() == "true"


# ============================================================================
# 依赖函数
# ============================================================================

async def verify_admin_token(
    x_admin_token: Optional[str] = Header(None, description="管理员API密钥")
) -> str:
    """
    验证管理员权限（用于知识图谱CRUD等写操作）

    ✅ 改进：防止未授权访问知识图谱写操作

    Args:
        x_admin_token: HTTP Header中的 X-Admin-Token

    Returns:
        str: 验证通过的token

    Raises:
        HTTPException: 401 (未提供token) 或 403 (token无效)

    使用示例：
        @router.post("/entity/create", dependencies=[Depends(verify_admin_token)])
        def create_entity(...):
            ...
    """
    # 如果禁用认证（仅开发环境），直接通过
    if not AUTH_ENABLED:
        logger.warning("⚠️ 认证已禁用（开发模式），跳过权限检查")
        return "dev-mode"

    # 检查是否提供token
    if not x_admin_token:
        logger.warning("❌ 未提供管理员Token")
        raise HTTPException(
            status_code=401,
            detail={
                "error": "未授权",
                "message": "需要提供管理员API密钥",
                "hint": "在HTTP Header中添加 X-Admin-Token"
            }
        )

    # 获取有效的Admin Key
    valid_key = ADMIN_API_KEY if ADMIN_API_KEY else DEFAULT_DEV_KEY

    # 警告：使用默认密钥
    if valid_key == DEFAULT_DEV_KEY:
        logger.warning(
            "⚠️ 使用默认开发密钥！生产环境请设置环境变量 ADMIN_API_KEY"
        )

    # 验证token
    if x_admin_token != valid_key:
        logger.warning(
            f"❌ 管理员Token验证失败: 提供的token不匹配",
            extra={"provided": x_admin_token[:8] + "..." if len(x_admin_token) > 8 else x_admin_token}
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "权限不足",
                "message": "管理员API密钥无效"
            }
        )

    logger.info("✅ 管理员权限验证通过")
    return x_admin_token


async def verify_read_token(
    x_api_key: Optional[str] = Header(None, description="API密钥（读权限）")
) -> str:
    """
    验证读权限（用于查询知识图谱）

    ✅ 可选：区分读写权限，读操作可使用更宽松的密钥

    Args:
        x_api_key: HTTP Header中的 X-API-Key

    Returns:
        str: 验证通过的token

    Raises:
        HTTPException: 401 (未提供token) 或 403 (token无效)

    使用示例：
        @router.get("/entities", dependencies=[Depends(verify_read_token)])
        def list_entities(...):
            ...
    """
    # 如果禁用认证，直接通过
    if not AUTH_ENABLED:
        return "dev-mode"

    # 检查是否提供token
    if not x_api_key:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "未授权",
                "message": "需要提供API密钥",
                "hint": "在HTTP Header中添加 X-API-Key"
            }
        )

    # 获取有效的Read Key（如果未设置，允许Admin Key通用）
    valid_keys = [
        READ_API_KEY if READ_API_KEY else None,
        ADMIN_API_KEY if ADMIN_API_KEY else DEFAULT_DEV_KEY
    ]
    valid_keys = [k for k in valid_keys if k]  # 过滤None

    # 验证token
    if x_api_key not in valid_keys:
        logger.warning(
            f"❌ API密钥验证失败: 提供的key不匹配",
            extra={"provided": x_api_key[:8] + "..." if len(x_api_key) > 8 else x_api_key}
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "权限不足",
                "message": "API密钥无效"
            }
        )

    logger.debug("✅ 读权限验证通过")
    return x_api_key


def get_current_user(
    token: str = Depends(verify_admin_token)
) -> dict:
    """
    获取当前用户信息（可扩展为JWT解析）

    ✅ 未来可扩展：集成OAuth2/JWT，返回真实用户信息

    Args:
        token: 验证通过的token（由verify_admin_token提供）

    Returns:
        dict: 用户信息
    """
    # 简化版本：仅返回token标识
    # 生产环境：解析JWT，返回 {"user_id": "...", "role": "admin", ...}
    return {
        "token": token,
        "role": "admin"
    }


# ============================================================================
# 辅助函数
# ============================================================================

def is_auth_configured() -> bool:
    """
    检查认证是否已配置（用于健康检查）

    Returns:
        bool: 是否已设置非默认的Admin Key
    """
    if not AUTH_ENABLED:
        return False

    return ADMIN_API_KEY != "" and ADMIN_API_KEY != DEFAULT_DEV_KEY


def get_auth_status() -> dict:
    """
    获取认证配置状态（用于调试和监控）

    Returns:
        dict: 认证状态信息
    """
    return {
        "auth_enabled": AUTH_ENABLED,
        "admin_key_configured": bool(ADMIN_API_KEY),
        "read_key_configured": bool(READ_API_KEY),
        "using_default_key": ADMIN_API_KEY == "" or ADMIN_API_KEY == DEFAULT_DEV_KEY,
        "warning": "使用默认密钥不安全！" if (ADMIN_API_KEY == "" or ADMIN_API_KEY == DEFAULT_DEV_KEY) else None
    }
```

#### 文件位置
- **新增文件**: `server/utils/auth.py`

---

### 实现 2: 知识图谱端点权限保护

#### 修改示例

```python
from server.utils.auth import verify_admin_token
from fastapi import Depends

# ✅ 添加管理员权限验证
@router.post("/entity/create", dependencies=[Depends(verify_admin_token)])
def create_entity(entity_data: EntityData):
    """
    创建实体

    ✅ 改进：需要管理员权限（X-Admin-Token Header）

    Security:
        - Requires: X-Admin-Token in HTTP Headers

    Args:
        entity_data: 实体数据

    Returns:
        dict: 创建结果
    """
    db_manager = get_db_manager()
    # ... 原有逻辑 ...
```

#### 受保护的端点

所有以下端点已添加 `dependencies=[Depends(verify_admin_token)]`：

1. `POST /entity/create` - 创建实体
2. `POST /entity/update` - 更新实体
3. `POST /entity/delete` - 删除实体
4. `POST /relation/create` - 创建关系
5. `POST /relation/update` - 更新关系
6. `POST /relation/delete` - 删除关系

#### 文件位置
- **修改文件**: `server/routers/knowledge_graph.py`
- **修改行数**: 每个端点添加 1 行 `dependencies=` 参数

---

### 实现 3: GraphConfig 配置强校验

#### 核心代码

```python
from pydantic import BaseModel, Field, model_validator

class GraphConfig(BaseModel):
    """通用图谱配置 - 完整的多领域配置"""
    project_name: str = Field(..., description="项目名称")
    version: str = Field(default="1.0", description="配置版本")
    # ... 其他字段 ...

    bridge_definitions: List[BridgeDefinition] = Field(..., description="桥接点定义列表")
    domain_definitions: List[DomainDefinition] = Field(..., description="领域定义列表")

    @model_validator(mode='after')
    def validate_integrity(self):
        """
        校验配置完整性

        ✅ 改进：在 Pydantic 模型层面验证配置，避免无效配置进入系统

        检查项：
        1. Bridge Key 唯一性 - 同一个 key 不能定义多次
        2. Domain Name 唯一性 - 同一个领域名不能定义多次
        3. Bridge Mapping 引用完整性 - 引用的 bridge_key 必须存在

        Raises:
            ValueError: 当发现重复或引用不存在时
        """
        # 1. 检查 Bridge Key 唯一性
        bridge_keys = set()
        for bridge in self.bridge_definitions:
            if bridge.key in bridge_keys:
                raise ValueError(
                    f"❌ 配置错误：重复的 Bridge Key '{bridge.key}'。\n"
                    f"   提示：每个 bridge.key 必须唯一，请修改重复的 key。"
                )
            bridge_keys.add(bridge.key)

        # 2. 检查 Domain Name 唯一性
        domain_names = set()
        for domain in self.domain_definitions:
            if domain.domain_name in domain_names:
                raise ValueError(
                    f"❌ 配置错误：重复的 Domain Name '{domain.domain_name}'。\n"
                    f"   提示：每个领域名称必须唯一，请修改重复的领域名。"
                )
            domain_names.add(domain.domain_name)

            # 3. 检查 Bridge Mapping 的引用完整性
            for mapping in domain.bridge_mappings:
                if mapping.bridge_key not in bridge_keys:
                    raise ValueError(
                        f"❌ 配置错误：领域 '{domain.domain_name}' 引用了不存在的 Bridge Key '{mapping.bridge_key}'。\n"
                        f"   提示：请确保在 bridge_definitions 中定义了该 key，或修正 bridge_mappings 中的引用。\n"
                        f"   已定义的 Bridge Keys: {sorted(bridge_keys)}"
                    )

        return self
```

#### 文件位置
- **修改文件**: `graphrag_agent/config/graph_config_model.py`
- **修改内容**:
  - 导入 `model_validator`
  - 添加 `validate_integrity()` 方法

---

## 配置说明

### 环境变量配置

在 `.env` 文件中添加：

```bash
# ============================================================================
# 认证配置 (Authentication)
# ============================================================================

# 是否启用认证（默认启用）
# - true: 启用认证，需要提供 API Key
# - false: 禁用认证（仅开发环境使用，生产环境禁止）
AUTH_ENABLED=true

# 管理员 API 密钥（用于知识图谱 CRUD 等写操作）
# ⚠️ 生产环境必须设置强密钥！
# 生成方法: python -c "import secrets; print(secrets.token_urlsafe(32))"
ADMIN_API_KEY=your_secret_admin_key_here

# 只读 API 密钥（可选，用于查询操作）
# 如果不设置，查询操作也可以使用 ADMIN_API_KEY
READ_API_KEY=your_read_only_key_here
```

### 密钥生成

**推荐方法** - 使用 Python 生成安全的随机密钥：

```bash
# 生成 32 字节的 URL 安全密钥
python -c "import secrets; print(secrets.token_urlsafe(32))"

# 示例输出:
# wJ8KfZ3X9mQn7LpR2vTy4cG1hN6bA5dE8xW0sY9uV3k
```

**不推荐** - 使用简单字符串（容易被暴力破解）：
```bash
# ❌ 弱密钥（不要使用）
ADMIN_API_KEY=admin123
ADMIN_API_KEY=password
```

### 三种部署模式

#### 模式 1: 开发模式（跳过认证）

```bash
# .env
AUTH_ENABLED=false
```

**特点**:
- 不需要提供任何 API Key
- 所有请求直接通过
- ⚠️ **仅用于本地开发，禁止生产环境使用**

---

#### 模式 2: 测试模式（默认密钥）

```bash
# .env
AUTH_ENABLED=true
# 不设置 ADMIN_API_KEY，使用默认密钥
```

**特点**:
- 使用内置默认密钥: `dev-mode-insecure-key-change-in-production`
- 日志中会显示警告
- ⚠️ **仅用于测试环境，禁止生产环境使用**

---

#### 模式 3: 生产模式（自定义密钥）

```bash
# .env
AUTH_ENABLED=true
ADMIN_API_KEY=wJ8KfZ3X9mQn7LpR2vTy4cG1hN6bA5dE8xW0sY9uV3k
READ_API_KEY=aB2cD3eF4gH5iJ6kL7mN8oP9qR0sT1uV2wX3yZ4
```

**特点**:
- 使用强随机密钥
- 生产环境必须使用此模式
- ✅ **推荐配置**

---

## 测试验证

### 测试 1: 知识图谱 CRUD 权限

#### 测试场景 1: 未提供 Token（预期 401）

```bash
# ❌ 请求失败（401 Unauthorized）
curl -X POST http://localhost:8000/api/knowledge_graph/entity/create \
  -H "Content-Type: application/json" \
  -d '{
    "entity_data": {
      "name": "测试实体",
      "entity_type": "测试类型"
    }
  }'

# 预期响应:
# {
#   "detail": {
#     "error": "未授权",
#     "message": "需要提供管理员API密钥",
#     "hint": "在HTTP Header中添加 X-Admin-Token"
#   }
# }
```

---

#### 测试场景 2: 提供无效 Token（预期 403）

```bash
# ❌ 请求失败（403 Forbidden）
curl -X POST http://localhost:8000/api/knowledge_graph/entity/create \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: invalid_token_here" \
  -d '{
    "entity_data": {
      "name": "测试实体",
      "entity_type": "测试类型"
    }
  }'

# 预期响应:
# {
#   "detail": {
#     "error": "权限不足",
#     "message": "管理员API密钥无效"
#   }
# }
```

---

#### 测试场景 3: 提供有效 Token（预期 200）

```bash
# ✅ 请求成功（200 OK）
curl -X POST http://localhost:8000/api/knowledge_graph/entity/create \
  -H "Content-Type: application/json" \
  -H "X-Admin-Token: wJ8KfZ3X9mQn7LpR2vTy4cG1hN6bA5dE8xW0sY9uV3k" \
  -d '{
    "entity_data": {
      "name": "测试实体",
      "entity_type": "测试类型"
    }
  }'

# 预期响应:
# {
#   "success": true,
#   "entity_id": "...",
#   "message": "实体创建成功"
# }
```

---

### 测试 2: GraphConfig 配置校验

#### 测试用例 1: 重复的 Bridge Key

```python
from graphrag_agent.config.graph_config_model import GraphConfig, BridgeDefinition

# ❌ 应该抛出 ValueError
try:
    config = GraphConfig(
        project_name="测试项目",
        bridge_definitions=[
            BridgeDefinition(name="问题类型", key="bridge_issue", description="test", examples=[]),
            BridgeDefinition(name="问题分类", key="bridge_issue", description="test", examples=[])  # 重复！
        ],
        domain_definitions=[]
    )
except ValueError as e:
    print(f"✅ 捕获到预期错误: {e}")
    # 输出: ❌ 配置错误：重复的 Bridge Key 'bridge_issue'。
    #       提示：每个 bridge.key 必须唯一，请修改重复的 key。
```

---

#### 测试用例 2: 重复的 Domain Name

```python
from graphrag_agent.config.graph_config_model import (
    GraphConfig, BridgeDefinition, DomainDefinition, DomainSchema
)

# ❌ 应该抛出 ValueError
try:
    config = GraphConfig(
        project_name="测试项目",
        bridge_definitions=[
            BridgeDefinition(name="问题类型", key="bridge_issue", description="test", examples=[])
        ],
        domain_definitions=[
            DomainDefinition(
                domain_name="规则库",
                description="test",
                trigger_condition="test",
                schema=DomainSchema(entities=[], relations=[]),
                bridge_mappings=[]
            ),
            DomainDefinition(
                domain_name="规则库",  # 重复！
                description="test",
                trigger_condition="test",
                schema=DomainSchema(entities=[], relations=[]),
                bridge_mappings=[]
            )
        ]
    )
except ValueError as e:
    print(f"✅ 捕获到预期错误: {e}")
    # 输出: ❌ 配置错误：重复的 Domain Name '规则库'。
    #       提示：每个领域名称必须唯一，请修改重复的领域名。
```

---

#### 测试用例 3: Bridge Mapping 引用不存在的 Key

```python
from graphrag_agent.config.graph_config_model import (
    GraphConfig, BridgeDefinition, DomainDefinition, DomainSchema, BridgeMapping
)

# ❌ 应该抛出 ValueError
try:
    config = GraphConfig(
        project_name="测试项目",
        bridge_definitions=[
            BridgeDefinition(name="问题类型", key="bridge_issue", description="test", examples=[])
        ],
        domain_definitions=[
            DomainDefinition(
                domain_name="规则库",
                description="test",
                trigger_condition="test",
                schema=DomainSchema(entities=[], relations=[]),
                bridge_mappings=[
                    BridgeMapping(bridge_key="bridge_non_exist", role="test")  # 不存在！
                ]
            )
        ]
    )
except ValueError as e:
    print(f"✅ 捕获到预期错误: {e}")
    # 输出: ❌ 配置错误：领域 '规则库' 引用了不存在的 Bridge Key 'bridge_non_exist'。
    #       提示：请确保在 bridge_definitions 中定义了该 key，或修正 bridge_mappings 中的引用。
    #       已定义的 Bridge Keys: ['bridge_issue']
```

---

#### 测试用例 4: 有效配置（应该成功）

```python
# ✅ 应该成功创建
config = GraphConfig(
    project_name="测试项目",
    bridge_definitions=[
        BridgeDefinition(name="问题类型", key="bridge_issue", description="test", examples=[])
    ],
    domain_definitions=[
        DomainDefinition(
            domain_name="规则库",
            description="test",
            trigger_condition="test",
            schema=DomainSchema(entities=["法条"], relations=["规定"]),
            bridge_mappings=[
                BridgeMapping(bridge_key="bridge_issue", role="适用场景")
            ]
        )
    ]
)

print(f"✅ 配置创建成功: {config.project_name}")
# 输出: ✅ 配置创建成功: 测试项目
```

---

## 安全建议

### 🔒 密钥管理最佳实践

1. **生产环境必须设置强密钥**
   ```bash
   # ✅ 使用 32 字节以上的随机密钥
   python -c "import secrets; print(secrets.token_urlsafe(32))"
   ```

2. **禁止在代码中硬编码密钥**
   ```python
   # ❌ 错误示范
   ADMIN_API_KEY = "hardcoded_key_in_code"

   # ✅ 正确方式
   ADMIN_API_KEY = os.getenv("ADMIN_API_KEY", "")
   ```

3. **定期轮换密钥**
   - 建议每 90 天轮换一次
   - 泄露后立即轮换

4. **使用密钥管理服务**
   - AWS Secrets Manager
   - HashiCorp Vault
   - Azure Key Vault

---

### 🛡️ 权限控制最佳实践

1. **最小权限原则**
   - 查询操作使用 `READ_API_KEY`
   - 写操作使用 `ADMIN_API_KEY`
   - 不要所有操作都用管理员权限

2. **审计日志**
   ```python
   logger.info("✅ 管理员权限验证通过", extra={
       "user": "admin",
       "action": "entity_delete",
       "entity_id": entity_id
   })
   ```

3. **速率限制**（未来可扩展）
   ```python
   from fastapi_limiter.depends import RateLimiter

   @router.post(
       "/entity/create",
       dependencies=[
           Depends(verify_admin_token),
           Depends(RateLimiter(times=10, seconds=60))  # 限制: 每分钟10次
       ]
   )
   ```

---

### 📊 监控告警

推荐监控以下指标：

1. **认证失败次数**
   - 如果短时间内大量 401/403，可能是暴力破解

2. **异常操作**
   - 深夜大量删除操作
   - 单个 IP 高频创建/删除

3. **配置错误**
   - 重复的 Bridge Key
   - 引用不存在的 Bridge Key

---

## 附录

### A. 错误码对照表

| HTTP 状态码 | 错误类型 | 原因 | 解决方法 |
|------------|---------|------|---------|
| 401 | Unauthorized | 未提供 Token | 在 Header 中添加 X-Admin-Token |
| 403 | Forbidden | Token 无效 | 检查 .env 中的 ADMIN_API_KEY |
| 422 | Validation Error | GraphConfig 校验失败 | 检查配置中是否有重复或无效引用 |

---

### B. 迁移指南

#### 从无认证迁移到有认证

**Step 1**: 在 `.env` 中添加配置

```bash
AUTH_ENABLED=true
ADMIN_API_KEY=$(python -c "import secrets; print(secrets.token_urlsafe(32))")
```

**Step 2**: 重启服务

```bash
python server/main.py
```

**Step 3**: 更新客户端代码

```python
# ❌ 旧代码（无认证）
response = requests.post(
    "http://localhost:8000/api/knowledge_graph/entity/create",
    json={"entity_data": {...}}
)

# ✅ 新代码（带认证）
response = requests.post(
    "http://localhost:8000/api/knowledge_graph/entity/create",
    headers={"X-Admin-Token": os.getenv("ADMIN_API_KEY")},
    json={"entity_data": {...}}
)
```

---

### C. FAQ

**Q1: 如果忘记 ADMIN_API_KEY 怎么办？**

A: 重新生成并更新 `.env` 文件即可：
```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

**Q2: 可以支持多个管理员密钥吗？**

A: 当前版本不支持。未来可扩展为 JWT Token，支持多用户。

**Q3: GraphConfig 校验失败后如何修复？**

A: 根据错误提示修改配置：
- 重复的 Bridge Key → 改名
- 重复的 Domain Name → 改名
- 引用不存在的 Bridge Key → 修正引用或添加定义

**Q4: 如何在前端展示认证错误？**

A: 捕获 401/403 响应并引导用户登录：
```javascript
if (response.status === 401 || response.status === 403) {
    alert("权限不足，请联系管理员");
    window.location.href = "/login";
}
```

---

## 总结

本次改进解决了两个关键问题：

1. ✅ **知识图谱 CRUD 权限缺失** → 添加 FastAPI 依赖注入认证
2. ✅ **GraphConfig 配置校验不足** → 添加 Pydantic `@model_validator`

**影响范围**:
- 新增文件: `server/utils/auth.py`
- 修改文件: `server/routers/knowledge_graph.py`, `graphrag_agent/config/graph_config_model.py`

**安全提升**:
- 防止未授权用户删除知识图谱 ✅
- 防止无效配置进入系统 ✅
- 提供可扩展的认证架构（支持未来集成 JWT/OAuth2）✅

---

**文档版本**: v1.0
**最后更新**: 2025-12-24
**维护者**: Claude Code
