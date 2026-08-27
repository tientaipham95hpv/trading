"use client";

import { Shield } from "lucide-react";
import { type FormEvent, type ReactNode, useEffect, useState } from "react";

import { api } from "./api";

export function AuthGate({ children }: { children: ReactNode }) {
  const [checked, setChecked] = useState(false);
  const [authenticated, setAuthenticated] = useState(false);
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    let active = true;
    const expire = () => {
      if (active) setAuthenticated(false);
    };
    window.addEventListener(api.authExpiredEvent, expire);

    async function validateSession() {
      try {
        await api.status();
        if (active) setAuthenticated(true);
      } catch { /* login form remains visible */ } finally {
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
    if (!password) return;
    setSubmitting(true);
    setError(null);
    try {
      await api.login(password);
      await api.status();
      setAuthenticated(true);
    } catch {
      setError("Mật khẩu không hợp lệ hoặc máy chủ chưa sẵn sàng.");
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
        <h1 className="text-xl font-bold">Đăng nhập Trading Bot</h1>
        <p className="mt-2 text-sm text-[var(--text-muted)]">
          Nhập mật khẩu vận hành. Phiên đăng nhập được bảo vệ bằng cookie HttpOnly.
        </p>
        <label
          className="mt-5 block text-xs font-bold uppercase tracking-wide text-[var(--text-secondary)]"
          htmlFor="operator-password"
        >
          Mật khẩu
        </label>
        <input
          autoComplete="current-password"
          autoFocus
          className="field mt-2 w-full"
          id="operator-password"
          onChange={(event) => setPassword(event.target.value)}
          placeholder="Nhập mật khẩu vận hành"
          type="password"
          value={password}
        />
        {error ? <p className="mt-3 text-sm text-[var(--color-loss)]">{error}</p> : null}
        <button
          className="btn-primary mt-5 w-full"
          disabled={submitting || !password}
          type="submit"
        >
          {submitting ? "Đang xác thực…" : "Đăng nhập"}
        </button>
      </form>
    </main>
  );
}
