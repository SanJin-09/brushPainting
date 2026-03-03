import React, { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { exportSession, getSession } from "../lib/api";
import type { SessionDetail } from "../lib/types";

export default function ExportPage() {
  const { id } = useParams();
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [manifestUrl, setManifestUrl] = useState<string | null>(null);

  useEffect(() => {
    if (!id) {
      return;
    }
    getSession(id)
      .then(setSession)
      .catch((err: unknown) => setError(err instanceof Error ? err.message : "加载失败"));
  }, [id]);

  const latest = session?.compose_results.length
    ? [...session.compose_results].sort((a, b) => (a.created_at > b.created_at ? -1 : 1))[0]
    : null;

  return (
    <div className="page">
      <div className="topbar">
        <Link to={id ? `/sessions/${id}` : "/"}>返回工作台</Link>
      </div>

      <section className="panel">
        <h2>导出中心</h2>
        {session ? <div>会话：{session.id}</div> : <div>加载中...</div>}

        {latest ? (
          <div className="compose-list">
            <figure>
              <img src={latest.image_url} alt="final" />
              <figcaption>最新合成结果</figcaption>
            </figure>
          </div>
        ) : (
          <div>暂无可导出结果</div>
        )}

        <div className="group" style={{ marginTop: 12 }}>
          <button
            disabled={busy || !id || !latest}
            onClick={async () => {
              if (!id) {
                return;
              }
              setBusy(true);
              setError(null);
              try {
                const res = await exportSession(id);
                setManifestUrl(res.manifest_url);
              } catch (err: unknown) {
                setError(err instanceof Error ? err.message : "导出失败");
              } finally {
                setBusy(false);
              }
            }}
          >
            {busy ? "导出中..." : "生成导出文件"}
          </button>

          {latest ? (
            <a href={latest.image_url} target="_blank" rel="noreferrer">
              打开最终图片
            </a>
          ) : null}
          {manifestUrl ? (
            <a href={manifestUrl} target="_blank" rel="noreferrer">
              打开 manifest
            </a>
          ) : null}
        </div>
      </section>

      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}
