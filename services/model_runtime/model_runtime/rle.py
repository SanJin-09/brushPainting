from __future__ import annotations

import json

import numpy as np


def encode_mask_rle(mask: np.ndarray) -> str:
    if mask.ndim != 2:
        raise ValueError("Mask must be 2D")

    flat = mask.astype(np.uint8).flatten(order="C")
    counts: list[int] = []
    last = int(flat[0])
    run = 1
    for val in flat[1:]:
        val_i = int(val)
        if val_i == last:
            run += 1
        else:
            counts.append(run)
            run = 1
            last = val_i
    counts.append(run)
    return json.dumps({"h": int(mask.shape[0]), "w": int(mask.shape[1]), "start": int(flat[0]), "counts": counts})


def decode_mask_rle(payload: str) -> np.ndarray:
    data = json.loads(payload)
    h = int(data["h"])
    w = int(data["w"])
    start = int(data["start"])
    counts = data["counts"]

    out = np.zeros(h * w, dtype=np.uint8)
    val = start
    idx = 0
    for count in counts:
        end = idx + int(count)
        out[idx:end] = val
        val = 1 - val
        idx = end

    if idx != h * w:
        raise ValueError("Invalid RLE data")
    return out.reshape((h, w), order="C")
