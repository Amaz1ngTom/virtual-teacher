# 远程 FLOAT 模式

## 执行顺序

1. 运行 `01_start_session.ps1`，输入服务器参数；它会启动远程Worker并建立SSH隧道。
2. 保持SSH窗口开启，确认 `Invoke-RestMethod http://127.0.0.1:18011/health`
   返回 `ready`。
3. 运行 `02_start_web.bat`。
4. 浏览器打开脚本显示的地址，默认是 `http://127.0.0.1:8000`。
5. 关闭SSH窗口只会断开本地隧道；需要释放远程显存时运行 `03_stop_worker.ps1`。

示例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\remote_float\01_start_session.ps1 -SshHost <服务器地址> -SshPort <SSH端口> -SshUser <用户名>
```

多行写法：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass `
  -File scripts\remote_float\01_start_session.ps1 `
  -SshHost <服务器地址> `
  -SshPort <SSH端口> `
  -SshUser <用户名>
```

PowerShell反引号必须是每行最后一个字符，后面不能有空格。密码只在SSH提示时输入，
不要写入脚本、配置文件或Git仓库。
