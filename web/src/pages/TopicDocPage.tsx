import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type TopicDocDetail, type TopicDocSummary } from "../api";
import { useAuth } from "../auth";

const STATUS = { pending: "Đang chờ biên dịch", running: "Đang biên dịch PDF…", done: "Đã có PDF", failed: "Lỗi biên dịch" };

/** Danh sách chuyên đề đã tạo. */
export function TopicDocListPage() {
  const [rows, setRows] = useState<TopicDocSummary[] | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.topicDocs().then(setRows).catch((e: Error) => setError(e.message));
  }, []);
  return (
    <div>
      <div className="toolbar">
        <h2>Chuyên đề</h2>
        <span className="spacer" />
        <Link className="button primary" to="/chuyen-de/moi">
          Tạo chuyên đề
        </Link>
      </div>
      <p className="hint">Lý thuyết đã duyệt và bài tập tự luyện theo chủ đề, đáp án và lời giải ở cuối quyển, xuất PDF.</p>
      {error && <div className="alert error">{error}</div>}
      {rows && !rows.length && <p className="muted">Chưa có chuyên đề nào.</p>}
      {rows && rows.length > 0 && (
        <table className="table">
          <thead>
            <tr>
              <th>Chuyên đề</th>
              <th>Chủ đề</th>
              <th>Bài tập</th>
              <th>Người tạo</th>
              <th>Ngày tạo</th>
              <th>PDF</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((d) => (
              <tr key={d.id}>
                <td>
                  <Link to={`/chuyen-de/${d.id}`}>{d.title}</Link>
                </td>
                <td className="small">{d.topics.join(", ")}</td>
                <td>{d.count}</td>
                <td>{d.username ?? ""}</td>
                <td className="nowrap small">{d.created_at.replace("T", " ")}</td>
                <td className={d.status === "failed" ? "error-text" : "muted"}>
                  {d.status === "done" ? (
                    <a href={`/api/topic-docs/${d.id}/chuyen-de.pdf`} target="_blank" rel="noreferrer">
                      Mở PDF
                    </a>
                  ) : (
                    STATUS[d.status]
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

/** Một chuyên đề: trạng thái PDF, nội dung đã chọn, chỗ thiếu; cập nhật hoặc chọn lại bài tập. */
export default function TopicDocPage() {
  const id = Number(useParams().id);
  const navigate = useNavigate();
  const { me } = useAuth();
  const [doc, setDoc] = useState<TopicDocDetail | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(true);

  const load = useCallback(() => {
    api.topicDoc(id).then(setDoc).catch((e: Error) => setError(e.message));
  }, [id]);
  useEffect(load, [load]);

  const running = doc?.status === "pending" || doc?.status === "running";
  useEffect(() => {
    if (!running) return;
    const t = setInterval(load, 2000);
    return () => clearInterval(t);
  }, [running, load]);

  if (error && !doc) return <div className="alert error">{error}</div>;
  if (!doc) return <p className="muted">Đang tải…</p>;

  const act = async (fn: () => Promise<TopicDocDetail | void>) => {
    setBusy(true);
    setError("");
    try {
      const r = await fn();
      if (r) setDoc(r);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const remove = () =>
    act(async () => {
      if (!window.confirm(`Xoá chuyên đề "${doc.title}" và file PDF? Không hoàn tác được.`)) return;
      await api.deleteTopicDoc(doc.id);
      navigate("/chuyen-de");
    });

  const pdf = `/api/topic-docs/${doc.id}/chuyen-de.pdf`;

  return (
    <div className="topic-doc">
      <div className="editor-head">
        <Link to="/chuyen-de">‹ Chuyên đề</Link>
        <h2>{doc.title}</h2>
        <span className={doc.status === "failed" ? "error-text" : "muted"}>{STATUS[doc.status]}</span>
        <span className="spacer" />
        {doc.status === "done" && (
          <a className="button primary" href={`${pdf}?download=true`}>
            Tải PDF
          </a>
        )}
        <a className="button" href={`/api/topic-docs/${doc.id}/chuyen-de.tex`} title="File .tex kèm nhd.sty để sửa tiếp">
          Tải .tex
        </a>
        <button disabled={busy || running} onClick={() => act(() => api.refreshTopicDoc(doc.id, false))} title="Giữ các câu đã chọn, lấy nội dung lý thuyết và câu hỏi mới nhất">
          Cập nhật nội dung
        </button>
        <button disabled={busy || running} onClick={() => act(() => api.refreshTopicDoc(doc.id, true))} title="Chọn lại bài tập khác, cùng cấu hình">
          Chọn bài tập khác
        </button>
        <Link className="button" to={`/chuyen-de/moi?tu=${doc.id}`}>
          Tạo bản mới từ cấu hình này
        </Link>
        {me.role === "admin" && (
          <button className="danger" disabled={busy} onClick={remove}>
            Xoá
          </button>
        )}
      </div>
      {error && <div className="alert error">{error}</div>}
      {doc.status === "failed" && (
        <div className="alert error">
          Biên dịch lỗi{doc.error_question && (
            <>
              {" "}
              ở câu <Link to={`/cau/${encodeURIComponent(doc.error_question)}`}>{doc.error_question}</Link>
            </>
          )}
          : {doc.error}. Sửa câu hoặc lý thuyết rồi bấm "Cập nhật nội dung".
        </div>
      )}
      {doc.notes.length > 0 && (
        <details className="alert warn">
          <summary>{doc.notes.length} chỗ thiếu (ngân hàng không đủ câu hoặc chưa có lý thuyết đã duyệt)</summary>
          <ul className="small">
            {doc.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </details>
      )}
      <div className="topic-doc-grid">
        <div>
          {doc.outline.map((t) => (
            <div key={t.path} className="card">
              <b>
                <Link to={`/ly-thuyet/cd/${t.path}`}>{t.ten}</Link>
              </b>
              <ul className="small">
                {t.general > 0 && <li>Kiến thức cần nhớ: {t.general} khối</li>}
                {t.dang.map((d, i) => (
                  <li key={d.name}>
                    Dạng {i + 1}. {d.name}: {d.theory} khối lý thuyết, {d.exercises.length} bài tập
                    {d.exercises.length > 0 && (
                      <span className="muted">
                        {" "}
                        (
                        {d.exercises.map((q, j) => (
                          <span key={q.code}>
                            {j > 0 && ", "}
                            <Link to={`/cau/${encodeURIComponent(q.code)}`}>
                              Câu {q.number}
                            </Link>{" "}
                            {q.level}
                          </span>
                        ))}
                        )
                      </span>
                    )}
                  </li>
                ))}
                {t.mixed.length > 0 && <li>Bài tập tổng hợp: {t.mixed.length} câu</li>}
              </ul>
            </div>
          ))}
          <p className="muted small">
            Tạo lúc {doc.created_at.replace("T", " ")}
            {doc.username && <> bởi {doc.username}</>}. Nội dung chụp lúc tạo; sửa câu hay lý thuyết sau đó thì bấm "Cập nhật
            nội dung".
          </p>
        </div>
        {doc.status === "done" && (
          <div className="pdf-frame">
            <div className="pdf-head">
              Bản PDF{" "}
              <button className="link" onClick={() => setShow(!show)}>
                {show ? "Ẩn" : "Hiện"}
              </button>
            </div>
            {show && <iframe src={`${pdf}?t=${encodeURIComponent(doc.finished_at ?? "")}`} title="Chuyên đề PDF" />}
          </div>
        )}
      </div>
    </div>
  );
}
