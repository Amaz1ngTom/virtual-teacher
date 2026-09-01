# 启动脚本导航

日常使用只需要进入对应模式目录，按文件名前的编号依次执行。

| 模式 | 目录 | 用途 |
| --- | --- | --- |
| 无 FLOAT | `no_float` | 只启动虚拟教师网页；文本问答、课程管理、PDF与RAG功能可用，不生成说话视频。 |
| 本地 FLOAT | `local_float` | 在本机启动 FLOAT Worker，再启动网页。 |
| 远程 FLOAT | `remote_float` | 连接远程 GPU Worker并建立SSH隧道，再启动网页。 |
| 维护工具 | `maintenance` | 部署、诊断、PDF拆分、素材生成和发布检查；不是日常启动步骤。 |

为了兼容之前使用过的命令，根目录暂时保留
`start_remote_float_session.ps1`，它会转发到远程FLOAT组的新入口。

所有命令都应从项目根目录执行。网页端口可以作为最后一个参数传入，默认是 `8000`，
例如：`scripts\no_float\01_start_web.bat 8001`。
