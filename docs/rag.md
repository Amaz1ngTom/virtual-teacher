# 教材 RAG

## 当前实现

当前版本采用关键词与本地语义向量混合检索：

```text
整本PDF
  → 按PDF页提取文字
  → 在页内按完整句子切成约520字片段
  → 中文2/3字片段与英文单词索引
  → BGE-small生成512维归一化向量
  → SQLite持久化倒排索引与向量
  → BM25与余弦相似度分别排序
  → Reciprocal Rank Fusion融合后取前4段
  → 原文与PDF页码注入LangGraph教学提示词
  → 千问生成有教材依据的回答
```

索引文件位于 `data/textbook-rag.sqlite3`，运行数据不提交Git。建立索引默认只消耗CPU和少量
内存，不访问外部API，也不占用FLOAT所在GPU。课程正常讲授、固定检查题和确定性判题
不会检索或调用LLM；只有学生在已发布教材课程中使用“向老师提问”时才进行检索和动态回答。

## 页面操作

1. 在“导入教材PDF”中上传整本带文字层的PDF。
2. 确认章节识别结果，必要时先调整章节页码。
3. 点击“建立教材问答索引”。
4. 生成、审核并发布至少一个章节课程。
5. 进入该课程，讲授或答题过程中临时提问。
6. 回答下方应显示命中的原始PDF页码和章节名称。

扫描版PDF仍需先完成OCR。章节结构修改后建议重新建立索引，以刷新来源标签。

## 本地语义模型

当前使用 `BAAI/bge-small-zh-v1.5`，模型文件约92MB，保存在
项目同级的 `models/bge-small-zh-v1.5`。项目直接通过现有Transformers加载，不安装
`sentence-transformers`，也不需要克隆独立RAG项目。默认设备为CPU；可通过
`VT_RAG_EMBEDDING_MODEL`、`VT_RAG_EMBEDDING_DEVICE` 和
`VT_RAG_EMBEDDING_BATCH_SIZE` 调整。模型不可用时自动退回BM25。
新环境若要启用语义检索，安装 `requirements-rag.txt`；已有PyTorch/Transformers环境
无需重复安装。

下载方式（在 Web 环境安装好 requirements-rag.txt 后）：

```powershell
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-small-zh-v1.5', local_dir='../models/bge-small-zh-v1.5', allow_patterns=['config.json','model.safetensors','tokenizer.json','tokenizer_config.json','special_tokens_map.json','vocab.txt','README.md'])"
```

需能访问 Hugging Face；也可从官方模型仓库手动下载这些文件，不要重复下载 pytorch_model.bin。
将 .env 的 VT_RAG_EMBEDDING_MODEL 指向该目录。不下载模型仍可使用 BM25。

在数据量仍是一两本教材时，直接将float32向量保存在SQLite并通过NumPy做余弦相似度搜索，
暂时不必部署Milvus、Elasticsearch或独立向量数据库。只有教材数量和并发明显增加后，
再评估FAISS或外部向量服务。

## 与语音输入的关系

开发顺序可以先完成RAG再做ASR，两者便于独立测试；真实运行顺序必须是：

```text
麦克风语音 → ASR转文字 → 教材RAG检索 → LangGraph/LLM → TTS → FLOAT
```

RAG不能直接检索原始声音，所以它在功能开发排期上位于ASR之前，在在线请求链路中位于
ASR之后。
