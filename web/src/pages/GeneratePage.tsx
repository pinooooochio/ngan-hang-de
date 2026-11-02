import { Fragment, useEffect, useState } from "react";
import { Link } from "react-router-dom";
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
  type GenMultiCheck,
  type GenParams,
  type Level,
  type QType,
} from "../api";
import GenHistory, { bankLink } from "../components/GenHistory";
import TopicPicker from "../components/TopicPicker";
import Tex from "../components/Tex";

const TARGET_KEY = "nhd.gen.target";
const COUNT_KEY = "nhd.gen.count";

function readCount() {
  try {
    return Number(localStorage.getItem(COUNT_KEY)) || 10;
  } catch {
    return 10;
  }
}

/** Chia danh sách thành các phần liên tiếp, mỗi phần tối đa `limit` câu (cách chép prompt). */
function splitParts<T extends { count: number }>(rows: T[], limit: number): T[][] {
  const parts: T[][] = [];
  let cur: T[] = [];
  let n = 0;
  for (const r of rows) {
    if (cur.length && n + r.count > limit) {
      parts.push(cur);
      cur = [];
      n = 0;
    }
    cur.push(r);
    n += r.count;
  }
  if (cur.length) parts.push(cur);
  return parts;
}

/** Ước lượng token ra cho một câu (câu có hình dài hơn vì mã TikZ). */
const outTokens = (r: GenParams) => r.count * (r.figure ? 900 : 450);

function readTarget() {
  try {
    return Number(localStorage.getItem(TARGET_KEY)) || 20;
  } catch {
    return 20;
  }
}

export { STATUS_LABEL, bankLink } from "../components/GenHistory";

/** Một ô trong danh sách sinh. */
type Row = GenParams & { key: number };
let nextKey = 1;

