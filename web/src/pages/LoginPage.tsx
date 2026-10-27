import { useState } from "react";
import { api } from "../api";

interface Props {
  /** Chưa có tài khoản nào: tạo admin đầu tiên. */
  setup: boolean;
  onDone: () => void;
}

export default function LoginPage({ setup, onDone }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [again, setAgain] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (setup && password !== again) {
      setError("Hai lần nhập mật khẩu không khớp.");
      return;
    }
    setBusy(true);
    try {
      if (setup) await api.setup({ username, password, display_name: name || undefined });
      else await api.login(username, password);
      onDone();
    } catch (err) {
      setError(String((err as Error).message));
      setBusy(false);
    }
  };

  return (
    <div className="login-wrap">
      <form className="login-card" onSubmit={submit}>
        <div className="brand">Ngân hàng đề</div>
        <h2>{setup ? "Tạo tài khoản admin" : "Đăng nhập"}</h2>
        {setup && (
          <p className="hint">
            Chưa có tài khoản nào. Tài khoản đầu tiên là admin; các tài khoản khác do admin tạo trong menu tài khoản.
          </p>
        )}
        {error && <div className="alert error">{error}</div>}
        <label>
          Tên đăng nhập
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus autoComplete="username" required />
        </label>
        {setup && (
          <label>
            Tên hiển thị
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Không bắt buộc" />
          </label>
        )}
        <label>
          Mật khẩu
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            autoComplete={setup ? "new-password" : "current-password"}
            required
          />
        </label>
        {setup && (
          <label>
            Nhập lại mật khẩu
            <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" required />
          </label>
        )}
        <button className="primary" disabled={busy}>
          {setup ? "Tạo tài khoản" : "Đăng nhập"}
        </button>
        {!setup && <p className="hint">Quên mật khẩu? Nhờ admin đặt lại.</p>}
      </form>
    </div>
  );
}
