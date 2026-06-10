import { useEffect, useState } from "react";
import { Link, useParams, useNavigate } from "react-router-dom";
import { getBatch, generateBatch } from "../lib/api";
import { useAppStore } from "../store";
import type { BatchRead, JobRead } from "../lib/types";
import StatusBadge from "../components/StatusBadge";

export default function BatchDetailPage() {
  const { batchId } = useParams<{ batchId: string }>();
  const navigate = useNavigate();
  const { setBatch: setGlobalBatch } = useAppStore();

  const [batch, setBatch] = useState<BatchRead | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [jobs, setJobs] = useState<JobRead[]>([]);

  const loadBatch = async () => {
    if (!batchId) return;
    try {
      const data = await getBatch(batchId);
      setBatch(data);
      setGlobalBatch(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "加载批次失败");
    }
  };

  useEffect(() => {
    loadBatch();
  }, [batchId]);

  const handleGenerate = async () => {
    if (!batchId) return;
    setBusy(true);
    setError(null);
    try {
      const resp = await generateBatch(batchId);
      setJobs(resp.jobs);
      await loadBatch();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "生成失败");
    } finally {
      setBusy(false);
    }
  };

  const handleImageClick = (imageId: string) => {
    navigate(`/batches/${batchId}/images/${imageId}`);
  };

  if (!batch) {
    return <div className="page">加载中...</div>;
  }

  return (
    <div className="page batch-page">
      <div className="topbar">
        <Link to="/">返回首页</Link>
        <Link to={`/batches/${batch.id}/export`}>导出 ZIP</Link>
      </div>

      <h1>批次详情</h1>

      <section className="panel batch-info">
        <div>批次 ID: {batch.id}</div>
        <div>状态: <StatusBadge status={batch.status} /></div>
        <div>图片数量: {batch.images.length}</div>
        <div>创建时间: {new Date(batch.created_at).toLocaleString()}</div>
      </section>

      <section className="panel">
        <button onClick={handleGenerate} disabled={busy}>
          {busy ? "生成中..." : "批量生成"}
        </button>
      </section>

      {jobs.length > 0 && (
        <section className="panel">
          <h2>任务状态</h2>
          <div className="job-list">
            {jobs.map((job) => (
              <div key={job.id} className="job-item">
                <span>任务 {job.id.slice(0, 8)}</span>
                <StatusBadge status={job.status} />
                <span>{job.progress}%</span>
              </div>
            ))}
          </div>
        </section>
      )}

      {error ? <div className="error">{error}</div> : null}

      <section className="panel">
        <h2>图片列表</h2>
        {batch.images.length === 0 ? (
          <div className="empty">暂无图片</div>
        ) : (
          <div className="image-grid">
            {batch.images.map((image) => (
              <div
                key={image.id}
                className="image-card"
                onClick={() => handleImageClick(image.id)}
              >
                <img src={image.thumbnail_url} alt={image.filename} />
                <div className="image-info">
                  <div className="filename">{image.filename}</div>
                  <StatusBadge status={image.status} />
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
