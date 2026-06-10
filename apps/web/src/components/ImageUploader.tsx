import React, { useRef, useState, useImperativeHandle, forwardRef } from "react";

type Props = {
  disabled?: boolean;
  maxFiles?: number;
};

export type ImageUploaderHandle = {
  getFiles: () => File[];
  clear: () => void;
};

const ImageUploader = forwardRef<ImageUploaderHandle, Props>(
  function ImageUploader({ disabled, maxFiles = 5 }, ref) {
    const [files, setFiles] = useState<File[]>([]);
    const inputRef = useRef<HTMLInputElement>(null);

    useImperativeHandle(ref, () => ({
      getFiles: () => files,
      clear: () => setFiles([]),
    }));

    const handleSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
      const selected = e.target.files;
      if (!selected) return;

      const incoming = Array.from(selected);
      const merged = [...files, ...incoming].slice(0, maxFiles);

      setFiles(merged);
      // 重置 input，保证重复选同一文件也能触发 onChange
      if (inputRef.current) inputRef.current.value = "";
    };

    const handleRemove = (index: number) => {
      setFiles((prev) => prev.filter((_, i) => i !== index));
    };

    const remaining = maxFiles - files.length;

    return (
      <div className="image-uploader">
        {/* 已选图片缩略图网格 */}
        {files.length > 0 && (
          <div className="upload-preview-grid">
            {files.map((file, i) => (
              <div key={`${file.name}-${i}-${file.size}`} className="upload-preview-card">
                <img
                  src={URL.createObjectURL(file)}
                  alt={file.name}
                  className="upload-preview-img"
                />
                <button
                  type="button"
                  className="upload-preview-remove"
                  onClick={() => handleRemove(i)}
                  disabled={disabled}
                  title="移除此图片"
                >
                  ✕
                </button>
                <span className="upload-preview-name">{file.name}</span>
              </div>
            ))}

            {/* 继续添加卡片 */}
            {remaining > 0 && (
              <button
                type="button"
                className="upload-add-card"
                onClick={() => inputRef.current?.click()}
                disabled={disabled}
              >
                <span className="upload-add-icon">+</span>
                <span className="upload-add-label">添加图片</span>
              </button>
            )}
          </div>
        )}

        {/* 无选中时显示大上传区 */}
        {files.length === 0 && (
          <button
            type="button"
            className="upload-dropzone"
            onClick={() => inputRef.current?.click()}
            disabled={disabled}
          >
            <span className="upload-dropzone-icon">＋</span>
            <span className="upload-dropzone-title">点击选择图片</span>
            <span className="upload-dropzone-hint">
              支持批量选择，最多 {maxFiles} 张
            </span>
          </button>
        )}

        {/* 隐藏文件输入 */}
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          multiple
          onChange={handleSelect}
          disabled={disabled}
          style={{ display: "none" }}
        />

        {/* 底部计数 */}
        {files.length > 0 && (
          <div className="upload-footer">
            已选 <strong>{files.length}</strong> / {maxFiles} 张
          </div>
        )}
      </div>
    );
  }
);

export default ImageUploader;
