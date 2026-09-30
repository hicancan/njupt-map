# 校园地图工程

用 QGIS 打开 `campus.qgs`。工程以相对路径引用同目录的 `campus.gpkg`；
`campus_attachments.zip` 是 QGIS 4 原生工程样式资源，与工程一起保存。
GeoPackage 是当前空间事实的唯一编辑入口，JSON、GeoJSON 和图片均为导出。

## 坐标与身份

- 所有图层：EPSG:32650，米制投影坐标。
- Blender：局部米制，X 向网格东，Y 向网格北，Z 向上。
- 原点：WGS84 `(118.925, 32.115)`，投影坐标与地面基准存于 `map_metadata`。
- `asset_id`：地图、观测绑定和 Blender 资产共同使用的稳定 ID；改名不换 ID。
- `space_id`、`map_feature_id`：已知的 njupt-search 外部关联，可空，不根据猜测创建。
- `anchor_offset_e_m/n_m`：资产锚点相对轮廓质心的偏移，保住既有精修资产的局部原点。
  平移地图几何会平移锚点；改变形状会产生需要处理的三维差异。

## 图层与字段

| 图层 | 含义 |
| --- | --- |
| `boundary` | 校园范围 |
| `buildings` | 当前 129 个三维资产对应的正式轮廓与共同参数 |
| `building_volumes` | 3 个局部上层体量，以 `parent_asset_id` 关联建筑 |
| `roads` | 来源地图道路、步道的线形与宽度 |
| `waters/greens/sports/surfaces` | 水体、植被、运动场和硬质场地 |
| `pois/trees` | 兴趣点与确有独立观测的树木点位；树木图层当前为空 |
| `context_buildings` | 校园外的周边建筑 |
| `landscape_exclusions` | 场景生成的留空规则，不是实测地块 |
| `map_metadata` | 坐标约定、来源和配准记录 |

建筑的 `height_m` 表示主体高度，不含另存的局部上层及模型装饰；
`min_height_m` 表示底部净空；`levels` 表示主体层数。
`height_source/levels_source` 必须说明观测和推断依据。
教1主体为 5 层、18.5 m；连廊为 3 层、顶部 10.8 m、净空 3.8 m。
楼层记录来自现有资料，高度仍含推断，不能称为测量值。

`geometry_role` 明确轮廓含义。来源地图轮廓、平面图中庭修正轮廓、
K 组团设计图的近似屋顶块，以及局部上层楼板分别保留不同语义；
二维轮廓不被宣称为精确地面占地或完整 BIM。

`attributes_json` 保存来源标签、`source_ids`、可信度、建模提示等补充信息，
严禁重复保存几何、锚点、高度、层数等已有字段。QGIS 直接编辑正式字段；
新观测先进入 `observations/` 并记录来源，再据此修正图层。
额外来源地图候选只作为观测保留，不会自动变成三维建筑。

## 导出与验证

从仓库根目录运行：

```powershell
uv run python -m src.map.export
uv run python -m src.map.validate
uv run python -m src.sync.plan
```

前两项使用普通 CPython，不需要 QGIS。输出在 `build/map/` 与 `build/checks/map/`。
重建 QGIS 样式和预览时运行：

```powershell
uv run python -m src.map.project --qgis-root D:/Dev/QGIS-4.2.0 --preview build/map/overview.png
```

该命令重写项目样式，不修改 GeoPackage 几何。在其他 QGIS 环境中可直接使用
带 PyQGIS 的 Python 运行同模块。既有项目中的人工样式修改应先提交 Git，
按需运行此命令。

## 同步到现有 Blender 工程

高层入口会检查主校园和宣传片两个场景的实际实例。默认只读：

```powershell
uv run python -m src.sync
uv run python -m src.sync --apply
```

仅轮廓局部形状与共同高度未变时，计划才允许更新链接实例的位置与名称。
形状、孔洞、高度变化需要修改对应三维源稿并明确接受新的空间签名；
代码不会替换精修建筑、重建主场景或删除已移出地图的资产。
计划会检查源文件、目录和实际实例是否在计划生成后发生变化。
只有两个场景都通过身份与几何审查后才执行修改；检查时两个场景的文件指纹不变，
应用时校验相机、动画和非建筑构图，并保护全部建筑资产源稿。

主校园场景与宣传片场景分别保存实例放置，因此每次都以各自的真实放置检查，
不会因为目录已经记录新位置就跳过尚未更新的宣传片。
使用非 PATH 中的 Blender 时，追加 `--blender <可执行文件路径>`。
