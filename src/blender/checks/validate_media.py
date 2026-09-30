"""Decode and check the delivered film without modifying media or native sources.

This checks actual media integrity. It does not claim source-frame provenance
from timestamps or certify architectural accuracy.
"""
from pathlib import Path
import argparse, hashlib, json, shutil, subprocess
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]


def sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(8*1024*1024), b''):
            digest.update(block)
    return digest.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--video', type=Path, default=ROOT/'build/media/njupt-map.mp4')
    parser.add_argument('--frames', action='store_true', help='Also decode all 840 rendered PNG inputs')
    args = parser.parse_args()
    probe_tool = shutil.which('ffprobe')
    decode_tool = shutil.which('ffmpeg')
    if not probe_tool or not decode_tool:
        raise RuntimeError('FFmpeg and ffprobe must be available on PATH')
    before = sha256(args.video)
    probe = json.loads(subprocess.check_output([probe_tool,'-v','error','-show_streams','-show_format',
                                               '-of','json',str(args.video)], text=True,encoding='utf-8'))
    video = next(stream for stream in probe['streams'] if stream['codec_type']=='video')
    audio = next(stream for stream in probe['streams'] if stream['codec_type']=='audio')
    assert (video['width'],video['height'])==(1920,1080)
    assert video['codec_name']=='h264' and video['pix_fmt']=='yuv420p'
    assert video['avg_frame_rate']=='24/1' and int(video['nb_frames'])==840
    assert abs(float(video['duration'])-35)<.01
    assert audio['codec_name']=='aac' and int(audio['sample_rate'])==48000 and audio['channels']==2
    assert abs(float(audio['duration'])-35)<.05
    decoded = subprocess.run([decode_tool,'-hide_banner','-v','error','-i',str(args.video),
                              '-map','0:v:0','-map','0:a:0','-f','null','-'],
                             capture_output=True,text=True,encoding='utf-8')
    assert decoded.returncode==0 and not decoded.stderr.strip(), decoded.stderr
    frames=[]
    if args.frames:
        directory=ROOT/'build/blender/renders/film/frames'
        for number in range(1,841):
            path=directory/f'frame_{number:04d}.png'
            with Image.open(path) as image:
                assert image.size==(1920,1080)
                image.load()
            frames.append({'frame':number,'sha256':sha256(path)})
    assert sha256(args.video)==before, 'Film changed during validation'
    report={'status':'pass','video':args.video.relative_to(ROOT).as_posix(), 'sha256':before,
            'duration_seconds':35,'resolution':[1920,1080],'fps':24,'frames':840,
            'video_audio_decode':'pass','rendered_pngs_decoded':len(frames),
            'source_attribution':'Map data © OpenStreetMap contributors, ODbL',
            'scope':'Media integrity; architectural accuracy and exact render-source correspondence are separate checks.',
            'frame_sha256':frames,'ffprobe':probe}
    output=ROOT/'build/checks/film/media.json'
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print('FILM_VALIDATION_PASS',before)


if __name__=='__main__':
    main()
