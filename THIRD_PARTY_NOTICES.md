# 第三方组件与素材说明

核对日期：2026-09-01。根目录 MIT 许可证仅适用于本项目原创软件与文档，不重新许可
第三方源码、模型、教材、服务或生成素材。安装依赖时应保留它们自己的许可证。
本文是来源与使用边界记录，不是第三方商业授权或不侵权保证。

## FLOAT：单独安装的可选推理后端

- 作者项目：[deepbrainai-research/float](https://github.com/deepbrainai-research/float)。
- 论文：[FLOAT: Generative Motion Latent Flow Matching for Audio-driven Talking Portrait](https://arxiv.org/abs/2412.01064)。
- 本项目只提供独立 Worker 适配接口，不附带 FLOAT 模型实现、权重或 Conda 环境。
- 上游 [README 的 License 部分](https://github.com/deepbrainai-research/float#license)
  标注 **CC BY-NC-ND 4.0**，而 [LICENSE.md](https://github.com/deepbrainai-research/float/blob/main/LICENSE.md)
  正文标题是 **CC BY-NC 4.0**。两者存在不一致，本文不擅自裁定，也不将其概括成宽松商用授权。
- 两处均有非商业限制。使用 FLOAT 的完整系统需遵守实际适用的上游条款；修改、再分发或
  商业使用前应向上游确认。主项目采用 MIT 不会解除 FLOAT 的限制。
- 开发工作区中的 FLOAT 裁剪复现辅助脚本不包含在公开源码快照中。

研究中使用 FLOAT 时请按上游要求引用：

```bibtex
@inproceedings{ki2025float,
  title={Float: Generative motion latent flow matching for audio-driven talking portrait},
  author={Ki, Taekyung and Min, Dongchan and Chae, Gyeongsu},
  booktitle={Proceedings of the IEEE/CVF International Conference on Computer Vision},
  pages={14699--14710},
  year={2025}
}
```

## 运行依赖

此表记录主要直接依赖，不代替安装包内的完整许可证与传递依赖清单。

| 组件 | 用途 | 上游许可证 / 来源 |
| --- | --- | --- |
| LangGraph、SQLite checkpoint 扩展 | 状态编排与持久化 | [MIT](https://github.com/langchain-ai/langgraph/blob/main/LICENSE) |
| OpenAI Python SDK | 调用 OpenAI 兼容的千问接口，不代表调用 OpenAI 模型 | [Apache-2.0](https://github.com/openai/openai-python/blob/main/LICENSE) |
| FastAPI | Web API | [MIT](https://github.com/fastapi/fastapi/blob/master/LICENSE) |
| Uvicorn | ASGI 服务 | [BSD-3-Clause](https://github.com/encode/uvicorn/blob/main/LICENSE.md) |
| Requests | HTTP 客户端 | [Apache-2.0](https://github.com/psf/requests/blob/main/LICENSE) |
| python-dotenv | 本地配置 | [BSD-3-Clause](https://github.com/theskumar/python-dotenv/blob/main/LICENSE) |
| pypdf | PDF 文字与书签提取 | [BSD-3-Clause](https://github.com/py-pdf/pypdf/blob/main/LICENSE) |
| NumPy | 向量计算与音频输入 | [BSD-3-Clause](https://github.com/numpy/numpy/blob/main/LICENSE.txt) |
| PyTorch | 可选本地嵌入模型 | [BSD 风格及附带第三方通知](https://github.com/pytorch/pytorch/blob/main/LICENSE) |
| Transformers、Safetensors | 可选模型加载 | [Apache-2.0](https://github.com/huggingface/transformers/blob/main/LICENSE)、[Apache-2.0](https://github.com/huggingface/safetensors/blob/main/LICENSE) |
| React | Web 界面 | [MIT](https://github.com/facebook/react/blob/main/LICENSE) |
| Vite | 前端构建 | [MIT](https://github.com/vitejs/vite/blob/main/LICENSE) |
| TypeScript | 前端类型检查 | [Apache-2.0](https://github.com/microsoft/TypeScript/blob/main/LICENSE.txt) |
| Oxlint | 前端静态检查 | [MIT](https://github.com/oxc-project/oxc/blob/main/LICENSE) |
| sherpa-onnx | 可选 CPU ASR 引擎 | [Apache-2.0](https://github.com/k2-fsa/sherpa-onnx/blob/master/LICENSE) |

## 可选权重：不包含在源码包中

- **BAAI/bge-small-zh-v1.5**：[官方模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5)，
  标注 MIT。由用户单独下载，用于 CPU 语义检索。
- **SenseVoiceSmall INT8 ONNX**：[sherpa-onnx 模型来源](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)。
  注意区分 SenseVoice 源代码与模型：[源代码](https://github.com/FunAudioLLM/SenseVoice)是 MIT；
  [官方权重模型卡](https://huggingface.co/FunAudioLLM/SenseVoiceSmall/blob/main/README.md)
  指向单独的 [FunASR MODEL_LICENSE](https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE)。
  不能因为引擎是 Apache-2.0 或代码是 MIT，就把权重也标成同一种许可。
- **千问文本/TTS**：使用用户自己的阿里云百炼账户和 API Key，遵守相应服务条款与计费规则；
  本仓库不附带其模型权重、额度或商业授权。参考[百炼官方文档](https://help.aliyun.com/zh/model-studio/)。

## AI 示例图片与用户资料

示例人像的生成模型、具体版本、文件清单和使用说明见 [assets/README.md](assets/README.md)。
这是模型输出图片，不是麦橘模型权重。示例图片不自动继承代码的 MIT 许可证。
待机视频暂不随公开源码快照分发，用户可自行配置有权使用的视频。

教材、从教材生成的课程、用户录音/对话和 TTS/FLOAT 输出均不包含在公开源码快照中。
使用者需自行确认上传、发送到云端以及公开这些内容所需的权利；带页码引用不等于获得再分发授权。
