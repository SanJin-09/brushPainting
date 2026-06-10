import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getImageVersions, regenerateImage, semanticEdit, getJob, getBatch } from "../lib/api";
import { useAppStore } from "../store";
import type { JobRead, VersionsResponse } from "../lib/types";
import StatusBadge from "../components/StatusBadge";

const JOB_POLL_INTERVAL_MS = 1000;
const JOB_POLL_TIMEOUT_MS = 180000;

export default function ImageDetailPage() {
  const { batchId, imageId } = useParams<{ batchId: string; imageId: string }>();
  const { batch, selectedImage, setSelectedImage, setBatch } = useAppStore();

  const [versions, setVersions] = useState<VersionsResponse | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentJob, setCurrentJob] = useState<JobRead | null>(null);
  const [editPrompt, setEditPrompt] = useState("");
  const [editVersionId, setEditVersionId] = useState<string | null>(null);

  // 确保 batch 已加载（应对直接访问 URL 的情况）
  useEffect(() => {
    if (!batchId) return;
    if (batch?.id === batchId) return;
    getBatch(batchId)
      .then((data) => setBatch(data))
      .catch((err: unknown) =>
        setError(err instanceof Error ? err.message : "加载批次失败")
      );
  }, [batchId, batch?.id, setBatch]);

  const image =
    selectedImage?.id === imageId
      ? selectedImage
      : batch?.images.find((img) => img.id === imageId) ?? null;

  const loadVersions = async () => {
    if (!imageId) return;
    try {
      const data = await getImageVersions(imageId);
      setVersions(data);
      if (!editVersionId && data.active_version_id) {
        setEditVersionId(data.active_version_id);
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "加载版本失败");
    }
  };

  useEffect(() => {
    if (image) {
      setSelectedImage(image);
    }
    loadVersions();
  }, [imageId]);

  const pollJob = async (jobId: string): Promise<JobRead> => {
    const maxAttempts = Math.ceil(JOB_POLL_TIMEOUT_MS / JOB_POLL_INTERVAL_MS);
    for (let i = 0; i < maxAttempts; i++) {
      const job = await getJob(jobId);
      setCurrentJob(job);
      if (job.status === "succeeded" || job.status === "failed") {
        return job;
      }
      await new Promise((resolve) => setTimeout(resolve, JOB_POLL_INTERVAL_MS));
    }
    throw new Error("任务超时");
  };

  const handleRegenerate = async () => {
    if (!imageId) return;
    setBusy(true);
    setError(null);
    try {
      const job = await regenerateImage(imageId);
      setCurrentJob(job);
      const result = await pollJob(job.id);
      if (result.status === "succeeded") {
        await loadVersions();
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "重新生成失败");
    } finally {
      setBusy(false);
    }
  };

  const handleSemanticEdit = async () => {
    if (!imageId || !editVersionId || !editPrompt.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const job = await semanticEdit(imageId, {
        version_id: editVersionId,
        user_prompt: editPrompt.trim(),
      });
      setCurrentJob(job);
      const result = await pollJob(job.id);
      if (result.status === "succeeded") {
        await loadVersions();
        setEditPrompt("");
      }
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "语义编辑失败");
    } finally {
      setBusy(false);
    }
  };

  if (!image) {
    return <div className="page">加载中...</div>;
  }

  const activeVersion = versions?.versions.find((v) => v.id === versions.active_version_id);

  return (
    <div className="page image-detail-page">
      <div className="topbar">
        <Link to={`/batches/${batchId}`}>返回批次</Link>
      </div>

      <h1>图片详情</h1>

      <section className="panel image-info">
        <div>文件名: {image.filename}</div>
        <div>尺寸: {image.width} × {image.height}</div>
        <div>状态: <StatusBadge status={image.status} /></div>
      </section>

      <section className="panel">
        <h2>当前版本</h2>
        {activeVersion ? (
          <div className="active-version">
            <img src={activeVersion.output_url} alt="current version" />
            <div>类型: {activeVersion.kind}</div>
            {activeVersion.user_prompt && <div>指令: {activeVersion.user_prompt}</div>}
          </div>
        ) : (
          <div className="empty">暂无生成结果</div>
        )}
      </section>

      <section className="panel">
        <h2>操作</h2>
        <div className="actions">
          <button onClick={handleRegenerate} disabled={busy}>
            {busy ? "生成中..." : "重新生成"}
          </button>
        </div>

        <div className="semantic-edit">
          <h3>语义编辑</h3>
          <select
            value={editVersionId ?? ""}
            onChange={(e) => setEditVersionId(e.target.value)}
            disabled={busy}
          >
            <option value="">选择基础版本</option>
            {versions?.versions.map((v) => (
              <option key={v.id} value={v.id}>
                {v.id.slice(0, 8)} - {v.kind}
              </option>
            ))}
          </select>
          <input
            type="text"
            placeholder="输入编辑指令，例如：把花画得更红"
            value={editPrompt}
            onChange={(e) => setEditPrompt(e.target.value)}
            disabled={busy}
          />
          <button
            onClick={handleSemanticEdit}
            disabled={busy || !editVersionId || !editPrompt.trim()}
          >
            {busy ? "编辑中..." : "执行语义编辑"}
          </button>
        </div>
      </section>

      {currentJob && (
        <section className="panel">
          <h2>当前任务</h2>
          <div className="job-status">
            <div>ID: {currentJob.id.slice(0, 8)}</div>
            <div>类型: {currentJob.type}</div>
            <div>状态: <StatusBadge status={currentJob.status} /></div>
            <div>进度: {currentJob.progress}%</div>
            {currentJob.progress_message && <div>{currentJob.progress_message}</div>}
            {currentJob.error && <div className="error">{currentJob.error}</div>}
          </div>
        </section>
      )}

      {error ? <div className="error">{error}</div> : null}

      <section className="panel">
        <h2>版本历史</h2>
        {versions?.versions.length === 0 ? (
          <div className="empty">暂无版本</div>
        ) : (
          <div className="version-grid">
            {versions?.versions.map((v) => (
              <div
                key={v.id}
                className={`version-card ${v.id === versions.active_version_id ? "active" : ""}`}
              >
                <img src={v.output_url} alt={v.kind} />
                <div className="version-info">
                  <div>ID: {v.id.slice(0, 8)}</div>
                  <div>类型: {v.kind}</div>
                  <StatusBadge status={v.id === versions.active_version_id ? "succeeded" : "uploaded"} />
                  {v.user_prompt && <div className="prompt">{v.user_prompt}</div>}
                  <div className="time">{new Date(v.created_at).toLocaleString()}</div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}
