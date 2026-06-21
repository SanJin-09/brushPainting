import React, { useEffect, useState } from "react";
import {
  createAuthSession,
  deleteAuthSession,
  getAuthStatus,
  onAuthenticationRequired,
  type AuthStatus,
} from "../lib/api";

type AuthGateProps = {
  children: React.ReactNode;
};

export default function AuthGate({ children }: AuthGateProps) {
  const [status, setStatus] = useState<AuthStatus | null>(null);
  const [apiKey, setApiKey] = useState("");
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  const refreshStatus = async () => {
    try {
      setError("");
      setStatus(await getAuthStatus());
    } catch {
      setStatus(null);
      setError("无法连接 API 服务，请检查服务是否已启动。");
    }
  };

  useEffect(() => {
    void refreshStatus();
    return onAuthenticationRequired(() => {
      setStatus({ auth_required: true, authenticated: false, csrf_token: null });
      setError("会话已失效，请重新验证。");
    });
  }, []);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    if (!apiKey.trim()) {
      setError("请输入 API Key。");
      return;
    }
    setSubmitting(true);
    setError("");
    try {
      setStatus(await createAuthSession(apiKey.trim()));
      setApiKey("");
    } catch {
      setError("API Key 无效或服务拒绝了登录请求。");
    } finally {
      setSubmitting(false);
    }
  };

  const logout = async () => {
    try {
      await deleteAuthSession();
    } catch {
      // 本地立即结束会话；服务端 Cookie 会在过期后失效。
    } finally {
      setStatus({ auth_required: true, authenticated: false, csrf_token: null });
    }
  };

  if (!status) {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <h1>工笔重绘工作台</h1>
          <p>{error || "正在检查 API 安全状态…"}</p>
          {error && <button onClick={() => void refreshStatus()}>重试</button>}
        </section>
      </main>
    );
  }

  if (status.auth_required && !status.authenticated) {
    return (
      <main className="auth-shell">
        <form className="auth-card" onSubmit={submit}>
          <div className="auth-badge">受保护的单机服务</div>
          <h1>验证访问权限</h1>
          <p>请输入部署管理员提供的 API Key。密钥仅用于建立当前浏览器会话，不会写入本地存储。</p>
          <label htmlFor="api-key">API Key</label>
          <input
            id="api-key"
            type="password"
            autoComplete="current-password"
            value={apiKey}
            onChange={(event) => setApiKey(event.target.value)}
            autoFocus
          />
          {error && <div className="error">{error}</div>}
          <button type="submit" disabled={submitting}>
            {submitting ? "验证中…" : "进入工作台"}
          </button>
        </form>
      </main>
    );
  }

  return (
    <>
      {status.auth_required && (
        <div className="auth-session-bar">
          <span>安全会话已启用</span>
          <button type="button" onClick={() => void logout()}>退出会话</button>
        </div>
      )}
      {children}
    </>
  );
}
