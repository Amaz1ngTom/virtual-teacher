# 本地 FLOAT 模式

先按根目录 README 独立部署 FLOAT，并在 .env 填写 VT_FLOAT_ROOT / VT_FLOAT_PYTHON。
脚本本身不包含个人目录；Web 解释器使用当前环境或 scripts/local.settings.bat。

1. 运行 `01_start_worker.bat`，等待 `http://127.0.0.1:8011/health` 返回 ready。
2. 保持 Worker 窗口开启，运行 `02_start_web.bat`。
3. 打开脚本显示的网页，默认 http://127.0.0.1:8000。
4. 结束后先关 Web，再关 Worker，释放本机显存。

可给脚本传端口，例如 `02_start_web.bat 8001`。
本组 Web 包装脚本固定选择本地 Worker 8011；若自定义 Worker 端口，请修改 .env 并直接使用
`python -m app.launch web`，不要用固定端口包装脚本。
