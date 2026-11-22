"""Original procedural background music (no samples, no external sources)."""
import sys
import wave

import numpy as np

SR = 48000
DUR = 70.5
BPM = 96
BAR = 4 * 60 / BPM  # 2.5 s
N = int(SR * DUR)
t = np.arange(N) / SR
rng = np.random.default_rng(7)


def hz(m):
    return 440.0 * 2 ** ((m - 69) / 12)


# F maj7, C/E, Dm7, Bb maj9 (MIDI)
CHORDS = [[53, 57, 60, 64], [52, 55, 60, 67], [50, 57, 60, 65], [46, 53, 57, 62]]
BASS = [41, 40, 38, 34]


def env_adsr(n, a, r, sr=SR):
    e = np.ones(n)
    na, nr = int(a * sr), int(r * sr)
    e[:na] = np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return e


def tone(f, n, harm=(1, .3, .12), detune=0.0):
    tt = np.arange(n) / SR
    out = np.zeros(n)
    for k, a in enumerate(harm, 1):
        for d in (-detune, detune) if detune else (0,):
            out += a * np.sin(2 * np.pi * f * k * (1 + d) * tt + rng.uniform(0, 6.28))
    return out


def onepole(x, cutoff):
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = np.empty_like(x)
    acc = 0.0
    for i in range(len(x)):  # small enough loop for 70 s at 48 kHz? use block method instead
        acc = (1 - a) * x[i] + a * acc
        y[i] = acc
    return y


def lowpass(x, cutoff):
    # fast FIR approximation of a gentle low-pass (windowed sinc)
    taps = 255
    fc = cutoff / SR
    k = np.arange(taps) - (taps - 1) / 2
    h = np.sinc(2 * fc * k) * np.hamming(taps)
    h /= h.sum()
    return np.convolve(x, h, mode="same")


def add(buf, start, seg):
    if start >= N:
        return
    e = min(N, start + len(seg))
    buf[start:e] += seg[: e - start]


pad = np.zeros(N)
bass = np.zeros(N)
arp = np.zeros(N)
kick = np.zeros(N)
bars = int(np.ceil(DUR / BAR))
for b in range(bars):
    ci = b % 4
    s = int(b * BAR * SR)
    # pad: chord held for the bar with overlap tail
    n = int((BAR + 0.9) * SR)
    seg = sum(tone(hz(m), n, harm=(1, .25, .08), detune=.0018) for m in CHORDS[ci]) * env_adsr(n, .6, 1.0)
    add(pad, s, seg)
    # bass: root on beats 1 and 3
    for beat in (0, 2):
        bs = s + int(beat * BAR / 4 * SR); bn = int(1.1 * SR)
        seg = tone(hz(BASS[ci]), bn, harm=(1, .2)) * np.exp(-np.arange(bn) / SR * 2.2) * env_adsr(bn, .01, .2)
        add(bass, bs, seg)
    # arpeggio: eighth notes, from bar 2, thinned in the last two bars
    if 2 <= b < bars - 2:
        notes = [m + 12 for m in CHORDS[ci]] + [CHORDS[ci][2] + 24]
        pattern = [0, 2, 1, 3, 4, 2, 3, 1]
        for i, pi in enumerate(pattern):
            ns = s + int(i * BAR / 8 * SR); nn = int(.9 * SR)
            vel = .9 if i % 2 == 0 else .6
            seg = tone(hz(notes[pi]), nn, harm=(1, .35, .1, .05)) * np.exp(-np.arange(nn) / SR * 5.5) * env_adsr(nn, .004, .1) * vel
            add(arp, ns, seg)
    # soft kick on beats 1 and 3 during the middle section
    if 4 <= b < bars - 3:
        for beat in (0, 2):
            ks = s + int(beat * BAR / 4 * SR); kn = int(.35 * SR)
            kt = np.arange(kn) / SR
            f = 95 * np.exp(-kt * 18) + 45
            seg = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-kt * 9)
            add(kick, ks, seg)

pad = lowpass(pad, 1800)
arp = lowpass(arp, 4200)
mix = .55 * pad / np.abs(pad).max() + .5 * bass / np.abs(bass).max() + .42 * arp / np.abs(arp).max() + .35 * kick / max(1e-9, np.abs(kick).max())

# simple stereo + reverb-ish taps
left = mix.copy(); right = mix.copy()
for d, g in [(.031, .35), (.047, .3), (.083, .22), (.127, .16), (.191, .1)]:
    k = int(d * SR)
    left[k:] += g * mix[:-k]
    right[int(k * 1.13):] += g * mix[: -int(k * 1.13)]

stereo = np.stack([left, right], 1)
fade_in, fade_out = int(1.5 * SR), int(3.5 * SR)
stereo[:fade_in] *= np.linspace(0, 1, fade_in)[:, None]
stereo[-fade_out:] *= np.linspace(1, 0, fade_out)[:, None]
stereo *= 10 ** (-7 / 20) / np.abs(stereo).max()  # peak about -7 dBFS

pcm = (np.clip(stereo, -1, 1) * 32767).astype(np.int16)
with wave.open(sys.argv[1], "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes(pcm.tobytes())
print("ok", DUR, "s")
