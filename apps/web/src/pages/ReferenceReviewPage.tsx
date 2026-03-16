import React, { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  applyReferenceReviewAction,
  getReferenceReview,
  getReferenceReviewImageUrl,
  undoReferenceReview
} from "../lib/api";
import type { ReferenceReviewState } from "../lib/types";

const DEFAULT_DIRECTORY = "official_zero_auth_all/met_open_access";

function isTypingTarget(target: EventTarget | null) {
  return (
    target instanceof HTMLElement &&
    (target.tagName === "INPUT" ||
      target.tagName === "TEXTAREA" ||
      target.tagName === "SELECT" ||
      target.isContentEditable)
  );
}

export default function ReferenceReviewPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const searchDirectory = searchParams.get("directory")?.trim() || DEFAULT_DIRECTORY;
  const [directoryInput, setDirectoryInput] = useState(searchDirectory);
  const [directory, setDirectory] = useState(searchDirectory);
  const [review, setReview] = useState<ReferenceReviewState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setDirectoryInput(searchDirectory);
    setDirectory(searchDirectory);
  }, [searchDirectory]);

  const loadReview = async (nextDirectory: string) => {
    const normalized = nextDirectory.trim();
    if (!normalized) {
      setError("请先填写待审核目录");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const data = await getReferenceReview(normalized);
      setReview(data);
    } catch (err: unknown) {
      setReview(null);
      setError(err instanceof Error ? err.message : "加载审核目录失败");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    loadReview(directory);
  }, [directory]);

  const currentImageUrl = useMemo(() => {
    if (!review?.current) {
      return null;
    }
    return getReferenceReviewImageUrl(review.directory, review.current.relative_path, review.preview_max_edge);
  }, [review]);

  const nextImageUrl = useMemo(() => {
    if (!review?.next) {
      return null;
    }
    return getReferenceReviewImageUrl(review.directory, review.next.relative_path, review.preview_max_edge);
  }, [review]);

  const applyAction = async (action: "keep" | "discard") => {
    if (!review?.current || busy) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const data = await applyReferenceReviewAction({
        directory: review.directory,
        relative_path: review.current.relative_path,
        action
      });
      setReview(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "提交审核结果失败");
    } finally {
      setBusy(false);
    }
  };

  const undo = async () => {
    if (!review || busy || review.history_count === 0) {
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const data = await undoReferenceReview(review.directory);
      setReview(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "撤销失败");
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (busy || isTypingTarget(event.target)) {
        return;
      }
      if (event.metaKey || event.ctrlKey || event.altKey) {
        return;
      }
      const key = event.key.toLowerCase();
      if (key === "k") {
        event.preventDefault();
        void applyAction("keep");
      } else if (key === "d") {
        event.preventDefault();
        void applyAction("discard");
      } else if (key === "z") {
        event.preventDefault();
        void undo();
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [busy, review]);

  useEffect(() => {
    if (!nextImageUrl) {
      return;
    }
    const image = new Image();
    image.decoding = "async";
    image.src = nextImageUrl;
  }, [nextImageUrl]);

  return (
    <div className="page review-page">
      <div className="topbar">
        <Link to="/">返回上传</Link>
      </div>

      <section className="panel review-toolbar">
        <div className="review-toolbar-head">
          <div>
            <h1>人工筛图</h1>
            <p>逐张浏览已抓取图片，按键盘快捷键或点击按钮完成“保留 / 弃用”。</p>
          </div>
          <div className="review-hotkeys">
            <span className="badge">保留 {review?.keep_hotkey ?? "K"}</span>
            <span className="badge">弃用 {review?.discard_hotkey ?? "D"}</span>
            <span className="badge">撤销 {review?.undo_hotkey ?? "Z"}</span>
          </div>
        </div>

        <div className="review-directory-form">
          <label htmlFor="review-directory">审核目录</label>
          <input
            id="review-directory"
            value={directoryInput}
            onChange={(event) => setDirectoryInput(event.target.value)}
            placeholder={DEFAULT_DIRECTORY}
          />
          <button
            disabled={busy}
            onClick={() => {
              const nextDirectory = directoryInput.trim();
              setSearchParams(nextDirectory ? { directory: nextDirectory } : {});
              setDirectory(nextDirectory || DEFAULT_DIRECTORY);
            }}
          >
            载入目录
          </button>
        </div>
      </section>

      {error ? <div className="error">{error}</div> : null}

      <div className="review-shell">
        <section className="panel review-stage">
          {!review ? <div className="empty">正在读取审核目录...</div> : null}
          {review && review.current && currentImageUrl ? (
            <>
              <div className="review-image-wrap">
                <img
                  key={review.current.relative_path}
                  className="review-image"
                  src={currentImageUrl}
                  alt={review.current.file_name}
                  loading="eager"
                  decoding="async"
                />
              </div>
              <div className="review-caption">
                <strong>{review.current.file_name}</strong>
                <span>{review.current.relative_path}</span>
              </div>
            </>
          ) : null}
          {review && !review.current ? (
            <div className="empty review-finished">
              当前目录已没有待审核图片，可按 <code>Z</code> 撤销上一步，或切换到其他目录继续审核。
            </div>
          ) : null}
        </section>

        <aside className="panel review-sidebar">
          <h3>进度</h3>
          <div className="review-stats">
            <div className="review-stat-card">
              <span>待审核</span>
              <strong>{review?.pending_count ?? 0}</strong>
            </div>
            <div className="review-stat-card">
              <span>已保留</span>
              <strong>{review?.keep_count ?? 0}</strong>
            </div>
            <div className="review-stat-card">
              <span>已弃用</span>
              <strong>{review?.discard_count ?? 0}</strong>
            </div>
            <div className="review-stat-card">
              <span>总计</span>
              <strong>{review?.total_count ?? 0}</strong>
            </div>
          </div>

          <div className="review-actions">
            <button disabled={busy || !review?.current} onClick={() => void applyAction("keep")}>
              保留 (K)
            </button>
            <button className="button-secondary" disabled={busy || !review?.current} onClick={() => void applyAction("discard")}>
              弃用 (D)
            </button>
            <button className="button-ghost" disabled={busy || !review || review.history_count === 0} onClick={() => void undo()}>
              撤销上一步 (Z)
            </button>
          </div>

          <div className="review-notes">
            <p>目录：{review?.directory ?? directory}</p>
            <p>已审核：{review?.reviewed_count ?? 0}</p>
            <p>可撤销次数：{review?.history_count ?? 0}</p>
          </div>
        </aside>
      </div>
    </div>
  );
}
