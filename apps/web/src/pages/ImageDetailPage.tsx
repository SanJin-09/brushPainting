import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getImageVersions, regenerateImage, semanticEdit, getJob, getBatch } from "../lib/api";
import { useAppStore } from "../store";
import type { JobRead, VersionsResponse } from "../lib/types";
import StatusBadge from "../components/StatusBadge";

const JOB_POLL_INTERVAL_MS = 1000;
const JOB_POLL_TIMEOUT_MS = 180000;

export default function ImageDetailPage() {
  const { batchId, imageId } = useParams<{ batchId: string; imageId: string }>();
  const { batch, selectedImage, setBatch } = useAppStore();

  const [versions, setVersions] = useState<VersionsResponse | null>(null);
  const [versionsLoading, setVersionsLoading] = useState(true);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [currentJob, setCurrentJob] = useState<JobRead | null>(null);
  const [editPrompt, setEditPrompt] = useState("");
  const [editVersionId, setEditVersionId] = useState<string | null>(null);
  const [historyVersionId, setHistoryVersionId] = useState<string>("");

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

  const loadVersions = useCallback(async () => {
    if (!imageId) {
      setVersionsLoading(false);
      return;
    }
    setVersionsLoading(true);
    setVersionsError(null);
    try {
      const data = await getImageVersions(imageId);
      setVersions(data);
      // 自动选中：优先 active_version_id，否则选第一个版本
      const defaultId = data.active_version_id || (data.versions.length > 0 ? data.versions[0].id : "");
      setEditVersionId((prev) => prev ?? (defaultId || null));
      setHistoryVersionId((prev) => prev || defaultId);
    } catch (err: unknown) {
      setVersionsError(err instanceof Error ? err.message : "加载版本失败");
    } finally {
      setVersionsLoading(false);
    }
  }, [imageId]);

  useEffect(() => {
    loadVersions();
  }, [loadVersions]);

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

  // 无效路由参数
  if (!batchId || !imageId) {
    return <div className="page">无效的链接</div>;
  }

  const activeVersion = versions?.versions.find((v) => v.id === versions.active_version_id);
  const selectedHistoryVersion = historyVersionId
    ? versions?.versions.find((v) => v.id === historyVersionId) ?? null
    : null;

  return (
    <div className="page image-detail-page">
      <div className="topbar">
        <Link to={`/batches/${batchId}`}>返回批次</Link>
      </div>

      <h1>图片详情</h1>

      {!image ? (
        <section className="panel">
          <div className="empty">图片加载中...</div>
        </section>
      ) : (
        <>
          <section className="panel image-info">
            <div className="image-info-meta">
              <span>文件名: {image.filename}</span>
              <span>尺寸: {image.width} × {image.height}</span>
              <span>状态: <StatusBadge status={image.status} /></span>
            </div>
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

          <section className="panel">
            <h2>当前版本</h2>
            {activeVersion ? (
              <div className="compare-view">
                <div className="compare-row">
                  <div className="compare-col">
                    <div className="compare-label">原始图片</div>
                    <img src={image.original_url} alt="原始图片" className="compare-img" />
                  </div>
                  <div className="compare-col">
                    <div className="compare-label">生成结果</div>
                    <img src={activeVersion.output_url} alt="生成结果" className="compare-img" />
                  </div>
                </div>
                <div className="compare-meta">
                  <span>类型: {activeVersion.kind}</span>
                  {activeVersion.user_prompt && <span>指令: {activeVersion.user_prompt}</span>}
                </div>
              </div>
            ) : (
              <div className="compare-view">
                <div className="compare-row">
                  <div className="compare-col">
                    <div className="compare-label">原始图片</div>
                    <img src={image.original_url} alt="原始图片" className="compare-img" />
                  </div>
                  <div className="compare-col">
                    <div className="compare-label">生成结果</div>
                    <div className="compare-placeholder">暂无生成结果</div>
                  </div>
                </div>
              </div>
            )}
          </section>

          {error && (
            <div className="dialog-overlay" onClick={() => setError(null)}>
              <div className="dialog" onClick={(e) => e.stopPropagation()}>
                <div className="dialog-header">
                  <span className="dialog-icon">!</span>
                  <h3>提示</h3>
                </div>
                <p className="dialog-body">{error}</p>
                <button className="dialog-close" onClick={() => setError(null)}>
                  确定
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* 版本历史 —— 不依赖 image 对象，独立加载 */}
      <section className="panel">
        <h2>版本历史</h2>
        {versionsError ? (
          <div className="empty error">版本加载失败: {versionsError}</div>
        ) : versionsLoading ? (
          <div className="empty">版本加载中...</div>
        ) : (
          <div className="version-history">
            <select
              className="version-history-select"
              value={historyVersionId}
              onChange={(e) => setHistoryVersionId(e.target.value)}
            >
              <option value="" disabled>
                {versions && versions.versions.length > 0
                  ? "选择历史版本"
                  : "暂无版本 — 请先执行生成"}
              </option>
              {versions?.versions.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.id.slice(0, 8)} - {v.kind}
                  {v.user_prompt ? ` - ${v.user_prompt}` : ""}
                  {v.id === versions.active_version_id ? " (当前)" : ""}
                </option>
              ))}
            </select>
            {selectedHistoryVersion && image ? (
              <div className="compare-view">
                <div className="compare-row">
                  <div className="compare-col">
                    <div className="compare-label">原始图片</div>
                    <img src={image.original_url} alt="原图" className="compare-img" />
                  </div>
                  <div className="compare-col">
                    <div className="compare-label">生成结果</div>
                    <img src={selectedHistoryVersion.output_url} alt={selectedHistoryVersion.kind} className="compare-img" />
                  </div>
                </div>
                <div className="compare-meta">
                  <span>ID: {selectedHistoryVersion.id.slice(0, 8)}</span>
                  <span>类型: {selectedHistoryVersion.kind}</span>
                  {versions && selectedHistoryVersion.id === versions.active_version_id && (
                    <StatusBadge status="succeeded" />
                  )}
                  <span>{new Date(selectedHistoryVersion.created_at).toLocaleString()}</span>
                  {selectedHistoryVersion.user_prompt && <span>指令: {selectedHistoryVersion.user_prompt}</span>}
                </div>
              </div>
            ) : selectedHistoryVersion ? (
              <div className="compare-placeholder">图片加载中...</div>
            ) : (
              <div className="compare-placeholder">请选择历史版本查看</div>
            )}
          </div>
        )}
      </section>
    </div>
  );
}
