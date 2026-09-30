# 视频时间线审查

原视频保留于 `observations/videos/`，该目录被 Git 忽略。来源、权限、发表日期与内容哈希由 `observations/catalog.json` 管理；发表日期不代表拍摄日期。

## 完整时间线预处理

```powershell
uv run python -m src.observations.video_review --all
uv run python -m src.observations.video_review --source-id bilibili-BV1jD4y1z7Zu --interval 2
```

程序校验原视频哈希，顺序解码完整视频，合并固定时间网格与画面变化候选。短视频默认每秒、超过半小时的视频默认每两秒抽取；切点前后各 0.12 秒的连续邻帧由第二次顺序解码补充，避免仅靠时间网格遗漏短插入画面。没有为每帧重新从头解码。

结果写入 `build/processing/observations/video-review/<BV>/`，不修改原视频或正式观测目录：

- `manifest.json`：来源哈希、真实整数 PTS、time base、准确源时间、变化阈值、切点、候选帧和页面索引。
- `frame-<PTS毫秒>.jpg`：240 × 135 候选缩略图。
- `sheet-001.jpg` 等：每页 64 张、8 × 8，时间顺序排列，显示来源 ID 与准确时间标签。
- `timeline-decode.log`、`cut-neighbours-decode.log`：解码日志。

`grid` 表示常规抽样，`cut` 表示超过阈值的画面变化，`near-cut` 表示切点邻帧。镜头运动、字幕和光照也可能触发变化；慢速渐变也可能不触发。切点不是人工镜头边界，候选页不是逐帧观看的证明。需要判断招牌、门牌或细部时，应从原视频提取清晰帧或查看对应连续片段。

```powershell
uv run python -m src.observations.video_review --source-id bilibili-BV1aj411m7PU --full-at 25 26
```

此命令用一次顺序解码输出原分辨率 `detail-<PTS毫秒>.jpg`，并在 `details.json` 记录请求时间和实际源 PTS，不重建审查页。

所有候选继承原视频的传播权限。只有经选择、说明用途并绑定对象的清晰帧才进入正式观测；筛选结果不可因为能从视频重新生成而被视为一次性输出。

## 正式审查记录

每个视频的当前审查位于 `observations/annotations/video-review/<BV>.json`。`source_id`、`source_sha256` 和 `duration_seconds` 绑定具体内容；`segments` 无缝无重叠覆盖 `[0, duration_seconds)`。

每段使用 `start_seconds`、`end_seconds`、`campus`、`status`。校区为 `xianlin/sanpailou/other/unknown`，状态为 `accepted/excluded/unknown`。只有确认属于仙林的片段可以进入当前建模集合。未知段必须说明限制，排除段必须说明原因。`eligibility` 进一步区分当前候选、历史排除、其他校区排除与待核验。原片保留，因此排除不代表删除来源。

`asset_ids` 引用 GeoPackage 的共同对象 ID；`map_object_ids` 引用各地图层的共同对象 ID，适用于道路、POI 等尚无 Blender 单体的对象；`map_feature_ids` 只引用 GeoPackage 中实际存在的第三方地图 ID，该字段为空时不可临时编造；`place_ids` 引用空间关系图中的位置。`selected_frame_pts_seconds` 记录精选点的实际解码时间，`review_frame_pts_seconds` 记录审查过的候选源 PTS。室内楼层、房间和路段可以拥有位置 ID，即使尚无三维模型。每段可以保留 `place_label`、`observed_features`、`uncertainties`、`basis` 与 `confidence`。

`observed_connections` 使用 `{from_place_id, to_place_id, relation, basis, confidence, notes}`。依据可以是 `continuous_shot/plan/cross_reference/inferred`。剪辑切换不能单独证明空间连接，`inferred` 关系不能当作已核验连接。相邻、可见和实际可通行是不同关系。

```powershell
uv run python -m src.observations.video_review --validate observations/annotations/video-review/BV1jD4y1z7Zu.json --places observations/bindings/topology.json
```

验证只检查身份、时间覆盖和引用合法性，不能自动证明人工地理判断准确。未知地点是明确记录的覆盖缺口；不能用臆测标签填满来宣称校园已经全部理解。

## 本地浏览与总体验证

```powershell
uv run python -m src.observations.review_export --validate
uv run python -m src.observations.review_export
```

总体验证检查全部已登记 B 站视频都有完整审查、每段时间覆盖和对象引用合法、拓扑节点和关系均有具体来源/分段依据、正式精选帧的源 PTS 与审查精选点一致。推断连接不能标作已核验。可在其他验证代码中调用 `validate_review_sources(root)` 获取错误列表。

导出写入 `build/review/index.html`、`summary.json`、`coverage.json`、`summary.md`。浏览器支持校区、状态和时态过滤，保留完整时间条，点击时间段播放本地原视频，点击地点高亮相应父地图对象，并查看正式精选帧与拓扑依据。地图形状来自本次读取的 `projects/map/campus.gpkg`；地点的父对象绑定不等于入口测量坐标，更不等于重建相机姿态。

此页面只用于本地审查，包含指向受限原视频/精选帧的相对链接，不应作为公开网站发布。源资料不依赖导出的浏览器、报表或覆盖统计；后者随当前正式数据重建。


## 原分辨率选帧与持续维护

```powershell
uv run python -m src.observations.curate_video
uv run python -m src.observations export-ignore --write
uv run python -m src.observations.review_export --validate
uv run python -m src.observations.review_export
```

仅 `accepted/xianlin/current_candidate` 的明确精选点能够提升。程序按整数源 PTS 顺序解码，原分辨率 PNG 保存在 `observations/images/bilibili/<BV>/`，名称和来源 ID 使用原始 ticks；catalog 同时保存整数 PTS、time base、秒数、原视频 SHA、许可及语义绑定。请求时刻不能伪装为真实帧时刻，发表日期不能伪装为拍摄日期。

重复运行不会替换已有图像。审查的段 ID 或空间绑定演进时，应同时更新正式图像元数据、段内引用和资产绑定；不一致会明确报错，不能默默保留过期关系或覆盖已校准观测。新增精选点只生成新增图像。清晰立面帧与运动过渡帧用途不同，模糊过渡帧可支持路径判读，不应作为精细纹理来源。

`observations/bindings/topology.json` 持续维护带具体片段来源的地点及关系。一个场所可在不同视频重复出现；尚未确认同一实体的观测节点不强行合并。`semantic_parent_only` 只说明关联的父建筑或地图对象，`unregistered` 表示几何尚未配准；二者均不提供测得房间坐标、门口坐标或相机姿态。模型差异由 `observations/annotations/model-findings.json` 记录，明确区分已存在、已发现差异和待核对项。

本批完成 16 个视频的全时长候选审查，共 7,108 个候选帧、118 页、373 段，91 张正式精选帧。历史与非仙林资料排除当前输入；2025 现状未核实；当前候选仍需部件级核验。23 张既有教学楼平面图没有因为本批视频完成而自动获得几何配准。

长导览的机器语音转写保留在 `build/`，仅用于辅助辨认讲述地名；30 秒分块没有词级时间对齐，讲述地点可能与插入画面不同。可选的 `src/observations/transcribe_video.py` 使用已有隔离 Qwen3-ASR 环境和 GPU；输入散列、模型与分块长度共同约束中断恢复，不加入地图/Blender 的运行依赖。
