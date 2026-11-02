import { StreamLanguage } from "@codemirror/language";
import { stex } from "@codemirror/legacy-modes/mode/stex";
import CodeMirror, { EditorView } from "@uiw/react-codemirror";
import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, levelLabel, typeLabel, type LogEntry, type Parsed, type Question, type Status } from "../api";
import ParamPreview from "../components/ParamPreview";
import { PICKED_KEY } from "./BulkVariantPage";
import QuestionView from "../components/QuestionView";
import { useAuth } from "../auth";
import { LogTable } from "./LogPage";

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
  const { me } = useAuth();
  const admin = me.role === "admin";
  const [log, setLog] = useState<LogEntry[] | null>(null);
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
  const [rerolling, setRerolling] = useState(false);
  // Câu tham số: phân tích lại để máy chủ bốc 3 bộ số mới
  const reroll = () => {
    setRerolling(true);
    api
      .parse(source)
      .then(setParsed)
      .catch((e) => setError(String(e.message)))
      .finally(() => setRerolling(false));
  };
  const canSave = !!one && one.errors.length === 0 && !busy;

  useEffect(() => {
    if (code) api.questionLog(code).then(setLog).catch(() => setLog(null));
    else setLog(null);
  }, [code, question?.version, question?.status]);

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

  const reload = async () => {
    if (code) setQuestion(await api.getQuestion(code));
  };

  const editLabel = async () => {
    if (!question?.variant_group) return;
    const label = window.prompt("Mô tả dạng bài của nhóm (ví dụ: Độ dài vectơ từ toạ độ)", question.variant_label ?? "");
    if (label === null) return;
    try {
      await api.labelGroup(question.variant_group, label);
      await reload();
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  // group = null: tách khỏi nhóm; asked: đã hỏi mã nhóm (bấm huỷ thì thôi)
  const moveGroup = async (group: string | null, asked = false) => {
    if (!code || (asked && !group)) return;
    if (!asked && !window.confirm(`Tách câu ${code} khỏi nhóm ${question?.variant_group}?`)) return;
    try {
      const r = await api.setQuestionGroup(code, group?.trim() || null);
      setMessage(r.variant_group ? `Đã chuyển câu vào nhóm ${r.variant_group}.` : "Đã tách câu khỏi nhóm.");
      await reload();
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
        <button className={admin ? "" : "primary"} disabled={!canSave} onClick={() => save()}>
          {code ? "Lưu" : "Lưu nháp"}
        </button>
        {admin && (
          <button className="primary" disabled={!canSave} onClick={() => save("approved")}>
            Lưu và duyệt
          </button>
        )}
        <button disabled={!one || busy} onClick={previewPdf}>
          Xem PDF
        </button>
        {code && question && !question.params && (
          <Link className="button" to={`/sinh/bien-the/${encodeURIComponent(code)}`} title="Soạn thêm câu cùng dạng, khác số liệu">
            Sinh biến thể
          </Link>
        )}
        {code && question && !question.params && question.status === "approved" && (question.type === "mcq" || question.type === "short") && (
          <button
            title="Claude viết lại câu này thành câu tham số (đổi số mỗi lần ra đề)"
            onClick={() => {
              try {
                sessionStorage.setItem(PICKED_KEY, JSON.stringify([code]));
              } catch {
                /* không lưu được thì trang chuyển sẽ không có câu đã chọn */
              }
              navigate("/sinh/bien-the?chon=1&thamso=1");
            }}
          >
            Chuyển thành câu tham số
          </button>
        )}
        {code && admin && (
          <button className="danger" onClick={remove}>
            Xoá
          </button>
        )}
      </div>

      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert ok">{message}</div>}
      {question?.check_note && (
        <div className="alert error">
          Cảnh báo lúc sinh: {question.check_note}. Sửa và lưu lại câu thì cảnh báo này tự mất.
        </div>
      )}
      {question && code && (
        <div className="variant-strip">
          {question.variant_group ? (
            <>
              <span className="muted small">
                Nhóm biến thể <b>{question.variant_group}</b>
                {question.variant_label && <> · {question.variant_label}</>} ({question.variants?.length ?? 1} câu
                {question.variant_origin && question.variant_origin !== code && <>, câu gốc {question.variant_origin}</>}):
              </span>
              {question.variants!.map((v) =>
                v.code === code ? (
                  <span key={v.code} className="tag current">
                    {v.code}
                  </span>
                ) : (
                  <Link key={v.code} to={`/cau/${encodeURIComponent(v.code)}`} className={`tag ${v.status === "draft" ? "is-draft" : ""}`}>
                    {v.code}
                    {v.status === "draft" && " (nháp)"}
                  </Link>
                ),
              )}
              <Link className="small" to={`/?nhom=${encodeURIComponent(question.variant_group)}`}>
                Xem cả nhóm
              </Link>
              <button className="link small" onClick={editLabel}>
                {question.variant_label ? "Sửa mô tả dạng" : "Thêm mô tả dạng"}
              </button>
              <button className="link small" onClick={() => moveGroup(null)} title="Câu khác dạng với nhóm: để câu đứng riêng">
                Tách khỏi nhóm
              </button>
            </>
          ) : (
            <span className="muted small">Câu chưa thuộc nhóm biến thể nào.</span>
          )}
          <button className="link small" onClick={() => moveGroup(window.prompt("Mã nhóm muốn chuyển câu này vào (ví dụ N-000012):") || null, true)}>
            {question.variant_group ? "Chuyển sang nhóm khác…" : "Đưa vào nhóm…"}
          </button>
        </div>
      )}
      {!admin && !code && <p className="hint">Câu mới lưu ở dạng nháp, admin duyệt rồi mới dùng để ghép đề.</p>}

      <div className="editor-grid">
        <div className="editor-pane">
          <CodeMirror value={source} height="calc(100vh - 210px)" extensions={extensions} onChange={setSource} />
          <p className="hint">
            Định dạng <code>ex_test</code>: <code>\choice</code> trắc nghiệm, <code>\choiceTF</code> đúng/sai,{" "}
            <code>\shortans</code> trả lời ngắn, chỉ <code>\loigiai</code> là tự luận. <code>\True</code> đánh dấu đáp án
            đúng, <code>\Pin</code> giữ cố định vị trí. Dòng <code>% @tags: … ; @level: … ; @id: …</code> ở trên cùng khai
            báo thẻ, mức độ, mã câu.
          </p>
          <details className="hint">
            <summary>Câu tham số (đổi số mỗi lần ra đề)</summary>
            Thêm các dòng ngay dưới dòng <code>@tags</code>: <code>% @thamso: a = 1..6; b = -5..5; k = 2..10 buoc 2; r = {"{1/2, 3}"}</code>{" "}
            (miền giá trị), <code>% @dieukien: b != 0; a != b</code> (loại bộ số), <code>% @tinh: d = 2*a + b</code>{" "}
            (đại lượng tính từ tham số). Trong đề, lời giải và các phương án viết <code>{"{{a}}"}</code> hoặc biểu thức{" "}
            <code>{"{{2*a - b}}"}</code>; máy tính chính xác bằng phân số. Cách in: <code>{"{{b:+}}"}</code> có dấu,{" "}
            <code>{"{{a:c}}"}</code> hệ số (bỏ số 1), <code>{"{{b:c+}}"}</code> hệ số kèm dấu, <code>{"{{b:()}}"}</code> âm thì
            đóng ngoặc, <code>{"{{I:.1}}"}</code> làm tròn 1 chữ số thập phân. Hàm: sqrt, abs, gcd, lcm, comb, perm,
            factorial, round, ln, log, exp, sin, cos, tan.
          </details>
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
              {one.param_report ? (
                <ParamPreview report={one.param_report} type={one.type} busy={rerolling} onReroll={reroll} />
              ) : (
                <QuestionView
                  type={one.type}
                  stem={one.stem}
                  choices={one.choices}
                  shortAnswer={one.short_answer}
                  solution={one.solution}
                />
              )}
            </>
          )}
          {code && log && (
            <details className="log-box">
              <summary>Lịch sử thay đổi ({log.length})</summary>
              <LogTable items={log} />
            </details>
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
