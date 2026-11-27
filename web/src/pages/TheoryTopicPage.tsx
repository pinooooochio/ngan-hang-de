import { StreamLanguage } from "@codemirror/language";
import { stex } from "@codemirror/legacy-modes/mode/stex";
import CodeMirror, { EditorView } from "@uiw/react-codemirror";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type TheoryKind, type TheoryParsed, type TheoryTopic } from "../api";
import { useAuth } from "../auth";
import TheoryBlocks from "../components/TheoryBlocks";

const SNIPPETS: { kind: TheoryKind | "dang" | "cauhoi"; label: string; text: string }[] = [
  { kind: "dinhnghia", label: "Định nghĩa", text: "\\begin{dinhnghia}[Tên khái niệm]\n\n\\end{dinhnghia}\n" },
  { kind: "dinhly", label: "Định lý / Tính chất", text: "\\begin{dinhly}[Tên định lý]\n\n\\end{dinhly}\n" },
  { kind: "congthuc", label: "Công thức", text: "\\begin{congthuc}\n\\[ \\]\n\\end{congthuc}\n" },
  { kind: "phuongphap", label: "Phương pháp giải", text: "\\begin{phuongphap}\n\\begin{itemize}\n\\item Bước 1: \n\\item Bước 2: \n\\end{itemize}\n\\end{phuongphap}\n" },
  { kind: "vidu", label: "Ví dụ (tự soạn)", text: "\\begin{vidu}\n\n\\begin{loigiai}\n\n\\end{loigiai}\n\\end{vidu}\n" },
  { kind: "cauhoi", label: "Ví dụ từ ngân hàng", text: "\\cauhoi{Q00001}\n" },
  { kind: "luuy", label: "Lưu ý / Sai lầm thường gặp", text: "\\begin{luuy}\n\n\\end{luuy}\n" },
];

function starter(t: TheoryTopic["topic"]): string {
  const lines = [
    `% Lý thuyết chủ đề: ${t.names.join(" / ")}`,
    "% Khối đầu tiên là kiến thức chung của chủ đề. Dòng % @dang: ... chuyển sang một dạng bài.",
    "",
    "\\begin{dinhnghia}[]",
    "",
    "\\end{dinhnghia}",
  ];
  for (const d of t.dang) lines.push("", `% @dang: ${d}`, "\\begin{phuongphap}", "", "\\end{phuongphap}");
  return lines.join("\n") + "\n";
}

const ACTION = { sua: "Sửa", duyet: "Duyệt", import: "Import" } as Record<string, string>;

