"""CPU heuristic QA of the 840 source PNGs; run manually after rendering ends."""
from datetime import datetime, timezone
from pathlib import Path
import json
import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[3]
FRAMES = ROOT / 'build/blender/renders/film/frames'
REPORT = ROOT / 'build/checks/film/temporal_qa.json'


def measure(image, previous=None):
    pixels = np.asarray(image.convert('RGB').resize((256, 144), Image.Resampling.BOX), dtype=np.float32) / 255
    luma = pixels @ np.array([.2126, .7152, .0722], dtype=np.float32)
    mean, std = float(luma.mean()), float(luma.std())
    flags = []
    if mean < .008 and std < .006:
        flags.append('near_black_uniform')
    if mean > .992 and std < .006:
        flags.append('near_white_uniform')
    row = {'mean_luma': mean, 'luma_std': std, 'uniform_flags': flags,
           'previous_frame_rgb_mean_absolute_difference': None if previous is None else float(np.abs(pixels - previous).mean())}
    return pixels, row


def classify(rows):
    shots, anomalies, hard_cuts = [], [], []
    for shot in range(1, 8):
        group = rows[(shot - 1) * 120:shot * 120]
        differences = np.array([r['previous_frame_rgb_mean_absolute_difference'] for r in group[1:]])
        median = float(np.median(differences))
        mad = float(np.median(np.abs(differences - median)))
        threshold = max(median + 8 * 1.4826 * mad, 3 * median, .012)
        flagged = []
        for row in group[1:]:
            delta = row['previous_frame_rgb_mean_absolute_difference']
            if delta > threshold:
                flagged.append(row['frame'])
                anomalies.append({'frame': row['frame'], 'inspect_pair': [row['frame'] - 1, row['frame']],
                                  'shot': shot, 'difference': delta, 'threshold': threshold})
        shots.append({'shot': shot, 'frames': [group[0]['frame'], group[-1]['frame']],
                      'internal_difference_median': median, 'internal_difference_mad': mad,
                      'anomaly_threshold': threshold, 'candidate_frames': flagged})
        if shot > 1:
            first = group[0]
            hard_cuts.append({'frame': first['frame'], 'from_frame': first['frame'] - 1,
                              'difference': first['previous_frame_rgb_mean_absolute_difference'],
                              'classification': 'planned_hard_cut_excluded_from_anomaly_baseline'})
    return shots, anomalies, hard_cuts


def main():
    rows, previous = [], None
    for frame in range(1, 841):
        path = FRAMES / f'frame_{frame:04d}.png'
        with Image.open(path) as image:
            previous, row = measure(image, previous)
        rows.append({'frame': frame, 'path': path.relative_to(ROOT).as_posix(), **row})
    shots, anomalies, hard_cuts = classify(rows)
    uniform = [{'frame': row['frame'], 'flags': row['uniform_flags']} for row in rows if row['uniform_flags']]
    report = {
        'schema_version': '1.0', 'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'status': 'review_candidates' if anomalies or uniform else 'no_heuristic_candidates',
        'frame_count': len(rows), 'analysis_size': [256, 144], 'channel_scale': [0, 1],
        'method': 'Box-downsample RGB mean absolute adjacent-frame difference; per-shot median/MAD, excluding six planned cuts. Threshold=max(median+8*1.4826*MAD, 3*median, 0.012).',
        'uniform_thresholds': {'black_mean_below': .008, 'white_mean_above': .992, 'luma_std_below': .006},
        'scope': 'Source PNGs have no editorial fades. This is a CPU screening heuristic, not pixel-level truth, architectural fidelity, or final encoded-film certification. Normal occlusion and fast motion may trigger candidates; gradual defects, fine flicker and low-contrast errors may be missed. Inspect candidate pairs manually. No frames or media are modified.',
        'shots': shots, 'planned_hard_cuts': hard_cuts, 'internal_difference_candidates': anomalies,
        'uniform_frame_candidates': uniform, 'per_frame_metrics': rows,
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print(json.dumps({'report': str(REPORT), 'status': report['status'], 'difference_candidates': len(anomalies),
                      'uniform_candidates': len(uniform), 'planned_cuts': len(hard_cuts)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
