# Virtual Teacher Web

React + TypeScript + Vite 前端。安装与产品说明见项目根目录 README。

```powershell
npm ci
npm run lint
node --experimental-strip-types --test tests/audio-recorder.test.mjs
npm run build
```

从项目根目录运行 Python Web 服务后，同源托管 frontend/dist。
开发时可使用 npm run dev，API 代理设置见 vite.config.ts；不把 API Key 放在浏览器环境变量里。

ASR 浏览器集成验收见 ../docs/asr.md；Playwright 仅为可选开发测试依赖。
