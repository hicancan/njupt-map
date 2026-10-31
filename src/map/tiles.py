from __future__ import annotations
import json, math, struct
from collections import defaultdict
from pathlib import Path
from typing import Any
from PIL import Image, ImageDraw
from pyproj import Transformer
from shapely.geometry import shape
from shapely.ops import transform, unary_union

EXTENT=4096
WGS_TO_M=Transformer.from_crs('EPSG:4326','EPSG:32650',always_xy=True).transform

def varint(value:int)->bytes:
    value=int(value); out=bytearray()
    while value>127:
        out.append((value&127)|128); value>>=7
    out.append(value); return bytes(out)
def zigzag(value:int)->int: return (value<<1) ^ (value>>31)
def field(tag:int,wire:int,data:bytes)->bytes: return varint((tag<<3)|wire)+data
def string_field(tag:int,value:str)->bytes:
    raw=value.encode('utf8'); return field(tag,2,varint(len(raw))+raw)
def packed_field(tag:int,values:list[int])->bytes:
    raw=b''.join(varint(v) for v in values); return field(tag,2,varint(len(raw))+raw)

def value_message(value:Any)->bytes:
    if isinstance(value,bool): return field(7,0,varint(1 if value else 0))
    if isinstance(value,int): return field(4,0,varint(value if value>=0 else (1<<64)+value))
    return string_field(1,str(value))

