# 示例教师素材

## 随源码提供的图片

| 文件 | 用途 |
| --- | --- |
| teacher/real-teacher-002.png | 开发者自己生成的原始 AI 人像，供 FLOAT 参考输入 |
| teacher/real-teacher-002-float-aligned.png | 同一人像的裁剪对齐版，用于网页静态展示 |
| example/teacher.svg | 本项目原创几何占位图，适合纯文本预览，不能作为 FLOAT 人脸输入 |

前两项不是现实人物照片。原图 PNG 参数记录模型别名 `majicmix7`、
模型短哈希 `7c819b6d13`。2026-09-01 与 Civitai 官方记录核对，对应
**Merjic / majicMIX realistic v7**（版本 ID 176425）。
本项目只附生成图片，**没有使用或再分发麦橘权重**。

- [作者发布页](https://civitai.com/models/43331/majicmix-realistic)
- [版本与哈希记录](https://civitai.com/api/v1/model-versions/176425)
- [作者当前使用权限](https://civitai.com/api/v1/models/43331)：允许生成图片商业使用，且不强制署名作者。
- [基础 OpenRAIL 许可](https://github.com/CompVis/stable-diffusion/blob/main/LICENSE)第6条：输出用途仍需符合适用限制。

## 使用范围

开发者将上述 AI 人像作为本项目运行、学习和演示的可复制示例素材提供，不对 AI 输出是否具有
独占版权或第三方权利清理作保证。它们不自动套用代码的 MIT 许可证，也不授予模型权重许可。
另作商业宣传或其他用途时请独立核对适用条款与权利；勿把示例人物宣传为真实教师或官方代言。
原创 SVG 随项目 MIT 许可证提供。

原图保留生成参数供来源追溯。更换人像或叠加其他 LoRA/参考照片时，需重新核对相应权限。

## 待机视频和自己的素材

公开源码快照暂不附带开发机现有待机视频、音频和课程视频缓存；这不影响保留示例静态图片。
云端生成的待机视频需另外核对生成平台条款，用户可以自行放入被忽略的 `assets/private/`：

```env
VT_FLOAT_REFERENCE_IMAGE=assets/teacher/real-teacher-002.png
VT_AVATAR_REFERENCE_IMAGE=assets/teacher/real-teacher-002-float-aligned.png
VT_AVATAR_IDLE_VIDEO=assets/private/idle.mp4
```

第一项是送入 FLOAT 的原始图片，第二项是网页展示图。待机视频缺失时回退静态图。
更换素材时保持静态图、待机视频和说话视频构图一致，避免重复裁剪。无水印不等于获得再分发许可。
