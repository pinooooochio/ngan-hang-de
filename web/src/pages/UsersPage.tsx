import { useEffect, useState } from "react";
import { api, ROLES, roleLabel, type Role, type UserRow } from "../api";
import { useAuth } from "../auth";

const fmt = (s: string | null) => (s ? s.replace("T", " ").slice(0, 16) : "");

export default function UsersPage() {
  const { me } = useAuth();
  const [users, setUsers] = useState<UserRow[]>([]);
  const [form, setForm] = useState({ username: "", display_name: "", password: "", role: "student" as Role });
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const load = () => api.listUsers().then(setUsers);
  useEffect(() => {
    load();
  }, []);

  const run = async (fn: () => Promise<string>) => {
    setMsg("");
    setError("");
    try {
      setMsg(await fn());
      await load();
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const resetPassword = (u: UserRow) => {
    const pw = window.prompt(`Mật khẩu mới cho ${u.username} (ít nhất 6 ký tự):`);
    if (pw) run(async () => (await api.updateUser(u.id, { password: pw }), `Đã đặt lại mật khẩu cho ${u.username}.`));
  };

  return (
    <div>
      <h2>Người dùng và phân quyền</h2>
      {msg && <div className="alert ok">{msg}</div>}
      {error && <div className="alert error">{error}</div>}

      <section className="section-card">
        <h3>Tạo tài khoản</h3>
        <form
          className="form-row"
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              const u = await api.createUser({ ...form, display_name: form.display_name || undefined });
              setForm({ username: "", display_name: "", password: "", role: form.role });
              return `Đã tạo ${u.username} (${roleLabel(u.role)}). Gửi tên đăng nhập và mật khẩu cho người dùng; họ tự đổi mật khẩu sau.`;
            });
          }}
        >
          <label>
            Tên đăng nhập
            <input
              value={form.username}
              onChange={(e) => setForm({ ...form, username: e.target.value })}
              placeholder="vd: nguyen.an"
              required
            />
          </label>
          <label>
            Tên hiển thị
            <input value={form.display_name} onChange={(e) => setForm({ ...form, display_name: e.target.value })} />
          </label>
          <label>
            Mật khẩu tạm
            <input value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} required />
          </label>
          <label>
            Vai trò
            <select value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}>
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </select>
          </label>
          <button className="primary">Tạo</button>
        </form>
        <p className="hint">
          Admin: toàn quyền. Soạn đề: soạn, import, sinh câu AI, ghép đề; câu vào nháp chờ admin duyệt, không xoá được. Học
          viên: làm các đề đã mở và xem kết quả của mình.
        </p>
      </section>

      <table className="table">
        <thead>
          <tr>
            <th>Tài khoản</th>
            <th>Vai trò</th>
            <th>Đăng nhập gần nhất</th>
            <th>Trạng thái</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {users.map((u) => (
            <tr key={u.id} className={u.active ? "" : "muted"}>
              <td>
                <b>{u.display_name}</b>
                <div className="muted small">{u.username}</div>
              </td>
              <td>
                <select
                  value={u.role}
                  disabled={u.id === me.id}
                  onChange={(e) =>
                    run(async () => {
                      const r = await api.updateUser(u.id, { role: e.target.value as Role });
                      return `${u.username} giờ là ${roleLabel(r.role)}.`;
                    })
                  }
                >
                  {ROLES.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </td>
              <td className="muted">{fmt(u.last_login) || "Chưa đăng nhập"}</td>
              <td>{u.active ? <span className="badge approved">Hoạt động</span> : <span className="badge draft">Đã khoá</span>}</td>
              <td className="right nowrap">
                <button className="link" onClick={() => resetPassword(u)}>
                  Đặt lại mật khẩu
                </button>
                {u.id !== me.id && (
                  <button
                    className={u.active ? "link danger" : "link"}
                    onClick={() =>
                      run(async () => {
                        await api.updateUser(u.id, { active: !u.active });
                        return u.active ? `Đã khoá ${u.username}.` : `Đã mở khoá ${u.username}.`;
                      })
                    }
                  >
                    {u.active ? "Khoá" : "Mở khoá"}
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="hint">
        Khoá thay cho xoá để giữ lịch sử làm bài. Đổi vai trò, mật khẩu hay khoá thì người đó bị đăng xuất. Quên mật khẩu admin:
        chạy <code>nhd user passwd &lt;tên&gt;</code> trên máy chủ.
      </p>
    </div>
  );
}
