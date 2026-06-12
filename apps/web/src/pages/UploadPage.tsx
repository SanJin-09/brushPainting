import { useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import { uploadImages } from "../lib/api";
import ImageUploader, { type ImageUploaderHandle } from "../components/ImageUploader";

export default function UploadPage() {
  const uploaderRef = useRef<ImageUploaderHandle>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const navigate = useNavigate();

  const handleUpload = async () => {
    const files = uploaderRef.current?.getFiles() ?? [];

    if (files.length === 0) {
      setError("请先选择图片");
      return;
    }

    setBusy(true);
    setError(null);
    try {
      const resp = await uploadImages(files);
      uploaderRef.current?.clear();
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
      <h1>工笔重绘工作台</h1>
      <p>上传图片后批量生成工笔风格画作。</p>

      <div className="panel">
        <ImageUploader ref={uploaderRef} disabled={busy} />
        <button
          type="button"
          onClick={handleUpload}
          disabled={busy}
          style={{ marginTop: 14, width: "100%" }}
        >
          {busy ? "上传中..." : "上传并创建批次"}
        </button>
      </div>
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
    </div>
  );
}
