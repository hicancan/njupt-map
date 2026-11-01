"""Acceptance gates, exact-frame lineage and safe resumability."""
from contextlib import ExitStack
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from src.observations import common, curate_video
from src.observations.transcribe_video import resume_document


class VideoCurationTest(unittest.TestCase):
    def setUp(self):
        task = Path(tempfile.gettempdir())
        task.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=task)
        self.root = Path(self.temp.name).resolve()
        self.stack = ExitStack()
        self.stack.enter_context(patch.object(common, 'ROOT', self.root))

    def tearDown(self):
        self.stack.close()
        self.temp.cleanup()

    def test_only_accepted_xianlin_frames_are_promoted(self):
        annotation = {'segments': [{'status': 'excluded', 'campus': 'xianlin', 'start_seconds': 0,
                                    'end_seconds': 2, 'selected_frame_pts_seconds': [1]}]}
        with self.assertRaises(ValueError):
            curate_video.selections(annotation)
        annotation['segments'][0].update(status='accepted', campus='sanpailou')
        with self.assertRaises(ValueError):
            curate_video.selections(annotation)

    @unittest.skipUnless(shutil.which('ffmpeg') and shutil.which('ffprobe'), 'FFmpeg unavailable')
    def test_exact_frame_source_rights_native_size_and_idempotence(self):
        video = self.root / 'observations/videos/fixture.mp4'
        video.parent.mkdir(parents=True)
        subprocess.run(['ffmpeg', '-nostdin', '-hide_banner', '-loglevel', 'error', '-f', 'lavfi', '-i',
                        'testsrc2=size=96x64:rate=10', '-t', '2', '-c:v', 'mpeg4', str(video)], check=True)
        source = common.source_record('fixture', video, 'videos', 'unknown', platform_identifiers={'bvid': 'BVfixture'})
        catalog = {'sources': {'fixture': source}}
        bindings = {'bindings': [{'asset_id': 'building-a', 'source_ids': []}]}
        annotation = {'source_id': 'fixture', 'source_sha256': source['sha256'],
                      'segments': [{'id': 's001', 'start_seconds': 0, 'end_seconds': 2, 'status': 'accepted',
                                    'campus': 'xianlin', 'eligibility': 'current_candidate', 'asset_ids': ['building-a'], 'place_label': 'Entrance',
                                    'selected_frame_pts_seconds': [1.1]}]}
        self.assertEqual(curate_video.promote(annotation, catalog, bindings), 1)
        frame = next(v for v in catalog['sources'].values() if v['kind'] == 'selected_video_frame')
        self.assertEqual(frame['derived_from']['decoded_pts_seconds'], 1.1)
        self.assertEqual(frame['redistribution'], source['redistribution'])
        self.assertIsNone(frame['photo_taken_at'])
        from PIL import Image
        with Image.open(common.resolve(frame['local_path'])) as image:
            self.assertEqual(image.size, (96, 64))
        self.assertEqual(curate_video.promote(annotation, catalog, bindings), 0)
        self.assertEqual(len(bindings['bindings'][0]['components']), 1)
        annotation['segments'][0]['id'] = 's002'
        with self.assertRaisesRegex(ValueError, 'metadata differs'):
            curate_video.promote(annotation, catalog, bindings)
        annotation['segments'][0]['id'] = 's001'
        annotation['segments'][0]['eligibility'] = 'unresolved'
        with self.assertRaises(ValueError):
            curate_video.promote(annotation, catalog, bindings)
        annotation['segments'][0]['eligibility'] = 'current_candidate'
        annotation['segments'][0]['selected_frame_pts_seconds'] = [1.05]
        with self.assertRaisesRegex(ValueError, 'actual source PTS'):
            curate_video.promote(annotation, catalog, bindings)

    def test_transcript_resume_rejects_different_input_or_chunk_grid(self):
        audio, output = self.root / 'audio.wav', self.root / 'transcript.json'
        audio.write_bytes(b'input-one')
        document = resume_document(audio, output, 'model-a', 30)
        output.write_text(json.dumps(document), encoding='utf-8')
        self.assertEqual(resume_document(audio, output, 'model-a', 30), document)
        for model, chunk in [('model-b', 30), ('model-a', 15)]:
            with self.assertRaises(ValueError):
                resume_document(audio, output, model, chunk)
        audio.write_bytes(b'input-two')
        with self.assertRaises(ValueError):
            resume_document(audio, output, 'model-a', 30)


if __name__ == '__main__':
    unittest.main()
