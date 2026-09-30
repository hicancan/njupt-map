# 观测采集与来源

按 images、videos、plans、maps、spatial 与 documents 分类，唯一来源目录为 observations/catalog.json。分类表示用途，不区分人工采集与自动取得。

## 加入新资料

```powershell
uv run python -m src.observations ingest 'D:\capture\campus.mp4' --id campus-walk --kind videos --license CC-BY-4.0
uv run python -m src.observations.video_review --source-id campus-walk
# 完成 observations/annotations/video-review/ 中的完整时间线与明确选帧后
uv run python -m src.observations.curate_video --source-id campus-walk
uv run python -m src.observations.validate --hashes
uv run python -m src.observations export-ignore --write
```

只有用户拥有且明确愿意按 CC BY 4.0 公开的素材才用 CC-BY-4.0。第三方资料未声明分发许可时使用 unknown，保留本地。正式选帧继承原视频的许可和来源关系。

候选预览进入 build/processing/observations。审查清晰度、遮挡、重复程度、对象和方向后，将有效帧正式入库，并保存时间点与筛选原因。原视频继续保留。

## 空间绑定

先确认建筑或组团，再确认立面、楼层、部件与控制点。不明确的楼号、尺寸和相机位置保持未知或推定说明；一次近似对应不自动构成精确三维测量。

一项观测可支持多个对象，一个对象可对应多项观测。共同空间事实进入 GeoPackage，三维细节进入 Blender；来源目录不维护第二套校园几何。

## 本地与公开

公共索引保留来源地址、散列、许可和绑定。23 张教学楼疏散图含二维码和消防内容，保留本地作为可选参考，不进入公共 Git 历史，也不打包到公开 Blender 文件。

这些楼层图的已审阅房间标签和归一化轮廓进入 `projects/blender/design/interiors.json`，通过现有楼层绑定生成可编辑室内。原件不公开不妨碍公开工程保存当前创作的网格；生成过程不把照片像素作为材质打包。

图书馆新增来源为 [官方楼层布局页](https://lib.njupt.edu.cn/_t83/lcbj/list.htm) 的二、三、四、五层图，目录 ID 为 `library-official-floor-02` 至 `library-official-floor-05`。楼层、房间标签、阅览区和中庭关系来自图示；图示到建筑的方向与米制尺度属于近似配准。网页获取日期与图中校园现状日期分开记录，未知发布时间不猜测。原图目前仍按权限未知的第三方资料留在本地。

视频补充图书馆和第二食堂的室内外观。不能确认层号的图书馆空间保留未知观测层号，同时允许三维工程给出明确的当前设计位置；模型位置不反向变成观测事实。

检查默认允许公共检出缺少 local_only 原件；`--strict-local` 检查本地完整资料，`--hashes` 校验已有原件。新增资料的公开策略须与 Git 忽略规则一致。失败下载保留状态，不作为已取得原件。

许可须查看具体 catalog 条目。来源 URL 表示可追溯，不表示已经获得再分发许可。参见 [许可范围](../LICENSES.md)。

网页采集由 `src/observations/collect.py` 提供，使用 `--help` 查看当前参数。可选的 PDF 字形提取工具 `src/observations/extract_identity.py` 需要 `uv sync --locked --extra observations` 安装 PyMuPDF；正常打开、编辑与渲染校园不需要该额外依赖。
