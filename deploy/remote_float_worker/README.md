# 远程 FLOAT Worker 部署

此目录是模板，不是完整 FLOAT 工程。先从项目根目录运行
`scripts/maintenance/build_remote_worker_bundle.ps1`，
把生成的目录内容上传到服务器的 Worker 目录。部署包包含 server.py、脚本、示例图片和通知，
不含 FLOAT 源码、权重或 Python 环境；也不会覆盖已有服务器文件。

## 首次配置

1. 按上游 README 在服务器单独部署 FLOAT，并确认能正常推理。
2. 激活其环境，在 Worker 目录安装本适配器 requirements.txt。
3. 复制 worker.env.example 为 worker.env，填写 FLOAT_ROOT、FLOAT_ENV、
   **分配给你的物理 GPU 编号 PHYSICAL_GPU**、WORKER_PORT 和 SESSION_NAME。
4. 确认已安装 GNU Screen；不需要再装 tmux。
5. 执行 `bash start_worker.sh`，再用 `bash check_worker.sh` 检查 ready。
   查看加载情况：`tail -f logs/worker.log`。

例如部署目录是 /workspace/virtual-teacher-worker：

```bash
cd /workspace/virtual-teacher-worker
conda activate FLOAT
python -m pip install -r requirements.txt
cp worker.env.example worker.env
# 先编辑 worker.env，不要直接跳过。
bash start_worker.sh
bash check_worker.sh
```

没有配置 GPU 时脚本会拒绝启动，避免抢占共享服务器其他人的卡。
显式限制后，进程中的 cuda:0 代表你选择的物理卡，不需要修改模型内部 rank=0。
查不到 Conda 时可以在 worker.env 设置 CONDA_SH；端口/Screen 名称由使用者避免冲突。

脚本不会注册开机启动。Screen 可以在 SSH 断开后保持 Worker 运行，因此仍会占用显存。
查看控制台：`screen -r float-worker`；离开但保持运行：Ctrl+A 后按 D。
停止你配置的会话并释放资源：`bash stop_worker.sh`。
check_worker.sh 支持 curl，也支持已激活环境的 Python 回退。

## 本机 SSH 隧道

Worker 仅监听服务器 127.0.0.1，默认8011。保持本机 SSH 窗口开启：

```powershell
ssh -N -L 18011:127.0.0.1:8011 -p <SSH端口> <用户名>@<服务器地址>
```

本机 Web 的 .env 设置：

```env
VT_FLOAT_WORKER_URL=http://127.0.0.1:18011
VT_FLOAT_TRANSFER_MODE=upload
```

本机 http://127.0.0.1:18011/health 应返回 ready。
更方便的“启动服务 + 隧道”入口是项目 scripts/remote_float/01_start_session.ps1；
自定义服务器 Worker 端口时同时填写 RemoteWorkerPort，本地隧道端口也需与 Web 配置对应。
不要把 SSH 密码写入脚本、worker.env 或 Git，使用交互输入或 SSH 密钥。

已有部署不需要为了更新发布文档重启服务。要升级 Worker 时先备份旧部署与配置，在无任务时
更新这份包；保留个人 worker.env，不用示例文件覆盖它。源代码许可与 FLOAT 边界见包内
THIRD_PARTY_NOTICES.md；assets/README.md 说明默认示例图，自选图则需自行核对权限。