export default function GeneratePage() {
  const [cur, setCur] = useState<Curriculum | null>(null);
  const [grade, setGrade] = useState("Lớp 12");
  const [topics, setTopics] = useState<CoverageTopic[]>([]);
  const [target, setTarget] = useState(readTarget);
  const [rows, setRows] = useState<Row[]>([]);
  const [notes, setNotes] = useState("");
  const [batches, setBatches] = useState<GenBatch[]>([]);
  const [prompt, setPrompt] = useState("");
  const [output, setOutput] = useState("");
  const [checked, setChecked] = useState<GenMultiCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState<GenBatch[] | null>(null);
  const [copied, setCopied] = useState(false);
  const [focusTopic, setFocusTopic] = useState<string>();
  const [defaultCount, setDefaultCount] = useState(readCount);
  const [picker, setPicker] = useState(false);
  // dán tay nhiều phần: các phần đã lưu chung một mã đợt
  const [manualGroup, setManualGroup] = useState<string | null>(null);
  const [partsDone, setPartsDone] = useState(0);

  useEffect(() => {
    api.genCurriculum().then(setCur);
    api.genBatches().then(setBatches);
  }, []);

  useEffect(() => {
    api.genCoverage(grade).then((r) => setTopics(r.topics));
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

  const maxCount = cur?.max_count ?? 30;
  const maxTotal = cur?.max_total ?? 300;
  const maxPrompt = cur?.max_prompt ?? 60;
  const total = rows.reduce((s, r) => s + (r.count || 0), 0);
  const parts = splitParts(rows, maxPrompt);
  const partRows = parts[0] ?? [];

  // Đổi danh sách thì prompt và kết quả kiểm tra cũ không còn đúng
  const changeRows = (next: Row[]) => {
    setRows(next);
    setPrompt("");
    setChecked(null);
    setSaved(null);
    setManualGroup(null);
    setPartsDone(0);
  };
  const updateRow = (key: number, patch: Partial<GenParams>) =>
    changeRows(rows.map((r) => (r.key === key ? { ...r, ...patch } : r)));
  const newRow = (patch: Partial<GenParams>): Row => {
    const last = rows[rows.length - 1];
    return {
      key: nextKey++,
      grade,
      topic: "",
      level: "NB",
      type: last?.type ?? "mcq",
      count: defaultCount,
      figure: last?.figure,
      ...patch,
    };
  };

  const saveTarget = (n: number) => {
    setTarget(n);
    try {
      localStorage.setItem(TARGET_KEY, String(n));
    } catch {
      /* không lưu được thì thôi */
    }
  };

  const saveDefaultCount = (n: number) => {
    setDefaultCount(n);
    try {
      localStorage.setItem(COUNT_KEY, String(n));
    } catch {
      /* không lưu được thì thôi */
    }
  };

  const inCart = (topic: string, level: Level) => rows.some((r) => r.grade === grade && r.topic === topic && r.level === level);

  // Bấm ô: thêm vào danh sách (số câu mặc định), bấm lần nữa thì bỏ ra
  const pickCell = (t: CoverageTopic, level: Level) => {
    setFocusTopic(t.name);
    if (inCart(t.name, level)) {
      changeRows(rows.filter((r) => !(r.grade === grade && r.topic === t.name && r.level === level)));
    } else {
      changeRows([...rows, newRow({ topic: t.name, level })]);
    }
  };

  // Thêm từ hộp chọn chủ đề: dòng trùng (cùng lớp, chủ đề, dạng, mức độ, loại) thì cộng dồn số câu
  const addRows = (add: Omit<GenParams, "notes">[]) => {
    const next = [...rows];
    for (const a of add) {
      const i = next.findIndex(
        (r) => r.grade === a.grade && r.topic === a.topic && (r.dang ?? "") === (a.dang ?? "") && r.level === a.level && r.type === a.type,
      );
      if (i >= 0) next[i] = { ...next[i], count: Math.min(maxCount, next[i].count + a.count) };
      else next.push({ ...a, key: nextKey++ });
    }
    changeRows(next);
    setPicker(false);
  };

  const params = (list: Row[] = rows): GenParams[] =>
    list.map(({ key: _key, ...r }) => ({ ...r, notes: notes.trim() || undefined }));

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

  const afterSave = (g: { batches: GenBatch[] }) => {
    setBatches([...g.batches, ...batches.filter((b) => !g.batches.some((x) => x.id === b.id))].sort((a, b) => b.id - a.id));
    setSaved(g.batches);
    setRows([]);
    setPrompt("");
    setOutput("");
    setChecked(null);
    api.genCoverage(grade).then((r) => setTopics(r.topics));
  };

  const generate = () => run(async () => afterSave(await api.genCreateMulti(params(), "api")));

  // Cách chép prompt làm theo từng phần: luôn là phần đầu của danh sách còn lại
  const loadPrompt = async (list: Row[]) => {
    const r = await api.genPromptMulti(params(list));
    setPrompt(r.combined);
    setCopied(false);
  };
  const getPrompt = () => run(() => loadPrompt(partRows));

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(prompt);
      setCopied(true);
    } catch {
      setError("Trình duyệt không cho chép tự động, hãy bôi đen ô prompt rồi chép.");
    }
  };

  const check = () => run(async () => setChecked(await api.genCheckMulti(params(partRows), output)));
  const saveManual = () =>
    run(async () => {
      const g = await api.genCreateMulti(params(partRows), "manual", output, manualGroup ?? undefined);
      const rest = rows.slice(partRows.length);
      if (!rest.length) {
        afterSave({ batches: [...(saved ?? []), ...g.batches] });
        setManualGroup(null);
        setPartsDone(0);
        return;
      }
      setPartsDone(partsDone + 1);
      // còn phần sau: giữ mã đợt, bỏ các dòng đã lưu, lấy luôn prompt phần kế tiếp
      setBatches([...g.batches, ...batches].sort((a, b) => b.id - a.id));
      setSaved([...(saved ?? []), ...g.batches]);
      setManualGroup(g.group_id);
      setRows(rest);
      setOutput("");
      setChecked(null);
      await loadPrompt(rest.slice(0, splitParts(rest, maxPrompt)[0].length));
    });

  const filled = rows.length > 0 && rows.every((r) => r.topic.trim() && r.count > 0);
  const ready = filled && total <= maxTotal;
  const nNew = checked?.rows.flat().filter((i) => i.state === "new").length ?? 0;
  const topicsOf = (g: string) => cur?.grades.find((x) => x.ten === g)?.chu_de ?? [];

  return (
    <div className="generate">
      <div className="editor-head">
        <h2>Sinh câu hỏi bằng AI</h2>
        <span className="spacer" />
        <Link className="button" to="/sinh/bien-the" title="Sinh câu cùng dạng, khác số liệu cho nhiều câu đã duyệt">
          Sinh biến thể hàng loạt
        </Link>
      </div>
      <p className="hint">
        Bấm các ô còn thiếu trong bảng để đưa vào danh sách sinh (mỗi ô chỉnh riêng dạng, loại câu, số câu), sinh bằng Claude, rồi đọc lại và duyệt. Câu sinh ra luôn vào ngân hàng ở trạng thái
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
          Mục tiêu mỗi ô (để tô màu)
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
                const active = inCart(t.name, l.value);
                return (
                  <td key={l.value}>
                    <button
                      className={`cov-cell ${cls} ${active ? "active" : ""}`}
                      title={`${c.approved} câu đã duyệt, ${c.draft} câu nháp. Bấm để thêm vào (hoặc bỏ khỏi) danh sách sinh.`}
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
        <div className="toolbar">
          <h3>Danh sách sinh</h3>
          <span className="muted small">
            {rows.length} ô · {total}/{maxTotal} câu
          </span>
          <span className="spacer" />
          <label className="inline small" title="Số câu khi bấm ô ở bảng độ phủ hoặc thêm dòng mới">
            Mặc định
            <input
              type="number"
              className="num"
              min={1}
              max={maxCount}
              value={defaultCount}
              onChange={(e) => saveDefaultCount(Math.max(1, Math.min(maxCount, Number(e.target.value) || 1)))}
            />
            câu/dòng
          </label>
          <button className="link" onClick={() => setPicker(!picker)}>
            + Thêm chủ đề
          </button>
          <button className="link" onClick={() => changeRows([...rows, newRow({})])}>
            + Thêm dòng
          </button>
          {rows.length > 0 && (
            <button className="link" onClick={() => changeRows([])}>
              Xoá hết
            </button>
          )}
        </div>

        {picker && cur && (
          <TopicPicker
            grades={cur.grades}
            grade={grade}
            maxCount={maxCount}
            defaultCount={defaultCount}
            onAdd={addRows}
            onClose={() => setPicker(false)}
          />
        )}

        {rows.length === 0 ? (
          <p className="muted">
            Chưa có dòng nào. Bấm vào các ô trong bảng ở trên, hoặc "+ Thêm chủ đề" để chọn nhiều chủ đề cùng lúc.
          </p>
        ) : (
          <table className="table gen-rows">
            <thead>
              <tr>
                <th>Chủ đề</th>
                <th>Dạng bài</th>
                <th>Mức độ</th>
                <th>Loại câu</th>
                <th>Số câu</th>
                <th title="Mỗi câu có hình vẽ TikZ (đồ thị, bảng biến thiên, hình phẳng, hình không gian)">Có hình</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const ct = topicsOf(r.grade).find((t) => t.ten === r.topic);
                return (
                  <tr key={r.key}>
                    <td>
                      {r.grade !== grade && <div className="muted small">{r.grade}</div>}
                      <input
                        list={`gen-topics-${r.key}`}
                        value={r.topic}
                        onChange={(e) => updateRow(r.key, { topic: e.target.value, dang: undefined })}
                        placeholder="Chọn chủ đề"
                      />
                      <datalist id={`gen-topics-${r.key}`}>
                        {topicsOf(r.grade).map((t) => (
                          <option key={t.path} value={t.ten} />
                        ))}
                      </datalist>
                    </td>
                    <td>
                      <select value={r.dang ?? ""} onChange={(e) => updateRow(r.key, { dang: e.target.value || undefined })}>
                        <option value="">Đều các dạng</option>
                        {ct?.dang.map((d) => (
                          <option key={d} value={d}>
                            {d}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select value={r.level} onChange={(e) => updateRow(r.key, { level: e.target.value as Level })}>
                        {LEVELS.map((l) => (
                          <option key={l.value} value={l.value}>
                            {l.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <select value={r.type} onChange={(e) => updateRow(r.key, { type: e.target.value as QType })}>
                        {TYPES.map((t) => (
                          <option key={t.value} value={t.value}>
                            {t.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input
                        type="number"
                        className="num"
                        min={1}
                        max={maxCount}
                        value={r.count}
                        onChange={(e) => updateRow(r.key, { count: Math.min(maxCount, Number(e.target.value) || 0) })}
                      />
                    </td>
                    <td className="center">
                      <input
                        type="checkbox"
                        checked={!!r.figure}
                        onChange={(e) => updateRow(r.key, { figure: e.target.checked || undefined })}
                      />
                    </td>
                    <td>
                      <button className="link" title="Bỏ dòng này" onClick={() => changeRows(rows.filter((x) => x.key !== r.key))}>
                        ✕
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
        {total > maxTotal && (
          <div className="alert warn">
            Sinh bằng Claude mỗi đợt tối đa {maxTotal} câu; hãy bớt số câu hoặc chia thành nhiều đợt. Cách lấy prompt thì
            không giới hạn, hệ thống chia thành từng phần {maxPrompt} câu.
          </div>
        )}

        <label className="gen-notes">
          Yêu cầu thêm cho cả đợt (tuỳ chọn)
          <textarea
            rows={2}
            value={notes}
            onChange={(e) => {
              setNotes(e.target.value);
              setPrompt("");
              setChecked(null);
            }}
            placeholder="Ví dụ: có 3 câu bài toán thực tế; tránh dùng căn thức"
          />
        </label>

        {error && <div className="alert error">{error}</div>}
        {saved && (
          <div className="alert ok">
            Đã tạo {saved.length} lần sinh.{" "}
            {saved.some((b) => b.status === "pending") ? (
              <>Claude đang soạn lần lượt từng ô, xem tiến độ ở "Các lần sinh" bên dưới.</>
            ) : (
              <Link to={bankLink(saved.map((b) => b.source).join("|"))}>
                Duyệt {saved.reduce((s, b) => s + b.n_added, 0)} câu mới của đợt này
              </Link>
            )}
          </div>
        )}

        <div className="toolbar">
          <button className="primary" disabled={busy || !ready || !cur?.api} onClick={generate}>
            Sinh bằng Claude{rows.length > 1 ? ` (${rows.length} ô)` : ""}
          </button>
          <button disabled={busy || !filled} onClick={getPrompt}>
            Lấy prompt để tự dán vào Claude{parts.length > 1 ? ` (${parts.length} phần)` : ""}
          </button>
          <span className="muted small">
            {cur?.api ? (
              <>
                Máy chủ gọi {cur.model}, mỗi dòng là một lần gọi, chạy lần lượt
                {rows.length > 0 && (
                  <>
                    : {rows.length} lần gọi, khoảng {Math.round(rows.reduce((s, r) => s + outTokens(r), 0) / 1000)} nghìn token
                    ra
                  </>
                )}
                .
              </>
            ) : (
              <>Máy chủ chưa có ANTHROPIC_API_KEY nên chưa sinh trực tiếp được; dùng cách lấy prompt.</>
            )}
          </span>
        </div>

        {prompt && (
          <div className="manual">
            {partsDone + parts.length > 1 && (
              <div className="alert">
                <b>
                  Phần {partsDone + 1}/{partsDone + parts.length}
                </b>{" "}
                ({partRows.length} dòng, {partRows.reduce((s, r) => s + r.count, 0)} câu). Lưu xong phần này thì prompt phần
                kế tiếp hiện ra; các phần chung một đợt.
              </div>
            )}
            <div className="manual-step">
              <b>1.</b> Chép prompt này, dán vào một cuộc trò chuyện mới với Claude.{" "}
              <button onClick={copy}>{copied ? "Đã chép" : "Chép prompt"}</button>
            </div>
            <textarea className="mono" rows={8} readOnly value={prompt} />
            <div className="manual-step">
              <b>2.</b> Dán toàn bộ câu trả lời của Claude vào đây rồi bấm Kiểm tra. Mỗi câu được xếp về ô của nó theo dòng
              @tags và @level.
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
                Lưu {nNew} câu mới vào ngân hàng (nháp){parts.length > 1 ? ", sang phần sau" : ""}
              </button>
            </div>
            {checked && (
              <>
                {partRows.map((r, i) => {
                  const items = checked.rows[i] ?? [];
                  const n = items.filter((x) => x.state === "new").length;
                  return (
                    <div key={r.key} className="gen-check-row">
                      <h4>
                        Ô {i + 1}: {r.topic} · {levelLabel(r.level)} · {typeLabel(r.type)}{" "}
                        <span className={n < r.count ? "warn-text" : "muted"}>
                          ({n}/{r.count} câu mới)
                        </span>
                      </h4>
                      {items.length > 0 ? <GenItems items={items} /> : <div className="alert warn small">Không có câu nào cho ô này.</div>}
                    </div>
                  );
                })}
                {checked.unmatched.length > 0 && (
                  <div className="gen-check-row">
                    <h4>Câu không khớp ô nào (sẽ bỏ qua)</h4>
                    {checked.unmatched.map((u) => (
                      <div key={u.index} className="alert warn small">
                        Câu {u.index}: {u.tags.map((t) => t.join(" › ")).join("; ") || "không có @tags"} ·{" "}
                        {u.level ?? "không có @level"} · {typeLabel(u.type)} — {u.stem}
                      </div>
                    ))}
                  </div>
                )}
              </>
            )}
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
            {it.duplicate_of && <span className="muted small">trùng {/^[A-Z0-9-]+$/.test(it.duplicate_of) ? `câu ${it.duplicate_of}` : it.duplicate_of}</span>}
            {it.variant_of && <span className="badge variant-of">biến thể của {it.variant_of}</span>}
            {it.answer_checked && !it.answer_errors?.length && (
              <span className="badge approved" title="Máy chủ đã tính lại đáp án theo dòng @kiemtra và thấy khớp">
                Đáp án đã tự kiểm
              </span>
            )}
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
          {it.answer_errors?.map((e) => (
            <div key={e} className="alert error small">
              Kiểm đáp án: {e}. Câu vẫn được lưu vào nháp, cần xem lại đáp án trước khi duyệt.
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
