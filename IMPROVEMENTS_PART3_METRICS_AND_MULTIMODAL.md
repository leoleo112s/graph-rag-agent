# 指标监控与多模态输入 - 实施文档

本文档记录了第三批模块改进的完整实施过程，包括指标监控系统和多模态输入支持（OCR/ASR）。

---

## 📋 总览

### 已实施功能

#### 1. 指标监控系统 ✅
- ✅ QueryLog数据模型（问答查询日志）
- ✅ 统计API端点（构建与问答指标）
- ✅ 前端指标监控仪表盘
- ✅ 时间序列数据可视化

#### 2. 多模态输入支持 ✅
- ✅ ImageProcessor (OCR - 图像文字识别)
- ✅ AudioProcessor (ASR - 语音转文字)
- ✅ 文件读取器多模态路由
- ✅ 依赖项配置

---

## 🛠️ 实施细节

### 模块 1: QueryLog 数据模型

#### 文件: `server/models/query_log.py` (新建)

**功能:**
- 记录每次问答查询的性能指标
- 支持反馈评分追踪
- 提供时间序列统计

**数据库表结构:**
```sql
CREATE TABLE query_logs (
    id TEXT PRIMARY KEY,
    question TEXT NOT NULL,
    agent_type TEXT NOT NULL,
    session_id TEXT NOT NULL,
    message_id TEXT,
    response_time REAL NOT NULL,
    token_usage TEXT,            -- JSON: {"prompt": 100, "completion": 50, "total": 150}
    feedback_score INTEGER,       -- 1 (positive) or -1 (negative)
    retriever_type TEXT,         -- naive, graph, hybrid, deep_research
    search_time REAL,
    llm_time REAL,
    cache_hit INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP
);
```

**索引:**
- `idx_created_at` - 时间查询优化
- `idx_agent_type` - 代理类型过滤
- `idx_session_id` - 会话查询
- `idx_feedback_score` - 反馈统计

**关键方法:**

**创建日志:**
```python
log_db = get_query_log_db()
log_id = log_db.create_log(
    question="旷课多少学时会被退学？",
    agent_type="hybrid_agent",
    session_id="session_123",
    response_time=2.345,
    token_usage={"prompt": 100, "completion": 50, "total": 150},
    retriever_type="hybrid",
    search_time=0.5,
    llm_time=1.2,
    cache_hit=False
)
```

**更新反馈:**
```python
log_db.update_feedback(
    message_id="msg_123",
    feedback_score=1  # 1 = 正面, -1 = 负面
)
```

**获取统计:**
```python
stats = log_db.get_statistics(
    start_time="2024-01-01T00:00:00",
    end_time="2024-01-31T23:59:59",
    agent_type="hybrid_agent"
)

# 返回:
# {
#   "total_queries": 1250,
#   "avg_response_time": 2.145,
#   "avg_search_time": 0.523,
#   "avg_llm_time": 1.022,
#   "cache_hit_rate": 35.2,
#   "positive_feedback_rate": 78.5,
#   "avg_tokens_per_query": 325.5
# }
```

**时间序列数据:**
```python
time_series = log_db.get_time_series(
    metric="response_time",
    start_time="2024-01-01T00:00:00",
    interval="hour"  # hour, day, week
)

# 返回:
# [
#   {"time": "2024-01-01 10:00:00", "avg": 2.1, "min": 1.2, "max": 4.5, "count": 45},
#   {"time": "2024-01-01 11:00:00", "avg": 1.9, "min": 1.0, "max": 3.8, "count": 52},
#   ...
# ]
```

---

### 模块 2: 统计 API

#### 文件: `server/routers/stats.py` (新建)

**API端点:**

#### 2.1 构建任务统计
```
GET /admin/stats/build?start_time=2024-01-01T00:00:00&end_time=2024-01-31T23:59:59&task_type=full
```

**响应:**
```json
{
  "total_builds": 45,
  "successful_builds": 42,
  "failed_builds": 3,
  "success_rate": 93.33,
  "avg_duration_seconds": 125.5,
  "avg_chunks_per_build": 456.2,
  "avg_nodes_per_build": 289.7,
  "total_chunks": 20529,
  "total_nodes": 13037,
  "daily_stats": {
    "2024-01-15": {
      "total": 3,
      "successful": 3,
      "failed": 0,
      "success_rate": 100.0,
      "avg_duration": 120.5
    }
  },
  "type_distribution": {
    "full": 12,
    "incremental": 33
  }
}
```

