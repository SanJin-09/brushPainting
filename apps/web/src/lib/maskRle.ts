export type DecodedMask = {
  width: number;
  height: number;
  data: Uint8Array;
};

export function encodeMaskRle(mask: Uint8Array, width: number, height: number) {
  if (mask.length !== width * height) {
    throw new Error("Mask size does not match width * height");
  }

  const counts: number[] = [];
  let last = mask[0] ? 1 : 0;
  let run = 1;
  for (let i = 1; i < mask.length; i += 1) {
    const value = mask[i] ? 1 : 0;
    if (value === last) {
      run += 1;
    } else {
      counts.push(run);
      run = 1;
      last = value;
    }
  }
  counts.push(run);
  return JSON.stringify({ h: height, w: width, start: mask[0] ? 1 : 0, counts });
}

export function decodeMaskRle(payload: string): DecodedMask {
  const parsed = JSON.parse(payload) as {
    h: number;
    w: number;
    start: number;
    counts: number[];
  };
  const size = parsed.h * parsed.w;
  const out = new Uint8Array(size);
  let index = 0;
  let value = parsed.start ? 1 : 0;
  for (const count of parsed.counts) {
    out.fill(value, index, index + count);
    index += count;
    value = value ? 0 : 1;
  }
  if (index !== size) {
    throw new Error("Invalid RLE payload");
  }
  return {
    width: parsed.w,
    height: parsed.h,
    data: out
  };
}
