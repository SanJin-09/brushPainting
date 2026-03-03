import React, { useMemo } from "react";
import type { Crop } from "../lib/types";
import StatusBadge from "./StatusBadge";

type Props = {
  crop: Crop;
  onRegenerate: (cropId: string) => void;
  onApprove: (cropId: string) => void;
  loading: boolean;
};

export default function CropCard({ crop, onRegenerate, onApprove, loading }: Props) {
  const latest = useMemo(() => {
    if (!crop.versions.length) {
      return null;
    }
    return [...crop.versions].sort((a, b) => b.version_no - a.version_no)[0];
  }, [crop.versions]);

  return (
    <div className="crop-card">
      <div className="crop-card-header">
        <strong>Crop {crop.id.slice(0, 8)}</strong>
        <StatusBadge status={crop.status} />
      </div>

      <div className="crop-preview">
        {latest ? <img src={latest.image_url} alt={`crop-${crop.id}`} /> : <div className="empty">待生成</div>}
      </div>

      <div className="meta">
        <div>bbox: ({crop.bbox_x}, {crop.bbox_y}, {crop.bbox_w}, {crop.bbox_h})</div>
        <div>versions: {crop.versions.length}</div>
      </div>

      <div className="actions">
        <button disabled={loading} onClick={() => onRegenerate(crop.id)}>
          重生成
        </button>
        <button disabled={loading || !latest} onClick={() => onApprove(crop.id)}>
          通过
        </button>
      </div>
    </div>
  );
}
