import React, { useEffect, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import CropCard from "../components/CropCard";
import StatusBadge from "../components/StatusBadge";
import {
  approveCrop,
  composeSession,
  exportSession,
  generateCrops,
  getJob,
  getSession,
  lockStyle,
  regenerateCrop,
  resetGeneration,
  segmentSession
} from "../lib/api";
import { useAppStore } from "../store";

export default function SessionPage() {
  const { id } = useParams();
  const { session, setSession, busy, setBusy, lastJob, setLastJob, error, setError } = useAppStore();

  const [seed, setSeed] = useState<number | undefined>(undefined);
  const [styleId, setStyleId] = useState("gongbi_default");
  const [exportInfo, setExportInfo] = useState<{ final_image_url: string; manifest_url: string } | null>(null);

  const allApproved = useMemo(() => {
    return session?.crops.length ? session.crops.every((x) => x.status === "APPROVED") : false;
  }, [session]);

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
    for (let i = 0; i < 60; i += 1) {
      const job = await getJob(jobId);
      setLastJob(job);
      if (job.status === "SUCCEEDED") {
        return;
      }
      if (job.status === "FAILED") {
        throw new Error(job.error_message || "任务失败");
      }
      await new Promise((resolve) => setTimeout(resolve, 1000));
    }
    throw new Error("任务超时");
  };

  useEffect(() => {
    refresh();
  }, [id]);

  return (
    <div className="page">
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
            <img src={session.source_image_url} alt="source" className="source-preview" />
          </section>

          <section className="panel control-panel">
            <h3>流程控制</h3>
            <div className="group">
              <label>Seed：</label>
              <input
                type="number"
                value={seed ?? ""}
                onChange={(e) => setSeed(e.target.value ? Number(e.target.value) : undefined)}
                placeholder="可选"
              />
              <button
                disabled={busy}
                onClick={() =>
                  withBusy(async () => {
                    const job = await segmentSession(session.id, seed, 6);
                    setLastJob(job);
                    await pollJob(job.id);
                  })
                }
              >
                随机分割
              </button>
            </div>

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
              <button
                disabled={busy || !session.style_id || session.crops.length === 0}
                onClick={() =>
                  withBusy(async () => {
                    const job = await generateCrops(session.id);
                    setLastJob(job);
                    await pollJob(job.id);
                  })
                }
              >
                批量生成子图
              </button>

              <button
                disabled={busy || session.crops.length === 0}
                onClick={() =>
                  withBusy(async () => {
                    await resetGeneration(session.id);
                  })
                }
              >
                重置生成
              </button>

              <button
                disabled={busy || !allApproved}
                onClick={() =>
                  withBusy(async () => {
                    const job = await composeSession(session.id);
                    setLastJob(job);
                    await pollJob(job.id);
                  })
                }
              >
                全部通过后合成
              </button>

              <button
                disabled={busy || session.compose_results.length === 0}
                onClick={() =>
                  withBusy(async () => {
                    const result = await exportSession(session.id);
                    setExportInfo(result);
                  })
                }
              >
                导出
              </button>
            </div>

            {lastJob ? (
              <div className="job-box">
                最近任务：{lastJob.type} / <StatusBadge status={lastJob.status} />
                {lastJob.error_message ? <div className="error">{lastJob.error_message}</div> : null}
              </div>
            ) : null}
          </section>

          <section className="panel">
            <h3>子图审核</h3>
            <div className="crop-grid">
              {session.crops.map((crop) => (
                <CropCard
                  key={crop.id}
                  crop={crop}
                  loading={busy}
                  onRegenerate={(cropId) =>
                    withBusy(async () => {
                      const job = await regenerateCrop(cropId);
                      setLastJob(job);
                      await pollJob(job.id);
                    })
                  }
                  onApprove={(cropId) =>
                    withBusy(async () => {
                      const updated = await approveCrop(cropId);
                      setSession(updated);
                    })
                  }
                />
              ))}
            </div>
          </section>

          <section className="panel">
            <h3>合成结果</h3>
            {session.compose_results.length > 0 ? (
              <div className="compose-list">
                {session.compose_results.map((item) => (
                  <figure key={item.id}>
                    <img src={item.image_url} alt="compose" />
                    <figcaption>{item.created_at}</figcaption>
                  </figure>
                ))}
              </div>
            ) : (
              <div>暂无合成结果</div>
            )}
            {exportInfo ? (
              <div className="export-box">
                <a href={exportInfo.final_image_url} target="_blank" rel="noreferrer">
                  查看最终图
                </a>
                <a href={exportInfo.manifest_url} target="_blank" rel="noreferrer">
                  查看 manifest
                </a>
              </div>
            ) : null}
          </section>
        </>
      )}

      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}
