import { Fragment, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import {
  api,
  LEVELS,
  TYPES,
  levelLabel,
  typeLabel,
  type CoverageTopic,
  type Curriculum,
  type GenBatch,
  type GenItem,
  type GenParams,
  type Level,
  type QType,
} from "../api";
import GenHistory from "../components/GenHistory";
import Tex from "../components/Tex";

const TARGET_KEY = "nhd.gen.target";

function readTarget() {
  try {
    return Number(localStorage.getItem(TARGET_KEY)) || 20;
  } catch {
    return 20;
  }
}

export { STATUS_LABEL, bankLink } from "../components/GenHistory";

export default function GeneratePage() {
  const navigate = useNavigate();
  const [cur, setCur] = useState<Curriculum | null>(null);
  const [grade, setGrade] = useState("Lớp 12");
  const [topics, setTopics] = useState<CoverageTopic[]>([]);
  const [target, setTarget] = useState(readTarget);
  const [params, setParams] = useState<GenParams>({ grade: "Lớp 12", topic: "", level: "NB", type: "mcq", count: 10 });
  const [batches, setBatches] = useState<GenBatch[]>([]);
  const [prompt, setPrompt] = useState("");
  const [output, setOutput] = useState("");
  const [checked, setChecked] = useState<GenItem[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [focusTopic, setFocusTopic] = useState<string>();

  useEffect(() => {
    api.genCurriculum().then(setCur);
    api.genBatches().then(setBatches);
  }, []);

  useEffect(() => {
    api.genCoverage(grade).then((r) => setTopics(r.topics));
    setParams((p) => ({ ...p, grade, topic: p.grade === grade ? p.topic : "", dang: undefined }));
  }, [grade]);

  // Còn lần sinh đang chạy thì hỏi lại sau 3 giây
  const running = batches.some((b) => b.status === "pending" || b.status === "running");
  useEffect(() => {
    if (!running) return;
    const t = setInterval(() => {
      api.genBatches().then(setBatches);
      api.genCoverage(grade).then((r) => setTopics(r.topics));
    }, 3000);
    return () => clearInterval(t);
  }, [running, grade]);

  const update = (patch: Partial<GenParams>) => {
    setParams({ ...params, ...patch });
    setPrompt("");
    setChecked(null);
  };

  const saveTarget = (n: number) => {
    setTarget(n);
    try {
      localStorage.setItem(TARGET_KEY, String(n));
    } catch {
      /* không lưu được thì thôi */
    }
  };

  const pickCell = (t: CoverageTopic, level: Level) => {
    update({ topic: t.name, level, dang: undefined });
    setFocusTopic(t.name);
    document.getElementById("gen-form")?.scrollIntoView({ behavior: "smooth" });
  };

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError("");
    try {
      await fn();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  const generate = () =>
    run(async () => {
      const b = await api.genCreate(params, "api");
      setBatches([b, ...batches]);
    });

  const getPrompt = () =>
    run(async () => {
      const r = await api.genPrompt(params);
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

  const check = () => run(async () => setChecked(await api.genCheck(params, output)));

  const saveManual = () =>
    run(async () => {
      const b = await api.genCreate(params, "manual", output);
      navigate(`/sinh/${b.id}`);
    });

  const topic = topics.find((t) => t.name === params.topic);
  const ready = params.topic.trim() !== "" && params.count > 0;
  const nNew = checked?.filter((i) => i.state === "new").length ?? 0;

  return (
    <div className="generate">
      <h2>Sinh câu hỏi bằng AI</h2>
      <p className="hint">
        Chọn ô còn thiếu trong bảng, sinh câu bằng Claude, rồi đọc lại và duyệt. Câu sinh ra luôn vào ngân hàng ở trạng thái
        nháp, chưa dùng để ra đề cho tới khi được duyệt.
      </p>

      <div className="toolbar">
        <label className="inline">
          Lớp / học phần
          <select value={grade} onChange={(e) => setGrade(e.target.value)}>
            {[...new Set(cur?.grades.map((g) => g.bac))].map((bac) => (
              <optgroup key={bac} label={bac}>
                {cur?.grades
                  .filter((g) => g.bac === bac)
                  .map((g) => (
                    <option key={g.slug} value={g.ten}>
                      {g.ten}
                    </option>
                  ))}
              </optgroup>
            ))}
          </select>
        </label>
        <label className="inline">
          Mục tiêu mỗi ô
          <input type="number" min={1} value={target} onChange={(e) => saveTarget(Number(e.target.value) || 1)} />
          câu đã duyệt
        </label>
      </div>

      <table className="table coverage">
        <thead>
          <tr>
            <th>Chủ đề</th>
            {LEVELS.map((l) => (
              <th key={l.value}>{l.label}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {topics.map((t, i) => (
            <Fragment key={t.path}>
            {t.chuong && t.chuong !== topics[i - 1]?.chuong && (
              <tr className="cov-chapter">
                <td colSpan={LEVELS.length + 1}>{t.chuong}</td>
              </tr>
            )}
            <tr>
              <td className={t.chuong ? "cov-indent" : ""}>
                {t.label ?? t.name}
                {!t.in_curriculum && !t.label && <span className="muted small"> (ngoài khung chương trình)</span>}
              </td>
              {LEVELS.map((l) => {
                const c = t.counts[l.value] ?? { approved: 0, draft: 0 };
                const ratio = Math.min(1, c.approved / target);
                const cls = ratio >= 1 ? "full" : ratio >= 0.5 ? "half" : ratio > 0 ? "low" : "zero";
                const active = params.topic === t.name && params.level === l.value;
                return (
                  <td key={l.value}>
                    <button
                      className={`cov-cell ${cls} ${active ? "active" : ""}`}
                      title={`${c.approved} câu đã duyệt, ${c.draft} câu nháp. Bấm để sinh thêm.`}
                      onClick={() => pickCell(t, l.value)}
                    >
                      {c.approved}
                      {c.draft > 0 && <span className="cov-draft">+{c.draft}</span>}
                    </button>
                  </td>
                );
              })}
            </tr>
            </Fragment>
          ))}
        </tbody>
      </table>
      <p className="hint">Số trong ô là câu đã duyệt, "+n" là câu nháp chờ duyệt. Màu theo mục tiêu mỗi ô.</p>

      <section id="gen-form" className="section-card">
        <h3>Yêu cầu sinh câu</h3>
        <div className="gen-grid">
          <label className="wide">
            Chủ đề
            <input list="gen-topics" value={params.topic} onChange={(e) => update({ topic: e.target.value, dang: undefined })} />
            <datalist id="gen-topics">
              {topics.map((t) => (
                <option key={t.path} value={t.name} />
              ))}
            </datalist>
          </label>
          <label className="wide">
            Dạng bài
            <select value={params.dang ?? ""} onChange={(e) => update({ dang: e.target.value || undefined })}>
              <option value="">Phân bổ đều các dạng</option>
              {topic?.dang.map((d) => (
                <option key={d} value={d}>
                  {d}
                </option>
              ))}
            </select>
          </label>
          <label>
            Mức độ
            <select value={params.level} onChange={(e) => update({ level: e.target.value as Level })}>
              {LEVELS.map((l) => (
                <option key={l.value} value={l.value}>
                  {l.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Loại câu
            <select value={params.type} onChange={(e) => update({ type: e.target.value as QType })}>
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Số câu
            <input
              type="number"
              min={1}
              max={cur?.max_count ?? 30}
              value={params.count}
              onChange={(e) => update({ count: Number(e.target.value) || 0 })}
            />
          </label>
          <label className="check full">
            <input type="checkbox" checked={!!params.figure} onChange={(e) => update({ figure: e.target.checked || undefined })} />
            Câu có hình vẽ (đồ thị, bảng biến thiên, hình phẳng, hình không gian vẽ bằng TikZ)
          </label>
          <label className="full">
            Yêu cầu thêm (tuỳ chọn)
            <textarea
              rows={2}
              value={params.notes ?? ""}
              onChange={(e) => update({ notes: e.target.value || undefined })}
              placeholder="Ví dụ: có 3 câu bài toán thực tế; tránh dùng căn thức"
            />
          </label>
        </div>

        {error && <div className="alert error">{error}</div>}

        <div className="toolbar">
          <button className="primary" disabled={busy || !ready || !cur?.api} onClick={generate}>
            Sinh bằng Claude
          </button>
          <button disabled={busy || !ready} onClick={getPrompt}>
            Lấy prompt để tự dán vào Claude
          </button>
          <span className="muted small">
            {cur?.api ? (
              <>Máy chủ gọi {cur.model}, mất khoảng một đến vài phút.</>
            ) : (
              <>Máy chủ chưa có ANTHROPIC_API_KEY nên chưa sinh trực tiếp được; dùng cách lấy prompt.</>
            )}
          </span>
        </div>

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
                Lưu {nNew} câu mới vào ngân hàng (nháp)
              </button>
            </div>
            {checked && <GenItems items={checked} />}
          </div>
        )}
      </section>

      <GenHistory batches={batches} grades={cur?.grades ?? []} grade={grade} focusTopic={focusTopic} />
    </div>
  );
}

const STATE_LABEL = { new: "Mới", duplicate: "Trùng", error: "Lỗi" };

/** Kết quả kiểm tra từng câu của một lần sinh. */
export function GenItems({ items }: { items: GenItem[] }) {
  return (
    <div className="gen-items">
      {items.map((it) => (
        <div key={it.index} className={`card state-${it.state}`}>
          <div className="card-head">
            <span className={`badge state-${it.state}`}>{STATE_LABEL[it.state]}</span>
            {it.code && (
              <Link to={`/cau/${encodeURIComponent(it.code)}`} className="code">
                {it.code}
              </Link>
            )}
            {it.duplicate_of && <span className="muted small">trùng câu {it.duplicate_of}</span>}
            <span className="muted small">{it.tags.map((t) => t.join(" › ")).join("; ")}</span>
          </div>
          <Tex source={it.stem} />
          {it.errors.map((e) => (
            <div key={e} className="alert error small">
              {e}
            </div>
          ))}
          {it.figure_errors?.map((e) => (
            <div key={e} className="alert error small">
              {e}. Câu vẫn được lưu vào nháp, cần sửa hình trước khi duyệt.
            </div>
          ))}
          {it.warnings.map((w) => (
            <div key={w} className="alert warn small">
              {w}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
