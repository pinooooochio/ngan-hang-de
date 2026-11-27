import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type TheoryParsed, type TheorySaveResult, type TheoryTopicSummary } from "../api";
import { useAuth } from "../auth";
import TheoryBlocks from "../components/TheoryBlocks";

type Grade = { ten: string; slug: string; topics: TheoryTopicSummary[] };

/** Import lý thuyết từ file .tex: tách khối, xem trước theo chủ đề, chọn chủ đề cần lưu. */
export default function TheoryImportPage() {
  const { me } = useAuth();
  const admin = me.role === "admin";
  const [grades, setGrades] = useState<Grade[]>([]);
  const [source, setSource] = useState("");
  const [filename, setFilename] = useState<string>();
  const [path, setPath] = useState("");
  const [mode, setMode] = useState<"append" | "replace">("append");
  const [approve, setApprove] = useState(false);
  const [preview, setPreview] = useState<TheoryParsed | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [result, setResult] = useState<({ path: string; ten: string } & TheorySaveResult)[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    api.theoryTopics().then((r) => setGrades(r.grades)).catch((e: Error) => setError(e.message));
  }, []);

  const reset = () => {
    setPreview(null);
    setResult(null);
  };

  const readFile = async (file: File | undefined) => {
    if (!file) return;
    setSource(await file.text());
    setFilename(file.name);
    reset();
  };

  const check = async () => {
    setBusy(true);
    setError("");
    setResult(null);
    try {
      const p = await api.theoryImportPreview(source, path || undefined);
      setPreview(p);
      setChosen(new Set(p.sections.map((s) => s.topic.path)));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const commit = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.theoryImportCommit({
        source,
        path: path || undefined,
        filename,
        mode,
        approve,
        only: [...chosen],
      });
      setResult(r.topics);
      setPreview(null);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const toggle = (p: string) => {
    const next = new Set(chosen);
    if (next.has(p)) next.delete(p);
    else next.add(p);
    setChosen(next);
  };

  return (
    <div className="import-page">
      <h2>Import lý thuyết</h2>
      <p className="hint">
        Dán nội dung hoặc chọn file <code>.tex</code>. Dòng <code>% @chude: Lớp 11 / Góc trong không gian</code> cho biết
        các khối sau thuộc chủ đề nào (một file có thể chứa nhiều chủ đề), hoặc chọn chủ đề mặc định bên dưới. Các môi
        trường hay gặp như <code>definition</code>, <code>theorem</code>, <code>example</code>, <code>note</code>,{" "}
        <code>dn</code>, <code>dl</code>, <code>vd</code> được đổi sang khối tương ứng; <code>\section</code>,{" "}
        <code>\subsection</code> trùng tên dạng bài thì chuyển sang dạng đó. Phần đầu file (<code>\documentclass</code> …{" "}
        <code>\begin&#123;document&#125;</code>) được bỏ qua.
      </p>
      <div className="import-input">
        <input type="file" accept=".tex,.txt" onChange={(e) => readFile(e.target.files?.[0])} />
        <textarea
          value={source}
          onChange={(e) => {
            setSource(e.target.value);
            reset();
          }}
          placeholder={"% @chude: Lớp 11 / Góc trong không gian\n\\begin{dinhnghia}[...]\n...\n\\end{dinhnghia}"}
          rows={12}
        />
        <div className="toolbar">
          <label>
            Chủ đề mặc định{" "}
            <select
              value={path}
              onChange={(e) => {
                setPath(e.target.value);
                reset();
              }}
            >
              <option value="">(theo dòng % @chude trong file)</option>
              {grades.map((g) => (
                <optgroup key={g.slug} label={g.ten}>
                  {g.topics.map((t) => (
                    <option key={t.path} value={t.path}>
                      {t.chuong ? `${t.chuong} › ` : ""}
                      {t.ten}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
          <button className="primary" disabled={!source.trim() || busy} onClick={check}>
            Kiểm tra
          </button>
        </div>
      </div>
      {error && <div className="alert error">{error}</div>}

      {result && (
        <div className="alert ok">
          Đã import:
          <ul>
            {result.map((r) => (
              <li key={r.path}>
                <Link to={`/ly-thuyet/cd/${r.path}`}>{r.ten}</Link>: {r.added} khối mới
                {r.kept > 0 && <>, {r.kept} khối giữ nguyên</>}
                {r.removed > 0 && <>, bỏ {r.removed} khối cũ</>}
              </li>
            ))}
          </ul>
        </div>
      )}

      {preview && (
        <>
          {preview.errors.map((e, i) => (
            <div key={i} className="alert error">
              {e.line > 0 && <>Dòng {e.line}: </>}
              {e.message}
            </div>
          ))}
          {preview.warnings.map((w, i) => (
            <div key={i} className="alert warn">
              Dòng {w.line}: {w.message}
            </div>
          ))}
          {!preview.errors.length && !preview.sections.length && <p className="muted">Không tìm thấy khối lý thuyết nào.</p>}
          {preview.sections.length > 0 && (
            <div className="toolbar">
              <label>
                <input type="radio" checked={mode === "append"} onChange={() => setMode("append")} /> Thêm vào sau lý thuyết
                đang có
              </label>
              <label>
                <input type="radio" checked={mode === "replace"} onChange={() => setMode("replace")} /> Thay cả lý thuyết
                của chủ đề
              </label>
              {admin ? (
                <label>
                  <input type="checkbox" checked={approve} onChange={(e) => setApprove(e.target.checked)} /> Duyệt luôn
                </label>
              ) : (
                <span className="muted small">Lý thuyết import vào dạng nháp, chờ admin duyệt.</span>
              )}
              <span className="spacer" />
              <button
                className="primary"
                disabled={busy || !!preview.errors.length || !chosen.size}
                onClick={commit}
              >
                Import {chosen.size} chủ đề
              </button>
            </div>
          )}
          {preview.sections.map((s) => {
            const kinds: Record<string, number> = {};
            for (const b of s.blocks) kinds[b.kind_name] = (kinds[b.kind_name] ?? 0) + 1;
            return (
              <details key={s.topic.path} className="card">
                <summary>
                  <label onClick={(e) => e.stopPropagation()}>
                    <input type="checkbox" checked={chosen.has(s.topic.path)} onChange={() => toggle(s.topic.path)} />{" "}
                    <b>{s.topic.names.join(" › ")}</b>
                  </label>{" "}
                  <span className="muted small">
                    {s.blocks.length} khối ({Object.entries(kinds).map(([k, n]) => `${n} ${k.toLowerCase()}`).join(", ")})
                    {!!s.existing && (
                      <>
                        {" "}
                        · đang có {s.existing} khối
                        {mode === "replace" && <b> sẽ bị thay</b>}
                      </>
                    )}
                  </span>
                </summary>
                <TheoryBlocks blocks={s.blocks} staff />
              </details>
            );
          })}
        </>
      )}
    </div>
  );
}
