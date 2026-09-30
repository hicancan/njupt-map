"""Validate formal video reviews and export a local, read-only review browser.

Spatial anchors are read afresh from the GeoPackage. Parent-building anchors
are never represented as measured entrances or reconstructed camera poses.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote

from src.map.store import load_campus

from .common import ROOT, read, write
from .video_review import validate_annotation

ANNOTATIONS = "observations/annotations/video-review"
TOPOLOGY = "observations/bindings/topology.json"


def map_records(campus: dict) -> list[dict]:
    records = [campus["boundary"]]
    for value in campus.values():
        if isinstance(value, list):
            records.extend(value)
    for building in campus.get("buildings", []):
        records.extend(building.get("upper_volumes", []))
    return records


def inputs(root: Path = ROOT) -> tuple[dict, list[dict], dict, dict]:
    catalog = read(root / "observations/catalog.json")
    annotations = [read(path) for path in sorted((root / ANNOTATIONS).glob("*.json"))]
    topology_path = root / TOPOLOGY
    topology = read(topology_path) if topology_path.is_file() else {"places": {}, "edges": []}
    campus = load_campus(root / "projects/map/campus.gpkg")
    return catalog, annotations, topology, campus


def validate_review_sources(root: Path = ROOT) -> list[str]:
    """Return annotation/topology identity and reference errors, without outputs."""
    catalog, annotations, topology, campus = inputs(root)
    errors = validate_data(catalog, annotations, topology, campus)
    findings_path = root / "observations/annotations/model-findings.json"
    if findings_path.is_file():
        reviewed = {(a["source_id"], s["id"]) for a in annotations for s in a["segments"]}
        objects = {record["asset_id"] for record in map_records(campus)}
        for finding in read(findings_path).get("findings", []):
            if not finding.get("source_refs"):
                errors.append(f"Model finding {finding.get('id')}: Missing observation provenance")
            for ref in finding.get("source_refs", []):
                if (ref.get("source_id"), ref.get("segment_id")) not in reviewed:
                    errors.append(f"Model finding {finding.get('id')}: Unknown source segment")
            if set(finding.get("asset_ids", [])) - objects:
                errors.append(f"Model finding {finding.get('id')}: Unknown object identity")
    return errors


def validate_data(catalog: dict, annotations: list[dict], topology: dict, campus: dict) -> list[str]:
    sources = catalog["sources"]
    records = map_records(campus)
    asset_ids = {record["asset_id"] for record in records}
    feature_ids = {record.get("map_feature_id") for record in records if record.get("map_feature_id")}
    places = topology.get("places", {})
    errors = []
    segments = {}
    videos = {}
    for annotation in annotations:
        sid = annotation.get("source_id")
        if sid in videos:
            errors.append(f"Duplicate video review: {sid}")
        videos[sid] = annotation
        errors.extend(f"{sid}: {error}" for error in validate_annotation(annotation, sources, asset_ids, feature_ids, set(places)))
        for segment in annotation.get("segments", []):
            identifier = segment.get("id")
            key = (sid, identifier)
            if not identifier or key in segments:
                errors.append(f"Invalid or duplicate segment ID: {key}")
            segments[key] = segment
            eligibility = segment.get("eligibility")
            allowed = {"current_candidate", "excluded_historical", "excluded_other_campus", "unresolved"}
            if eligibility not in allowed:
                errors.append(f"{key}: Invalid temporal eligibility")
            if eligibility == "current_candidate" and (segment.get("campus") != "xianlin" or segment.get("status") != "accepted"):
                errors.append(f"{key}: Current candidate must be accepted Xianlin")
            if isinstance(eligibility, str) and eligibility.startswith("excluded_") and segment.get("status") != "excluded":
                errors.append(f"{key}: Excluded eligibility must use excluded status")
            if segment.get("status") != "accepted" and segment.get("selected_frame_pts_seconds"):
                errors.append(f"{key}: Excluded or unknown segment cannot have current selected frames")
            if len(set(segment.get("selected_frame_source_ids", []))) != len(segment.get("selected_frame_source_ids", [])):
                errors.append(f"{key}: Duplicate selected frame source IDs")
    # A recorded completed video set may not silently omit registered inputs.
    for sid, source in sources.items():
        if source.get("kind") == "videos" and source.get("platform") == "bilibili" and sid not in videos:
            errors.append(f"Bilibili source has no complete review: {sid}")

    def references(refs, context):
        if not refs:
            errors.append(f"{context}: No provenance references")
        for reference in refs or []:
            sid = reference.get("source_id")
            if sid not in sources:
                errors.append(f"{context}: Unknown source {sid}")
            segment_id = reference.get("segment_id")
            if sources.get(sid, {}).get("kind") == "videos" and segment_id is None:
                errors.append(f"{context}: Video provenance requires a specific reviewed segment")
            if segment_id is not None and (sid, segment_id) not in segments:
                errors.append(f"{context}: Unknown segment {sid}/{segment_id}")

    for pid, place in places.items():
        if place.get("campus") not in {"xianlin", "sanpailou", "other", "unknown"}:
            errors.append(f"Place {pid}: Unknown campus")
        if place.get("spatial_binding", {}).get("status") not in {"semantic_parent_only", "unregistered"}:
            errors.append(f"Place {pid}: Missing explicit unmeasured spatial binding")
        for aid in place.get("asset_ids", []) + place.get("map_object_ids", []):
            if aid not in asset_ids:
                errors.append(f"Place {pid}: Unknown common object ID {aid}")
        for fid in place.get("map_feature_ids", []):
            if fid not in feature_ids:
                errors.append(f"Place {pid}: Unknown map feature ID {fid}")
        references(place.get("source_refs"), f"Place {pid}")
    seen_edges = set()
    for edge in topology.get("edges", []):
        eid = edge.get("id")
        if not eid or eid in seen_edges:
            errors.append(f"Invalid or duplicate topology edge ID: {eid}")
        seen_edges.add(eid)
        for endpoint in ("from_place_id", "to_place_id"):
            if edge.get(endpoint) not in places:
                errors.append(f"Edge {eid}: Unknown endpoint {edge.get(endpoint)}")
        if edge.get("basis") not in {"continuous_shot", "plan", "cross_reference", "inferred"}:
            errors.append(f"Edge {eid}: Missing observation basis")
        if edge.get("basis") == "inferred" and edge.get("verified") is True:
            errors.append(f"Edge {eid}: Inference cannot be a verified connection")
        references(edge.get("source_refs"), f"Edge {eid}")
        temporal = edge.get("temporal_status")
        for reference in edge.get("source_refs", []):
            segment = segments.get((reference.get("source_id"), reference.get("segment_id")))
            if segment is not None and segment.get("eligibility") != temporal:
                errors.append(f"Edge {eid}: Temporal status differs from supporting segment")
            if temporal == "current_candidate" and segment is not None and (segment.get("status") != "accepted" or segment.get("campus") != "xianlin"):
                errors.append(f"Edge {eid}: Current relation cannot use historical or non-Xianlin footage")
        if temporal == "current_candidate":
            for endpoint in ("from_place_id", "to_place_id"):
                place = places.get(edge.get(endpoint), {})
                if place.get("campus") != "xianlin":
                    errors.append(f"Edge {eid}: Current relation leaves Xianlin")
                current_refs = [segments.get((ref.get("source_id"), ref.get("segment_id")))
                                for ref in place.get("source_refs", [])]
                if not any(ref and ref.get("eligibility") == "current_candidate" for ref in current_refs):
                    errors.append(f"Edge {eid}: Current relation endpoint has no current-candidate observation")
    selected_backlinks = {}
    for key, segment in segments.items():
        for frame_id in segment.get("selected_frame_source_ids", []):
            if frame_id in selected_backlinks:
                errors.append(f"Selected frame {frame_id}: Claimed by multiple segments")
            selected_backlinks[frame_id] = key
            if frame_id not in sources or sources[frame_id].get("kind") != "selected_video_frame":
                errors.append(f"{key}: Selected frame source ID is missing or not a frame: {frame_id}")
    for sid, source in sources.items():
        if source.get("kind") != "selected_video_frame":
            continue
        derivation = source.get("derived_from", {})
        parents = [pid for pid in derivation.get("source_ids", []) if pid in videos]
        for pid in parents:
            actual = derivation.get("decoded_pts_seconds")
            if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isfinite(actual):
                errors.append(f"Selected frame {sid}: Missing decoded source PTS")
                continue
            tick = derivation.get("decoded_pts")
            try:
                base = Fraction(derivation.get("time_base", ""))
                if not isinstance(tick, int) or isinstance(tick, bool) or tick < 0 or base <= 0:
                    raise ValueError("Invalid source tick or time base")
                if abs(float(tick * base) - actual) > 1e-7:
                    errors.append(f"Selected frame {sid}: Integer source PTS/time base differs from decoded seconds")
                frame_id = re.fullmatch(re.escape(pid) + r"-frame-pts-(\d+)", sid)
                if frame_id is None or int(frame_id.group(1)) != tick:
                    errors.append(f"Selected frame {sid}: Frame ID ticks differ from decoded integer source PTS")
            except (ValueError, TypeError, ZeroDivisionError, OverflowError):
                errors.append(f"Selected frame {sid}: Missing valid integer source PTS and rational time base")
            matching = [s for s in videos[pid]["segments"] if s["start_seconds"] <= actual < s["end_seconds"]]
            if len(matching) != 1:
                errors.append(f"Selected frame {sid}: Not in exactly one reviewed segment")
            else:
                segment = matching[0]
                if actual not in segment.get("selected_frame_pts_seconds", []):
                    errors.append(f"Selected frame {sid}: Decoded PTS is not a curated segment point")
                if selected_backlinks.get(sid) != (pid, segment["id"]):
                    errors.append(f"Selected frame {sid}: Formal segment/frame references are not bidirectional")
                if source.get("annotation_segment_id") != segment["id"]:
                    errors.append(f"Selected frame {sid}: Catalog segment ID differs from annotation")
                bvid = sources[pid].get("platform_identifiers", {}).get("bvid", pid)
                if source.get("annotation_path") != f"{ANNOTATIONS}/{bvid}.json":
                    errors.append(f"Selected frame {sid}: Catalog annotation path differs from source review")
                if segment.get("eligibility") != "current_candidate" or segment.get("status") != "accepted":
                    errors.append(f"Selected frame {sid}: Parent segment is not a current accepted candidate")
                if derivation.get("source_sha256") != sources[pid].get("sha256"):
                    errors.append(f"Selected frame {sid}: Inherited source SHA differs from parent video")
                if source.get("redistribution") != sources[pid].get("redistribution"):
                    errors.append(f"Selected frame {sid}: Media permissions differ from parent video")
                for field in ("asset_ids", "map_object_ids", "map_feature_ids", "place_ids"):
                    if set(source.get("spatial_binding", {}).get(field, [])) != set(segment.get(field, [])):
                        errors.append(f"Selected frame {sid}: Semantic {field} differs from reviewed segment")
    for key, segment in segments.items():
        for at in segment.get("selected_frame_pts_seconds", []):
            matching = [frame_id for frame_id in segment.get("selected_frame_source_ids", [])
                        if sources.get(frame_id, {}).get("derived_from", {}).get("decoded_pts_seconds") == at]
            if len(matching) != 1:
                errors.append(f"{key}: Curated PTS {at} must have exactly one formal selected frame")
    return errors


def build_payload(catalog: dict, annotations: list[dict], topology: dict, campus: dict,
                  root: Path, output: Path) -> tuple[dict, dict]:
    sources = catalog["sources"]
    by_source = {a["source_id"]: a for a in annotations}
    frame_sources = {sid: source for sid, source in sources.items() if source.get("kind") == "selected_video_frame"}

    def local_url(relative: str | None):
        if not relative:
            return None
        path = (root / relative).resolve()
        if not path.is_relative_to(root.resolve()):
            raise ValueError(f"Source path leaves repository: {relative}")
        return quote(os.path.relpath(path, output).replace("\\", "/"), safe="/")

    videos = []
    for sid, annotation in by_source.items():
        source = sources[sid]
        selected = []
        for frame_id, frame in frame_sources.items():
            if sid in frame.get("derived_from", {}).get("source_ids", []):
                selected.append({"id": frame_id, "url": local_url(frame.get("local_path")),
                                 "pts_seconds": frame["derived_from"].get("decoded_pts_seconds"),
                                 "reason": frame.get("selection_reason"), "redistribution": frame.get("redistribution")})
        videos.append({"source_id": sid, "title": source.get("source_name", sid),
                       "url": source.get("url"), "published_at": source.get("published_at"),
                       "capture_time": source.get("capture_time"), "local_url": local_url(source.get("local_path")),
                       "duration_seconds": annotation["duration_seconds"], "review": annotation.get("review", {}),
                       "segments": annotation["segments"], "selected_frames": selected})
    records = map_records(campus)
    feature_records = []
    for record in records:
        feature_records.append({key: record[key] for key in ("asset_id", "map_feature_id", "name", "outer", "points", "point", "center") if key in record})
    bounds = campus["boundary"]["outer"]
    xs, ys = [p[0] for p in bounds], [p[1] for p in bounds]
    seconds_by_eligibility = {}
    seconds_by_campus = {}
    seconds_by_space_type = {}
    source_refs = {}
    for video in videos:
        for segment in video["segments"]:
            length = segment["end_seconds"] - segment["start_seconds"]
            for counter, field in ((seconds_by_eligibility, "eligibility"), (seconds_by_campus, "campus"),
                                   (seconds_by_space_type, "space_type")):
                key = segment.get(field, "unknown")
                counter[key] = counter.get(key, 0) + length
            for aid in segment.get("asset_ids", []):
                source_refs.setdefault(aid, []).append({"source_id": video["source_id"], "segment_id": segment["id"],
                                                       "eligibility": segment["eligibility"], "confidence": segment.get("confidence"),
                                                       "space_type": segment.get("space_type", "unknown")})
    building_ids = {building["asset_id"] for building in campus.get("buildings", [])}
    coverage = {"asset_count": len(building_ids), "reviewed_visual_asset_count": len(building_ids & set(source_refs)),
                "current_candidate_asset_count": sum(any(ref["eligibility"] == "current_candidate" for ref in source_refs.get(aid, [])) for aid in building_ids),
                "assets": {aid: {"source_refs": source_refs.get(aid, []),
                                 "has_current_candidate": any(ref["eligibility"] == "current_candidate" for ref in source_refs.get(aid, []))}
                           for aid in sorted(building_ids)},
                "limitations": "Semantic appearance coverage only; parent binding does not establish camera pose, exact entrance coordinates, dimensional accuracy or complete interior coverage"}
    summary = {"videos": len(videos), "segments": sum(len(v["segments"]) for v in videos),
               "duration_seconds": sum(v["duration_seconds"] for v in videos), "seconds_by_eligibility": seconds_by_eligibility,
               "seconds_by_campus": seconds_by_campus, "selected_frames": sum(len(v["selected_frames"]) for v in videos),
               "seconds_by_space_type": seconds_by_space_type,
               "places": len(topology.get("places", {})), "relations": len(topology.get("edges", [])),
               "map_dataset_sha256": campus["metadata"].get("dataset_sha256"),
               "spatial_binding": "GeoPackage parent geometry read at export time; no measured entrance or camera poses"}
    payload = {"summary": summary, "videos": videos, "topology": topology,
               "map": {"records": feature_records, "bounds": [min(xs), min(ys), max(xs), max(ys)]}}
    return payload, coverage


PAGE = r'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>njupt-map · 视频观测审查</title>
<style>
:root{color-scheme:dark;font-family:system-ui,"Microsoft YaHei",sans-serif;background:#101720;color:#e6edf5}*{box-sizing:border-box}body{margin:0}header{padding:22px 28px;border-bottom:1px solid #334158}h1{margin:0 0 8px;font-size:26px}small,.muted{color:#a6b5c8}.warning{color:#ffca71}main{display:grid;grid-template-columns:minmax(350px,1fr) minmax(400px,1fr);gap:18px;padding:20px}section,.card{background:#182331;border:1px solid #30425a;border-radius:10px;padding:16px}.card{margin:12px 0}.controls{display:flex;gap:12px;position:sticky;top:0;background:#101720;padding:10px;z-index:2}select,button{background:#26364a;color:white;border:1px solid #53667f;border-radius:6px;padding:7px;cursor:pointer}.timeline{height:20px;display:flex;gap:1px;margin:10px 0}.segment{padding:0;border:0;border-radius:0;min-width:1px}.accepted{background:#52b89c}.excluded{background:#67768a}.unknown{background:#e9b45a}.selected{outline:2px solid #fff}.segment-list{max-height:270px;overflow:auto}.row{padding:7px;border-bottom:1px solid #2e3d50;cursor:pointer}.row:hover{background:#27394e}.row .unknown{background:none;color:#ffca71}.row .excluded{background:none;color:#bbc5d0}#map{width:100%;height:420px;background:#102a2a}#map path,#map circle{vector-effect:non-scaling-stroke;stroke:#668b94;stroke-width:1;fill:#355463;cursor:pointer}#map .active{stroke:#ffcc66;fill:#db9f3e;stroke-width:3}video{width:100%;max-height:380px;margin-top:12px;background:black}.photos{display:flex;overflow-x:auto;gap:8px}.photos img{height:95px}.tag{border:1px solid #587089;padding:2px 5px;border-radius:4px;margin:3px;display:inline-block;font-size:12px}#detail{white-space:pre-wrap;font-size:14px;line-height:1.7}#relations{max-height:300px;overflow:auto}.stats{display:flex;gap:18px;flex-wrap:wrap;margin-top:12px}.stats b{font-size:22px}.dimmed{opacity:.12}@media(max-width:950px){main{grid-template-columns:1fr}}
</style><header><h1>njupt-map · 全视频观测审查</h1><div class="muted">来源 → 连续时间段 → 地点 / 部件 → 当前模型候选</div><div class="warning">本地资料浏览器。历史片段明确排除当前；未知显著保留。地图高亮表示父对象对应，不代表测得入口或相机位置。</div><div class="stats" id="stats"></div></header><main><div><div class="controls"><select id="campus"><option value="">全部校区</option><option>xianlin</option><option>sanpailou</option><option>other</option><option>unknown</option></select><select id="status"><option value="">全部状态</option><option>accepted</option><option>excluded</option><option>unknown</option></select><select id="eligibility"><option value="">全部时态</option><option>current_candidate</option><option>excluded_historical</option><option>excluded_other_campus</option><option>unresolved</option></select></div><div id="videos"></div></div><div><section><svg id="map" role="img" aria-label="地图对象语义对应"></svg><div class="muted">地图源：projects/map/campus.gpkg；局部米制坐标，父对象形状。</div><video id="player" controls preload="metadata"></video><div id="detail">点击时间段查看依据，点击地点或对象查看其来源。</div></section><section style="margin-top:18px"><h3>地点和连接关系</h3><div class="warning">只展示来源支持的关系；推断关系单独标记，不生成导航路径。</div><div id="places"></div><div id="relations"></div></section></div></main><script id="data" type="application/json">__DATA__</script><script>
const D=JSON.parse(document.querySelector('#data').textContent), $=s=>document.querySelector(s), escape=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time=t=>Math.floor(t/60)+':'+(t%60).toFixed(2).padStart(5,'0');
$('#stats').innerHTML=[['视频',D.summary.videos],['时间段',D.summary.segments],['分钟',(D.summary.duration_seconds/60).toFixed(1)],['精选帧',D.summary.selected_frames],['地点',D.summary.places]].map(([s,n])=>`<span><b>${n}</b> ${s}</span>`).join('');
const [xmin,ymin,xmax,ymax]=D.map.bounds;$('#map').setAttribute('viewBox',`${xmin-30} ${-ymax-30} ${xmax-xmin+60} ${ymax-ymin+60}`);
function geometry(r){const pts=r.outer||r.points;if(pts)return `<path data-asset="${escape(r.asset_id)}" d="M${pts.map(p=>`${p[0]},${-p[1]}`).join('L')}${r.outer?'Z':''}" ${r.points?'style="fill:none;stroke:#4d8b8b"':''}><title>${escape(r.name)} | ${escape(r.asset_id)}</title></path>`;if(r.point)return `<circle data-asset="${escape(r.asset_id)}" cx="${r.point[0]}" cy="${-r.point[1]}" r="2"><title>${escape(r.name)}</title></circle>`;return ''}
$('#map').innerHTML=D.map.records.map(geometry).join('');function highlight(aids){document.querySelectorAll('#map [data-asset]').forEach(e=>e.classList.toggle('active',aids.includes(e.dataset.asset)))}
document.querySelectorAll('#map [data-asset]').forEach(e=>e.addEventListener('click',()=>{const r=D.map.records.find(r=>r.asset_id===e.dataset.asset);highlight([r.asset_id]);$('#detail').textContent=`地图对象：${r.name}\n共同 ID：${r.asset_id}\n地图 ID：${r.map_feature_id||'未提供'}\n这里只展示权威地图几何，不等于视频相机配准。`}));
function matches(s){return ['campus','status','eligibility'].every(k=>!$('#'+k).value||s[k]===$('#'+k).value)}
function render(){const container=$('#videos');container.innerHTML='';for(const v of D.videos){const filtered=v.segments.filter(matches);if(!filtered.length)continue;const card=document.createElement('div');card.className='card';card.innerHTML=`<b>${escape(v.title)}</b><div class="muted">${escape(v.source_id)} · 发表 ${escape(v.published_at)} · ${time(v.duration_seconds)}</div><div class="timeline"></div><div class="segment-list"></div><div class="photos"></div><a href="${escape(v.url)}" target="_blank" rel="noreferrer">Bilibili 原页面</a>`;for(const s of v.segments){const btn=document.createElement('button');btn.className='segment '+s.status+(matches(s)?'':' dimmed');btn.style.flexGrow=s.end_seconds-s.start_seconds;btn.title=`${time(s.start_seconds)}–${time(s.end_seconds)} ${s.place_label} ${s.eligibility}`;btn.onclick=()=>choose(v,s);card.querySelector('.timeline').append(btn)}for(const s of filtered){const row=document.createElement('div');row.className='row';row.innerHTML=`<b>${time(s.start_seconds)}–${time(s.end_seconds)}</b> ${escape(s.place_label)}<br><small class="${s.status}">${escape(s.campus)} · ${escape(s.status)} · ${escape(s.eligibility)}</small>`;row.onclick=()=>choose(v,s);card.querySelector('.segment-list').append(row)}for(const f of v.selected_frames){const a=document.createElement('a');a.href=f.url;a.target='_blank';a.title=`${time(f.pts_seconds)} ${f.reason||''}`;const im=document.createElement('img');im.src=f.url;im.loading='lazy';im.alt=f.id;a.append(im);card.querySelector('.photos').append(a)}container.append(card)}}
function choose(v,s){highlight([...(s.asset_ids||[]),...(s.map_object_ids||[])]);const player=$('#player');if(player.dataset.source!==v.source_id){player.src=v.local_url;player.dataset.source=v.source_id;player.addEventListener('loadedmetadata',()=>{player.currentTime=s.start_seconds},{once:true})}else player.currentTime=s.start_seconds;$('#detail').textContent=`${v.title}\n${time(s.start_seconds)}–${time(s.end_seconds)}  ${s.place_label}\n${s.campus} · ${s.status} · ${s.eligibility}\n\n观察：${(s.observed_features||[]).join('；')}\n依据：${s.basis||''}\n置信度：${s.confidence||''}\n排除原因：${s.exclusion_reason||''}\n未知：${(s.uncertainties||[]).join('；')}\n位置：${(s.place_ids||[]).join(', ')}\n对象：${(s.asset_ids||[]).join(', ')}\n\n${(v.review.limitations||[]).join('\n')}`}
$('#places').innerHTML=Object.entries(D.topology.places).map(([id,p])=>`<button class="tag" data-place="${escape(id)}">${escape(p.label)} · ${escape(p.campus)}</button>`).join('');document.querySelectorAll('[data-place]').forEach(e=>e.onclick=()=>{const p=D.topology.places[e.dataset.place];highlight([...(p.asset_ids||[]),...(p.map_object_ids||[])]);$('#detail').textContent=`地点：${p.label}\n${p.kind} · ${p.campus}\n绑定：${p.spatial_binding.status}（父对象对应，具体入口位置未测量）\n来源：${JSON.stringify(p.source_refs,null,2)}`});
$('#relations').innerHTML=['current_candidate','excluded_historical','excluded_other_campus','unresolved'].map(kind=>`<h4>${escape(kind==='current_candidate'?'当前候选关系':kind==='excluded_historical'?'历史关系（排除当前）':kind==='unresolved'?'待核验关系':kind)}</h4>`+D.topology.edges.filter(e=>e.temporal_status===kind).map(e=>`<div class="row"><b>${escape(D.topology.places[e.from_place_id]?.label||e.from_place_id)} → ${escape(D.topology.places[e.to_place_id]?.label||e.to_place_id)}</b><br>${escape(e.relation)} · ${escape(e.basis)} · ${escape(e.temporal_status||'')}<br><small>${escape(JSON.stringify(e.source_refs))}</small></div>`).join('')).join('');['campus','status','eligibility'].forEach(k=>$('#'+k).onchange=render);render();
</script></html>'''


def export(root: Path = ROOT) -> dict:
    catalog, annotations, topology, campus = inputs(root)
    errors = validate_data(catalog, annotations, topology, campus)
    if errors:
        raise ValueError("Formal review validation failed:\n" + "\n".join(errors))
    output = root / "build/review"
    output.mkdir(parents=True, exist_ok=True)
    payload, coverage = build_payload(catalog, annotations, topology, campus, root, output)
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    (output / "index.html").write_text(PAGE.replace("__DATA__", data), encoding="utf-8")
    summary = payload["summary"]
    write(output / "summary.json", summary)
    write(output / "coverage.json", coverage)
    lines = ["# 视频观测审查总览", "", f"{summary['videos']} 个视频，{summary['segments']} 个连续分段，{summary['duration_seconds']/60:.2f} 分钟。",
             f"正式精选帧 {summary['selected_frames']} 张；地点 {summary['places']} 个；来源关系 {summary['relations']} 条。", "",
             "| 当前适用性 | 秒数 |", "| --- | ---: |"]
    lines.extend(f"| {key} | {value:.3f} |" for key, value in summary["seconds_by_eligibility"].items())
    lines.extend(["", f"视频标签关联建筑 {coverage['reviewed_visual_asset_count']}/{coverage['asset_count']}；当前候选涉及 {coverage['current_candidate_asset_count']} 个。",
                  "", "地图高亮为父对象语义对应，不能当作测得入口、相机姿态、尺寸精度或完整内部覆盖。未知保持显著；历史片段排除当前状态。",
                  "", "本地 index.html 可浏览时间段、视频、正式精选帧和来源关系；含受限资料的本地相对引用，不应部署成公共网站。"])
    (output / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--validate", action="store_true", help="Only validate formal annotations and topology")
    args = parser.parse_args()
    if args.validate:
        errors = validate_review_sources()
        print(json.dumps({"valid": not errors, "errors": errors}, ensure_ascii=False, indent=2))
        raise SystemExit(bool(errors))
    print(json.dumps(export(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
