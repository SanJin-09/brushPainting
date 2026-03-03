import React, { useState } from "react";
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
      <h1>工笔拼接管理台</h1>
      <p>上传原图后开始分割、统一风格生成、审核与合成。</p>

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
