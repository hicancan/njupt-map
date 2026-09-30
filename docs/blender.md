# Blender 工程与影片

`projects/blender/campus.blend` 保存校园场景，`projects/blender/buildings/` 保存链接建筑资产；`projects/blender/presentation/film.blend` 保存已创作的相机、动画和影片场景。它们是需要保留的源稿。

影片脚本默认打开现有 `film.blend`，读取场景内的 `film_plan`，不重建相机，也不保存渲染时的设置到源稿。修改运镜后应在 Blender 中明确保存源稿，再重新渲染。

## 当前三维设计输入

`projects/blender/design/exteriors.json` 保存外观细节的当前参数；`campus.json` 保存低校名墙、水池、K 开放高跨及道路景观的当前解释；`interiors.json` 保存教学楼已审阅的房间轮廓、官方图书馆布局与室内设计。共享建筑高度、楼层、位置和基底读取地图，观测绑定提供楼层图配准。

外观细化沿用现有网格与窗格位置，室内按建筑、楼层和角色分别存放。具有房间图示的楼层保留来源 ID 和原始标签；家具、开门方式、服务设施和未观测房间属于推定设计。图书馆官方二至五层示意图也采用近似米制配准，不能当作施工图。

南门校名的六个可编辑书法曲线直接维护在校园和影片原生源稿中。部件更新保留现有曲线、材质与相对布置，通过共同 ID 对应的门卫房锚点调整位置。许可未明确的原始矢量文件和提取 JSON 保持本地，不是公开工程更新部件的必需输入；工具会先检查六字曲线和原生部件锚点，缺失时在删除或改写部件前停止。

## 查看室内与剖切

打开 `projects/blender/buildings/` 中的一栋 `.blend`，在 Text Editor 选择 `View interior.py`。修改脚本中的 `floor=1` 查看其他楼层，`ceilings=False` 适合从上方检查平面布局；运行后使用保存的查看相机，按数字键盘 `0` 进入相机视图。检查状态只在你保存文件时写入源稿。

也可以在该建筑文件的 Python Console 中执行以下内容；路径根据已打开的分栋文件自动找到仓库根目录：

```python
from pathlib import Path
import sys, bpy, json
root = Path(bpy.data.filepath).resolve().parents[3]
sys.path.insert(0, str(root / "src/blender"))
from enrich_interiors import show_interior, show_exterior
asset = bpy.context.scene["asset_id"]
col = next(c for c in bpy.context.scene.collection.children if c.get("asset_id") == asset)
interior = show_interior(col, floor=1, ceilings=False, exterior=False)
views = json.loads(interior["camera_specs"])
view = next(v for v in views if v["id"] == "cutaway")
bpy.context.scene.camera = bpy.data.objects[view["name"]]
```

`ceilings=True` 可查看室内吊顶，`floor=None` 显示全部已建楼层。恢复外观显示执行 `show_exterior(col)`。大校门、连廊、看台等开放结构不创建虚构的室内楼层。

校园外观渲染默认抑制室内集合，分栋源稿仍保留全部几何与相机。便携场景包含已创作网格；仓库版同时提供脚本、设计输入和来源绑定，更适合后续维护。

## 明确应用新的三维细节

以下操作会保存当前作者工程，必须先完成地图导出，并明确选择要接纳的设计修改。查看作用范围的命令不带 `--apply`：

```powershell
uv run python -m src.map.export
blender --background --factory-startup --python-exit-code 1 --python src/blender/author_campus.py -- --assets
```

以下是新资产首次接纳外观与室内，以及接纳校园和影片部件设计的用法。公开工程已保存的作者成果直接打开或渲染即可，无需重复执行这一批命令：

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/author_campus.py -- --apply --assets
blender --background --factory-startup --python-exit-code 1 --python src/blender/author_campus.py -- --apply --campus --presentation
```

`--ids` 接收逗号分隔的共同 ID，可限定单栋。每完成一栋即保存源稿和目录散列；中断后检查实际完成范围，再按 ID 处理剩余建筑。室内已有作者成果时，工具默认拒绝替换，不能把整批应用当作日常渲染命令。分栋手工精修直接在 Blender 中进行，并重新检查目录散列、链接和地图签名。

明确接纳新的室内布局时，`--replace-interiors` 替换该工具维护的室内集合，保留原外观；它会替换该集合中后续手工修改的内容，适合已确认要整体更新的建筑。下面示例仅选择图书馆：

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/author_campus.py -- --apply --assets --replace-interiors --ids osm_way_223859810
```

