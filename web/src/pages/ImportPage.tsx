import { useState } from "react";
import { Link } from "react-router-dom";
import { api, LEVELS, levelLabel, typeLabel, type ImportPreviewItem, type Level, type Status } from "../api";
import QuestionView from "../components/QuestionView";

const STATE_LABEL = { new: "Mới", duplicate: "Trùng", error: "Lỗi" };

export default function ImportPage() {
  const [source, setSource] = useState("");
  const [filename, setFilename] = useState<string>();
  const [items, setItems] = useState<ImportPreviewItem[] | null>(null);
  const [chosen, setChosen] = useState<Set<number>>(new Set());
  const [extraTag, setExtraTag] = useState("");
  const [defaultLevel, setDefaultLevel] = useState<Level | "">("");
  const [status, setStatus] = useState<Status>("approved");
  const [error, setError] = useState("");
  const [result, setResult] = useState<{ added: string[]; duplicates: number; failed: number } | null>(null);
  const [busy, setBusy] = useState(false);

  const readFile = async (file: File | undefined) => {
    if (!file) return;
    setSource(await file.text());
    setFilename(file.name);
    setItems(null);
    setResult(null);
  };

  const check = async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const list = await api.importPreview(source);
      setItems(list);
      setChosen(new Set(list.filter((i) => i.state === "new").map((i) => i.index)));
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.importCommit({
        source,
        filename,
        only: [...chosen],
        extra_tag: extraTag || undefined,
        default_level: defaultLevel || undefined,
        status,
      });
      setResult(r);
      setItems(null);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const toggle = (i: number) => {
    const next = new Set(chosen);
    if (next.has(i)) next.delete(i);
    else next.add(i);
    setChosen(next);
  };

  const counts = items
    ? { new: items.filter((i) => i.state === "new").length, duplicate: items.filter((i) => i.state === "duplicate").length, error: items.filter((i) => i.state === "error").length }
    : null;

  return (
    <div className="import-page">
      <h2>Import câu hỏi</h2>
      <p className="hint">
        Dán nội dung file <code>.tex</code> hoặc chọn file. Mỗi câu nằm trong <code>\begin&#123;ex&#125;…\end&#123;ex&#125;</code>.
        Hệ thống kiểm tra từng câu trước, chỉ lưu những câu anh/chị chọn.
      </p>
      <div className="import-input">
        <input type="file" accept=".tex,.txt" onChange={(e) => readFile(e.target.files?.[0])} />
        <textarea
          value={source}
          onChange={(e) => {
            setSource(e.target.value);
            setItems(null);
          }}
          placeholder="\begin{ex} ... \end{ex}"
          rows={10}
        />
        <button className="primary" disabled={!source.trim() || busy} onClick={check}>
          Kiểm tra
        </button>
      </div>

      {error && <div className="alert error">{error}</div>}
      {result && (
        <div className="alert ok">
          Đã lưu {result.added.length} câu
          {result.duplicates > 0 && `, bỏ qua ${result.duplicates} câu trùng`}
          {result.failed > 0 && `, ${result.failed} câu lỗi`}. <Link to="/">Xem trong ngân hàng</Link>
        </div>
      )}

      {items && counts && (
        <>
          <div className="import-summary">
            Tìm thấy {items.length} câu: <b>{counts.new}</b> mới, <b>{counts.duplicate}</b> trùng, <b>{counts.error}</b> lỗi.
          </div>
          <div className="bulkbar">
            <input placeholder="Gắn thêm thẻ cho mọi câu, ví dụ: Lớp 11 / Lượng giác" value={extraTag} onChange={(e) => setExtraTag(e.target.value)} />
            <select value={defaultLevel} onChange={(e) => setDefaultLevel(e.target.value as Level | "")}>
              <option value="">Mức độ cho câu chưa có…</option>
              {LEVELS.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
            <select value={status} onChange={(e) => setStatus(e.target.value as Status)}>
              <option value="approved">Lưu là đã duyệt</option>
              <option value="draft">Lưu là nháp</option>
            </select>
            <button className="primary" disabled={chosen.size === 0 || busy} onClick={commit}>
              Lưu {chosen.size} câu
            </button>
          </div>
          {items.map((it) => (
            <article key={it.index} className={`card state-${it.state}`}>
              <div className="card-head">
                <input type="checkbox" disabled={it.state !== "new"} checked={chosen.has(it.index)} onChange={() => toggle(it.index)} />
                <span className={`badge state-${it.state}`}>{STATE_LABEL[it.state]}</span>
                <span className="muted">Dòng {it.line}</span>
                {it.code && <span className="code">{it.code}</span>}
                <span className={`badge level-${it.level ?? "none"}`}>{levelLabel(it.level)}</span>
                <span className="badge">{typeLabel(it.type)}</span>
                <span className="tags">
                  {it.tags.map((t) => (
                    <span key={t.join("/")} className="tag">
                      {t.join(" › ")}
                    </span>
                  ))}
                </span>
              </div>
              {it.duplicate_of && <div className="alert warn">Trùng với {it.duplicate_of}</div>}
              {it.errors.map((e) => (
                <div key={e} className="alert error">
                  Lỗi: {e}
                </div>
              ))}
              {it.warnings.map((w) => (
                <div key={w} className="alert warn">
                  Cảnh báo: {w}
                </div>
              ))}
              <QuestionView type={it.type} stem={it.stem} choices={it.choices} shortAnswer={it.short_answer} solution={it.solution} />
            </article>
          ))}
        </>
      )}
    </div>
  );
}
