import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useNavigate } from "react-router-dom";
import { uploadImages } from "../lib/api";

export default function UploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const onSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!file) {
      setError("请先选择图片");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const resp = await uploadImages([file]);
      navigate(`/batches/${resp.batch_id}`);
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : "上传失败";
      setError(message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="page upload-page">
      <div className="topbar">
        <Link to="/reference-review">前往人工筛图</Link>
      </div>
      <h1>工笔重绘工作台</h1>
      <p>上传图片后批量生成工笔风格画作。</p>

      <form onSubmit={onSubmit} className="panel">
        <input
          type="file"
          accept="image/*"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button type="submit" disabled={busy}>
          {busy ? "上传中..." : "上传并创建批次"}
        </button>
      </form>
      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}