export default function TheoryTopicPage() {
  const path = useParams()["*"] ?? "";
  const { me } = useAuth();
  const staff = me.role !== "student";
  const admin = me.role === "admin";
  const [data, setData] = useState<TheoryTopic | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [editing, setEditing] = useState(false);
  const [source, setSource] = useState("");
  const [parsed, setParsed] = useState<TheoryParsed | null>(null);
  const [busy, setBusy] = useState(false);
  const view = useRef<EditorView | null>(null);
  const extensions = useMemo(() => [StreamLanguage.define(stex), EditorView.lineWrapping], []);

  const load = () =>
    api
      .theoryTopic(path)
      .then((d) => {
        setData(d);
        setError("");
      })
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    setData(null);
    setEditing(false);
    setMessage("");
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path]);

  // xem trước khi đang soạn (đợi gõ xong một chút)
  useEffect(() => {
    if (!editing) return;
    const t = setTimeout(() => {
      api
        .theoryParse(source, path)
        .then(setParsed)
        .catch((e: Error) => setParsed({ errors: [{ line: 0, message: e.message }], warnings: [], sections: [] }));
    }, 400);
    return () => clearTimeout(t);
  }, [source, editing, path]);

  // rời trang khi chưa lưu
  const dirty = editing && data !== null && source !== (data.source || "") && source !== starter(data.topic);
  useEffect(() => {
    if (!dirty) return;
    const warn = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);

  if (error && !data)
    return (
      <div>
        <p>
          <Link to="/ly-thuyet">← Lý thuyết</Link>
        </p>
        <div className="alert error">{error}</div>
      </div>
    );
  if (!data) return <p className="muted">Đang tải…</p>;
  const t = data.topic;
  const drafts = data.blocks.filter((b) => b.status === "draft").length;

  const startEdit = (text?: string) => {
    setSource(text ?? (data.source || starter(t)));
    setParsed(null);
    setMessage("");
    setEditing(true);
  };

  const save = async (approve: boolean) => {
    setBusy(true);
    setError("");
    try {
      const r = await api.theorySave(path, source, approve);
      setData(r);
      setEditing(false);
      setMessage(
        r.added || r.removed
          ? `Đã lưu: ${r.added} khối mới hoặc đã sửa${r.removed ? `, bỏ ${r.removed} khối` : ""}${
              approve ? ", đã duyệt cả chủ đề" : admin ? "" : ". Khối mới ở dạng nháp, chờ admin duyệt"
            }.`
          : approve
            ? "Đã duyệt cả chủ đề."
            : "Không có thay đổi.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const approveAll = async () => {
    setBusy(true);
    try {
      const r = await api.theoryApprove(path);
      setMessage(`Đã duyệt ${r.approved} khối.`);
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const insert = (text: string) => {
    const v = view.current;
    if (!v) {
      setSource(source + (source.endsWith("\n") ? "" : "\n") + text);
      return;
    }
    const pos = v.state.selection.main.head;
    const line = v.state.doc.lineAt(pos);
    const at = line.text.trim() ? line.to : pos;
    const prefix = at > 0 && line.text.trim() ? "\n" : "";
    v.dispatch({ changes: { from: at, insert: prefix + text }, selection: { anchor: at + prefix.length + text.length } });
    v.focus();
  };

  const gotoLine = (n: number) => {
    const v = view.current;
    if (!v || n < 1 || n > v.state.doc.lines) return;
    const line = v.state.doc.line(n);
    v.dispatch({ selection: { anchor: line.from }, effects: EditorView.scrollIntoView(line.from, { y: "center" }) });
    v.focus();
  };

  const restore = async (id: number) => {
    try {
      const r = await api.theoryLog(id);
      startEdit(r.before);
      setMessage("Đã đưa bản trước vào ô soạn. Bấm Lưu để khôi phục.");
    } catch (e) {
      setError((e as Error).message);
    }
  };

  const head = (
    <div className="editor-head">
      <div>
        <div className="muted small">
          <Link to="/ly-thuyet">Lý thuyết</Link> › {t.grade}
          {t.chuong && <> › {t.chuong}</>}
        </div>
        <h2>{t.ten}</h2>
      </div>
      <span className="spacer" />
      {staff && !editing && (
        <>
          {admin && drafts > 0 && (
            <button disabled={busy} onClick={approveAll}>
              Duyệt {drafts} khối nháp
            </button>
          )}
          <button className="primary" onClick={() => startEdit()}>
            {data.blocks.length ? "Soạn / sửa" : "Soạn lý thuyết"}
          </button>
        </>
      )}
      {editing && (
        <>
          <button disabled={busy} onClick={() => setEditing(false)}>
            Huỷ
          </button>
          <button disabled={busy || !!parsed?.errors.length} onClick={() => save(false)}>
            {admin ? "Lưu" : "Lưu (nháp)"}
          </button>
          {admin && (
            <button className="primary" disabled={busy || !!parsed?.errors.length} onClick={() => save(true)}>
              Lưu và duyệt
            </button>
          )}
        </>
      )}
    </div>
  );

  if (editing) {
    const blocks = parsed?.sections.find((s) => s.topic.path === t.path)?.blocks ?? [];
    const others = parsed?.sections.filter((s) => s.topic.path !== t.path) ?? [];
    return (
      <div className="theory-topic">
        {head}
        {error && <div className="alert error">{error}</div>}
        {message && <div className="alert ok">{message}</div>}
        <div className="toolbar small">
          <span className="muted">Chèn:</span>
          {SNIPPETS.map((s) => (
            <button key={s.kind} className="small" onClick={() => insert(s.text)}>
              {s.label}
            </button>
          ))}
          {t.dang.length > 0 && (
            <select
              value=""
              onChange={(e) => {
                if (e.target.value) insert(`% @dang: ${e.target.value === "-" ? "" : e.target.value}\n`.replace(": \n", ":\n"));
              }}
            >
              <option value="">Chuyển dạng bài…</option>
              {t.dang.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
              <option value="-">(kiến thức chung)</option>
            </select>
          )}
        </div>
        <div className="editor-grid">
          <div className="editor-pane">
            <CodeMirror
              value={source}
              height="calc(100vh - 250px)"
              extensions={extensions}
              onChange={setSource}
              onCreateEditor={(v) => (view.current = v)}
            />
            <details className="hint">
              <summary>Cách soạn</summary>
              Mỗi khối nằm trong một môi trường: <code>dinhnghia</code>, <code>dinhly</code>, <code>congthuc</code>,{" "}
              <code>phuongphap</code>, <code>vidu</code> (lời giải trong <code>\begin&#123;loigiai&#125;</code>),{" "}
              <code>luuy</code>; tiêu đề trong ngoặc vuông ngay sau, ví dụ <code>\begin&#123;dinhly&#125;[Định lý ba đường vuông góc]</code>.
              Chữ nằm ngoài các môi trường là đoạn văn. <code>\cauhoi&#123;Q01173&#125;</code> lấy câu có sẵn trong ngân hàng
              làm ví dụ. Dòng <code>% @dang: tên dạng</code> chuyển các khối sau sang dạng bài đó (tên theo khung chương trình),
              <code>% @dang:</code> để trống là quay về kiến thức chung.
            </details>
            {t.noi_dung && (
              <details className="hint">
                <summary>Kiến thức trọng tâm theo khung chương trình</summary>
                <div style={{ whiteSpace: "pre-wrap" }}>{t.noi_dung}</div>
              </details>
            )}
          </div>
          <div className="preview-pane">
            {parsed?.errors.map((e, i) => (
              <div key={i} className="alert error">
                {e.line > 0 && (
                  <button className="link" onClick={() => gotoLine(e.line)}>
                    Dòng {e.line}
                  </button>
                )}{" "}
                {e.message}
              </div>
            ))}
            {parsed?.warnings.map((w, i) => (
              <div key={i} className="alert warn">
                <button className="link" onClick={() => gotoLine(w.line)}>
                  Dòng {w.line}
                </button>{" "}
                {w.message}
              </div>
            ))}
            {others.length > 0 && (
              <div className="alert error">
                Trang này chỉ soạn chủ đề {t.ten}. Bỏ dòng % @chude: {others[0].topic.names.join(" / ")}, hoặc dùng trang{" "}
                <Link to="/ly-thuyet/import">Import</Link>.
              </div>
            )}
            {parsed && !blocks.length && !parsed.errors.length && <p className="muted">Chưa có khối nào.</p>}
            <TheoryBlocks blocks={blocks} staff onLine={gotoLine} />
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="theory-topic">
      {head}
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert ok">{message}</div>}
      {t.dang.length > 0 && data.blocks.length > 0 && (
        <nav className="theory-toc small">
          <span className="muted">Dạng bài:</span>
          {t.dang.map((d) =>
            data.blocks.some((b) => b.dang === d) ? (
              <a key={d} href={`#dang-${d}`}>
                {d}
              </a>
            ) : (
              staff && (
                <span key={d} className="muted" title="Chưa có lý thuyết cho dạng này">
                  {d}
                </span>
              )
            ),
          )}
        </nav>
      )}
      {!data.blocks.length && (
        <div className="card">
          <p>{staff ? "Chủ đề này chưa có lý thuyết." : "Chủ đề này chưa có lý thuyết đã duyệt."}</p>
          {staff && t.noi_dung && (
            <>
              <p className="muted small">Kiến thức trọng tâm theo khung chương trình:</p>
              <div className="small" style={{ whiteSpace: "pre-wrap" }}>
                {t.noi_dung}
              </div>
            </>
          )}
        </div>
      )}
      <TheoryBlocks blocks={data.blocks} staff={staff} />
      {staff && data.logs && data.logs.length > 0 && (
        <details className="log-box">
          <summary>Lịch sử thay đổi ({data.logs.length})</summary>
          <table className="small">
            <tbody>
              {data.logs.map((lg) => (
                <tr key={lg.id}>
                  <td className="nowrap">{lg.at.replace("T", " ")}</td>
                  <td>{lg.username ?? ""}</td>
                  <td>{ACTION[lg.action] ?? lg.action}</td>
                  <td className="muted">{lg.detail}</td>
                  <td>
                    {lg.has_before && (
                      <button className="link small" onClick={() => restore(lg.id)}>
                        Mở bản trước khi sửa
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}
    </div>
  );
}
