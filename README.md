# njupt-map

南京邮电大学仙林校区的二维地图与 Blender 三维校园工程。持续整理现实校园的观测，在统一空间基准上维护地图、建筑与场景。

[![njupt-map 宣传片预览](README.assets/film.gif)](https://github.com/hicancan/njupt-map/releases/download/v0.1.0/njupt-map.mp4)

**[观看 / 下载完整宣传片](https://github.com/hicancan/njupt-map/releases/download/v0.1.0/njupt-map.mp4)** · 35 秒 · 1920 × 1080 · 24 fps · 原创配乐。上方为 12 秒动图预览。

[下载便携 Blender 场景](https://github.com/hicancan/njupt-map/releases/download/v0.1.0/njupt-map.blend) · [打开发布页](https://github.com/hicancan/njupt-map/releases/latest)

## 两个持续演进的工程

| 工程 | 正式源稿 | 负责什么 |
| --- | --- | --- |
| 地图 | `projects/map/campus.qgs`、`campus.gpkg` | 地理坐标、校园边界、建筑基底、道路、水面与共同空间参数 |
| 三维校园 | `projects/blender/campus.blend`、`buildings/` | 129 个建筑资产、立面和门头、材质、景观、灯光与相机 |
| 宣传片 | `projects/blender/presentation/film.blend` | 运镜、动画与原创配乐源稿 |

![仙林校园二维地图](README.assets/map.png)

![校园宣传片静帧](README.assets/cover.jpg)

两个工程使用共同对象 ID。GeoPackage 保存投影坐标，Blender 使用校园局部米制坐标；位置变化通过显式转换同步，轮廓变化先检查差异，保留精修模型。

## 获取与打开

正式 `.blend`、`.gpkg`、贴图和媒体使用 Git LFS。安装 Git LFS 后获取完整工程：

```powershell
git lfs install
git clone https://github.com/hicancan/njupt-map.git
Set-Location njupt-map
git lfs pull
```

- **QGIS**：打开 `projects/map/campus.qgs`，直接编辑同目录的 `campus.gpkg`。当前工程在 QGIS 4.2 验证。
- **Blender**：用 Blender 5.2 LTS 打开 `projects/blender/campus.blend`。单栋建筑位于 `projects/blender/buildings/`；主场景链接它们。
- **影片**：打开 `projects/blender/presentation/film.blend`。已有成片可从上方直接获取。

保持目录关系一起移动；工程使用相对引用。便携场景适合快速查看，长期编辑使用仓库内的分栋工程。

## 文件架构

```text
njupt-map/
├── observations/          原始观测、精选图像、来源目录与对象绑定
├── projects/
│   ├── map/               QGIS 工程与唯一可编辑的校园空间数据库
│   └── blender/           校园源稿、分栋资产、材质与影片源稿
├── src/
│   ├── observations/      采集、视频候选预览、正式选帧与观测检查
│   ├── map/               空间读取、导出与检查
│   ├── sync/              共同 ID、坐标与变化检查
│   └── blender/           建模工具、渲染、影片与便携导出
├── tests/                 必要的不变量和同步测试
├── docs/                  架构与工作流程
├── README.assets/         精选文档展示图
└── build/                 可重新生成的输出，不进入 Git
```

**Architecture as ontology. Invariants over ceremony.** 每类成果只有一个正式维护位置；Git/LFS 承担历史，工作目录只保留当前实现。

## 检查与继续完善

Python 3.12 与 uv：

```powershell
uv venv --python 3.12
uv sync --locked
uv run python -m src.map.export
uv run python -m src.map.validate
uv run python -m src.observations.validate --public
uv run python -m unittest discover -s tests -p 'test_*.py'
uv run python -m src.sync
```

地图导出写入 `build/map/`，检查写入 `build/checks/`。`src.sync` 调用 Blender，只读检查校园和影片两个原生场景；确认差异后以 `--apply` 同步位置与名称。轮廓或高度变化会阻止自动应用，留给原生模型精修。已有资产、灯光、相机和动画不会被默认重新生成覆盖。

新照片、视频、平面图和已发布地图进入观测目录。精选视频帧是正式观测，保留原视频来源、时间点、筛选原因与对象绑定；候选帧属于临时处理输出。

[架构与不变量](docs/architecture.md) · [编辑、同步与导出](docs/workflow.md) · [观测采集与来源](docs/observations.md) · [Blender 与影片](docs/blender.md)

## 视频观测审查

已完成本地 16 个 Bilibili 视频的全时长审查：81 分 46 秒，7,108 个候选帧、118 页时间线，整理为 373 个连续地点片段。短视频采用 1 秒网格，长导览采用 2 秒网格，并复查画面变化邻帧及重要原分辨率细节；这不代表每个原始视频帧都经过人工识别。

| 本批结果 | 数量 |
| --- | ---: |
| 当前仙林候选片段 | 42 |
| 历史、其他校区及无效片段排除 | 302 |
| 地点或现状待核实片段 | 29 |
| 正式原分辨率精选帧 | 91 |
| 有具体片段来源的空间关系 | 57 |

三牌楼、锁金村和历史施工画面已分别标记。2025 素材的当前状态未核实；2026 发表日期也不当作拍摄日期。图书馆和第二食堂新增内部空间标签；没有拍到的上下楼、房间号和精确入口位置保留未知。视频标签关联到 26 个现有建筑对象，其中 16 个有当前候选片段；组团共现不能代表各栋完整外观覆盖。

正式记录在 `observations/annotations/video-review/`，空间关系在 `observations/bindings/topology.json`，模型差异在 `observations/annotations/model-findings.json`。地点节点包含来源特定的待定位空间；父对象对应不等于相机标定、房间坐标或测绘精度。原视频与权限未明的精选帧保持本地，公共仓库提供元数据和引用。

```powershell
uv run python -m src.observations.review_export --validate
uv run python -m src.observations.review_export
```

生成的 `build/review/index.html` 可在本地浏览时间段、原视频、地图父对象和精选帧；该页面引用本地媒体。[审查方法与继续维护](docs/video-review.md)。

## 当前还原程度

已有 129 个可编辑建筑资产，包含主要地标、教学楼、宿舍、场地和景观。23 张教学楼原始楼层图保留为本地可选参考；房间隔墙尚未逐一建模。

| 外观观测覆盖 | 资产数 |
| --- | ---: |
| 有可明确对应单体的参考 | 14 |
| 有组团照片或局部匹配 | 22 |
| 有校园或同类建筑参考 | 71 |
| 主要依赖地图，尚无匹配立面照片 | 22 |

尺寸、隐藏立面、树种和局部细节仍有推定。渲染展示当前模型，空间精度通过后续控制点、实测尺寸和观测校准继续提高。当前未接入设备或实时运营数据。

## 来源与许可

- 代码：**AGPL-3.0-or-later**。
- 原创模型制作、场景、动画、文档与合成配乐：**CC BY 4.0**，第三方内容除外。
- 校园空间数据库：**ODbL 1.0**，© OpenStreetMap contributors。
- Poly Haven 通用贴图与树木资产：**CC0**。
- 第三方照片、地图、楼层图和学校标识保留各自权利。未明确允许再分发的原件保留本地，公共仓库提供来源和绑定；Blender 文件不内嵌受限楼层原图。

独立校园重建项目，无学校官方背书。完整范围见 [许可与署名](LICENSES.md)。
