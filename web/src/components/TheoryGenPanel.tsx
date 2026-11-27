import { useEffect, useState } from "react";
import { api, type TheoryBlock, type TheoryGenBatch, type TheoryParsed, type TheoryTopicInfo } from "../api";
import TheoryBlocks from "./TheoryBlocks";

const STATUS = { pending: "Đang chờ", running: "Claude đang soạn…", done: "Xong", failed: "Lỗi" };

/** Danh sách các lần Claude soạn lý thuyết; tự cập nhật khi còn lần đang chạy. */
export function TheoryGenList({ path, onDone, refresh = 0 }: { path?: string; onDone?: () => void; refresh?: number }) {
  const [rows, setRows] = useState<TheoryGenBatch[]>([]);
  const [tick, setTick] = useState(0);
  const running = rows.some((b) => b.status === "pending" || b.status === "running");

  useEffect(() => {
    let alive = true;
    api
      .theoryGenList(path)
      .then((r) => {
        if (!alive) return;
        setRows((old) => {
          const wasRunning = new Set(old.filter((b) => b.status === "pending" || b.status === "running").map((b) => b.id));
          if (r.batches.some((b) => wasRunning.has(b.id) && b.status === "done")) onDone?.();
          return r.batches;
        });
      })
      .catch(() => undefined);
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [path, tick, refresh]);

  useEffect(() => {
    if (!running) return;
    const t = setTimeout(() => setTick((x) => x + 1), 3000);
    return () => clearTimeout(t);
  }, [running, tick]);

  if (!rows.length) return null;
  return (
    <details className="log-box" open={running}>
      <summary>
        Các lần Claude soạn ({rows.length}){running && <span className="muted small"> · đang chạy</span>}
      </summary>
      <table className="small">
        <tbody>
          {rows.map((b) => (
            <tr key={b.id}>
              <td className="nowrap">{b.created_at.replace("T", " ")}</td>
              <td>{b.source}</td>
              {!path && <td>{b.topic}</td>}
              <td className="muted">
                {[b.params.general && "kiến thức chung", b.params.dang.length && `${b.params.dang.length} dạng`]
                  .filter(Boolean)
                  .join(", ")}
              </td>
              <td>{b.mode === "api" ? "API" : "dán tay"}</td>
              <td>{b.username ?? ""}</td>
              <td className={b.status === "failed" ? "error-text" : ""}>
                {STATUS[b.status]}
                {b.status === "done" && <> · {b.added} khối mới</>}
                {b.error && <> · {b.error}</>}
              </td>
              <td>
                {b.status === "failed" && b.mode === "api" && (
                  <button className="link small" onClick={() => api.theoryGenRetry(b.id).then(() => setTick((x) => x + 1))}>
                    Chạy lại
                  </button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

interface Props {
  topic: TheoryTopicInfo;
  blocks: TheoryBlock[];
  onClose: () => void;
  /** Đã thêm lý thuyết (dán kết quả) hoặc đã gửi Claude. */
  onSaved: (message: string) => void;
}

/** Chọn phần cần soạn của một chủ đề, rồi gửi Claude (API) hoặc lấy prompt để dán vào Claude. */
export default function TheoryGenPanel({ topic, blocks, onClose, onSaved }: Props) {
  const has = new Set(blocks.map((b) => b.dang ?? ""));
  const [general, setGeneral] = useState(!has.has(""));
  const [dang, setDang] = useState<Set<string>>(new Set(topic.dang.filter((d) => !has.has(d))));
  const [examples, setExamples] = useState(2);
  const [note, setNote] = useState("");
  const [apiOk, setApiOk] = useState<boolean | null>(null);
  const [prompt, setPrompt] = useState("");
  const [output, setOutput] = useState("");
  const [preview, setPreview] = useState<TheoryParsed | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    api.theoryGenList(topic.path).then((r) => setApiOk(r.api)).catch(() => setApiOk(false));
  }, [topic.path]);

  const body = { paths: [topic.path], general, dang: [...dang], examples, note };
  const nothing = !general && !dang.size;

  const toggle = (d: string) => {
    const next = new Set(dang);
    if (next.has(d)) next.delete(d);
    else next.add(d);
    setDang(next);
    setPrompt("");
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const sendApi = () =>
    run(async () => {
      await api.theoryGen({ ...body, mode: "api" });
      onSaved("Đã gửi Claude soạn. Lý thuyết mới sẽ hiện ở dạng nháp khi xong (thường 1–3 phút).");
    });

  const getPrompt = () =>
    run(async () => {
      const r = await api.theoryGenPrompt(body);
      setPrompt(r.combined);
      setCopied(false);
    });

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
    } catch {
      setError("Trình duyệt không cho chép tự động, hãy bôi đen ô prompt rồi chép.");
    }
  };

  const check = () =>
    run(async () => {
      setPreview(await api.theoryParse(output.replace(/^\s*```.*$/gm, ""), topic.path));
    });

  const save = () =>
    run(async () => {
      const [b] = await api.theoryGen({ ...body, mode: "manual", output });
      if (b.status === "failed") throw new Error(b.error ?? "kết quả không đúng định dạng");
      onSaved(`Đã thêm ${b.added} khối lý thuyết (${b.source}) ở dạng nháp.`);
    });

  const previewBlocks = preview?.sections.find((s) => s.topic.path === topic.path)?.blocks ?? [];

  return (
    <div className="card theory-gen">
      <div className="toolbar">
        <b>Claude soạn lý thuyết</b>
        <span className="spacer" />
        <button className="link" onClick={onClose}>
          Đóng
        </button>
      </div>
      <div className="theory-gen-parts">
        <label>
          <input type="checkbox" checked={general} onChange={(e) => (setGeneral(e.target.checked), setPrompt(""))} /> Kiến thức
          chung (định nghĩa, định lý, công thức){has.has("") && <span className="muted small"> · đã có</span>}
        </label>
        {topic.dang.map((d) => (
          <label key={d}>
            <input type="checkbox" checked={dang.has(d)} onChange={() => toggle(d)} /> Dạng: {d}
            {has.has(d) && <span className="muted small"> · đã có</span>}
          </label>
        ))}
      </div>
      <div className="toolbar">
        <label>
          Số ví dụ mỗi dạng{" "}
          <select value={examples} onChange={(e) => (setExamples(Number(e.target.value)), setPrompt(""))}>
            {[0, 1, 2, 3, 4].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
        </label>
        <input
          className="grow"
          placeholder="Yêu cầu thêm (không bắt buộc), ví dụ: ví dụ dùng hình lập phương, có bảng tóm tắt công thức"
          value={note}
          onChange={(e) => (setNote(e.target.value), setPrompt(""))}
        />
      </div>
      <p className="hint">
        Claude chỉ thêm khối mới vào sau phần đã có (không sửa phần đã có), các khối mới ở dạng nháp để bạn sửa và
        duyệt.
      </p>
      {error && <div className="alert error">{error}</div>}
      <div className="toolbar">
        {apiOk && (
          <button className="primary" disabled={busy || nothing} onClick={sendApi}>
            Gửi Claude soạn
          </button>
        )}
        <button disabled={busy || nothing} onClick={getPrompt}>
          {apiOk ? "Hoặc lấy prompt để tự dán" : "Lấy prompt"}
        </button>
        {apiOk === false && <span className="muted small">Máy chủ chưa có ANTHROPIC_API_KEY nên chỉ dùng được cách chép prompt.</span>}
      </div>
      {prompt && (
        <div className="theory-gen-manual">
          <div className="toolbar small">
            <b>1. Chép prompt, dán vào Claude</b>
            <button className="small" onClick={copy}>
              {copied ? "Đã chép" : "Chép prompt"}
            </button>
          </div>
          <textarea readOnly rows={6} value={prompt} />
          <div className="toolbar small">
            <b>2. Dán kết quả Claude trả lời</b>
          </div>
          <textarea
            rows={8}
            value={output}
            onChange={(e) => {
              setOutput(e.target.value);
              setPreview(null);
            }}
            placeholder={"\\begin{dinhnghia}[...]\n...\n% @dang: ...\n\\begin{phuongphap} ..."}
          />
          <div className="toolbar">
            <button disabled={busy || !output.trim()} onClick={check}>
              Kiểm tra
            </button>
            <button className="primary" disabled={busy || !preview || !!preview.errors.length || !previewBlocks.length} onClick={save}>
              Thêm {previewBlocks.length || ""} khối vào nháp
            </button>
          </div>
          {preview?.errors.map((e, i) => (
            <div key={i} className="alert error">
              {e.line > 0 && <>Dòng {e.line}: </>}
              {e.message}
            </div>
          ))}
          {preview?.warnings.map((w, i) => (
            <div key={i} className="alert warn">
              Dòng {w.line}: {w.message}
            </div>
          ))}
          {preview && <TheoryBlocks blocks={previewBlocks} staff />}
        </div>
      )}
    </div>
  );
}
