import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, levelLabel, typeLabel, type Curriculum, type GenBatchDetail, type GenItem, type GenParams, type Question } from "../api";
import QuestionView from "../components/QuestionView";
import { bankLink } from "../components/GenHistory";
import { GenItems } from "./GeneratePage";

/** Sinh biến thể của một câu: cùng dạng, cùng mức độ, chỉ đổi số liệu. Câu mới vào cùng nhóm biến thể. */
export default function VariantPage() {
  const { code = "" } = useParams();
  const [q, setQ] = useState<Question | null>(null);
  const [cur, setCur] = useState<Curriculum | null>(null);
  const [count, setCount] = useState(5);
  const [params, setParams] = useState<GenParams | null>(null);
  const [prompt, setPrompt] = useState("");
  const [copied, setCopied] = useState(false);
  const [output, setOutput] = useState("");
  const [checked, setChecked] = useState<GenItem[] | null>(null);
  const [saved, setSaved] = useState<GenBatchDetail | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.getQuestion(code).then(setQ).catch((e) => setError(String(e.message)));
    api.genCurriculum().then(setCur).catch(() => setCur(null));
  }, [code]);

  // Tham số (lớp, chủ đề, dạng, có hình) lấy từ thẻ của câu gốc
  useEffect(() => {
    setPrompt("");
    setChecked(null);
    api
      .variantParams(code, count)
      .then((p) => {
        setParams(p);
        setError("");
      })
      .catch((e) => setError(String(e.message)));
  }, [code, count]);

  // Lần sinh bằng API chạy nền: tải lại đến khi xong
  useEffect(() => {
    if (!saved || (saved.status !== "pending" && saved.status !== "running")) return;
    const t = setInterval(() => api.genBatch(saved.id).then(setSaved).catch(() => undefined), 3000);
    return () => clearInterval(t);
  }, [saved]);

  const run = async <T,>(f: () => Promise<T>) => {
    setBusy(true);
    setError("");
    try {
      return await f();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const generate = () => params && run(async () => setSaved(await api.genCreate(params, "api")));
  const getPrompt = () => params && run(async () => setPrompt((await api.genPrompt(params)).combined));
  const check = () => params && run(async () => setChecked(await api.genCheck(params, output)));
  const saveManual = () =>
    params &&
    run(async () => {
      setSaved(await api.genCreate(params, "manual", output));
      setPrompt("");
      setOutput("");
      setChecked(null);
    });
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
    } catch {
      setError("Trình duyệt không cho chép tự động, hãy bôi đen ô prompt rồi chép.");
    }
  };

  const nNew = checked?.filter((x) => x.state === "new").length ?? 0;
  const running = saved && (saved.status === "pending" || saved.status === "running");
  const group = q?.variant_group ?? code;

  return (
    <div className="generate">
      <div className="editor-head">
        <Link to={`/cau/${encodeURIComponent(code)}`}>‹ Câu {code}</Link>
        <h2>Sinh biến thể</h2>
        <span className="spacer" />
        {(q?.n_variants ?? 1) > 1 && (
          <Link className="button" to={`/?nhom=${encodeURIComponent(group)}`}>
            Xem nhóm ({q?.n_variants} câu)
          </Link>
        )}
      </div>
      <p className="hint">
        Claude soạn các câu cùng dạng, cùng mức độ và cách hỏi với câu gốc, chỉ đổi số liệu; lời giải được giải lại theo số
        mới và mỗi câu kèm dòng <code>@kiemtra</code> để máy chủ tính lại đáp án. Câu mới vào ngân hàng ở dạng nháp, cùng
        nhóm biến thể với câu gốc. Khi ghép đề, mỗi đề chỉ lấy một câu của một nhóm.
      </p>

      {q && (
        <div className="card variant-source">
          <div className="card-head">
            <b>Câu gốc {q.code}</b>
            <span className={`badge level-${q.level ?? "none"}`}>{levelLabel(q.level)}</span>
            <span className="badge">{typeLabel(q.type)}</span>
            {q.tags.map((t) => (
              <span key={t.path} className="tag">
                {t.names.join(" › ")}
              </span>
            ))}
          </div>
          <QuestionView type={q.type} stem={q.stem} choices={q.choices} shortAnswer={q.short_answer} solution={q.solution} />
        </div>
      )}

      {error && <div className="alert error">{error}</div>}

      <div className="toolbar">
        <label className="inline">
          Số biến thể{" "}
          <input
            type="number"
            min={1}
            max={cur?.max_count ?? 20}
            value={count}
            onChange={(e) => setCount(Math.max(1, Math.min(cur?.max_count ?? 20, Number(e.target.value) || 1)))}
            style={{ width: "4.5em" }}
          />
        </label>
        {params && (
          <span className="muted small">
            Xếp vào: {params.grade} › {params.topic}
            {params.dang && <> › {params.dang}</>}
            {params.figure && <> · có hình vẽ</>}
          </span>
        )}
      </div>
      <div className="toolbar">
        <button className="primary" disabled={busy || !params || !cur?.api || !!running} onClick={generate}>
          Sinh {count} biến thể bằng Claude
        </button>
        <button disabled={busy || !params} onClick={getPrompt}>
          Lấy prompt để tự dán vào Claude
        </button>
        {cur && !cur.api && (
          <span className="muted small">Máy chủ chưa có ANTHROPIC_API_KEY nên chưa sinh trực tiếp được; dùng cách lấy prompt.</span>
        )}
      </div>

      {saved && (
        <div className={`alert ${saved.status === "failed" ? "error" : running ? "warn" : "ok"}`}>
          {running ? (
            <>Claude đang soạn biến thể, trang tự cập nhật khi xong.</>
          ) : saved.status === "failed" ? (
            <>Lần sinh lỗi: {saved.error}</>
          ) : (
            <>
              Đã thêm {saved.n_added} biến thể vào nhóm ({saved.n_duplicate} trùng, {saved.n_error} lỗi).{" "}
              {saved.n_added > 0 && <Link to={bankLink(saved.source)}>Duyệt các câu mới</Link>}{" "}
              · <Link to={`/sinh/${saved.id}`}>Chi tiết lần sinh #{saved.id}</Link>
            </>
          )}
        </div>
      )}
      {saved && saved.items.length > 0 && <GenItems items={saved.items} />}

      {prompt && (
        <div className="manual">
          <div className="manual-step">
            <b>1.</b> Chép prompt này, dán vào một cuộc trò chuyện mới với Claude.{" "}
            <button onClick={copy}>{copied ? "Đã chép" : "Chép prompt"}</button>
          </div>
          <textarea className="mono" rows={8} readOnly value={prompt} />
          <div className="manual-step">
            <b>2.</b> Dán toàn bộ câu trả lời của Claude vào đây rồi bấm Kiểm tra.
          </div>
          <textarea
            className="mono"
            rows={8}
            value={output}
            onChange={(e) => {
              setOutput(e.target.value);
              setChecked(null);
            }}
            placeholder="% @tags: ... \begin{ex} ... \end{ex}"
          />
          <div className="toolbar">
            <button disabled={busy || !output.trim()} onClick={check}>
              Kiểm tra
            </button>
            <button className="primary" disabled={busy || !checked || nNew === 0} onClick={saveManual}>
              Lưu {nNew} biến thể vào ngân hàng (nháp)
            </button>
          </div>
          {checked && <GenItems items={checked} />}
        </div>
      )}
    </div>
  );
}