#### 2.2 问答查询统计
```
GET /admin/stats/qa?start_time=2024-01-01T00:00:00&agent_type=hybrid_agent
```

**响应:**
```json
{
  "total_queries": 1250,
  "avg_response_time": 2.145,
  "avg_search_time": 0.523,
  "avg_llm_time": 1.022,
  "cache_hit_rate": 35.2,
  "positive_feedback_count": 235,
  "negative_feedback_count": 65,
  "positive_feedback_rate": 78.33,
  "agent_distribution": {
    "hybrid_agent": 650,
    "graph_agent": 380,
    "naive_rag_agent": 220
  },
  "retriever_distribution": {
    "hybrid": 650,
    "graph": 400,
    "naive": 200
  },
  "avg_tokens_per_query": 325.5,
  "total_tokens": 406875
}
```

#### 2.3 时间序列数据
```
GET /admin/stats/qa/timeseries?metric=response_time&interval=hour&start_time=2024-01-01T00:00:00
```

**支持的指标:**
- `response_time` - 总响应时间
- `search_time` - 搜索时间
- `llm_time` - LLM生成时间

**响应:**
```json
[
  {
    "time": "2024-01-01 10:00:00",
    "avg": 2.123,
    "min": 0.987,
    "max": 5.432,
    "count": 45
  },
  {
    "time": "2024-01-01 11:00:00",
    "avg": 1.956,
    "min": 1.012,
    "max": 4.123,
    "count": 52
  }
]
```

#### 2.4 系统总览
```
GET /admin/stats/overview
```

**响应:**
```json
{
  "build": {
    "total_builds": 45,
    "success_rate": 93.33,
    "avg_duration": 125.5
  },
  "qa": {
    "total_queries": 1250,
    "avg_response_time": 2.145,
    "cache_hit_rate": 35.2,
    "positive_feedback_rate": 78.33
  },
  "time_range": {
    "start": "2024-01-01T00:00:00",
    "end": "2024-01-07T23:59:59"
  }
}
```

---

### 模块 3: 指标监控仪表盘

#### 文件: `frontend/page_components/metrics_dashboard.py` (新建)

**功能:**
- 系统总览仪表盘
- 构建任务监控
- 问答查询监控
- 时间序列可视化

**UI布局:**
```
┌──────────────────────────────────────────────────────┐
│ 📊 指标监控仪表盘                                      │
├──────────────────────────────────────────────────────┤
│ 时间范围: [最近 7 天 ▼]                               │
├──────────────────────────────────────────────────────┤
│ 🌐 系统总览                                           │
│  ┌────────┬────────┬────────┬────────────┐          │
│  │ 总构建 │ 成功率 │ 总查询 │ 平均响应   │          │
│  │   45   │  93%   │  1250  │  2.15s     │          │
│  ├────────┼────────┼────────┼────────────┤          │
│  │ 平均   │ 缓存   │ 用户   │            │          │
│  │ 耗时   │ 命中率 │ 满意度 │            │          │
│  │ 2.1m   │ 35.2%  │ 78.3%  │            │          │
│  └────────┴────────┴────────┴────────────┘          │
├──────────────────────────────────────────────────────┤
│ [🏗️ 构建任务监控] [💬 问答查询监控]                    │
│                                                      │
│ 📊 核心KPI                                           │
│  总构建: 45  成功率: 93.33%  平均耗时: 125.5s        │
│                                                      │
│ 📅 每日构建统计                                       │
│  日期       │ 总数 │ 成功 │ 失败 │ 成功率 │ 平均耗时 │
│  2024-01-15 │  3   │  3   │  0   │ 100%  │ 120.5s   │
│  2024-01-14 │  2   │  2   │  0   │ 100%  │ 130.2s   │
│                                                      │
│ 📈 构建趋势                                           │
│  ┌────────────────────────────────────────┐         │
│  │  [折线图: 每日构建次数]                 │         │
│  └────────────────────────────────────────┘         │
│                                                      │
│ 📊 构建类型分布                                       │
│  ┌────────────────────────────────────────┐         │
│  │  [柱状图: full vs incremental]          │         │
│  └────────────────────────────────────────┘         │
└──────────────────────────────────────────────────────┘
```

**关键组件:**

**1. 系统总览:**
```python
def render_system_overview():
    data = requests.get(f"{API_URL}/admin/stats/overview").json()

    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("总构建次数", data["build"]["total_builds"])
    with col2: st.metric("构建成功率", f"{data['build']['success_rate']}%")
    with col3: st.metric("总查询次数", data["qa"]["total_queries"])
    with col4: st.metric("平均响应时间", f"{data['qa']['avg_response_time']:.2f}s")
```

