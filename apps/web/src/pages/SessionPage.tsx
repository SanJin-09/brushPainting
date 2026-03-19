import React, { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import MaskEditor, { type MaskEditorHandle } from "../components/MaskEditor";
import StatusBadge from "../components/StatusBadge";
import {
  adoptVersion,
  createEdit,
  exportSession,
  getJob,
  getSession,
  lockStyle,
  maskAssist,
  renderSession
} from "../lib/api";
import type { ImageVersion, Job, MaskAssistResult } from "../lib/types";
import { useAppStore } from "../store";

const JOB_POLL_INTERVAL_MS = 1000;
const JOB_POLL_TIMEOUT_MS = 180000;

function clampProgressPercent(value: number) {
  return Math.max(0, Math.min(100, Math.round(value)));
}

function getJobTypeLabel(jobType: string) {
  if (jobType === "render_full") {
    return "整图生成";
  }
  if (jobType === "edit_mask") {
    return "局部候选";
  }
  return jobType;
}

function getJobProgressPercent(job: Job) {
  if (typeof job.progress_percent === "number") {
    return clampProgressPercent(job.progress_percent);
  }
  if (job.status === "QUEUED") {
    return 0;
  }
  if (job.status === "RUNNING") {
    return 60;
  }
  if (job.status === "SUCCEEDED") {
    return 100;
  }
  if (job.status === "FAILED") {
    return 100;
  }
  return 0;
}

function getJobProgressMessage(job: Job) {
  if (job.error_message) {
    return job.error_message;
  }
  if (job.progress_message) {
    return job.progress_message;
  }
  if (job.status === "QUEUED") {
    return "任务已提交，等待开始";
  }
  if (job.status === "RUNNING") {
    return "任务执行中";
  }
  if (job.status === "SUCCEEDED") {
    return "任务完成";
  }
  if (job.status === "FAILED") {
    return "任务失败";
  }
  return "等待状态更新";
}

function sortVersions(versions: ImageVersion[]) {
  return [...versions].sort((a, b) => (a.created_at > b.created_at ? -1 : 1));
}

export default function SessionPage() {
  const { id } = useParams();
  const { session, setSession, busy, setBusy, lastJob, setLastJob, error, setError } = useAppStore();
  const editorRef = useRef<MaskEditorHandle | null>(null);

  const [seed, setSeed] = useState<number | undefined>(undefined);
  const [styleId, setStyleId] = useState("gongbi_default");
  const [promptOverride, setPromptOverride] = useState("");
  const [assistResult, setAssistResult] = useState<MaskAssistResult | null>(null);
  const [selectedVersionId, setSelectedVersionId] = useState<string | null>(null);
  const [exportInfo, setExportInfo] = useState<{ final_image_url: string; manifest_url: string } | null>(null);

  const orderedVersions = useMemo(() => sortVersions(session?.versions ?? []), [session?.versions]);
  const currentVersion = useMemo(
    () => orderedVersions.find((version) => version.is_current) ?? null,
    [orderedVersions]
  );
  const selectedVersion = useMemo(
    () => orderedVersions.find((version) => version.id === selectedVersionId) ?? currentVersion,
    [currentVersion, orderedVersions, selectedVersionId]
  );

  useEffect(() => {
    if (session?.style_id) {
      setStyleId(session.style_id);
    }
  }, [session?.style_id]);

  useEffect(() => {
    if (currentVersion && !selectedVersionId) {
      setSelectedVersionId(currentVersion.id);
    }
    if (selectedVersionId && !orderedVersions.some((version) => version.id === selectedVersionId)) {
      setSelectedVersionId(currentVersion?.id ?? null);
    }
  }, [currentVersion, orderedVersions, selectedVersionId]);

  const refresh = async () => {
    if (!id) {
      return;
    }
    try {
      const data = await getSession(id);
      setSession(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "加载会话失败");
    }
  };

  const withBusy = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await refresh();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "操作失败");
    } finally {
      setBusy(false);
    }
  };

  const pollJob = async (jobId: string) => {
    const maxAttempts = Math.ceil(JOB_POLL_TIMEOUT_MS / JOB_POLL_INTERVAL_MS);
    for (let i = 0; i < maxAttempts; i += 1) {
      const job = await getJob(jobId);
      setLastJob(job);
      if (job.status === "SUCCEEDED") {
        return;
      }
      if (job.status === "FAILED") {
        throw new Error(job.error_message || "任务失败");
      }
      await new Promise((resolve) => setTimeout(resolve, JOB_POLL_INTERVAL_MS));
    }
    throw new Error(`任务超时（${JOB_POLL_TIMEOUT_MS / 1000} 秒内未完成）`);
  };

  useEffect(() => {
    refresh();
  }, [id]);

  const editableImageUrl = currentVersion?.image_url ?? session?.source_image_url ?? "";
  const selectedIsCurrent = !selectedVersion || selectedVersion.id === currentVersion?.id;
  const visibleJob = session && lastJob && lastJob.session_id === session.id ? lastJob : null;
  const jobProgressPercent = visibleJob ? getJobProgressPercent(visibleJob) : 0;

  return (
    <div className="page workspace-page">
      <div className="topbar">
        <Link to="/">返回上传</Link>
        {session ? <Link to={`/sessions/${session.id}/export`}>前往导出页</Link> : null}
      </div>

      {!session ? (
        <div className="panel">加载中...</div>
      ) : (
        <>
          <section className="panel">
            <h2>会话 {session.id}</h2>
            <div className="row">
              <span>状态：</span>
              <StatusBadge status={session.status} />
            </div>
            <div className="row">
              <span>风格：</span>
              <strong>{session.style_id ?? "未锁定"}</strong>
            </div>
            <div className="row">
              <span>当前版本：</span>
              <strong>{session.current_version_id ? session.current_version_id.slice(0, 8) : "暂无"}</strong>
            </div>
          </section>

          <section className="panel control-panel">
            <h3>流程控制</h3>
            <div className="group">
              <label>风格ID：</label>
              <input value={styleId} onChange={(e) => setStyleId(e.target.value)} />
              <button
                disabled={busy}
                onClick={() =>
                  withBusy(async () => {
                    await lockStyle(session.id, styleId);
                  })
                }
              >
                锁定风格
              </button>
            </div>

            <div className="group">
              <label>Seed：</label>
              <input
                type="number"
                value={seed ?? ""}
                onChange={(e) => setSeed(e.target.value ? Number(e.target.value) : undefined)}
                placeholder="可选"
              />
              <button
                disabled={busy || !session.style_id}
                onClick={() =>
                  withBusy(async () => {
                    const job = await renderSession(session.id, seed);
                    setLastJob(job);
                    await pollJob(job.id);
                  })
                }
              >
                {currentVersion ? "重新整图生成" : "生成整图"}
              </button>
            </div>

            <div className="group">
              <button
                disabled={busy || !currentVersion}
                onClick={() => {
                  editorRef.current?.clear();
                  setAssistResult(null);
                }}
              >
                清空选区
              </button>

              <button
                disabled={busy || !currentVersion}
                onClick={async () => {
                  if (!currentVersion || !id) {
                    return;
                  }
                  const maskRle = editorRef.current?.exportMaskRle();
                  if (!maskRle) {
                    setError("请先画出局部选区");
                    return;
                  }
                  await withBusy(async () => {
                    const result = await maskAssist(id, maskRle);
                    setAssistResult(result);
                    editorRef.current?.replaceMask(result.mask_rle);
                  });
                }}
              >
                吸附选区
              </button>
            </div>

            <div className="group">
              <label>局部指令：</label>
              <input
                value={promptOverride}
                onChange={(e) => setPromptOverride(e.target.value)}
                placeholder="可选，例如：花瓣颜色更淡"
              />
              <button
                disabled={busy || !currentVersion || !assistResult}
                onClick={() =>
                  withBusy(async () => {
                    const job = await createEdit(session.id, {
                      mask_rle: assistResult.mask_rle,
                      bbox_x: assistResult.bbox_x,
                      bbox_y: assistResult.bbox_y,
                      bbox_w: assistResult.bbox_w,
                      bbox_h: assistResult.bbox_h,
                      seed,
                      prompt_override: promptOverride || undefined
                    });
                    setLastJob(job);
                    await pollJob(job.id);
                    setAssistResult(null);
                    editorRef.current?.clear();
                    setPromptOverride("");
                  })
                }
              >
                生成局部候选
              </button>

              <button
                disabled={busy || !currentVersion}
                onClick={() =>
                  withBusy(async () => {
                    const result = await exportSession(session.id);
                    setExportInfo(result);
                  })
                }
              >
                导出当前版本
              </button>
            </div>

            {assistResult ? (
              <div className="selection-meta">
                当前精修选区 bbox: ({assistResult.bbox_x}, {assistResult.bbox_y}, {assistResult.bbox_w}, {assistResult.bbox_h})
              </div>
            ) : null}

            {visibleJob ? (
              <div className="job-box">
                <div className="job-box-head">
                  <strong>{getJobTypeLabel(visibleJob.type)}</strong>
                  <span>{jobProgressPercent}%</span>
                </div>
                <div className="job-box-status">
                  最近任务：{getJobTypeLabel(visibleJob.type)} / <StatusBadge status={visibleJob.status} />
                </div>
                <div className="job-progress" aria-label={`${getJobTypeLabel(visibleJob.type)}进度 ${jobProgressPercent}%`}>
                  <div className="job-progress-track">
                    <div
                      className={`job-progress-fill${visibleJob.status === "FAILED" ? " is-failed" : ""}`}
                      style={{ width: `${jobProgressPercent}%` }}
                    />
                  </div>
                  <div className="job-progress-meta">{getJobProgressMessage(visibleJob)}</div>
                </div>
                {visibleJob.error_message ? <div className="error">{visibleJob.error_message}</div> : null}
              </div>
            ) : null}

            {exportInfo ? (
              <div className="export-box">
                <a href={exportInfo.final_image_url} target="_blank" rel="noreferrer">
                  打开当前导出图片
                </a>
                <a href={exportInfo.manifest_url} target="_blank" rel="noreferrer">
                  打开 manifest
                </a>
              </div>
            ) : null}
          </section>

          <section className="workspace-grid">
            <div className="panel">
              <h3>局部编辑画布</h3>
              {editableImageUrl ? (
                <MaskEditor
                  key={editableImageUrl}
                  ref={editorRef}
                  imageUrl={editableImageUrl}
                  disabled={!currentVersion || busy}
                />
              ) : (
                <div className="empty">先生成整图，再进行局部编辑。</div>
              )}
            </div>

            <div className="panel">
              <h3>版本预览</h3>
              <div className="preview-stack">
                {currentVersion ? (
                  <figure>
                    <img src={currentVersion.image_url} alt="current-version" className="preview-image" />
                    <figcaption>当前版本</figcaption>
                  </figure>
                ) : (
                  <figure>
                    <img src={session.source_image_url} alt="source-reference" className="preview-image" />
                    <figcaption>原图参考</figcaption>
                  </figure>
                )}

                {!selectedIsCurrent && selectedVersion ? (
                  <figure>
                    <img src={selectedVersion.image_url} alt="selected-candidate" className="preview-image" />
                    <figcaption>候选预览</figcaption>
                  </figure>
                ) : null}

                <figure>
                  <img src={session.source_image_url} alt="source" className="preview-image" />
                  <figcaption>原图</figcaption>
                </figure>
              </div>
            </div>
          </section>

          <section className="panel">
            <h3>版本列表</h3>
            {orderedVersions.length === 0 ? (
              <div className="empty">暂无版本。先锁定风格并生成整图。</div>
            ) : (
              <div className="version-grid">
                {orderedVersions.map((version) => (
                  <div
                    key={version.id}
                    className={`version-card${version.is_current ? " is-current" : ""}${selectedVersionId === version.id ? " is-selected" : ""}`}
                  >
                    <img src={version.image_url} alt={version.id} />
                    <div className="version-card-header">
                      <strong>{version.kind === "FULL_RENDER" ? "整图" : "局部"}</strong>
                      {version.is_current ? <StatusBadge status="CURRENT" /> : null}
                    </div>
                    <div className="meta">
                      <div>id: {version.id.slice(0, 8)}</div>
                      <div>seed: {version.seed}</div>
                      <div>时间: {new Date(version.created_at).toLocaleString()}</div>
                      {version.prompt_override ? <div>指令: {version.prompt_override}</div> : null}
                    </div>
                    <div className="actions">
                      <button disabled={busy} onClick={() => setSelectedVersionId(version.id)}>
                        预览
                      </button>
                      <button
                        disabled={busy || version.is_current}
                        onClick={() =>
                          withBusy(async () => {
                            const updated = await adoptVersion(session.id, version.id);
                            setSession(updated);
                            setSelectedVersionId(version.id);
                          })
                        }
                      >
                        设为当前
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>
        </>
      )}

      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}
