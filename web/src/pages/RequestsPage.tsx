import { useEffect, useState } from "react";
import { api, type AnswerRequestRow, type RequestStatus } from "../api";
import { useAuth } from "../auth";

const STATUS: Record<RequestStatus, string> = { pending: "Chờ duyệt", approved: "Đã đồng ý", rejected: "Từ chối" };
const fmt = (s: string | null) => (s ? s.replace("T", " ").slice(0, 16) : "");

export default function RequestsPage() {
  const { reload } = useAuth();
  const [rows, setRows] = useState<AnswerRequestRow[] | null>(null);
  const [filter, setFilter] = useState<RequestStatus | "">("pending");
  const [error, setError] = useState("");

  const load = () => api.listRequests(filter || undefined).then(setRows);
  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter]);

  const decide = async (r: AnswerRequestRow, status: "approved" | "rejected") => {
    setError("");
    const note = status === "rejected" ? window.prompt("Lý do từ chối (không bắt buộc):") ?? undefined : undefined;
    try {
      await api.decideRequest(r.id, status, note);
      await load();
      await reload();
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  return (
    <div>
      <h2>Yêu cầu tải đáp án</h2>
      <p className="hint">
        Học viên tải được file đề của các đề đã mở; muốn tải đáp án và lời giải thì gửi yêu cầu ở trang Luyện đề. Đồng ý thì
        học viên tải được ngay ở lần mở trang tiếp theo.
      </p>
      {error && <div className="alert error">{error}</div>}
      <div className="filters">
        <select value={filter} onChange={(e) => setFilter(e.target.value as RequestStatus | "")}>
          <option value="pending">Chờ duyệt</option>
          <option value="approved">Đã đồng ý</option>
          <option value="rejected">Từ chối</option>
          <option value="">Tất cả</option>
        </select>
      </div>
      {rows && rows.length === 0 && <div className="muted">Không có yêu cầu nào.</div>}
      {rows && rows.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Học viên</th>
              <th>Đề</th>
              <th>Gửi lúc</th>
              <th>Trạng thái</th>
              <th />
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.id}>
                <td>
                  {r.user?.display_name}
                  <div className="muted small">{r.user?.username}</div>
                </td>
                <td>{r.exam?.title ?? "(đề đã xoá)"}</td>
                <td className="muted">{fmt(r.created_at)}</td>
                <td>
                  {STATUS[r.status]}
                  {r.decided_by && (
                    <div className="muted small">
                      {r.decided_by}, {fmt(r.decided_at)}
                      {r.note ? ` · ${r.note}` : ""}
                    </div>
                  )}
                </td>
                <td className="right nowrap">
                  {r.status !== "approved" && (
                    <button className="primary" onClick={() => decide(r, "approved")}>
                      Đồng ý
                    </button>
                  )}{" "}
                  {r.status !== "rejected" && (
                    <button className="danger" onClick={() => decide(r, "rejected")}>
                      {r.status === "approved" ? "Thu hồi" : "Từ chối"}
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
