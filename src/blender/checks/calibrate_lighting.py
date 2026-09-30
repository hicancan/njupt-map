"""Reproducible lighting comparison; does not save changes to the master."""
from pathlib import Path
import bpy, math
ROOT=Path(__file__).resolve().parents[3]
bpy.ops.wm.open_mainfile(filepath=str(ROOT/'projects/blender/campus.blend'))
s=bpy.context.scene
s.camera=bpy.data.objects['03_图书馆']
s.cycles.samples=32
s.render.resolution_x=1200;s.render.resolution_y=750
prefs=bpy.context.preferences.addons['cycles'].preferences
prefs.compute_device_type='OPTIX';prefs.refresh_devices()
for d in prefs.devices:d.use=d.type=='OPTIX'
s.cycles.device='GPU'
sky=next(n for n in s.world.node_tree.nodes if n.type=='TEX_SKY')
bg=next(n for n in s.world.node_tree.nodes if n.type=='BACKGROUND')
sun=bpy.data.objects['Afternoon sun']
for name,sky_type,strength,power,exp in [
    ('A_scattering_low_fill','MULTIPLE_SCATTERING',.045,3.5,.7),
    ('B_hosek_day','HOSEK_WILKIE',.4,3.5,.0),
    ('C_scattering_warm','MULTIPLE_SCATTERING',.065,5.,.65),
]:
    sky.sky_type=sky_type;bg.inputs['Strength'].default_value=strength
    sky.sun_direction=(.5,-.6,.55);sky.turbidity=2.2;sky.ground_albedo=.2
    sun.data.energy=power;sun.data.color=(1,.94,.85)
    sun.rotation_euler=(math.radians(48),math.radians(-30),math.radians(-105))
    s.view_settings.exposure=exp
    s.render.filepath=str(ROOT/'build/blender/renders/calibration'/f'{name}.png')
    bpy.ops.render.render(write_still=True)
