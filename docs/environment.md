# 环境与安装边界

本项目提供依赖清单，不分发 Python/Conda 环境。此次发布整理没有新建环境或重新安装依赖。
以下是开发环境与复用既有解释器的验证记录，不是“全新电脑安装已通过”的声明。

## 两套环境的分工

| 环境 | 组件 | 是否必须 |
| --- | --- | --- |
| Web（Python 3.10） | FastAPI、LangGraph、PDF、Qwen API 客户端 | 必须 |
| 同一个 Web 环境中的可选依赖 | BGE 检索的 PyTorch/Transformers、ASR 的 sherpa-onnx | 按需 |
| FLOAT 环境 | 用户自行部署的 FLOAT 与其 PyTorch/CUDA 依赖 | 仅说话视频需要 |

不启用语义检索和 FLOAT 时，Web 不要求安装 PyTorch。仅 ASR 也不需要 PyTorch/CUDA。
不需要 Ollama，也不需要另行克隆 LangGraph、RAG 或 ASR 工程。

## 已用版本（2026-09-01）

- Windows 11，Python 3.10.16；Node.js 24.20.0、npm 11.19.0。
- LangGraph 1.2.11、langgraph-checkpoint-sqlite 3.1.1、OpenAI SDK 2.54.0。
- FastAPI 0.115.9、Uvicorn 0.34.0、pypdf 6.16.2、NumPy 1.26.4。
- 可选 RAG：PyTorch 2.1.0+cu118、Transformers 4.41.0、Safetensors 0.4.5。
  这是开发机已有组合；CPU 检索不要求安装 CUDA 版本的 PyTorch。
- 可选 ASR：sherpa-onnx 1.13.6、SenseVoiceSmall INT8 ONNX。
- React 19.2.8、Vite 8.2.2、TypeScript 6.0.2；前端以 package-lock.json 为准。
- FLOAT：本地 RTX 4060 8GB，以及 Linux 远程 RTX 4090；其环境由用户独立安装。

新用户先安装 requirements.txt；可选语义检索再装 requirements-rag.txt，ASR 再装
requirements-asr.txt。主依赖清单使用兼容区间而非整个开发环境的 pip freeze，未来解析出的
版本可能不同，遇到问题请提供版本与脱敏日志。前端使用 npm ci 复现锁文件。

## 本机配置不进入 Git

`.env` 配置 API Key、模型地址和素材路径，相对路径以项目根目录为基准。
Windows 双击脚本需要指定解释器时，将 `scripts/local.settings.example.bat` 复制为
`scripts/local.settings.bat` 后填写自己的路径。该文件被忽略，不包含在公开源码包中。
不配置时使用当前 PATH 中的 python，因此建议先激活 Web 环境。

Linux/Windows 的 FLOAT 依赖以其上游文档为准。这里只提供服务适配代码，不提供 FLOAT
环境锁文件，也不承诺任意 GPU、驱动或操作系统上都能一键运行。
