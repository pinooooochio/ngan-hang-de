import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type ExamSummary } from "../api";

export function buildSummary(b: ExamSummary["builds"]) {
  const total = b.pending + b.running + b.done + b.failed;
  if (b.failed) return <span className="badge state-error">{b.failed} file lỗi</span>;
  if (b.pending + b.running) return <span className="badge draft">Đang biên dịch {b.done}/{total}</span>;
  return <span className="badge approved">Đủ {total} PDF</span>;
}

export default function ExamListPage() {
  const [exams, setExams] = useState<ExamSummary[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .listExams()
      .then(setExams)
      .catch((e) => setError(String(e.message)));
  }, []);

  return (
    <div className="exam-list">
      <div className="editor-head">
        <h2>Kho đề</h2>
        <span className="spacer" />
        <Link to="/de/moi" className="button primary">
          Ghép đề mới
        </Link>
      </div>
      {error && <div className="alert error">{error}</div>}
      {exams && exams.length === 0 && (
        <div className="empty">
          Chưa có đề nào. <Link to="/de/moi">Ghép đề đầu tiên</Link>.
        </div>
      )}
      {exams && exams.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Đề</th>
              <th>Ngày</th>
              <th>Số câu</th>
              <th>Mã đề</th>
              <th>PDF</th>
              <th>Tạo lúc</th>
            </tr>
          </thead>
          <tbody>
            {exams.map((e) => (
              <tr key={e.id}>
                <td>
                  <Link to={`/de/${e.id}`}>{e.title}</Link>
                </td>
                <td>{e.date ?? ""}</td>
                <td>{e.n_questions}</td>
                <td>{e.n_variants}</td>
                <td>{buildSummary(e.builds)}</td>
                <td className="muted">{e.created_at.replace("T", " ")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
