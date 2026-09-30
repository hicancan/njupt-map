# 校园观测

`catalog.json` 是唯一来源索引，`bindings/` 将来源关联到两个工程共用的建筑 ID、楼层、部件和空间基准。图片、视频、平面图、地图图片、空间数据及原始网页资料分别归入 `images/`、`videos/`、`plans/`、`maps/`、`spatial/` 和 `documents/`。目前没有已采集的现实校园视频；渲染宣传片不属于现实观测。

拍摄时间、发表时间和取得资料的时间分别记录。无法确定的拍摄时间保持 `null`。建筑 ID 的关联不表示已经解算相机位置；没有实际标定的控制点和相机姿态留空。绑定通过实体 ID 引用地图位置，避免另一份建筑中心坐标随更新漂移。

正式楼层图保留原始照片；已有图片范围和参考平面摆放参数保存在楼层绑定中，明确标记为近似配准。它们可以辅助建模，不构成实测室内模型。观察到的形状、文字资料记载和尺寸推断分别记录在 `assertions` 中，保留缺口和不确定性。

视频先保存原件，再生成候选预览进行筛选。正式选帧进入 `images/`，同时记录原视频 ID、SHA-256、请求时点、实际解码帧时间和选择理由。候选预览进入 `build/processing/observations/`。

```powershell
uv run python -m src.observations ingest D:/capture/walk.mp4 --id xianlin-walk --kind videos --license unknown
uv run python -m src.observations preview-video --source-id xianlin-walk --interval 5
uv run python -m src.observations select-frame --source-id xianlin-walk --at 12.5 --asset-id osm_way_223699451 --component south-entrance --reason "入口侧面清楚显示柱梁和石材接缝"
uv run python -m src.observations export-ignore --write
uv run python -m src.observations.validate --hashes --public
```

选帧需要 FFmpeg 和 FFprobe。`select-frame` 是视觉筛选后的接受步骤，不会将所有候选帧自动认定为有效观测，也不会把视频偏移秒数当作相机拍摄日期。

网页资料可以通过 `uv run python -m src.observations.collect --url <来源页面> --id <来源ID> --images` 取得；此工具记录访问失败，不绕过来源网站的访问限制。新来源应继续进行相关性、建筑身份和时效性检查。

`redistribution.status` 为 `local_only` 的媒体留在本地，公开仓库只包含来源元数据和绑定。取得一张学校照片或实拍一张疏散图，不会自动取得其中第三方图像或图纸的再分发许可。23 张原始疏散图及联系表没有纳入公共仓库，二维码、消防细节等也不写入公开索引。公开版本缺少这些本地资料时，普通验证仍可通过；本地完整性检查使用 `--strict-local`。

新增或明确许可后运行 `export-ignore --write`，从当前索引更新仓库的媒体排除块。`validate --public` 会拒绝已被 Git 跟踪的未许可媒体，避免一次 `git add .` 将新取得的原件意外公开。
