import React, { useEffect, useMemo, useState } from "react";
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

  const currentVersion = useMemo(
    () => session?.versions.find((version) => version.is_current) ?? null,
    [session?.versions]
  );

  return (
    <div className="page">
      <div className="topbar">
        <Link to={id ? `/sessions/${id}` : "/"}>返回工作台</Link>
      </div>

      <section className="panel">
        <h2>导出中心</h2>
        {session ? <div>会话：{session.id}</div> : <div>加载中...</div>}

        {currentVersion ? (
          <div className="compose-list">
            <figure>
              <img src={currentVersion.image_url} alt="current-version" />
              <figcaption>当前版本</figcaption>
            </figure>
          </div>
        ) : (
          <div>暂无可导出结果</div>
        )}

        <div className="group" style={{ marginTop: 12 }}>
          <button
            disabled={busy || !id || !currentVersion}
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

          {currentVersion ? (
            <a href={currentVersion.image_url} target="_blank" rel="noreferrer">
              打开当前图片
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
