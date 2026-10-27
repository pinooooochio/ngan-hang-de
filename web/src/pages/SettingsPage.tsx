import { useEffect, useState } from "react";
import { api, type AppSettings } from "../api";
import { useAuth } from "../auth";

export default function SettingsPage() {
  const { reload } = useAuth();
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api.getSettings().then(setSettings);
  }, []);

  const save = async (patch: Partial<AppSettings>) => {
    setMsg("");
    setError("");
    try {
      setSettings(await api.saveSettings(patch));
      await reload();
      setMsg("Đã lưu.");
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  if (!settings) return null;
  return (
    <div className="narrow-page">
      <h2>Cài đặt chung</h2>
      {msg && <div className="alert ok">{msg}</div>}
      {error && <div className="alert error">{error}</div>}
      <section className="section-card">
        <h3>Học viên</h3>
        <label className="inline">
          <input type="checkbox" checked={settings.student_quick} onChange={(e) => save({ student_quick: e.target.checked })} />{" "}
          Cho học viên luyện nhanh từ ngân hàng
        </label>
        <p className="hint">
          Luyện nhanh bốc ngẫu nhiên câu đã duyệt theo thẻ và mức độ, kể cả luyện lại câu sai. Tắt thì học viên chỉ làm được
          các đề đã bật "Mở cho học viên" trong kho đề.
        </p>
      </section>
    </div>
  );
}
