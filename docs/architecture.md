# 系统实现导航

整体流程图见根目录 README。以下是代码与职责映射，方便阅读和面试讲解。

| 模块 | 文件 | 职责 |
| --- | --- | --- |
| 教学编排 | app/graph.py、app/lessons.py | LangGraph 路由、课程状态、确定性判题、临时提问 |
| 模型输入输出 | app/prompts.py、app/adapters/llm.py | 模板、上下文组装、结构化响应解析与校验 |
| 持久化 | app/profile_store.py、app/conversation_store.py | 用户偏好、学习进度、自由问答历史；SQLite checkpoint 保存线程状态 |
| 教材导入与课程设计 | app/course_import.py、app/course_design.py、app/course_import_store.py | PDF 提取/章节、分批生成、编辑校验、发布记录 |
| 检索 | app/rag.py、app/embeddings.py | BM25 与本地 BGE 的融合排序、页码出处 |
| ASR | app/asr.py、app/asr_api.py、frontend/src/SpeechInput.tsx | 录音识别，输入框回填，不自动发送 |
| 语音与视频 | app/adapters/tts.py、app/adapters/float_renderer.py、float_worker/server.py | 云 TTS、本地/远程 Worker 适配、单队列推理 |
| 分段与缓存 | app/text_segmentation.py、app/speech_text.py、app/course_media_cache.py | 中英断句、术语朗读规范化、确定性课程媒体复用 |
| 页面与接口 | frontend/src/App.tsx、app/api.py | 历史列表、课程管理、媒体预加载/跳过与请求状态 |
| 可观测性 | app/pipeline_metrics.py、app/trace_viewer.py | 阶段计时、模型原始请求响应排查 |

## 三类状态不要混淆

- `thread_id`：该会话的上下文与教学状态；新建问答不等于继续上一会话。
- `user_id`：可跨会话共享的偏好/学习档案；不是身份认证，也不是所有旧聊天都注入提示词。
- 确定性课程定义与媒体缓存：课程内容及可复用结果；与用户私有历史分开存储。

恢复历史问答会恢复该线程；进入固定课程走新的课程会话。只有固定内容进入课程媒体缓存。
RAG 只在已绑定教材且建立索引的课程提问分支中使用，不是无条件搜索全部导入资料。

## 可替换边界

文本和 TTS 经适配器调用云端接口；FLOAT Worker 在独立 Python 环境中加载模型。
本地共享文件路径与远程上传/下载两种传输方式共用服务接口。
Web 的 CPU ASR 和 BGE 不依赖 FLOAT GPU；模型按需要加载。

预加载能用播放时间覆盖后续生成时间，但不能消除首轮 LLM/TTS/推理等待。
当前实现不是神经网络原生逐帧流式输出，也不是全双工语音通话。
