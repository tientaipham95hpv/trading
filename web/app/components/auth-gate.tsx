"use client";

import { Shield } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import { api } from "./api";

export function AuthGate({ children }: { children: ReactNode }) {
  const [checked, setChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [token, setToken] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    const expire = () => {
      if (active) setAuthenticated(false);
    };
    window.addEventListener(api.authExpiredEvent, expire);

    async function validateSession() {
      if (!api.hasToken()) {
        if (active) setChecked(true);
        return;
      }
      try {
        await api.status();
        if (active) setAuthenticated(true);
      } catch {
        api.clearToken();
      } finally {
        if (active) setChecked(true);
      }
    }
    void validateSession();
    return () => {
      active = false;
      window.removeEventListener(api.authExpiredEvent, expire);
    };
  }, []);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!token.trim()) return;
    setSubmitting(true);
    setError(null);
    api.setToken(token);
    try {
      await api.status();
      setAuthenticated(true);
    } catch {
      api.clearToken();
      setError("Token không hợp lệ hoặc máy chủ chưa sẵn sàng.");
    } finally {
      setSubmitting(false);
    }
  }

  if (!checked) {
    return (
      <main className="flex min-h-screen items-center justify-center bg-[var(--bg-base)] text-sm text-[var(--text-muted)]">
        Đang kiểm tra phiên đăng nhập…
      </main>
    );
  }
  if (authenticated) return children;
  return (
    <main className="flex min-h-screen items-center justify-center bg-[var(--bg-base)] p-4">
      <form className="glass-card w-full max-w-md p-6" onSubmit={submit}>
        <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-xl bg-[rgba(59,130,246,0.12)] text-[var(--color-info)]">
          <Shield size={22} />
        </div>
        <h1 className="text-xl font-bold">Đăng nhập Trading Control</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Nhập token vận hành. Token chỉ được giữ trong phiên trình duyệt này.
        </p>
        <label
          className="mt-5 block text-xs font-bold uppercase tracking-wide text-[var(--text-secondary)]"
          htmlFor="operator-token"
        >
          Token truy cập
        </label>
        <input
          autoComplete="current-password"
          autoFocus
          className="field mt-2 w-full"
          id="operator-token"
          onChange={(event) => setToken(event.target.value)}
          placeholder="Dán token tại đây"
          type="password"
          value={token}
        />
        {error ? <p className="mt-3 text-sm text-[var(--color-loss)]">{error}</p> : null}
        <button
          className="btn-primary mt-5 w-full"
          disabled={submitting || !token.trim()}
          type="submit"
        >
          {submitting ? "Đang xác thực…" : "Đăng nhập"}
        </button>
      </form>
    </main>
  );
}
