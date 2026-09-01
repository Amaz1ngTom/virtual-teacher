# 本地语音输入（ASR）

## 使用方式

1. 用 Chrome/Edge 打开本机教学网页，找到输入框下方的“语音输入”。
2. 点击后允许麦克风权限，开始讲话。
3. 点击“停止并识别”，麦克风随即关闭，本地CPU将录音转成文字。
4. 文字追加到已有输入后面，可以修改；只有手动发送才进入原有教学流程。
5. 不想使用本段录音时点击“取消”。单次最长60秒，到达上限自动停止并识别。

ASR不调用千问，也不调用TTS/FLOAT，不需要API Key或4090服务。录音不保存到磁盘，识别文本
不记录到日志或历史；只有用户确认发送的文字才成为对话记录。取消已提交的识别会丢弃结果，
但已经开始的本地推理可能仍会短暂运行到结束，不会产生API费用。

连续自动讲授或已经提前提交一问时，沿用原有提交限制；请先暂停讲授/等当前请求结束。
普通回答视频播放时可以录音，建议佩戴耳机，避免扬声器中的教师语音被麦克风一起录下。
第一版没有始终监听、VAD自动断句、唤醒词或语音打断。无麦克风也可继续打字。

## 环境与模型

- 引擎：`sherpa-onnx==1.13.6`，CPU执行，默认2线程；不依赖PyTorch或CUDA。
- 模型：SenseVoiceSmall INT8 ONNX，自动识别中英文等语言，启用数字与标点规范化。
- 权重约228.2MiB；默认保存在项目同级 `models/sensevoice-small-int8`，不进入Git仓库。
- 懒加载：启动网页只检查文件，第一次有声录音才加载；之后模型留在Web进程内复用。
  运行时会占CPU内存，不占FLOAT显存；模型文件大小不等于实际运行内存。
- 初次下载需要联网，之后语音识别离线进行，没有云端ASR或云端失败回退。

在运行Web的Python环境中执行（不要在独立FLOAT环境里装）：

```powershell
python -m pip install -r requirements-asr.txt
python scripts/maintenance/download_asr_model.py
```

下载脚本只取INT8模型、词表和许可证，不克隆项目、不下载FP32模型；校验模型SHA-256。
支持 `--output-dir <MODEL_DIR>`；如更改位置，在 `.env` 设置 `VT_ASR_MODEL_DIR`。
`VT_ASR_NUM_THREADS` 可设为1～4。安装完成后重新启动Web服务，刷新页面。
不用新增Conda环境，不用给远程4090安装ASR。

模型与Python调用参考：[sherpa-onnx SenseVoice说明](https://k2-fsa.github.io/sherpa/onnx/sense-voice/pretrained.html)。
下载保留模型自带LICENSE；未来整合包再分发时须核对模型与引擎各自许可证，不由主项目许可证覆盖。

## 接口和前端

- `GET /v1/asr/status`：依赖与文件就绪状态、是否加载、CPU设备、最长录音时间；不加载权重。
- `POST /v1/asr/transcribe`：原始WAV请求体，`Content-Type: audio/wav`；返回text、language、
  audio_seconds、elapsed_ms、device等，不进入LangGraph。
- 接受0.25～60秒、单声道、16位PCM WAV、8～48kHz，最多6MiB；超限和格式错误有明确提示。
- 浏览器使用AudioWorklet采集PCM并编码WAV，因此不需要FFmpeg解码WebM，也不调用浏览器云端语音识别。
- 同时只执行一次ASR推理，不会因重复请求加载多个模型。
- HTTPS或localhost/127.0.0.1下可使用麦克风；普通局域网HTTP地址可能被浏览器拒绝。

## 验证（2026-09-01）

- 后端120项离线测试通过，含14项ASR测试；测试不依赖真实模型，也不调用付费API。
- 前端lint/build通过；PCM编码、尾帧保留、60秒限制共3项离线测试通过。
- 实际CPU样例：5.592秒中文首次识别含模型加载约1.97秒；随后7.152秒英文约0.25秒。
- 现有8.16秒教师TTS音频也已识别，无重新合成语音。
- Edge无头浏览器使用现成WAV模拟麦克风，实际跑通AudioWorklet→接口→模型→输入框。
  已验证保留原输入、不自动发送、取消录音、丢弃迟到结果、空识别、权限拒绝和迟到授权释放。
- 上述耗时只是本机少量样例，不是准确率评测；用户真实麦克风、口音、噪声与代码名词仍需体验。

```powershell
python -m unittest discover -s tests -v
cd frontend
node --experimental-strip-types --test tests/audio-recorder.test.mjs
```

可选浏览器验收脚本 `frontend/tests/asr-browser.cjs` 需要开发机提供Playwright及Chrome/Edge，
不属于运行项目的依赖。使用隔离的本机测试服务（默认8002）、设置 `ASR_TEST_WAV` 指向现有
WAV再运行；脚本拦截所有非ASR的POST请求，防止意外消耗API。不要用测试脚本录用户真实麦克风。
