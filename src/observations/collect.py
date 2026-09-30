"""Archive a public source page and its media into the current observation catalog."""
from __future__ import annotations

import argparse
from html.parser import HTMLParser
import json
import mimetypes
from pathlib import Path
import re
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .__main__ import identifier
from .common import CATALOG, read, redistribution, resolve, source_record, now, write


class MediaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.images = []

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "img":
            for attribute in ("src", "original-src"):
                if values.get(attribute):
                    self.images.append((values[attribute], values.get("alt", "")))


def download(catalog: dict, sid: str, url: str, license_name: str, page: str | None = None) -> tuple[dict, bytes]:
    if sid in catalog["sources"]:
        raise ValueError(f"Source ID exists; use a new observation ID for a new acquisition: {sid}")
    if urlparse(url).scheme not in {"http", "https"}:
        raise ValueError("Only public HTTP(S) sources are accepted")
    request = Request(url, headers={"User-Agent":"njupt-map observation collector", "Referer":page or url})
    try:
        with urlopen(request, timeout=30) as response:
            data = response.read()
            mime = response.headers.get_content_type()
            modified = response.headers.get("Last-Modified")
            final_url = response.url
        suffix = Path(urlparse(final_url).path).suffix.lower()
        if mime == "text/html":
            suffix, kind = ".html", "documents"
        elif mime.startswith("image/"):
            suffix = mimetypes.guess_extension(mime) or suffix or ".bin"
            kind = "images"
        else:
            suffix = suffix if re.fullmatch(r"\.[a-zA-Z0-9]{1,8}",suffix) else ".bin"
            kind = "documents"
        path = resolve(f"observations/{kind}/{sid}{suffix}")
        if path.exists():
            raise ValueError(f"Unregistered source file exists: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        record = source_record(sid,path,kind,license_name,url=url,source_page=page or url,
                               final_url=final_url,mime_type=mime,server_last_modified=modified,
                               visual_review="pending")
        catalog["sources"][sid] = record
        return record,data
    except OSError as error:
        record = {"id":sid,"url":url,"source_page":page or url,"photo_taken_at":None,
                  "published_at":None,"retrieved_at":now(),"status":"unavailable",
                  "redistribution":redistribution(license_name),"error":str(error)}
        catalog["sources"][sid] = record
        return record,b""


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--id", type=identifier, required=True)
    parser.add_argument("--license", default="unknown")
    parser.add_argument("--images", action="store_true", help="Archive page image sources, retaining original URLs")
    args = parser.parse_args()
    catalog = read(CATALOG)
    record,data = download(catalog,args.id,args.url,args.license)
    if data and record.get("mime_type") == "text/html":
        text = data.decode("utf-8", errors="replace")
        title = re.search(r"<title[^>]*>(.*?)</title>", text, re.S|re.I)
        if title:
            record["title"] = re.sub(r"\s+"," ",title.group(1)).strip()
        date = re.search(r"(?:发布时间|发布日期)[^\d]{0,100}(20\d\d[-年]\d{1,2}[-月]\d{1,2})",text)
        if date:
            record["published_at"] = date.group(1)
            record["published_at_basis"] = "Publisher page label, not a photograph capture date"
        if args.images:
            media = MediaParser()
            media.feed(text)
            seen = set()
            for relative,alt in media.images:
                url = urljoin(record["final_url"],relative)
                if url in seen or urlparse(url).scheme not in {"http","https"}:
                    continue
                seen.add(url)
                sid = identifier(f"{args.id}-image-{len(seen):03d}")
                image,_ = download(catalog,sid,url,args.license,args.url)
                image["alt"] = alt
                image["published_at"] = record.get("published_at")
                image["photo_taken_at"] = None
    write(CATALOG,catalog)
    added = [sid for sid in catalog["sources"] if sid==args.id or sid.startswith(args.id+"-image-")]
    print(json.dumps({"source_ids":added,"unavailable_source_ids":[sid for sid in added if catalog["sources"][sid]["status"]=="unavailable"]}))


if __name__ == "__main__":
    main()
