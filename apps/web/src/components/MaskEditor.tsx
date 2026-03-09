import React, {
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState
} from "react";
import { decodeMaskRle, encodeMaskRle } from "../lib/maskRle";

export type MaskEditorHandle = {
  exportMaskRle: () => string | null;
  clear: () => void;
  replaceMask: (maskRle: string | null) => void;
};

type Props = {
  imageUrl: string;
  disabled?: boolean;
  brushSize?: number;
};

const OVERLAY_FILL = "rgba(182, 18, 18, 0.38)";

function hasSelectedPixels(mask: Uint8Array) {
  for (let i = 0; i < mask.length; i += 1) {
    if (mask[i]) {
      return true;
    }
  }
  return false;
}

function drawMaskIntoCanvas(canvas: HTMLCanvasElement, mask: Uint8Array, width: number, height: number) {
  const ctx = canvas.getContext("2d");
  if (!ctx) {
    return;
  }

  canvas.width = width;
  canvas.height = height;
  const imageData = ctx.createImageData(width, height);
  for (let i = 0; i < mask.length; i += 1) {
    if (!mask[i]) {
      continue;
    }
    const base = i * 4;
    imageData.data[base] = 182;
    imageData.data[base + 1] = 18;
    imageData.data[base + 2] = 18;
    imageData.data[base + 3] = 108;
  }
  ctx.clearRect(0, 0, width, height);
  ctx.putImageData(imageData, 0, 0);
}

const MaskEditor = forwardRef<MaskEditorHandle, Props>(function MaskEditor({ imageUrl, disabled = false, brushSize = 32 }, ref) {
  const imageRef = useRef<HTMLImageElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const maskRef = useRef<Uint8Array | null>(null);
  const dimsRef = useRef<{ width: number; height: number } | null>(null);
  const drawingRef = useRef(false);
  const lastPointRef = useRef<{ x: number; y: number } | null>(null);
  const [loaded, setLoaded] = useState(false);

  const resetMask = (width: number, height: number) => {
    const blank = new Uint8Array(width * height);
    maskRef.current = blank;
    const canvas = canvasRef.current;
    if (canvas) {
      drawMaskIntoCanvas(canvas, blank, width, height);
    }
  };

  const replaceMask = (maskRle: string | null) => {
    const dims = dimsRef.current;
    const canvas = canvasRef.current;
    if (!dims || !canvas) {
      return;
    }

    if (!maskRle) {
      resetMask(dims.width, dims.height);
      return;
    }

    const decoded = decodeMaskRle(maskRle);
    if (decoded.width !== dims.width || decoded.height !== dims.height) {
      throw new Error("Mask dimensions do not match current image");
    }
    maskRef.current = decoded.data;
    drawMaskIntoCanvas(canvas, decoded.data, dims.width, dims.height);
  };

  useImperativeHandle(ref, () => ({
    exportMaskRle() {
      const dims = dimsRef.current;
      const mask = maskRef.current;
      if (!dims || !mask || !hasSelectedPixels(mask)) {
        return null;
      }
      return encodeMaskRle(mask, dims.width, dims.height);
    },
    clear() {
      const dims = dimsRef.current;
      if (!dims) {
        return;
      }
      resetMask(dims.width, dims.height);
    },
    replaceMask(maskRle: string | null) {
      replaceMask(maskRle);
    }
  }), []);

  useEffect(() => {
    setLoaded(false);
    dimsRef.current = null;
    maskRef.current = null;
    const img = new window.Image();
    img.onload = () => {
      dimsRef.current = { width: img.naturalWidth, height: img.naturalHeight };
      resetMask(img.naturalWidth, img.naturalHeight);
      setLoaded(true);
    };
    img.src = imageUrl;
  }, [imageUrl]);

  const drawCircle = (cx: number, cy: number) => {
    const dims = dimsRef.current;
    const canvas = canvasRef.current;
    const mask = maskRef.current;
    if (!dims || !canvas || !mask) {
      return;
    }
    const ctx = canvas.getContext("2d");
    if (!ctx) {
      return;
    }

    const radius = Math.max(2, Math.round(brushSize / 2));
    const x0 = Math.max(0, Math.floor(cx - radius));
    const y0 = Math.max(0, Math.floor(cy - radius));
    const x1 = Math.min(dims.width - 1, Math.ceil(cx + radius));
    const y1 = Math.min(dims.height - 1, Math.ceil(cy + radius));

    for (let y = y0; y <= y1; y += 1) {
      for (let x = x0; x <= x1; x += 1) {
        const dx = x - cx;
        const dy = y - cy;
        if (dx * dx + dy * dy <= radius * radius) {
          mask[y * dims.width + x] = 1;
        }
      }
    }

    ctx.fillStyle = OVERLAY_FILL;
    ctx.beginPath();
    ctx.arc(cx, cy, radius, 0, Math.PI * 2);
    ctx.fill();
  };

  const pointerToCanvas = (event: React.PointerEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    const dims = dimsRef.current;
    if (!canvas || !dims) {
      return null;
    }
    const rect = canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) {
      return null;
    }
    const x = ((event.clientX - rect.left) / rect.width) * dims.width;
    const y = ((event.clientY - rect.top) / rect.height) * dims.height;
    return {
      x: Math.max(0, Math.min(dims.width - 1, x)),
      y: Math.max(0, Math.min(dims.height - 1, y))
    };
  };

  const drawStroke = (from: { x: number; y: number }, to: { x: number; y: number }) => {
    const distance = Math.hypot(to.x - from.x, to.y - from.y);
    const steps = Math.max(1, Math.ceil(distance / Math.max(brushSize / 3, 1)));
    for (let i = 0; i <= steps; i += 1) {
      const t = i / steps;
      drawCircle(from.x + (to.x - from.x) * t, from.y + (to.y - from.y) * t);
    }
  };

  return (
    <div className="mask-editor">
      <div className="mask-editor-stage">
        <img
          ref={imageRef}
          src={imageUrl}
          alt="editable"
          className={`mask-editor-image${loaded ? " is-ready" : ""}`}
        />
        <canvas
          ref={canvasRef}
          className={`mask-editor-canvas${disabled ? " is-disabled" : ""}`}
          onPointerDown={(event) => {
            if (disabled || !loaded) {
              return;
            }
            const point = pointerToCanvas(event);
            if (!point) {
              return;
            }
            drawingRef.current = true;
            lastPointRef.current = point;
            drawCircle(point.x, point.y);
            event.currentTarget.setPointerCapture(event.pointerId);
          }}
          onPointerMove={(event) => {
            if (!drawingRef.current || disabled || !loaded) {
              return;
            }
            const point = pointerToCanvas(event);
            if (!point) {
              return;
            }
            drawStroke(lastPointRef.current ?? point, point);
            lastPointRef.current = point;
          }}
          onPointerUp={(event) => {
            drawingRef.current = false;
            lastPointRef.current = null;
            if (event.currentTarget.hasPointerCapture(event.pointerId)) {
              event.currentTarget.releasePointerCapture(event.pointerId);
            }
          }}
          onPointerLeave={() => {
            drawingRef.current = false;
            lastPointRef.current = null;
          }}
        />
      </div>
      <div className="mask-editor-hint">
        在画布上涂抹需要修改的区域，点击“吸附选区”生成精确 mask。
      </div>
    </div>
  );
});

export default MaskEditor;
