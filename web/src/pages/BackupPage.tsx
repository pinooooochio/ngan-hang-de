import { useEffect, useState } from "react";
import { api, type BackupInfo, type BackupSummary } from "../api";

const MAIN_TABLES: [string, string][] = [
  ["questions", "câu hỏi"],
  ["taxonomy_nodes", "thẻ"],
  ["exam_templates", "khung đề"],
  ["exams", "đề"],
  ["exam_variants", "mã đề"],
  ["attempts", "lượt luyện"],
  ["generation_batches", "lần sinh AI"],
];

const fileSize = (n: number) => (n >= 1e5 ? `${(n / 1e6).toFixed(1)} MB` : `${Math.round(n / 1e3)} KB`);
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString("vi-VN") : "không rõ");
const describe = (tables: Record<string, number>) =>
  MAIN_TABLES.map(([t, label]) => `${tables[t] ?? 0} ${label}`).join(", ");

/** Sao lưu toàn bộ dữ liệu ra một file .zip và khôi phục lại từ file đó. */
export default function BackupPage() {
  const [info, setInfo] = useState<BackupInfo | null>(null);
  const [withFiles, setWithFiles] = useState(true);
  // Bản sắp khôi phục: file vừa chọn hoặc tên một bản trên máy chủ, kèm nội dung đọc thử
  const [pending, setPending] = useState<{ src: File | string; label: string; summary: BackupSummary } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = () => {
    api.backupInfo().then(setInfo).catch((e) => setError(String(e.message)));
  };
  useEffect(load, []);

  const run = async (fn: () => Promise<string | void>) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const msg = await fn();
      if (msg) setMessage(msg);
      load();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const inspect = (src: File | string, label: string) =>
    run(async () => {
      setPending(null);
      setPending({ src, label, summary: await api.backupInspect(src) });
    });

  const restore = () =>
    pending &&
    run(async () => {
      const r = await api.backupRestore(pending.src);
      setPending(null);
      return (
        `Đã khôi phục: ${describe(r.tables)}.` +
        (r.safety_backup ? ` Dữ liệu trước khi khôi phục được lưu thành bản "${r.safety_backup}" bên dưới.` : "") +
        (r.relogin ? " Trong bản này tài khoản của bạn không còn là admin, hãy đăng nhập lại." : "")
      );
    });

  const counts = Object.fromEntries((info?.tables ?? []).map((t) => [t.name, t.count]));

  return (
    <div className="backup-page">
      <h2>Sao lưu và khôi phục</h2>
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert ok">{message}</div>}

      <section className="section-card">
        <h3>Tải bản sao lưu</h3>
        <p>
          Một file <code>.zip</code> chứa toàn bộ dữ liệu: câu hỏi (cả nháp), thẻ, khung đề, kho đề cùng mã đề và đáp án, lượt
          luyện, lịch sử sinh AI{withFiles ? " và các PDF đã biên dịch" : ""}. Cất file này ở nơi khác máy chủ (ổ ngoài, Google
          Drive…).
        </p>
        {info && (
          <p className="muted">
            Hiện có {describe(counts)}; {info.files} file PDF ({fileSize(info.files_size)}).
          </p>
        )}
        <div className="toolbar backup-actions">
          <label className="checkbox">
            <input type="checkbox" checked={withFiles} onChange={(e) => setWithFiles(e.target.checked)} /> Kèm PDF
          </label>
          <a className="button primary" href={`/api/backup/download?files=${withFiles}`}>
            Tải bản sao lưu
          </a>
          <button disabled={busy} onClick={() => run(async () => `Đã lưu bản ${(await api.backupSave(withFiles)).name} trên máy chủ.`)}>
            Lưu một bản trên máy chủ
          </button>
          <a className="button" href="/api/export/questions.tex">
            Xuất câu hỏi ra .tex
          </a>
        </div>
        <p className="hint">
          Không kèm PDF thì file nhẹ hơn, PDF biên dịch lại được bằng nút "Biên dịch lại" ở trang đề. File .tex chỉ gồm câu hỏi,
          thẻ và mức độ (không có đề, khung đề, lượt luyện), đọc được bằng mắt và import lại ở trang Import.
        </p>
      </section>

      <section className="section-card">
        <h3>Khôi phục từ file</h3>
        <p>
          Khôi phục <strong>thay toàn bộ</strong> dữ liệu hiện có bằng dữ liệu trong file. Trước khi ghi đè, máy chủ tự lưu một bản
          dữ liệu hiện tại (tên bắt đầu bằng <code>truoc-khoi-phuc-</code>) để quay lại được nếu chọn nhầm file.
        </p>
        <label className="button">
          Chọn file sao lưu (.zip)
          <input
            type="file"
            accept=".zip,application/zip"
            hidden
            onChange={(e) => {
              const f = e.target.files?.[0];
              e.target.value = "";
              if (f) inspect(f, f.name);
            }}
          />
        </label>

        {pending && (
          <div className="alert warn restore-confirm">
            <div>
              <strong>{pending.label}</strong>, tạo lúc {when(pending.summary.created_at)}: {describe(pending.summary.tables)};{" "}
              {pending.summary.files} file PDF.
            </div>
            {pending.summary.warnings.map((w) => (
              <div key={w} className="small">
                Cảnh báo: {w}
              </div>
            ))}
            <div className="toolbar">
              <button className="danger" disabled={busy} onClick={restore}>
                {busy ? "Đang khôi phục…" : "Thay dữ liệu hiện tại bằng bản này"}
              </button>
              <button disabled={busy} onClick={() => setPending(null)}>
                Huỷ
              </button>
            </div>
          </div>
        )}
      </section>

      <section className="section-card">
        <h3>Các bản trên máy chủ</h3>
        {info && info.backups.length === 0 ? (
          <div className="muted">Chưa có bản nào.</div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>Tên</th>
                <th>Lúc</th>
                <th>Dung lượng</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {info?.backups.map((b) => (
                <tr key={b.name}>
                  <td>
                    {b.name}
                    {b.safety && <div className="muted small">tự lưu trước một lần khôi phục</div>}
                  </td>
                  <td>{when(b.modified)}</td>
                  <td>{fileSize(b.size)}</td>
                  <td>
                    <div className="row-actions">
                    <a href={`/api/backup/stored/${encodeURIComponent(b.name)}`}>Tải</a>
                    <button className="link" disabled={busy} onClick={() => inspect(b.name, b.name)}>
                      Khôi phục
                    </button>
                    <button
                      className="link"
                      disabled={busy}
                      onClick={() => confirm(`Xoá bản ${b.name}?`) && run(() => api.backupDelete(b.name))}
                    >
                      Xoá
                    </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {info && (
          <p className="hint">
            Thư mục <code>backups</code> cạnh file <code>docker-compose.yml</code> (trong máy chủ: <code>{info.folder}</code>). Sao
            lưu định kỳ: hẹn giờ chạy <code>docker compose exec -T app nhd backup --giu 14</code>, xem README.
          </p>
        )}
      </section>
    </div>
  );
}
