import io

import numpy as np
import soundfile as sf

from sleepmix.audio import AudioBuffer, encode_wav


def _buf(secs=0.5, sr=22050):
    t = np.arange(int(sr * secs)) / sr
    y = (0.3 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    return AudioBuffer(np.stack([y, y], axis=1), sr)


def test_encodes_a_riff_wav():
    data = encode_wav(_buf())
    assert data[:4] == b"RIFF"
    assert data[8:12] == b"WAVE"


def test_round_trips_through_soundfile():
    buf = _buf()
    back, sr = sf.read(io.BytesIO(encode_wav(buf)), dtype="float32", always_2d=True)
    assert sr == buf.sr
    assert back.shape == buf.data.shape
    assert np.abs(back - buf.data).max() < 1e-3   # PCM_16 quantization


def test_encodes_an_empty_buffer_without_raising():
    data = encode_wav(AudioBuffer(np.zeros((0, 2), dtype=np.float32), 44100))
    assert data[:4] == b"RIFF"
