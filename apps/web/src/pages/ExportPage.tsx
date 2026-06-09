import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getBatch, exportBatch } from "../lib/api";
import type { BatchRead } from "../lib/types";
import StatusBadge from "../components/StatusBadge";

export default function ExportPage() {
  const { batchId } = useParams<{ batchId: string }>();

  const [batch, setBatch] = useState<BatchRead | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [zipUrl, setZipUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!batchId) return;
    getBatch(batchId)
      .then((data) => {
        setBatch(data);
        setSelectedIds(new Set(data.images.map((img) => img.id)));
      })
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "加载批次失败"));
  }, [batchId]);

  const toggleImage = (imageId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(imageId)) {
        next.delete(imageId);
      } else {
        next.add(imageId);
      }
      return next;
    });
  };

  const selectAll = () => {
    if (!batch) return;
    setSelectedIds(new Set(batch.images.map((img) => img.id)));
  };

  const deselectAll = () => {
    setSelectedIds(new Set());
  };

  const handleExport = async () => {
    if (!batchId) return;
    setBusy(true);
    setError(null);
    setZipUrl(null);
    try {
      const allSelected = batch && selectedIds.size === batch.images.length;
      const body = allSelected ? {} : { image_ids: Array.from(selectedIds) };
      const resp = await exportBatch(batchId, body);
      setZipUrl(resp.zip_url);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "导出失败");
    } finally {
      setBusy(false);
    }
  };

  if (!batch) {
    return <div className="page">加载中...</div>;
  }

  const exportableImages = batch.images.filter(
    (img) => img.status === "succeeded" && img.active_version
  );

  return (
    <div className="page">
      <div className="topbar">
        <Link to={`/batches/${batchId}`}>返回批次</Link>
      </div>

      <section className="panel">
        <h2>导出</h2>
        <p>选择要导出的图片（仅显示已生成成功的图片）：</p>
        <div className="group">
          <button onClick={selectAll}>全选</button>
          <button onClick={deselectAll}>取消全选</button>
          <span>已选 {selectedIds.size} / {exportableImages.length}</span>
        </div>

        <div className="image-grid">
          {exportableImages.map((img) => (
            <label key={img.id} className="image-card">
              <input
                type="checkbox"
                checked={selectedIds.has(img.id)}
                onChange={() => toggleImage(img.id)}
              />
              <img src={img.thumbnail_url} alt={img.filename} />
              <div className="image-info">
                <div className="filename">{img.filename}</div>
                <StatusBadge status={img.status} />
              </div>
            </label>
          ))}
        </div>

        {exportableImages.length === 0 ? (
          <div className="empty">暂无可导出的图片，请先完成图片生成。</div>
        ) : null}
      </section>

      <section className="panel">
        <div className="group">
          <button
            onClick={handleExport}
            disabled={busy || selectedIds.size === 0}
          >
            {busy ? "导出中..." : `导出 ${selectedIds.size} 张图片`}
          </button>
        </div>
      </section>

      {error ? <div className="error">{error}</div> : null}

      {zipUrl ? (
        <section className="panel">
          <h2>导出完成</h2>
          <a href={zipUrl} target="_blank" rel="noreferrer">
            下载 ZIP 文件
          </a>
        </section>
      ) : null}
    </div>
  );
}
