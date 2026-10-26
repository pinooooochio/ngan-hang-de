import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, levelLabel, typeLabel, type GenBatchDetail } from "../api";
import { bankLink, GenItems, STATUS_LABEL } from "./GeneratePage";

export default function GenBatchPage() {
  const { id } = useParams();
  const batchId = Number(id);
  const [b, setB] = useState<GenBatchDetail | null>(null);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    api
      .genBatch(batchId)
      .then(setB)
      .catch((e) => setError(String(e.message)));
  }, [batchId]);

  useEffect(load, [load]);

  const busy = !!b && (b.status === "pending" || b.status === "running");
  useEffect(() => {
    if (!busy) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [busy, load]);

  if (error) return <div className="alert error">{error}</div>;
  if (!b) return <div className="muted">Đang tải…</div>;
  const p = b.params;

  return (
    <div className="generate">
      <div className="editor-head">
        <Link to="/sinh">‹ Sinh câu hỏi</Link>
        <h2>Lần sinh #{b.id}</h2>
        <span className={`badge ${b.status === "done" ? "approved" : b.status === "failed" ? "state-error" : "draft"}`}>
          {STATUS_LABEL[b.status]}
        </span>
        <span className="spacer" />
        {b.n_added > 0 && (
          <Link to={bankLink(b.source)} className="button primary">
            Duyệt {b.n_added} câu nháp
          </Link>
        )}
        {b.status === "failed" && b.mode === "api" && <button onClick={() => api.genRetry(b.id).then(setB)}>Chạy lại</button>}
      </div>
      <div className="muted">
        {p.grade} › {p.topic}
        {p.dang && <> › {p.dang}</>} · {levelLabel(p.level)} · {typeLabel(p.type)} · {p.count} câu ·{" "}
        {b.mode === "api" ? `Claude API (${b.model})` : "dán tay"}
        {b.usage && (
          <>
            {" "}
            · {b.usage.input_tokens + (b.usage.cache_read_input_tokens ?? 0)} token vào, {b.usage.output_tokens} token ra
          </>
        )}
      </div>
      {p.notes && <div className="muted">Yêu cầu thêm: {p.notes}</div>}
      {busy && <div className="alert warn">Claude đang soạn câu hỏi, trang tự cập nhật khi xong.</div>}
      {b.error && <div className={`alert ${b.status === "failed" ? "error" : "warn"}`}>{b.error}</div>}

      {b.items.length > 0 && (
        <>
          <h3>
            Kết quả: {b.n_added} câu mới, {b.n_duplicate} trùng, {b.n_error} lỗi
          </h3>
          <GenItems items={b.items} />
        </>
      )}

      <details>
        <summary>Prompt đã dùng</summary>
        <pre className="mono-block">{b.system_prompt}</pre>
        <pre className="mono-block">{b.user_prompt}</pre>
      </details>
      {b.output && (
        <details>
          <summary>Kết quả gốc từ Claude</summary>
          <pre className="mono-block">{b.output}</pre>
        </details>
      )}
    </div>
  );
}
