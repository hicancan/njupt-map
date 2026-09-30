# 编辑、同步与导出

## 环境

Python 3.12、uv、Git LFS；地图编辑使用 QGIS 4.2，三维编辑使用 Blender 5.2 LTS，媒体处理使用 FFmpeg。Python 脚本用项目环境，Blender 脚本用 Blender 内置 Python。

```powershell
uv venv --python 3.12
uv sync --locked
```

## 地图与观测

打开 projects/map/campus.qgs，编辑同目录的 GeoPackage。保存后导出和检查：

```powershell
uv run python -m src.map.export
uv run python -m src.map.validate
uv run python -m src.observations.validate --hashes
uv run python -m src.sync
```

不要直接编辑 build/map/campus.json。建筑高度、楼层和共同位置在正式 GeoPackage 中维护，不在建模脚本中重复覆盖。占地轮廓、上层体块分别有明确几何角色。

`src.sync` 通过 Blender 同时检查校园与影片两个原生场景，默认只读，输出各自计划及汇总到 `build/checks/sync/`。检查通过后执行 `uv run python -m src.sync --apply`，只对共同 ID 匹配的实例同步位置与名称；无法安全处理的轮廓或高度变化保持源稿并报告，随后人工精修。相机、动画、景观和分栋网格保持不变。Blender 不在 PATH 时指定 `--blender 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'`。参见 [架构](architecture.md)。

## 三维编辑与渲染

单栋编辑 projects/blender/buildings 下的文件。校园源稿 projects/blender/campus.blend 链接单栋；影片 projects/blender/presentation/film.blend 保存运镜与动画。

```powershell
$blenderExe = 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe'
& $blenderExe --background --factory-startup --python-exit-code 1 --python src/blender/build_campus.py -- --preview
& $blenderExe --background --factory-startup --python-exit-code 1 --python src/blender/export_portable_blend.py -- --temp-dir D:/Temp/codex/njupt-map-export
```

预览从已保存的校园源稿渲染。便携导出写入 build/blender/njupt-map.blend，不修改校园或单栋源稿。公开导出只打包允许分发的通用资产，不打包受限楼层图。

需要程序生成候选校园时，使用 build_campus.py 的显式 `--assemble --output build/blender/candidate.blend`。既有建筑继续作为作者源稿链接；缺失建筑只生成到 build。新成果须明确接纳进原生工程，生成脚本不默认覆盖源稿。

全校园细节与室内的当前设计位于 `projects/blender/design/`，显式应用工具为 `src/blender/author_campus.py`。它要求最新地图导出，只有 `--apply` 和明确的作用范围一起出现才会保存源稿。已有室内默认受保护，批量作者工具不能替代后续手工精修。静帧渲染使用 `src/blender/render_quality.py`，室内查看、作用范围和命令见 [Blender 工程与影片](blender.md)。

发布前检查原生引用与源稿保护：

```powershell
& $blenderExe --background --factory-startup --python-exit-code 1 --python src/blender/checks/validate_native.py
& $blenderExe --background --factory-startup --python-exit-code 1 --python src/blender/checks/validate_interiors.py -- --authored
uv run python -m src.sync
```

便携导出验证重新打开后的建筑身份、引用和受限原图保护，同时检查导出没有改写作者工程。任务临时目录仅用于导出过程中间文件；验证路径位于 `D:/Temp/codex/` 后清理。正式便携成果保存在 `build/`，发布为 Release 附件。

## 影片

35秒影片的相机计划、音频与标题源稿位于 projects/blender/presentation。渲染帧进入 build/blender/renders，成片进入 build/media。已有公开成片随 GitHub Release 提供。

使用 `src/blender/build_campus_film.py -- --storyboard` 或 `--render` 从保存的影片源稿渲染。具体命令、质量参数和候选组装见 [Blender 与影片](blender.md)。

原创配乐使用 src/blender/compose_film_score.py 生成；它不采样第三方歌曲或录音。音频母带作为影片作者成果维护。

## 提交与发布

```powershell
uv run python -m src.map.export
uv run python -m src.map.validate
uv run python -m src.observations.validate --public
uv run python -m unittest discover -s tests -p 'test_*.py'
```

检查 Git 暂存内容与来源许可。正式二进制使用 LFS，build 和环境忽略。受限资料只保留本地，来源元数据和绑定可以提交。不要加入 API 凭据或含敏感内容的原始疏散图。

完成迁移后删除旧实现。回溯用 Git，不在当前工程留旧格式或备份。发布图、视频和便携导出是附属下载，不构成第二套作者工程。