只调整已保存的室内材质时，用独立的 `--interior-materials` 作用范围，保留网格和相机。它要求 `--apply`，不能与 `--assets` 同时使用：

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/author_campus.py -- --apply --interior-materials --ids osm_way_223859810
```

只更新工具维护的外部附加细节时使用 `--exteriors`，保留已保存室内和查看相机。工具核对室内网格、拓扑、矩阵和相机参数的散列，变化时拒绝保存；外窗来源按集合的用途标记筛选，隐藏室内玻璃不会进入外部细化：

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/author_campus.py -- --apply --exteriors
blender --background --factory-startup --python-exit-code 1 --python src/blender/checks/validate_exterior_source_filter.py
```

检查全部已保存室内时使用 `--authored`，检查源文件未改写、查看相机、楼层与开洞记录、官方图书馆图示使用情况和查看文本保存：

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/checks/validate_interiors.py -- --authored
```

检查报告写入 `build/checks/interior-source-validation.json`。不带 `--authored` 的模式仅供未创作室内的原资产做内存试用，不能在已有室内的公开工程上重复应用。

便携场景导出后，可以只读执行内置查看与恢复脚本，并核对所有室内相机的共同 ID：

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/checks/validate_portable_interior.py
```

该检查直接打开 `build/blender/njupt-map.blend`，在内存中切换图书馆三层、核对世界坐标相机和恢复外观；不保存场景。报告写入 `build/checks/portable-interiors.json`。

## 渲染高清静帧

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/render_quality.py
```

默认以 Cycles OptiX 渲染 3840 × 2160、128 采样的全景、门头、主要建筑与室内视图。输出位于 `build/blender/renders/quality/`，检查记录位于 `build/checks/quality-renders.json`；不会保存渲染时的场景设置到源稿。

用 `--views` 选择视角，降低分辨率和采样可以先检查构图：

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/render_quality.py -- --views entrance,k_group --width 960 --samples 24
blender --background --factory-startup --python-exit-code 1 --python src/blender/render_quality.py -- --views library_inside,library_cutaway,canteen_inside,teaching_cutaway,dorm_inside
```

室内渲染使用分栋文件保存的查看相机，临时隐藏外壳、隔离楼层并设置灯光。检查结果显示的是当前设计，测量精度仍须通过观测与控制点另行验证。

## 渲染现有影片

在仓库根目录的 PowerShell 7 中运行；`blender` 需要在 PATH 中。

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/build_campus_film.py -- --help
blender --background --factory-startup --python-exit-code 1 --python src/blender/build_campus_film.py -- --storyboard
blender --background --factory-startup --python-exit-code 1 --python src/blender/build_campus_film.py -- --render
```

`--storyboard` 取每个镜头的起点、中点、终点，默认宽 960 像素、20 个采样；`--render` 默认宽 1920 像素、64 个采样。`--draft` 每隔四帧输出预览；`--benchmark` 输出第 421–423 帧。四种模式互斥，均可用 `--start`、`--end` 限制范围，以 `--width`、`--samples` 覆盖质量设置。

快速验证一帧：

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/build_campus_film.py -- --storyboard --start 1 --end 1 --engine BLENDER_EEVEE --width 160 --samples 1
```

默认 Cycles 使用 OptiX GPU；也可选择 `--engine BLENDER_EEVEE`。输出固定放在 `build/blender/renders/film/`：`preflight/` 为分镜及性能预览，`draft/` 为草稿，`frames/` 为正式帧。正式帧默认跳过已存在文件；修改源稿或渲染设置后用 `--overwrite` 更新所选范围。

正式帧渲染将本次实际输入的 SHA-256 和设置写入 `build/checks/film/runs/`，并检查渲染期间输入是否变化。场景中最初组装时的校园哈希作为来源记录保留；校园后续修改不会阻止独立创作的影片源稿渲染。

完成 840 帧后合成 35 秒成片，并检查规格和时间连续性：

```powershell
uv run python src/blender/edit_campus_film.py --wav projects/blender/presentation/audio/njupt_campus_original_score_35s.wav
uv run python src/blender/checks/validate_media.py --frames
uv run python src/blender/checks/audit_film_temporal.py
```

成片写入 `build/media/njupt-map.mp4`。产品标题由 `projects/blender/presentation/` 下的当前标题源稿维护。

## 显式组装候选影片

只有 `--assemble` 会从校园源稿和 `camera_plan.json` 生成候选影片。先生成 `build/map/campus.json`，再运行：

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/build_campus_film.py -- --assemble --output build/blender/film.blend
```

候选输出必须位于 `build/` 内，扩展名必须为 `.blend`；脚本拒绝输出到校园、影片或建筑原生源稿。`--output` 只用于候选组装，不改变默认渲染源稿。可组合 `--assemble --storyboard` 来检查刚生成的候选。

候选确认后，如需替换正式影片，应将它作为明确的工程修改接纳，并检查链接路径、镜头与 Git 差异。不要建立备份目录或保留多套影片实现。
