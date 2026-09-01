# GitHub 仓库展示文案

## 仓库名称建议

`virtual-teacher`

## About / Description

基于 LangGraph 的虚拟教师：PDF 教材生成可审核课程、教材 RAG、本地语音输入，以及 Qwen TTS + FLOAT 分段说话视频；支持本地与远程 GPU Worker。

## Topics

`virtual-teacher` `langgraph` `rag` `pdf` `qwen` `tts` `asr` `talking-head` `fastapi` `react` `education`

## 首个版本建议

版本：`v0.1.0`（演示版，不宣称生产就绪）。

- 自由问答、动态连续讲授、固定课程讲授和互动练习。
- PDF 整本导入、章节识别、课程草稿审核发布与课程管理。
- BM25 + BGE 教材混合检索，回答展示原始 PDF 页码。
- CPU 本地语音输入，识别后可编辑并手动发送。
- Qwen TTS 与独立 FLOAT Worker，分段生成、预加载播放与确定性课程媒体缓存。
- 本地/远程 GPU 两种部署方式，远程通过 SSH 隧道连接。

已在开发环境验证；尚未进行全新环境安装验证。不包含第三方模型、教材、API Key、历史对话和视频缓存。
真实设备性能与云服务延迟会影响体验；接入 FLOAT 时需遵守上游非商业等限制。

发布建议附三种教学模式截图及一段短演示视频。不要上传个人账户、教材正文或真实 SSH 配置截图。