**2. 构建任务监控:**
```python
def render_build_metrics(start_time, end_time):
    data = requests.get(
        f"{API_URL}/admin/stats/build",
        params={"start_time": start_time, "end_time": end_time}
    ).json()

    # 核心KPI
    col1, col2, col3, col4 = st.columns(4)
    with col1: st.metric("总构建次数", data["total_builds"])
    with col2: st.metric("成功率", f"{data['success_rate']}%")
    with col3: st.metric("平均耗时", f"{data['avg_duration_seconds']:.1f}s")
    with col4: st.metric("失败次数", data["failed_builds"], delta_color="inverse")

    # 每日统计表格
    daily_df = pd.DataFrame(data["daily_stats"])
    st.dataframe(daily_df)

    # 趋势图
    st.line_chart(daily_df.set_index("日期"))
```

**3. 问答查询监控:**
```python
def render_qa_metrics(start_time, end_time):
    data = requests.get(
        f"{API_URL}/admin/stats/qa",
        params={"start_time": start_time, "end_time": end_time}
    ).json()

    # 核心KPI
    st.metric("平均响应时间", f"{data['avg_response_time']:.3f}s")
    st.metric("缓存命中率", f"{data['cache_hit_rate']:.1f}%")
    st.metric("正面反馈率", f"{data['positive_feedback_rate']:.1f}%")

    # 时间序列图表
    ts_data = requests.get(
        f"{API_URL}/admin/stats/qa/timeseries",
        params={"metric": "response_time", "interval": "hour"}
    ).json()

    ts_df = pd.DataFrame(ts_data)
    st.line_chart(ts_df.set_index("时间")[["平均响应时间(秒)"]])
```

**导航集成:**

**修改文件:** `frontend/app.py`

```python
# 导入
from page_components.metrics_dashboard import render_metrics_dashboard

# 导航菜单
options=["...", "📊 指标监控"]

# 路由
elif page == "📊 指标监控":
    render_metrics_dashboard()
```

---

## 🎭 模块 4: 多模态输入支持

### 4.1 依赖项

#### 文件: `requirements.txt` (扩展)

**新增依赖:**
```
# Multimodal processing (OCR/ASR)
paddleocr==2.7.3
paddlepaddle==2.6.0
openai-whisper==20231117
Pillow>=10.0.0
```

**安装:**
```bash
pip install -r requirements.txt
```

---

### 4.2 ImageProcessor (OCR)

#### 文件: `graphrag_agent/pipelines/ingestion/image_processor.py` (新建)

**功能:**
- 使用 PaddleOCR 提取图像中的文字
- 支持中文、英文、繁体中文
- GPU/CPU 可选
- 批量处理

**使用示例:**
```python
from graphrag_agent.pipelines.ingestion.image_processor import ImageProcessor

# 初始化
processor = ImageProcessor(use_gpu=False, lang="ch")

# 处理单个图像
text, metadata = processor.process_image("/path/to/image.png")

print(f"提取的文字: {text}")
print(f"置信度: {metadata['avg_confidence']}")
print(f"文本行数: {metadata['text_count']}")

# 批量处理
results = processor.batch_process(["/path/to/img1.png", "/path/to/img2.jpg"])
for filename, text, metadata in results:
    print(f"{filename}: {len(text)} 字符")
```

**支持的图像格式:**
- .png
- .jpg / .jpeg
- .bmp
- .tiff / .tif
- .webp

**输出示例:**
```
[图像OCR结果 - 置信度: 0.95]
学生管理规定

第一章 总则
第一条 为规范学生管理工作，根据...
```

---

### 4.3 AudioProcessor (ASR)

#### 文件: `graphrag_agent/pipelines/ingestion/audio_processor.py` (新建)

**功能:**
- 使用 OpenAI Whisper 将音频转录为文字
- 多种模型大小可选 (tiny, base, small, medium, large)
- 自动语言检测
- 支持转录和翻译

**使用示例:**
```python
from graphrag_agent.pipelines.ingestion.audio_processor import AudioProcessor

# 初始化
processor = AudioProcessor(model_size="base", device="cpu")

# 处理单个音频
text, metadata = processor.process_audio("/path/to/audio.mp3", language="zh")

print(f"转录文字: {text}")
print(f"检测语言: {metadata['detected_language']}")
print(f"时长: {metadata['duration_seconds']}秒")

# 批量处理
results = processor.batch_process(["/path/to/audio1.mp3", "/path/to/audio2.wav"])
for filename, text, metadata in results:
    print(f"{filename}: {len(text)} 字符")
```

