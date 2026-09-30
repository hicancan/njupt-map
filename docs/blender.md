# Blender 工程与影片

`projects/blender/campus.blend` 保存校园场景，`projects/blender/buildings/` 保存链接建筑资产；`projects/blender/presentation/film.blend` 保存已创作的相机、动画和影片场景。它们是需要保留的源稿。

影片脚本默认打开现有 `film.blend`，读取场景内的 `film_plan`，不重建相机，也不保存渲染时的设置到源稿。修改运镜后应在 Blender 中明确保存源稿，再重新渲染。

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

## 显式组装候选影片

只有 `--assemble` 会从校园源稿和 `camera_plan.json` 生成候选影片。先生成 `build/map/campus.json`，再运行：

```powershell
blender --background --factory-startup --python-exit-code 1 --python src/blender/build_campus_film.py -- --assemble --output build/blender/film.blend
```

候选输出必须位于 `build/` 内，扩展名必须为 `.blend`；脚本拒绝输出到校园、影片或建筑原生源稿。`--output` 只用于候选组装，不改变默认渲染源稿。可组合 `--assemble --storyboard` 来检查刚生成的候选。

候选确认后，如需替换正式影片，应将它作为明确的工程修改接纳，并检查链接路径、镜头与 Git 差异。不要建立备份目录或保留多套影片实现。