def lonlat_to_tile(c,z):
    lon,lat=c; n=2**z
    x=(lon+180)/360*n
    lat=max(-85.05112878,min(85.05112878,lat))
    y=(1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n
    return x,y

def tile_range(geom,z):
    minx,miny,maxx,maxy=shape(geom).bounds
    a=lonlat_to_tile((minx,miny),z); b=lonlat_to_tile((maxx,maxy),z); n=2**z
    return range(max(0,int(math.floor(min(a[0],b[0])))),min(n-1,int(math.floor(max(a[0],b[0]))))+1), range(max(0,int(math.floor(min(a[1],b[1])))),min(n-1,int(math.floor(max(a[1],b[1]))))+1)

def encode_geometry(geom,z,x,y):
    g=shape(geom); tx0,ty0=x,y
    def q(c):
        tx,ty=lonlat_to_tile(c,z); return round((tx-tx0)*EXTENT),round((ty-ty0)*EXTENT)
    def line(coords,close=False):
        pts=[q(c) for c in coords]
        if len(pts)>1 and pts[0]==pts[-1]: pts=pts[:-1]
        if not pts:return [],1
        out=[(1<<3)|1]; last=(0,0); out += [zigzag(pts[0][0]-last[0]),zigzag(pts[0][1]-last[1])]; last=pts[0]
        if len(pts)>1:
            out += [((len(pts)-1)<<3)|2]
            for p in pts[1:]: out += [zigzag(p[0]-last[0]),zigzag(p[1]-last[1])]; last=p
        if close: out += [15]
        return out,3 if close else 2
    if g.geom_type=='Point':
        p=q(g.coords[0]); return [9,zigzag(p[0]),zigzag(p[1])],1
    if g.geom_type=='LineString': return (*line(list(g.coords)),)
    if g.geom_type=='Polygon':
        commands=[]
        for ring in [g.exterior,*g.interiors]: commands.extend(line(list(ring.coords),True)[0])
        return commands,3
    if g.geom_type=='MultiLineString':
        commands=[]
        for ls in g.geoms: commands.extend(line(list(ls.coords))[0])
        return commands,2
    if g.geom_type=='MultiPolygon':
        commands=[]
        for p in g.geoms:
            for ring in [p.exterior,*p.interiors]: commands.extend(line(list(ring.coords),True)[0])
        return commands,3
    return [],1

def encode_layer(name:str,features:list[dict],z:int,x:int,y:int)->bytes:
    keys=[]; values=[]; key_index={}; value_index={}; encoded=[]
    for f in features:
        props=f.get('properties') or {}; tags=[]
        for k,v in sorted(props.items()):
            if v is None: continue
            if k not in key_index: key_index[k]=len(keys); keys.append(k)
            vk=json.dumps(v,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            if vk not in value_index: value_index[vk]=len(values); values.append(v)
            tags += [key_index[k],value_index[vk]]
        geom,type_id=encode_geometry(f['geometry'],z,x,y)
        if not geom: continue
        body=packed_field(2,tags)+field(3,0,varint(type_id))+packed_field(4,geom)
        encoded.append(field(2,2,varint(len(body))+body))
    layer=field(15,0,varint(2))+string_field(1,name)
    layer+=b''.join(encoded)
    layer+=b''.join(string_field(3,k) for k in keys)
    layer+=b''.join(field(4,2,varint(len(value_message(v)))+value_message(v)) for v in values)
    layer+=field(5,0,varint(EXTENT))
    return field(3,2,varint(len(layer))+layer)

def tile_bytes(tile_layers,z,x,y):
    return b''.join(encode_layer(name,fs,z,x,y) for name,fs in sorted(tile_layers.items()) if fs)

def tile_id(z,x,y):
    # PMTiles Hilbert id, matching the v3 specification.
    acc=((1<<z)*(1<<z)-1)//3; a=z-1; tx,ty=x,y
    def rot(n,x,y,rx,ry): return (n-1-y,n-1-x) if ry==0 and rx else ((y,x) if ry==0 else (x,y))
    s=1<<a
    while s>0:
        rx=tx&s; ry=ty&s; acc+=((3*rx)^ry)*(1<<a)
        tx,ty=rot(s,tx,ty,rx,ry); a-=1; s>>=1
    return acc

def directory(entries):
    entries=sorted(entries)
    out=bytearray(varint(len(entries))); last=0
    for tid,_,_,_ in entries: out+=varint(tid-last); last=tid
    for _,_,length,run in entries: out+=varint(run)
    for _,_,length,_ in entries: out+=varint(length)
    prev=None
    for _,offset,_,_ in entries:
        if prev is not None and offset==prev: out+=varint(0)
        else: out+=varint(offset+1)
        prev=offset+entries[entries.index((_,offset,_,_))][2] if False else offset
    # Above prev is only used for contiguous offsets; rebuild correctly.
    out=bytearray(varint(len(entries))); last=0
    for tid,_,_,_ in entries: out+=varint(tid-last); last=tid
    for _,_,_,run in entries: out+=varint(run)
    for _,_,length,_ in entries: out+=varint(length)
    last_end=None
    for _,offset,length,_ in entries:
        out+=varint(0 if last_end is not None and offset==last_end else offset+1); last_end=offset+length
    return bytes(out)

def write_pmtiles(path:Path,layers:dict[str,list[dict]],minzoom=12,maxzoom=16):
    tiles={}
    for z in range(minzoom,maxzoom+1):
        by=defaultdict(lambda:defaultdict(list))
        for name,features in layers.items():
            for f in features:
                if not f.get('geometry'): continue
                xs,ys=tile_range(f['geometry'],z)
                for x in xs:
                    for y in ys: by[(x,y)][name].append(f)
        for (x,y),tile_layers in by.items():
            data=tile_bytes(tile_layers,z,x,y)
            if data: tiles[tile_id(z,x,y)]=data
    tile_data=b''; entries=[]
    for tid in sorted(tiles):
        data=tiles[tid]; entries.append((tid,len(tile_data),len(data),1)); tile_data+=data
    root=directory(entries); metadata={'name':'njupt-map authored basemap','format':'pbf','version':'1','minzoom':minzoom,'maxzoom':maxzoom,'vector_layers':[{'id':k,'fields':{}} for k in sorted(layers)],'bounds':[118.8,32.09,119.0,32.14]}
    meta=json.dumps(metadata,ensure_ascii=False,separators=(',',':')).encode('utf8')
    root_off=127; meta_off=root_off+len(root); data_off=meta_off+len(meta)
    header=bytearray(127); header[:7]=b'PMTiles'; header[7]=3
    vals=[root_off,len(root),meta_off,len(meta),0,0,data_off,len(tile_data),len(entries),len(entries),len(entries)]
    for i,v in enumerate(vals): struct.pack_into('<Q',header,8+i*8,v)
    header[96]=1; header[97]=1; header[98]=1; header[99]=1; header[100]=minzoom; header[101]=maxzoom
    for off,v in zip((102,106,110,114),(118.8,32.09,119.0,32.14)): struct.pack_into('<i',header,off,round(v*1e7))
    header[118]=14; struct.pack_into('<i',header,119,round(118.925*1e7)); struct.pack_into('<i',header,123,round(32.115*1e7))
    path.parent.mkdir(parents=True,exist_ok=True); path.write_bytes(bytes(header)+root+meta+tile_data)
    return {'tiles':len(entries),'bytes':path.stat().st_size,'minzoom':minzoom,'maxzoom':maxzoom}

def render_preview(path:Path,layers:dict[str,list[dict]],width=1600,height=1200):
    geoms=[shape(f['geometry']) for fs in layers.values() for f in fs if f.get('geometry')]
    bounds=unary_union(geoms).bounds; minx,miny,maxx,maxy=bounds; pad=0.0005
    minx-=pad; miny-=pad; maxx+=pad; maxy+=pad
    def px(c): return ((c[0]-minx)/(maxx-minx)*width,height-(c[1]-miny)/(maxy-miny)*height)
    im=Image.new('RGB',(width,height),'#f4f1e9'); d=ImageDraw.Draw(im)
    colors={'greens':'#b8cda5','waters':'#9cced8','sports':'#d69a87','surfaces':'#ddd7ca','context_buildings':'#cfc9bd','buildings':'#b9956d','ways':'#a99f91','campuses':'#f0eee5'}
    def draw_geom(g,color):
        if g.geom_type=='Polygon': d.polygon([px(c) for c in g.exterior.coords],fill=color,outline='#918879')
        elif g.geom_type=='LineString': d.line([px(c) for c in g.coords],fill=color,width=2)
    for name in ('greens','waters','sports','surfaces','context_buildings','campuses','buildings','ways'):
        for f in layers.get(name,[]): draw_geom(shape(f['geometry']),colors.get(name,'#888'))
    im.save(path,'PNG'); return {'path':str(path),'bounds':[minx,miny,maxx,maxy],'bytes':path.stat().st_size}