**支持的音频格式:**
- .mp3
- .wav
- .m4a
- .mp4 (音频)
- .ogg
- .flac
- .webm

**模型大小选择:**
| 模型 | 大小 | 速度 | 准确度 | 推荐场景 |
|------|------|------|--------|----------|
| tiny | ~39M | 最快 | 最低 | 实时转录 |
| base | ~74M | 快 | 中等 | **推荐（默认）** |
| small | ~244M | 中等 | 较好 | 高质量需求 |
| medium | ~769M | 慢 | 更好 | 专业场景 |
| large | ~1550M | 最慢 | 最佳 | 极致质量 |

**输出示例:**
```
[音频ASR结果 - 语言: zh]
今天我们来讨论一下学生管理规定的相关内容。
根据第三章第十五条的规定，学生旷课超过...
```

---

### 4.4 文件读取器多模态路由

#### 文件: `graphrag_agent/pipelines/ingestion/file_reader.py` (扩展)

**功能:**
- 根据文件扩展名自动路由到对应处理器
- 支持启用/禁用 OCR/ASR
- 延迟加载处理器（按需初始化）

**使用示例:**
```python
from graphrag_agent.pipelines.ingestion.file_reader import FileReader

# 初始化（启用OCR和ASR）
reader = FileReader(
    directory_path="./files",
    enable_ocr=True,   # 启用OCR
    enable_asr=True    # 启用ASR
)

# 读取所有支持的文件（包括图像和音频）
files = reader.read_files()

for filename, content in files:
    print(f"{filename}: {len(content)} 字符")
```

**支持的文件类型扩展:**
```python
supported_extensions = {
    # 文本类
    '.txt': self._read_txt,
    '.pdf': self._read_pdf,
    '.md': self._read_markdown,
    '.docx': self._read_docx,
    '.doc': self._read_doc,
    '.csv': self._read_csv,
    '.json': self._read_json,
    '.yaml': self._read_yaml,
    '.yml': self._read_yaml,

    # 图像类 (OCR)
    '.png': self._read_image,
    '.jpg': self._read_image,
    '.jpeg': self._read_image,
    '.bmp': self._read_image,
    '.tiff': self._read_image,
    '.tif': self._read_image,

    # 音频类 (ASR)
    '.mp3': self._read_audio,
    '.wav': self._read_audio,
    '.m4a': self._read_audio,
    '.mp4': self._read_audio,
    '.ogg': self._read_audio,
    '.flac': self._read_audio,
}
```

**处理流程:**
```
用户上传文件
    ↓
file_reader 检测扩展名
    ↓
    ├─ 文本文件 → 直接读取
    ├─ 图像文件 → ImageProcessor (OCR) → 文字
    └─ 音频文件 → AudioProcessor (ASR) → 文字
    ↓
统一文本流 → 分块 → 实体提取 → 图谱构建
```

---

## 📊 性能考虑

### OCR 性能

**PaddleOCR:**
- CPU模式: 每张图片 ~2-5秒
- GPU模式: 每张图片 ~0.5-1秒
- 内存占用: ~500MB (模型加载后)

**优化建议:**
- 批量处理图片时使用GPU
- 对低质量图片降低分辨率
- 缓存OCR结果避免重复处理

### ASR 性能

**Whisper (base model):**
- CPU模式: 每分钟音频 ~15-30秒处理时间
- GPU模式: 每分钟音频 ~3-5秒处理时间
- 内存占用: ~1GB (模型加载后)

**优化建议:**
- 使用较小的模型 (base/small) 平衡速度和准确度
- 长音频文件分段处理
- 使用GPU加速

---

## 🔧 使用场景

### 场景 1: 扫描件文档处理

**问题:** 用户上传PDF扫描件，无法提取文字

**解决方案:**
1. 将PDF页面转换为图像
2. 使用OCR提取文字
3. 构建知识图谱

**代码示例:**
```python
from pdf2image import convert_from_path

# 转换PDF为图像
images = convert_from_path("scan.pdf")

# 处理每一页
processor = ImageProcessor()
full_text = ""
for i, image in enumerate(images):
    image.save(f"page_{i}.png")
    text, _ = processor.process_image(f"page_{i}.png")
    full_text += text + "\n"
```

### 场景 2: 会议录音转录

**问题:** 用户需要从会议录音中提取知识

**解决方案:**
1. 上传音频文件 (MP3/WAV)
2. 使用ASR转录为文字
3. 自动摘要和知识图谱构建

