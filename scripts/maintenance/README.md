# 维护工具

这些文件不属于日常启动流程：

| 工具 | 用途 |
| --- | --- |
| build_remote_worker_bundle.ps1 | 生成新的远程部署包，不删除旧包；可用 -ReferenceImage 指定自己的图片 |
| diagnose_float_audio.py | FLOAT 环境内诊断音频预处理；需显式提供 --wav2vec-path |
| generate_wan_idle.py | 按需调用视频生成 API 制作待机视频，会产生费用 |
| split_pdf_by_bookmarks.py | 本地按 PDF 书签拆章 |
| download_asr_model.py | 下载 CPU 语音识别模型，不调用付费 API |
| run_release_checks.ps1 | 现有环境离线测试、前端构建与发布文件扫描 |
| export_github_source.py | 白名单生成公开源码快照及 ZIP；--check 仅扫描 |

除 generate_wan_idle.py 外，以上工具不默认调用付费模型。
开发工作区可能另有裁剪复现辅助工具，该工具不包含在公开源码快照中。
