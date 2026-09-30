"""Compose an original 35 s cinematic electronic score, without sampled music.

Run with the project's Python environment. Requires numpy and ffmpeg/ffprobe.
Musical material, synthesizers, effects, mix and deterministic random seeds are
all contained here so this soundtrack can be reproduced and re-edited.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import wave

import numpy as np

SR = 48_000
DURATION = 35.0
BPM = 96
BEAT = 60 / BPM
BAR = 4 * BEAT
N = int(SR * DURATION)
ROOT = Path(__file__).resolve().parents[2]
RNG = np.random.default_rng(2026093001)


def midi(note: float) -> float:
    return 440.0 * 2.0 ** ((note - 69) / 12)


def timebase(duration: float) -> np.ndarray:
    return np.arange(round(duration * SR), dtype=np.float32) / SR


def gate(t: np.ndarray, attack: float, hold: float, release: float) -> np.ndarray:
    """C1-continuous envelope avoids attacks/cutoffs becoming clicks."""
    a = np.sin(np.minimum(t / attack, 1) * np.pi / 2) ** 2
    r = np.cos(np.clip((t - hold) / release, 0, 1) * np.pi / 2) ** 2
    return a * r


def colored_noise(length: int, low: float, high: float) -> np.ndarray:
    freqs = np.fft.rfftfreq(length, 1 / SR)
    spectrum = np.fft.rfft(RNG.standard_normal(length))
    filt = 1 / (1 + (np.maximum(freqs, 1) / high) ** 6)
    filt *= 1 - 1 / (1 + (np.maximum(freqs, 1) / low) ** 6)
    signal = np.fft.irfft(spectrum * filt, n=length).astype(np.float32)
    return signal / max(float(np.std(signal)), 1e-9)


def add(track: np.ndarray, sound: np.ndarray, start: float, gain: float = 1, pan: float = 0) -> None:
    index = round(start * SR)
    if index >= N:
        return
    if index < 0:
        sound = sound[-index:]
        index = 0
    count = min(len(sound), N - index)
    if count <= 0:
        return
    if sound.ndim == 2:
        track[index:index + count] += sound[:count] * gain
    else:
        angle = (pan + 1) * np.pi / 4
        track[index:index + count, 0] += sound[:count] * (gain * np.cos(angle))
        track[index:index + count, 1] += sound[:count] * (gain * np.sin(angle))


def pad(note: int, duration: float, phase: float, brightness: float = 1) -> np.ndarray:
    t = timebase(duration + 1.8)
    f = midi(note)
    envelope = gate(t, .65, duration - .18, 1.85)
    sound = np.zeros((len(t), 2), np.float32)
    # Slightly detuned additive voices: soft analogue/string timbre, no saw aliasing.
    for ch in range(2):
        v = np.zeros(len(t), np.float32)
        cents = [-4.8, 3.7][ch]
        vibrato = .007 * np.sin(2 * np.pi * (.19 + ch * .04) * t + phase)
        for partial in range(1, 13):
            weight = math.exp(-partial / (3.3 * brightness)) / partial ** 1.2
            v += weight * np.sin(2 * np.pi * f * 2 ** (cents / 1200) * partial * t + vibrato * partial + phase)
        sound[:, ch] = v * envelope * (1 + .06 * np.sin(2 * np.pi * .41 * t + ch))
    return sound


def keys(note: int, duration: float = 2.4, velocity: float = 1) -> np.ndarray:
    t = timebase(duration)
    f = midi(note)
    out = np.zeros(len(t), np.float32)
    # Hammer-like warm electric keys, upper partials decay before the fundamental.
    for harmonic, weight in [(1, 1), (2, .40), (3, .19), (4, .095), (5, .035), (7, .012)]:
        detune = 1 + .00010 * (harmonic ** 2)
        out += weight * np.sin(2 * np.pi * f * harmonic * detune * t) * np.exp(-t * (.95 + .48 * harmonic))
    out *= (1 - np.exp(-t * 310)) * gate(t, .006, duration - .24, .24)
    return out * velocity


def shimmer(note: int, duration: float) -> np.ndarray:
    t = timebase(duration)
    f = midi(note)
    out = np.sin(2 * np.pi * f * t + .07 * np.sin(2 * np.pi * 4.4 * t))
    out += .25 * np.sin(2 * np.pi * 2 * f * t)
    return out * gate(t, .48, duration - .55, .55)


def pulse(note: int, duration: float = .34) -> np.ndarray:
    t = timebase(duration)
    f = midi(note)
    out = np.sin(2 * np.pi * f * t) + .19 * np.sin(2 * np.pi * f * 2 * t) + .07 * np.sin(2 * np.pi * f * 3 * t)
    return out * (1 - np.exp(-t * 550)) * np.exp(-t * 17) * gate(t, .003, duration - .035, .035)


def bass(note: int, duration: float) -> np.ndarray:
    t = timebase(duration)
    f = midi(note)
    sound = np.sin(2 * np.pi * f * t) + .23 * np.sin(2 * np.pi * f * 2 * t) + .06 * np.sin(2 * np.pi * f * 3 * t)
    return sound * gate(t, .036, duration - .22, .28)


def kick(strength: float = 1) -> np.ndarray:
    t = timebase(.8)
    # Integrate a falling oscillator, keeping the sub tail in phase.
    phase = 2 * np.pi * (42 * t + 65 * .038 * (1 - np.exp(-t / .038)))
    sub = np.sin(phase) * np.exp(-t * 7.5)
    tap = colored_noise(len(t), 1200, 5500) * np.exp(-t * 150) * .08
    return np.tanh((sub + tap) * 1.2) * gate(t, .0015, .55, .25) * strength


def snare() -> np.ndarray:
    t = timebase(.38)
    noise = colored_noise(len(t), 850, 5800)
    body = .4 * np.sin(2 * np.pi * 177 * t) * np.exp(-t * 29)
    return (noise * .18 * np.exp(-t * 20) + body) * gate(t, .002, .27, .11)


def hat() -> np.ndarray:
    t = timebase(.16)
    return colored_noise(len(t), 5600, 10500) * np.exp(-t * 64) * gate(t, .001, .10, .06)


def whoosh(duration: float = 1.4) -> np.ndarray:
    t = timebase(duration)
    env = np.sin(np.pi * t / duration) ** 2
    sound = colored_noise(len(t), 400, 4200) * env
    # Continuous stereo travel is a restrained edit cue, not a jump scare.
    theta = (.1 + .8 * t / duration) * np.pi / 2
    return np.column_stack((sound * np.cos(theta), sound * np.sin(theta)))


def boom() -> np.ndarray:
    t = timebase(2.7)
    phase = 2 * np.pi * (34 * t + 24 * .09 * (1 - np.exp(-t / .09)))
    return (np.sin(phase) * np.exp(-t * 2.2) + .14 * colored_noise(len(t), 130, 1000) * np.exp(-t * 4)) * gate(t, .009, 2.0, .7)


def fft_convolve(signal: np.ndarray, impulse: np.ndarray) -> np.ndarray:
    length = len(signal) + len(impulse) - 1
    size = 1 << (length - 1).bit_length()
    return np.fft.irfft(np.fft.rfft(signal, size) * np.fft.rfft(impulse, size), size)[:len(signal)].astype(np.float32)


def room(track: np.ndarray, wet: float, decay: float = 1.7) -> np.ndarray:
    # Diffuse stereo response with decorrelated early reflections and dark tails.
    count = int(SR * 3.3)
    t = np.arange(count) / SR
    result = np.zeros_like(track)
    for ch in range(2):
        noise = colored_noise(count, 180, 4200)
        ir = noise * np.exp(-t * 6.9078 / decay) * .0033
        ir[:int(.023 * SR)] = 0
        for delay, gain in [(0.037, .22), (.071, .14), (.109, .10), (.173, .07)]:
            ir[int((delay + ch * .0067) * SR)] += gain
        result[:, ch] = fft_convolve(track[:, ch] * .85 + track[:, 1 - ch] * .15, ir) * wet
    return result


def write_wav(path: Path, sound: np.ndarray) -> None:
    pcm = (np.clip(sound, -.99999, .99999) * 32767).astype('<i2')
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(2)
        f.setsampwidth(2)
        f.setframerate(SR)
        f.writeframes(pcm.tobytes())


def command(args: list[str]) -> subprocess.CompletedProcess:
    proc = subprocess.run(args, capture_output=True, text=True, encoding='utf-8', errors='replace')
    if proc.returncode:
        raise RuntimeError(f"Command failed: {args}\n{proc.stderr}")
    return proc


def loudness_json(log: str) -> dict:
    start = log.rfind('{')
    end = log.find('}', start)
    return json.loads(log[start:end + 1])


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'build/media/audio')
    parser.add_argument('--temp', type=Path, default=ROOT/'build/media/_work/audio')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    args.temp.mkdir(parents=True, exist_ok=True)
    ffmpeg, ffprobe = shutil.which('ffmpeg'), shutil.which('ffprobe')
    if not ffmpeg or not ffprobe:
        raise RuntimeError('ffmpeg and ffprobe must be on PATH')

    pads = np.zeros((N, 2), np.float32)
    piano = np.zeros_like(pads)
    rhythm = np.zeros_like(pads)
    air = np.zeros_like(pads)
    low = np.zeros_like(pads)
    # D minor opening turns into F major light at the end. Chord voicings are
    # intentionally open, avoiding the muddy stacked thirds of a cheap preset.
    chords = [
        (38, [57, 62, 65, 69, 76], 'Dm9'),
        (34, [53, 58, 62, 69, 72], 'Bbmaj9'),
        (41, [57, 60, 65, 67, 72], 'Fadd9'),
        (36, [55, 60, 64, 67, 74], 'Cadd9'),
        (38, [57, 62, 65, 69, 76], 'Dm9'),
        (34, [53, 58, 62, 69, 72], 'Bbmaj9'),
        (31, [53, 58, 62, 65, 69], 'Gm9'),
        (33, [52, 57, 62, 64, 69], 'Asus4'),
        (34, [53, 58, 62, 69, 72], 'Bbmaj9'),
        (36, [55, 60, 64, 67, 74], 'Cadd9'),
        (41, [57, 60, 65, 67, 72], 'Fadd9'),
        (38, [57, 62, 65, 69, 76], 'Dm9'),
        (34, [53, 58, 62, 65, 72], 'Bbmaj9'),
        (29, [53, 60, 65, 67, 72], 'Fadd9'),
    ]
    for bar, (root, notes, _) in enumerate(chords):
        at = bar * BAR
        energy = [.50, .53, .62, .64, .72, .74, .85, .9, .97, 1, 1.12, 1.10, .9, .75][bar]
        for index, note in enumerate(notes):
            add(pads, pad(note, BAR, index * .91 + bar * .3, .82 + energy * .18), at, .040 * energy)
        add(low, bass(root, BAR + .08), at, .17 * energy)
        if bar >= 2:
            # A syncopated eight-note figure. Varying voicing keeps pulse alive.
            pattern = [0, 2, 1, 3, 2, 4, 1, 3]
            for step, idx in enumerate(pattern):
                start = at + step * BEAT / 2
                gain = .029 * energy * (1 if step % 2 == 0 else .70)
                if bar == 13:
                    gain *= .45
                add(piano, keys(notes[idx] + 12, 1.6), start, gain, -.4 + .8 * ((step * 3) % 8) / 7)
        if 4 <= bar <= 11:
            for step in range(16):
                note = root + 24 + [0, 7, 12, 7][step % 4]
                add(rhythm, pulse(note), at + step * BEAT / 4, .018 * energy * (1 if step % 4 == 0 else .6), .22 if step % 2 else -.22)
        if 2 <= bar <= 12:
            # Broad beats with restraint: architecture remains the subject.
            kick_beats = [0, 2] if bar < 8 else [0, 1.5, 2, 3.5]
            for beat in kick_beats:
                add(rhythm, kick(), at + beat * BEAT, .19 * energy)
            if bar >= 4:
                for beat in [1, 3]:
                    add(rhythm, snare(), at + beat * BEAT, .105 * energy, -.05)
                for eighth in range(8):
                    add(rhythm, hat(), at + eighth * BEAT / 2, .012 * energy * (1 if eighth % 2 else .6), .4)
        elif bar == 13:
            add(rhythm, kick(.6), at, .12)

    # Original exposed motif, then a higher answering phrase at the wide reveal.
    melody = [
        (5.0, 69, .7), (5.94, 72, .8), (7.18, 67, .9),
        (8.12, 64, .8), (9.06, 67, .7),
        (10.0, 69, .9), (11.25, 77, .9), (12.50, 74, .9), (13.75, 72, 1.0),
        (15.0, 70, .9), (16.25, 69, .8), (17.50, 69, .8), (18.75, 76, .9),
        (20.0, 77, .8), (20.94, 74, .8), (22.50, 76, .9), (23.75, 79, .9),
        (25.0, 81, 1.1), (26.25, 79, .8), (27.50, 77, .8), (28.75, 76, .8),
        (30.0, 74, 1.0), (31.25, 72, .8), (32.50, 77, 2.2),
    ]
    for at, note, length in melody:
        add(piano, keys(note, max(2.0, length + 1.1)), at, .060 if at < 20 else .072, -.10)
        if at >= 15:
            add(air, shimmer(note - 12, length + .65), at, .020, .18)

    # Larger phrase accents occur on the seven-shot edit grid.
    for at in [0, 5, 10, 15, 20, 25, 30, 32.5]:
        add(low, boom(), at, .10 if at in [0, 25] else .055)
    for at in [5, 10, 15, 20, 25, 30]:
        add(air, whoosh(), at - .95, .009 if at < 20 else .012)
    # Soft opening air and a high, gentle final suspended resolution.
    add(air, shimmer(81, 5), 0, .01, -.35)
    add(air, shimmer(84, 4.5), 29.8, .009, .35)

    mix = pads + piano + rhythm + air + low
    mix += room(piano, .70, 2.35)
    mix += room(pads + air, .36, 2.85)
    mix += room(rhythm, .16, .90)
    # Sparse dotted-eighth key echoes widen the score without washing the kick.
    for delay, gain, swap in [(BEAT * .75, .22, True), (BEAT * 1.5, .11, False)]:
        shift = round(delay * SR)
        mix[shift:] += piano[:-shift, ::-1] * gain if swap else piano[:-shift] * gain
    # Remove DC, smoothly round rare peaks, preserve transient crest factor.
    mix -= np.mean(mix, axis=0)
    mix = np.tanh(mix * 1.3) / 1.3
    mix *= min(.88 / float(np.max(np.abs(mix))), 1.7)
    t = np.arange(N, dtype=np.float64) / SR
    mix *= (np.sin(np.clip(t / .7, 0, 1) * np.pi / 2) ** 2)[:, None]
    mix *= (np.cos(np.clip((t - 33.6) / 1.4, 0, 1) * np.pi / 2) ** 2)[:, None]
    raw = args.temp / 'score_mix_pre_normalization.wav'
    write_wav(raw, mix)

    target = 'I=-16:TP=-1.5:LRA=9'
    first = command([ffmpeg, '-hide_banner', '-nostdin', '-i', str(raw), '-af', f'loudnorm={target}:print_format=json', '-f', 'null', '-'])
    measured = loudness_json(first.stderr)
    normalized = args.output / 'njupt_campus_original_score_35s.wav'
    params = (f'loudnorm={target}:measured_I={measured["input_i"]}:measured_TP={measured["input_tp"]}'
              f':measured_LRA={measured["input_lra"]}:measured_thresh={measured["input_thresh"]}'
              f':offset={measured["target_offset"]}:linear=true:print_format=json')
    second = command([ffmpeg, '-y', '-hide_banner', '-nostdin', '-i', str(raw), '-af', params,
                      '-ar', str(SR), '-ac', '2', '-c:a', 'pcm_s24le', '-t', str(DURATION), str(normalized)])
    verified = command([ffmpeg, '-hide_banner', '-nostdin', '-i', str(normalized), '-af', f'loudnorm={target}:print_format=json', '-f', 'null', '-'])
    actual = loudness_json(verified.stderr)
    aac = args.output / 'njupt_campus_original_score_35s.m4a'
    command([ffmpeg, '-y', '-hide_banner', '-nostdin', '-i', str(normalized), '-c:a', 'aac', '-b:a', '320k', '-movflags', '+faststart', str(aac)])
    probe = json.loads(command([ffprobe, '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(normalized)]).stdout)
    stats = command([ffmpeg, '-hide_banner', '-nostdin', '-i', str(normalized), '-af', 'astats=metadata=1:reset=0', '-f', 'null', '-'])
    (args.temp / 'master_astats.log').write_text(stats.stderr, encoding='utf-8')
    with wave.open(str(normalized), 'rb') as source:
        packed = np.frombuffer(source.readframes(source.getnframes()), dtype=np.uint8).reshape(-1, 3)
    integers = (packed[:, 0].astype(np.int32) | (packed[:, 1].astype(np.int32) << 8) |
                (packed[:, 2].astype(np.int32) << 16))
    decoded = np.where(integers & 0x800000, integers - 0x1000000, integers).reshape(-1, 2) / 8388608
    pcm_metrics = {
        'frame_count': len(decoded),
        'peak_dbfs': float(20 * np.log10(np.max(np.abs(decoded)))),
        'clipped_samples': int(np.count_nonzero(np.abs(decoded) >= .99999)),
        'stereo_correlation': float(np.corrcoef(decoded.T)[0, 1]),
        'five_second_rms_dbfs': [round(float(20 * np.log10(np.sqrt(np.mean(decoded[i * 240000:(i + 1) * 240000] ** 2)))), 2) for i in range(7)],
        'last_sample': decoded[-1].tolist(),
    }
    streams = probe['streams']
    valid = (abs(float(probe['format']['duration']) - DURATION) < 1 / SR and
             streams[0]['channels'] == 2 and streams[0]['sample_rate'] == str(SR) and
             float(actual['input_tp']) <= -1.40 and abs(float(actual['input_i']) + 16) <= .30 and
             pcm_metrics['clipped_samples'] == 0 and pcm_metrics['frame_count'] == N)
    timeline = [
        {'start': 0, 'end': 5, 'character': '克制氛围与低频起势；D 小调九和弦'},
        {'start': 5, 'end': 10, 'character': '温暖琴键主题进入；轻节拍'},
        {'start': 10, 'end': 15, 'character': '十六分电子脉冲加入；主题上扬'},
        {'start': 15, 'end': 20, 'character': '铺底与旋律加厚；悬置和声积累'},
        {'start': 20, 'end': 25, 'character': '节奏展开；向全景高潮推进'},
        {'start': 25, 'end': 30, 'character': 'F 大调亮色高潮；主题高音回答'},
        {'start': 30, 'end': 35, 'character': '收束与终止；33.6 秒开始柔和淡出'},
    ]
    report = {'passed': valid, 'title': 'Xianlin / A Campus in Light', 'duration_seconds': DURATION,
              'tempo_bpm': BPM, 'time_signature': '4/4', 'bars': 14, 'sample_rate_hz': SR,
              'channels': 2, 'pcm_bit_depth': 24, 'target_lufs': -16, 'target_true_peak_dbtp': -1.5,
              'first_pass': measured, 'second_pass': loudness_json(second.stderr), 'final_measured': actual,
              'wav': str(normalized), 'aac': str(aac), 'sha256': hashlib.sha256(normalized.read_bytes()).hexdigest(),
              'probe': probe, 'pcm_metrics': pcm_metrics, 'timeline': timeline,
              'provenance': 'Original algorithmically composed electronic score. All waveforms synthesized locally; no external recordings, songs, samples, or voices.',
              'limitations': 'Synthetic instrumental production; not a recording of a human orchestra.'}
    report_path = ROOT / 'build/checks/film_audio_validation.json'
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    license_text = '''# 仙林校园宣传片原创配乐

作品名：Xianlin / A Campus in Light

本配乐为本项目专门编写的原创电子器乐。旋律、和声、节奏、音色与混音由可重跑脚本生成；未使用外部歌曲、录音、音色采样包或人声。它是合成配乐，不是真人管弦乐录音。

文件：`njupt_campus_original_score_35s.wav` 是 48 kHz / 24 bit / 双声道母带；`.m4a` 是 320 kbps AAC 试听版。时长 35.000 秒，96 BPM，14 小节，建议 0、5、10、15、20、25、30、35 秒作为镜头节点。片尾在 33.6 秒后平滑淡出。

可在本校园宣传片及用户的后续剪辑中使用、修改。作者不引入额外署名要求。未做第三方曲库的相似性检索或版权登记。

复现：在项目根目录运行 `.venv/Scripts/python.exe src/blender/compose_film_score.py`。依赖已有 numpy 与 FFmpeg，固定随机种子。实际响度及峰值见 `build/checks/film_audio_validation.json`。
'''
    (args.output / '原创配乐说明.md').write_text(license_text, encoding='utf-8')
    print(json.dumps({'passed': valid, 'wav': str(normalized), 'duration': probe['format']['duration'],
                      'measured_lufs': actual['input_i'], 'true_peak_dbtp': actual['input_tp'], 'lra': actual['input_lra']}, ensure_ascii=False))
    if not valid:
        raise RuntimeError('Audio validation failed; inspect build/checks/film_audio_validation.json')


if __name__ == '__main__':
    main()
