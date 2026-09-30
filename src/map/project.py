"""Rebuild the native QGIS presentation and optionally render a map preview.

This operation changes styling and the .qgs project, never campus.gpkg geometry.
QGIS provides its own Python environment; the map exporter does not depend on it.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LAYER_NAMES = {
    "boundary": "校园范围", "buildings": "建筑与中庭", "building_volumes": "局部上层体量",
    "roads": "道路与步道", "waters": "水面", "greens": "绿地", "sports": "运动场",
    "surfaces": "硬质场地", "context_buildings": "周边建筑", "pois": "来源地图兴趣点",
    "trees": "观测树木", "landscape_exclusions": "景观生成留空区",
}
COLORS = {"boundary": ("#edf0e6", "#83967d"), "buildings": ("#c7a47e", "#8b7256"),
          "building_volumes": ("#dfbe8b", "#ad8754"), "waters": ("#9ccfda", "#6dabb9"),
          "greens": ("#b6caa2", "#a1b690"), "sports": ("#cf9680", "#b9816b"),
          "surfaces": ("#e0dbd2", "#c1bbae"), "context_buildings": ("#e0d9cd", "#c2bbae"),
          "landscape_exclusions": ("#00000000", "#cc705e")}


def qgis_environment(root: Path):
    env = os.environ.copy()
    env_file = root / "bin/qgis-bin.env"
    if not env_file.is_file():
        raise FileNotFoundError(f"Expected QGIS environment description: {env_file}")
    for line in env_file.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.partition("=")
        if sep:
            env[key] = value
    env["PATH"] = str(root / "apps/qgis/bin") + os.pathsep + env["PATH"]
    env["PYTHONPATH"] = os.pathsep.join([str(root / "apps/qgis/python"), str(ROOT), env.get("PYTHONPATH", "")])
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def make_project(source: Path, project_path: Path, preview: Path | None = None):
    from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsFillSymbol,
        QgsLineSymbol, QgsMarkerSymbol, QgsPalLayerSettings, QgsProject, QgsRelation,
        QgsTextBufferSettings, QgsTextFormat, QgsVectorLayer, QgsVectorLayerSimpleLabeling,
        QgsMapSettings, QgsMapRendererParallelJob, QgsRectangle, QgsFieldConstraints)
    from qgis.PyQt.QtCore import QSize
    from qgis.PyQt.QtGui import QColor, QFont, QFontDatabase, QPainter, QPen

    app = QgsApplication([], False)
    app.initQgis()
    # The bundled offscreen Qt platform may not enumerate Windows CJK fonts.
    label_font = "sans-serif"
    for font_file in (Path("C:/Windows/Fonts/msyh.ttc"), Path("C:/Windows/Fonts/simhei.ttf")):
        if font_file.is_file():
            font_id = QFontDatabase.addApplicationFont(str(font_file))
            families = QFontDatabase.applicationFontFamilies(font_id)
            if families:
                label_font = families[0]
                break
    project = QgsProject.instance()
    project.setCrs(QgsCoordinateReferenceSystem("EPSG:32650"))
    project.setTitle("njupt-map · 南京邮电大学仙林校区")
    project.setFilePathStorage(Qgis.FilePathType.Relative)
    layers = {}
    try:
        for layer_name, title in LAYER_NAMES.items():
            layer = QgsVectorLayer(f"{source.as_posix()}|layername={layer_name}", title, "ogr")
            if not layer.isValid():
                raise ValueError(f"Cannot open GeoPackage layer: {layer_name}")
            if layer_name in COLORS:
                color, stroke = COLORS[layer_name]
                layer.renderer().setSymbol(QgsFillSymbol.createSimple({"color": color,
                    "outline_color": stroke, "outline_width": "0.18" if layer_name != "boundary" else "0.45"}))
            elif layer_name == "roads":
                layer.renderer().setSymbol(QgsLineSymbol.createSimple({"line_color": "#c4c1b7", "line_width": "0.7", "joinstyle": "round"}))
            else:
                layer.renderer().setSymbol(QgsMarkerSymbol.createSimple({"name": "circle", "color": "#5c8790", "size": "1.3", "outline_width": "0"}))
            id_index = layer.fields().indexFromName("asset_id")
            if id_index >= 0:
                layer.setFieldConstraint(id_index, QgsFieldConstraints.ConstraintUnique)
                layer.setFieldConstraint(id_index, QgsFieldConstraints.ConstraintNotNull)
                form = layer.editFormConfig()
                form.setReadOnly(id_index, True)
                layer.setEditFormConfig(form)
                layer.setFieldAlias(id_index, "共同资产 ID（保持稳定）")
            if layer_name == "buildings":
                for field, alias in {"height_m": "主体高度 m（见依据）", "levels": "主体层数",
                    "min_height_m": "底部净空 m", "height_source": "高度依据", "levels_source": "楼层依据",
                    "geometry_role": "轮廓含义", "space_id": "njupt-search 空间 ID",
                    "anchor_offset_e_m": "模型锚点相对质心东偏移 m", "anchor_offset_n_m": "模型锚点相对质心北偏移 m"}.items():
                    layer.setFieldAlias(layer.fields().indexFromName(field), alias)
                label = QgsPalLayerSettings()
                representative = {}
                for feature in layer.getFeatures():
                    name = feature["name"]
                    if name and (name.startswith("教") or any(key in name for key in ("图书馆", "圆楼", "体育馆", "南门", "活动中心", "食堂", "材料科学"))):
                        area = feature.geometry().area()
                        if name not in representative or area > representative[name][1]:
                            representative[name] = (feature["asset_id"], area)
                ids = ",".join("'" + value[0].replace("'", "''") + "'" for value in representative.values())
                label.fieldName = f'CASE WHEN "asset_id" IN ({ids}) THEN replace(replace("name",\'南邮仙林\',\'\'),\'-新大楼\',\'\') END'
                label.isExpression = True
                text = QgsTextFormat()
                text.setFont(QFont(label_font, 9))
                text.setSize(9)
                text.setColor(QColor("#3b403b"))
                buffer = QgsTextBufferSettings()
                buffer.setEnabled(True)
                buffer.setSize(0.8)
                buffer.setColor(QColor("#faf9f5"))
                text.setBuffer(buffer)
                label.setFormat(text)
                layer.setLabeling(QgsVectorLayerSimpleLabeling(label))
                layer.setLabelsEnabled(True)
            project.addMapLayer(layer)
            layers[layer_name] = layer
            project.layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(layer_name not in {"landscape_exclusions", "pois", "trees"})
        relation = QgsRelation()
        relation.setId("building_upper_volumes")
        relation.setName("建筑的局部上层体量")
        relation.setReferencedLayer(layers["buildings"].id())
        relation.setReferencingLayer(layers["building_volumes"].id())
        relation.addFieldPair("parent_asset_id", "asset_id")
        if not relation.isValid():
            raise ValueError("Invalid building / upper volume relation")
        project.relationManager().addRelation(relation)
        draw_order = [layers[k] for k in ("building_volumes", "buildings", "roads", "sports", "surfaces", "waters", "greens", "context_buildings", "boundary")]
        project.layerTreeRoot().setHasCustomLayerOrder(True)
        project.layerTreeRoot().setCustomLayerOrder(draw_order)
        extent = QgsRectangle(layers["boundary"].extent())
        extent.scale(1.06)
        from qgis.core import QgsReferencedRectangle
        project.viewSettings().setDefaultViewExtent(QgsReferencedRectangle(extent, project.crs()))
        project.setBackgroundColor(QColor("#faf9f5"))
        project_path.parent.mkdir(parents=True, exist_ok=True)
        if not project.write(str(project_path)):
            raise RuntimeError(f"Could not save QGIS project: {project_path}")
        if preview:
            settings = QgsMapSettings()
            settings.setDestinationCrs(project.crs())
            settings.setLayers(draw_order)
            settings.setExtent(extent)
            settings.setBackgroundColor(QColor("#faf9f5"))
            settings.setOutputSize(QSize(1500, 1200))
            settings.setOutputDpi(150)
            job = QgsMapRendererParallelJob(settings)
            job.start()
            job.waitForFinished()
            if job.errors():
                raise RuntimeError(str([(e.layerID, e.message) for e in job.errors()]))
            preview.parent.mkdir(parents=True, exist_ok=True)
            rendered = job.renderedImage()
            painter = QPainter(rendered)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setPen(QColor("#3b403b"))
            painter.setFont(QFont(label_font, 22))
            painter.drawText(55, 75, "njupt-map")
            painter.setFont(QFont(label_font, 13))
            painter.drawText(55, 108, "南京邮电大学 · 仙林校区")
            painter.setFont(QFont(label_font, 11))
            painter.drawText(55, 140, "二维空间基底 / EPSG:32650")
            painter.drawText(1380, 78, "N")
            painter.setPen(QPen(QColor("#526b52"), 3))
            painter.drawLine(1388, 128, 1388, 88)
            painter.drawLine(1388, 88, 1380, 103)
            painter.drawLine(1388, 88, 1396, 103)
            painter.setFont(QFont(label_font, 11))
            for index, (layer_key, title) in enumerate((("buildings", "建筑"), ("greens", "绿地"), ("waters", "水面"), ("sports", "运动场"), ("surfaces", "硬质场地"))):
                y = 918 + index * 31
                painter.fillRect(55, y, 22, 16, QColor(COLORS[layer_key][0]))
                painter.setPen(QColor("#3b403b"))
                painter.drawText(90, y+14, title)
            scale_pixels = round(100 / settings.mapUnitsPerPixel())
            painter.setPen(QPen(QColor("#3b403b"), 3))
            painter.drawLine(55, 1105, 55+scale_pixels, 1105)
            painter.drawLine(55, 1100, 55, 1110)
            painter.drawLine(55+scale_pixels, 1100, 55+scale_pixels, 1110)
            painter.drawText(55, 1134, "100 m")
            painter.setFont(QFont(label_font, 9))
            painter.drawText(55, 1170, "© OpenStreetMap contributors · ODbL 1.0")
            painter.end()
            if not rendered.save(str(preview), "PNG"):
                raise RuntimeError(f"Cannot save rendered map: {preview}")
        # Actually reopen the saved project; a successful write alone is insufficient.
        expected = {layer.source().split("|layername=")[-1] for layer in layers.values()}
        project.clear()
        if not project.read(str(project_path)):
            raise RuntimeError("Saved QGIS project cannot be reopened")
        loaded = list(project.mapLayers().values())
        if len(loaded) != len(expected) or any(not layer.isValid() for layer in loaded):
            raise RuntimeError("Saved project has missing or invalid layers")
        # QGIS creates an adjacent previous-save file; repository history is Git.
        backup = project_path.with_name(project_path.name + "~")
        if backup.is_file():
            backup.unlink()
        report = {"project": str(project_path), "qgis": Qgis.QGIS_VERSION,
                  "layers": len(loaded), "all_layers_valid": True, "relative_paths": True}
        output = ROOT / "build/checks/map/qgis.json"
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
        project.clear()
    finally:
        # Avoid Qt/GDAL teardown races; all project references are cleared first.
        layers.clear()
        app.exitQgis()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "projects/map/campus.gpkg")
    parser.add_argument("--project", type=Path, default=ROOT / "projects/map/campus.qgs")
    parser.add_argument("--preview", type=Path)
    parser.add_argument("--qgis-root", type=Path, default=Path(os.environ.get("QGIS_ROOT", "D:/Dev/QGIS-4.2.0")))
    parser.add_argument("--native", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.native:
        make_project(args.source.resolve(), args.project.resolve(), args.preview.resolve() if args.preview else None)
        return
    if sys.platform != "win32":
        make_project(args.source.resolve(), args.project.resolve(), args.preview.resolve() if args.preview else None)
        return
    command = [str(args.qgis_root / "bin/python.exe"), str(Path(__file__).resolve()), "--native",
               "--source", str(args.source.resolve()), "--project", str(args.project.resolve())]
    if args.preview:
        command.extend(["--preview", str(args.preview.resolve())])
    subprocess.run(command, env=qgis_environment(args.qgis_root), check=True, cwd=ROOT)


if __name__ == "__main__":
    main()
