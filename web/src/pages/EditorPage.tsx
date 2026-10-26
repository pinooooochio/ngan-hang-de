import { StreamLanguage } from "@codemirror/language";
import { stex } from "@codemirror/legacy-modes/mode/stex";
import CodeMirror, { EditorView } from "@uiw/react-codemirror";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, levelLabel, typeLabel, type Parsed, type Question, type Status } from "../api";
import QuestionView from "../components/QuestionView";

export default function EditorPage() {
  const { code } = useParams();
  const navigate = useNavigate();
  const [source, setSource] = useState("");
  const [question, setQuestion] = useState<Question | null>(null);
  const [parsed, setParsed] = useState<Parsed[] | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [pdfUrl, setPdfUrl] = useState("");
  const justSaved = useRef<string | null>(null);
  const extensions = useMemo(() => [StreamLanguage.define(stex), EditorView.lineWrapping], []);

  // Tải câu hỏi (hoặc mẫu câu mới)
  useEffect(() => {
    if (code && justSaved.current === code) {
      justSaved.current = null; // vừa lưu và đổi địa chỉ: dữ liệu đã có sẵn
      return;
    }
    setError("");
    setMessage("");
    setPdfUrl("");
    if (code) {
      api
        .getQuestion(code)
        .then((q) => {
          setQuestion(q);
          setSource(q.ex_source);
        })
        .catch((e) => setError(String(e.message)));
    } else {
      setQuestion(null);
      api.template().then((t) => setSource(t.source));
    }
  }, [code]);

  // Phân tích lại sau mỗi lần ngừng gõ 400 ms để xem trước
  useEffect(() => {
    if (!source) return;
    const timer = setTimeout(() => {
      api
        .parse(source)
        .then(setParsed)
        .catch((e) => setError(String(e.message)));
    }, 400);
    return () => clearTimeout(timer);
  }, [source]);

  const one = parsed && parsed.length === 1 ? parsed[0] : null;
  const canSave = !!one && one.errors.length === 0 && !busy;

  const save = async (status?: Status) => {
    setBusy(true);
    setError("");
    try {
      const q = code ? await api.updateQuestion(code, source, status) : await api.createQuestion(source, status);
      setQuestion(q);
      setSource(q.ex_source);
      setMessage(code ? "Đã lưu thay đổi." : `Đã tạo câu ${q.code}.`);
      if (q.code !== code) {
        justSaved.current = q.code;
        navigate(`/cau/${encodeURIComponent(q.code)}`, { replace: true });
      }
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    if (!code || !window.confirm(`Xoá câu ${code}? Không hoàn tác được.`)) return;
    try {
      await api.deleteQuestion(code);
      navigate("/");
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const previewPdf = async () => {
    setBusy(true);
    setError("");
    try {
      const blob = await api.previewPdf(source);
      if (pdfUrl) URL.revokeObjectURL(pdfUrl);
      setPdfUrl(URL.createObjectURL(blob));
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="editor-page">
      <div className="editor-head">
        <Link to="/">‹ Ngân hàng</Link>
        <h2>{code ? `Sửa câu ${code}` : "Soạn câu mới"}</h2>
        {question && (
          <span className={`badge ${question.status === "draft" ? "draft" : "approved"}`}>
            {question.status === "draft" ? "Nháp" : "Đã duyệt"} · phiên bản {question.version}
          </span>
        )}
        <span className="spacer" />
        <button disabled={!canSave} onClick={() => save()}>
          {code ? "Lưu" : "Lưu nháp"}
        </button>
        <button className="primary" disabled={!canSave} onClick={() => save("approved")}>
          Lưu và duyệt
        </button>
        <button disabled={!one || busy} onClick={previewPdf}>
          Xem PDF
        </button>
        {code && (
          <button className="danger" onClick={remove}>
            Xoá
          </button>
        )}
      </div>

      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert ok">{message}</div>}

      <div className="editor-grid">
        <div className="editor-pane">
          <CodeMirror value={source} height="calc(100vh - 210px)" extensions={extensions} onChange={setSource} />
          <p className="hint">
            Định dạng <code>ex_test</code>: <code>\choice</code> trắc nghiệm, <code>\choiceTF</code> đúng/sai,{" "}
            <code>\shortans</code> trả lời ngắn, chỉ <code>\loigiai</code> là tự luận. <code>\True</code> đánh dấu đáp án
            đúng, <code>\Pin</code> giữ cố định vị trí. Dòng <code>% @tags: … ; @level: … ; @id: …</code> ở trên cùng khai
            báo thẻ, mức độ, mã câu.
          </p>
        </div>
        <div className="preview-pane">
          {parsed && parsed.length !== 1 && (
            <div className="alert error">Cần đúng một khối \begin&#123;ex&#125;…\end&#123;ex&#125;, hiện có {parsed.length}.</div>
          )}
          {one && (
            <>
              <div className="meta">
                <span className="badge">{typeLabel(one.type)}</span>
                <span className={`badge level-${one.level ?? "none"}`}>{levelLabel(one.level)}</span>
                {one.code && <span className="badge">Mã: {one.code}</span>}
                {one.tags.map((t) => (
                  <span key={t.join("/")} className="tag">
                    {t.join(" › ")}
                  </span>
                ))}
              </div>
              {one.errors.map((e) => (
                <div key={e} className="alert error">
                  Lỗi: {e}
                </div>
              ))}
              {one.warnings.map((w) => (
                <div key={w} className="alert warn">
                  Cảnh báo: {w}
                </div>
              ))}
              <QuestionView
                type={one.type}
                stem={one.stem}
                choices={one.choices}
                shortAnswer={one.short_answer}
                solution={one.solution}
              />
            </>
          )}
          {pdfUrl && (
            <div className="pdf-frame">
              <div className="pdf-head">
                Bản PDF (XeLaTeX) <button className="link" onClick={() => setPdfUrl("")}>Đóng</button>
              </div>
              <iframe src={pdfUrl} title="Xem trước PDF" />
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