**代码示例:**
```python
processor = AudioProcessor(model_size="base")

# 转录会议录音
text, metadata = processor.process_audio("meeting.mp3", language="zh")

print(f"会议时长: {metadata['duration_seconds'] / 60:.1f} 分钟")
print(f"转录文字: {len(text)} 字符")

# 后续可以提取关键信息、构建知识图谱
```

### 场景 3: 混合文档处理

**问题:** 文件夹包含多种格式 (PDF, 图片, 音频)

**解决方案:**
```python
# 一次性处理所有文件
reader = FileReader("./mixed_files", enable_ocr=True, enable_asr=True)
files = reader.read_files()

# 所有文件统一为文本流
for filename, content in files:
    print(f"处理: {filename} ({len(content)} 字符)")
    # 进入统一的分块和实体提取流程
```

---

## 🐛 已知限制

### OCR 限制

1. **手写字识别准确度较低**
   - PaddleOCR 主要针对印刷体
   - 解决方案: 手写字需要专门的手写识别模型

2. **复杂排版处理不佳**
   - 表格、多列文本可能顺序混乱
   - 解决方案: 使用专门的表格识别工具

3. **低分辨率图像效果差**
   - 建议: 图像DPI > 300
   - 预处理: 图像增强、去噪

### ASR 限制

1. **多人对话识别困难**
   - Whisper 不区分说话人
   - 解决方案: 使用说话人分离工具（speaker diarization）

2. **方言识别准确度低**
   - 标准普通话效果最佳
   - 解决方案: 使用专门的方言ASR模型

3. **背景噪音影响大**
   - 建议: 使用清晰的录音
   - 预处理: 降噪处理

---

## 🚀 未来优化

### 短期（1-2周）

1. **上传API扩展**
   - 允许前端直接上传图像和音频文件
   - 实时显示OCR/ASR进度

2. **预处理优化**
   - 图像去噪、增强
   - 音频降噪、分段

3. **缓存机制**
   - OCR/ASR结果缓存避免重复处理
   - 基于文件hash的去重

### 中期（1个月）

1. **表格识别**
   - 专门的表格结构识别
   - 转换为结构化数据

2. **说话人分离**
   - 识别音频中的不同说话人
   - 标注对话归属

3. **批处理优化**
   - 并行处理多个文件
   - GPU资源池管理

---

## 📈 指标监控使用指南

### 日常监控

**每日检查:**
1. 访问 "📊 指标监控" 页面
2. 查看系统总览：
   - 构建成功率是否正常 (>90%)
   - 平均响应时间是否在预期范围 (<3s)
   - 用户满意度是否良好 (>70%)

**每周检查:**
1. 查看构建趋势图
   - 识别构建失败的高峰时段
   - 分析失败原因

2. 查看问答性能趋势
   - 响应时间是否有上升趋势
   - 缓存命中率是否优化

### 性能优化

**基于指标的优化决策:**

**如果平均响应时间过高 (>5s):**
1. 查看性能分解: search_time vs llm_time
2. 如果 search_time 高 → 优化检索策略/索引
3. 如果 llm_time 高 → 减少prompt长度/使用更快的模型

**如果缓存命中率低 (<30%):**
1. 检查查询模式分布
2. 优化缓存策略（相似度匹配）
3. 增加缓存容量

**如果用户满意度低 (<60%):**
1. 分析负面反馈的查询类型
2. 检查这些查询的检索结果质量
3. 针对性改进实体提取/图谱构建

---

## 🎉 总结

本次实施完成了两大核心功能模块：

### 指标监控系统
- ✅ 完整的查询日志记录
- ✅ 多维度统计分析
- ✅ 可视化监控仪表盘
- ✅ 时间序列趋势分析

### 多模态输入支持
- ✅ OCR图像文字识别
- ✅ ASR语音转文字
- ✅ 统一的文件处理流程
- ✅ 可扩展的处理架构

**业务价值:**
- 🎯 实时性能监控和问题定位
- 🎯 数据驱动的系统优化
- 🎯 支持更多样化的输入格式
- 🎯 降低数据准备门槛

**技术亮点:**
- 📝 完整的日志追踪体系
- 📝 高效的时间序列查询
- 📝 延迟加载的多模态处理
- 📝 可插拔的处理器架构

---

**实施日期:** 2024-12-25

**版本:** v3.0.0

**下一步计划:**
1. 上传API扩展支持图像/音频
2. 实时进度显示
3. 批处理优化
