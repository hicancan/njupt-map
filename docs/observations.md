# 观测采集与来源

按 images、videos、plans、maps、spatial 与 documents 分类，唯一来源目录为 observations/catalog.json。分类表示用途，不区分人工采集与自动取得。

## 加入新资料

```powershell
uv run python -m src.observations ingest 'D:\capture\campus.mp4' --id campus-walk --kind videos --license owned
uv run python -m src.observations preview-video --source-id campus-walk --interval 5
uv run python -m src.observations select-frame --source-id campus-walk --at 12.5 --asset-id osm_way_223699451 --reason '教1入口和北侧窗列清晰可见'
uv run python -m src.observations.validate --hashes
uv run python -m src.observations export-ignore --write
```

只有用户拥有且愿意按项目许可公开的素材才用 owned。第三方资料未声明分发许可时使用 unknown，保留本地。正式选帧继承原视频的许可和来源关系。

候选预览进入 build/processing/observations。审查清晰度、遮挡、重复程度、对象和方向后，将有效帧正式入库，并保存时间点与筛选原因。原视频继续保留。

## 空间绑定

先确认建筑或组团，再确认立面、楼层、部件与控制点。不明确的楼号、尺寸和相机位置保持未知或推定说明；一次近似对应不自动构成精确三维测量。

一项观测可支持多个对象，一个对象可对应多项观测。共同空间事实进入 GeoPackage，三维细节进入 Blender；来源目录不维护第二套校园几何。

## 本地与公开

公共索引保留来源地址、散列、许可和绑定。23 张教学楼疏散图含二维码和消防内容，保留本地作为可选参考，不进入公共 Git 历史，也不打包到公开 Blender 文件。

检查默认允许公共检出缺少 local_only 原件；`--strict-local` 检查本地完整资料，`--hashes` 校验已有原件。新增资料的公开策略须与 Git 忽略规则一致。失败下载保留状态，不作为已取得原件。

许可须查看具体 catalog 条目。来源 URL 表示可追溯，不表示已经获得再分发许可。参见 [许可范围](../LICENSES.md)。

网页采集由 `src/observations/collect.py` 提供，使用 `--help` 查看当前参数。可选的 PDF 字形提取工具 `src/observations/extract_identity.py` 需要 `uv sync --locked --extra observations` 安装 PyMuPDF；正常打开、编辑与渲染校园不需要该额外依赖。
