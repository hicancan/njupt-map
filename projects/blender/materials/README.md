# 校园共享环境资产

来源：Poly Haven，全部原始资产许可为 CC0 1.0。`manifest.json` 记录每个下载地址、字节数与 MD5，下载脚本校验成功后才写入。

| 资产 | 用途 | 作者 | 分辨率 |
|---|---|---|---|
| [Grass Ground](https://polyhaven.com/a/grass_ground) | 草土表面漫反射、法线、粗糙度 | Charlotte Baglioni | 2K |
| [Asphalt 02](https://polyhaven.com/a/asphalt_02) | 沥青表面漫反射、法线、粗糙度 | Rob Tuytel | 2K |
| [Rock Tile Floor](https://polyhaven.com/a/rock_tile_floor) | 步道、广场石材 | Charlotte Baglioni | 2K |
| [Jacaranda Tree](https://polyhaven.com/a/jacaranda_tree) | 可共享网格的真实阔叶树视觉替身 | Rico Cilliers、Rob Tuytel | 原始 .blend 与 1K 贴图 |

使用 `[资产目录]/source-api.json` 可查看获取时的原始清单。`src/blender/download_assets.ps1` 能从官方地址重新取得并校验源文件。`src/blender/prepare_tree.py` 在独立 Blender 后台中读取原始 LOD1，生成候选 `build/blender/jacaranda_campus_lod.blend`：509,357 顶点、221,320 面；原始文件保持不变。生成命令：

```powershell
& 'C:\Program Files\Blender Foundation\Blender 5.2\blender.exe' --background --factory-startup --python '.\src\blender\prepare_tree.py'
```

树种及单株位置尚未经实地核实。该树作为阔叶树外观替身使用，不表示南邮种植了蓝花楹。湖岸垂柳则由 `campus_landscape.py` 依据官方校园湖区照片所见的垂枝形态生成轻量母版，具体枝叶、株数、位置均为推断。

全校树木共享同一份网格和材质，未将数千株树的网格复制展开。环境批量网格带米制 UV，铺装不使用拉伸的单张低分辨率图片。校内道路、绿地、水体轮廓保留 OSM 来源关系；道路宽度、材质、灯具、球场细分和运动跑道为可修订的建模假设。

鼎山的 OSM 峰顶记录为绝对高程 31m。当前模型相对地面隆起 16m 是视觉推断，不能把二者当作同一个测量值。

许可：[Poly Haven License](https://polyhaven.com/license)。本目录不包含从官方校园摄影图中复制出的贴图。
