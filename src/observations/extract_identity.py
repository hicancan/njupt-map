"""Extract editable name outlines from the registered school vector artwork.

Requires the optional PyMuPDF dependency and the local-only original artwork.
This transforms the school's supplied identity; it does not license the identity.
"""
from __future__ import annotations

import argparse
import json

from .common import CATALOG, checksum, read, resolve, source_record, write

GLYPHS = [("南",[224,225,226]),("京",[227,228,229]),("邮",[230]),
          ("电",[231,232,233]),("大",[237]),("学",[234,235,236])]


def extract(source) -> list[dict]:
    try:
        import pymupdf
    except ImportError as error:
        raise RuntimeError("PyMuPDF is required for this optional source-artwork extraction") from error
    with pymupdf.open(stream=source.read_bytes(),filetype="pdf") as document:
        paths = document[0].get_drawings()
    glyphs = []
    for character,indices in GLYPHS:
        contours = []
        for index in indices:
            ring = []
            for item in paths[index]["items"]:
                kind = item[0]
                if kind not in ("c","l"):
                    raise ValueError(f"Unexpected artwork command at path {index}: {kind}")
                start = item[1]
                if ring and abs(ring[-1][0]-start.x)+abs(ring[-1][1]-start.y) > .015:
                    if len(ring) > 2:
                        contours.append(ring)
                    ring = []
                if not ring:
                    ring.append(list(start))
                if kind == "l":
                    ring.append(list(item[2]))
                else:
                    a,b,c,d = item[1:]
                    for j in range(1,13):
                        t = j/12
                        u = 1-t
                        ring.append([u**3*a.x+3*u*u*t*b.x+3*u*t*t*c.x+t**3*d.x,
                                     u**3*a.y+3*u*u*t*b.y+3*u*t*t*c.y+t**3*d.y])
            if len(ring) > 2:
                contours.append(ring)
        flat = [point for ring in contours for point in ring]
        glyphs.append({"character":character,"source_path_indices":indices,
                       "bounds":[min(p[0] for p in flat),min(p[1] for p in flat),max(p[0] for p in flat),max(p[1] for p in flat)],
                       "contours":contours})
    return glyphs


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", default="official-logo-ai")
    parser.add_argument("--output", default="projects/blender/identity/njupt_official_name.json")
    args = parser.parse_args()
    catalog = read(CATALOG)
    original = catalog["sources"][args.source_id]
    source = resolve(original["local_path"])
    if checksum(source) != original["sha256"]:
        raise ValueError("Registered source artwork changed; path indices must be reviewed")
    output = resolve(args.output)
    value = {"source_url":original.get("url"),"source_page":original.get("source_page"),
             "source_sha256":original["sha256"],
             "scope":"Official six-character name outlines; placement and extrusion are inferred, not surveyed.",
             "glyphs":extract(source)}
    write(output,value)
    entry = source_record("official-name-vector",output,"derived_identity_outline",original["redistribution"]["license"],
                          derived_from={"source_ids":[args.source_id],"source_sha256":original["sha256"],
                                        "method":"Registered PDF-compatible artwork paths; cubic curves sampled in artwork coordinates"})
    entry["redistribution"] = dict(original["redistribution"])
    catalog["sources"][entry["id"]] = entry
    write(CATALOG,catalog)
    print(json.dumps({"output":args.output,"glyph_count":len(value["glyphs"])}))


if __name__ == "__main__":
    main()
