import { useState } from "react";
import { api, roleLabel } from "../api";
import { useAuth } from "../auth";

const ROLE_HINT = {
  admin: "Toàn quyền: duyệt và xoá câu, xoá đề, quản lý người dùng, sao lưu.",
  editor: "Soạn, import, sinh câu AI, ghép đề. Câu mới vào nháp chờ admin duyệt; không xoá được câu hay đề.",
  student: "Làm các đề được mở cho học viên, xem kết quả của mình, xin tải đáp án.",
};

export default function AccountPage() {
  const { me, reload } = useAuth();
  const [name, setName] = useState(me.display_name);
  const [oldPw, setOldPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [again, setAgain] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const run = async (fn: () => Promise<string>) => {
    setMsg("");
    setError("");
    try {
      setMsg(await fn());
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  return (
    <div className="narrow-page">
      <h2>Tài khoản của tôi</h2>
      {msg && <div className="alert ok">{msg}</div>}
      {error && <div className="alert error">{error}</div>}

      <section className="section-card">
        <h3>Thông tin</h3>
        <p>
          Tên đăng nhập <b>{me.username}</b> · vai trò <b>{roleLabel(me.role)}</b>
        </p>
        <p className="hint">{ROLE_HINT[me.role]}</p>
        <form
          className="form-row"
          onSubmit={(e) => {
            e.preventDefault();
            run(async () => {
              await api.updateMe(name);
              await reload();
              return "Đã đổi tên hiển thị.";
            });
          }}
        >
          <label>
            Tên hiển thị
            <input value={name} onChange={(e) => setName(e.target.value)} required />
          </label>
          <button disabled={!name.trim() || name === me.display_name}>Lưu</button>
        </form>
      </section>

      <section className="section-card">
        <h3>Đổi mật khẩu</h3>
        <form
          className="form-col"
          onSubmit={(e) => {
            e.preventDefault();
            if (newPw !== again) {
              setError("Hai lần nhập mật khẩu mới không khớp.");
              return;
            }
            run(async () => {
              await api.changePassword(oldPw, newPw);
              setOldPw("");
              setNewPw("");
              setAgain("");
              return "Đã đổi mật khẩu. Các phiên đăng nhập ở máy khác đã bị đăng xuất.";
            });
          }}
        >
          <label>
            Mật khẩu hiện tại
            <input type="password" value={oldPw} onChange={(e) => setOldPw(e.target.value)} autoComplete="current-password" required />
          </label>
          <label>
            Mật khẩu mới (ít nhất 6 ký tự)
            <input type="password" value={newPw} onChange={(e) => setNewPw(e.target.value)} autoComplete="new-password" required />
          </label>
          <label>
            Nhập lại mật khẩu mới
            <input type="password" value={again} onChange={(e) => setAgain(e.target.value)} autoComplete="new-password" required />
          </label>
          <div>
            <button className="primary">Đổi mật khẩu</button>
          </div>
        </form>
      </section>
    </div>
  );
}
