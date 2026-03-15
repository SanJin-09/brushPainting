import React, { useState } from "react";
import { Link } from "react-router-dom";
import { useNavigate } from "react-router-dom";
import { createSession } from "../lib/api";

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
      const resp = await createSession(file);
      navigate(`/sessions/${resp.session_id}`);
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
      <p>上传原图后先统一整图风格化，再针对不满意区域做掩码局部重绘。</p>

      <form onSubmit={onSubmit} className="panel">
        <input
          type="file"
          accept="image/*"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
        <button type="submit" disabled={busy}>
          {busy ? "上传中..." : "创建会话"}
        </button>
      </form>
      {error ? <div className="error">{error}</div> : null}
    </div>
  );
}
