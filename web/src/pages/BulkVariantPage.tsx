import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import {
  api,
  LEVELS,
  levelLabel,
  TYPES,
  typeLabel,
  type Curriculum,
  type ExamSummary,
  type GenBatch,
  type GenItem,
  type Level,
  type QType,
  type TagNode,
  type VariantPlan,
} from "../api";
import { bankLink } from "../components/GenHistory";
import { TagSelect } from "../components/TagTree";
import Tex from "../components/Tex";
import { GenItems } from "./GeneratePage";

/** Mã câu chọn ở ngân hàng, chuyển sang trang này qua sessionStorage (danh sách có thể dài). */
export const PICKED_KEY = "nhd.variant.codes";

type Scope = "topic" | "exam" | "picked";

function readPicked(): string[] {
  try {
    return JSON.parse(sessionStorage.getItem(PICKED_KEY) ?? "[]");
  } catch {
    return [];
  }
}

/** Sinh biến thể hàng loạt: chọn câu gốc theo chủ đề, theo đề đã ghép hoặc theo các câu đang chọn ở ngân
 *  hàng; mỗi câu gốc sinh đúng k biến thể, gộp vài câu gốc vào một lần gọi. */
export default function BulkVariantPage() {
  const [params] = useSearchParams();
  const [picked] = useState(() => (params.get("chon") ? readPicked() : []));
  const [scope, setScope] = useState<Scope>(picked.length ? "picked" : "topic");
  const [tags, setTags] = useState<TagNode[]>([]);
  const [exams, setExams] = useState<ExamSummary[]>([]);
  const [cur, setCur] = useState<Curriculum | null>(null);
  const [tag, setTag] = useState("");
  const [levels, setLevels] = useState<Set<Level>>(new Set(LEVELS.map((l) => l.value)));
  const [types, setTypes] = useState<Set<QType>>(new Set(TYPES.map((t) => t.value)));
  const [examId, setExamId] = useState<number | "">("");
  const [computational, setComputational] = useState(false);
  const [per, setPer] = useState(5);
  const [notes, setNotes] = useState("");
  const [plan, setPlan] = useState<VariantPlan | null>(null);
  const [chosen, setChosen] = useState<Set<string>>(new Set());
  const [parts, setParts] = useState<{ codes: string[]; count: number; combined: string }[] | null>(null);
  const [partIdx, setPartIdx] = useState(0);
  const [output, setOutput] = useState("");
  const [checked, setChecked] = useState<GenItem[] | null>(null);
  const [groupId, setGroupId] = useState<string | null>(null);
  const [saved, setSaved] = useState<GenBatch[]>([]);
  const [copied, setCopied] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.tags().then(setTags);
    api.listExams().then(setExams);
    api.genCurriculum().then(setCur);
  }, []);

  // Đổi phạm vi hoặc bộ lọc thì danh sách câu gốc cũ không còn đúng
  const reset = () => {
    setPlan(null);
    setParts(null);
    setChecked(null);
    setSaved([]);
    setGroupId(null);
  };
  useEffect(reset, [scope, tag, levels, types, examId, computational]);
  useEffect(() => {
    setParts(null);
    setChecked(null);
  }, [per, chosen, notes]);

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

  const findSources = () =>
    run(async () => {
      const filter = { levels: [...levels], types: [...types], computational_only: computational };
      const body =
        scope === "topic"
          ? { ...filter, tag }
          : scope === "exam"
            ? { ...filter, exam_id: Number(examId) }
            : { ...filter, codes: picked };
      const r = await api.variantPlan(body);
      setPlan(r);
      setChosen(new Set(r.sources.map((q) => q.code)));
      setSaved([]);
      setGroupId(null);
    });

  const codes = useMemo(() => plan?.sources.filter((q) => chosen.has(q.code)).map((q) => q.code) ?? [], [plan, chosen]);
  const body = { codes, per, notes: notes.trim() || undefined };
  const maxPer = plan?.max_per ?? 10;
  const pack = Math.max(1, Math.min(plan?.pack ?? 4, Math.floor((cur?.max_count ?? 30) / per)));
  const calls = Math.ceil(codes.length / pack);

  const generate = () =>
    run(async () => {
      const g = await api.variantBatches(body, "api");
      setSaved(g.batches);
      setChosen(new Set());
    });

  const getPrompts = () =>
    run(async () => {
      const r = await api.variantPrompts(body);
      setParts(r.parts);
      setPartIdx(0);
      setOutput("");
      setChecked(null);
      setCopied(false);
    });

  const part = parts?.[partIdx];
  const partBody = part ? { codes: part.codes, per, notes: body.notes } : null;
  const check = () => partBody && run(async () => setChecked(await api.variantCheck(partBody, output)));
  const savePart = () =>
    partBody &&
    run(async () => {
      const g = await api.variantBatches(partBody, "manual", output, groupId ?? undefined);
      setGroupId(g.group_id);
      setSaved([...saved, ...g.batches]);
      setOutput("");
      setChecked(null);
      setCopied(false);
      setPartIdx(partIdx + 1);
    });
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(part?.combined ?? "");
      setCopied(true);
    } catch {
      setError("Trình duyệt không cho chép tự động, hãy bôi đen ô prompt rồi chép.");
    }
  };

  const nNew = checked?.filter((x) => x.state === "new").length ?? 0;
  const savedAdded = saved.reduce((s, b) => s + b.n_added, 0);
  const pending = saved.some((b) => b.status === "pending" || b.status === "running");
  const toggleSet = <T,>(set: Set<T>, v: T, on: boolean) => {
    const n = new Set(set);
    if (on) n.add(v);
    else n.delete(v);
    return n;
  };
  const canFind =
    !busy && (scope === "topic" ? !!tag : scope === "exam" ? examId !== "" : picked.length > 0) && levels.size > 0 && types.size > 0;

  return (
    <div className="generate">
      <div className="editor-head">
        <Link to="/sinh">‹ Sinh câu hỏi</Link>
        <h2>Sinh biến thể hàng loạt</h2>
      </div>
      <p className="hint">
        Chọn các câu gốc, mỗi câu gốc được sinh đúng {per} biến thể (cùng dạng, cùng mức độ, chỉ đổi số liệu) và vào cùng
        nhóm biến thể với câu gốc. Chỉ câu đã duyệt mới làm câu gốc; mỗi nhóm lấy một câu đại diện. Biến thể vào ngân hàng ở
        dạng nháp, được tự kiểm đáp án và không được trùng số liệu với câu khác trong nhóm.
      </p>

      <section className="section-card">
        <div className="toolbar">
          <b>Chọn câu gốc</b>
          <label className="inline">
            <input type="radio" checked={scope === "topic"} onChange={() => setScope("topic")} /> Theo chủ đề
          </label>
          <label className="inline">
            <input type="radio" checked={scope === "exam"} onChange={() => setScope("exam")} /> Theo đề đã ghép
          </label>
          <label className="inline" title={picked.length ? "" : "Tick câu ở ngân hàng rồi bấm Sinh biến thể trên thanh chọn"}>
            <input type="radio" disabled={!picked.length} checked={scope === "picked"} onChange={() => setScope("picked")} /> Câu
            đang chọn ở ngân hàng ({picked.length})
          </label>
        </div>
        <div className="toolbar">
          {scope === "topic" && (
            <TagSelect tags={tags} value={tag} onChange={setTag} placeholder="Chọn chủ đề hoặc dạng" allowEmpty={false} showCount />
          )}
          {scope === "exam" && (
            <select value={examId} onChange={(e) => setExamId(e.target.value ? Number(e.target.value) : "")}>
              <option value="">Chọn đề…</option>
              {exams.map((x) => (
                <option key={x.id} value={x.id}>
                  #{x.id} {x.title} ({x.n_questions} câu)
                </option>
              ))}
            </select>
          )}
          {scope === "picked" && <span className="muted">{picked.length} câu đã chọn ở ngân hàng</span>}
        </div>
        <div className="toolbar picker-defaults">
          <span>Mức độ:</span>
          <label className="inline">
            <input
              type="checkbox"
              checked={levels.size === LEVELS.length}
              onChange={(e) => setLevels(new Set(e.target.checked ? LEVELS.map((l) => l.value) : []))}
            />{" "}
            Tất cả
          </label>
          {LEVELS.map((l) => (
            <label key={l.value} className="inline">
              <input type="checkbox" checked={levels.has(l.value)} onChange={(e) => setLevels(toggleSet(levels, l.value, e.target.checked))} />{" "}
              {l.label}
            </label>
          ))}
        </div>
        <div className="toolbar picker-defaults">
          <span>Loại câu:</span>
          {TYPES.map((t) => (
            <label key={t.value} className="inline">
              <input type="checkbox" checked={types.has(t.value)} onChange={(e) => setTypes(toggleSet(types, t.value, e.target.checked))} />{" "}
              {t.label}
            </label>
          ))}
          <label className="inline" title="Bỏ qua câu tự luận và câu đúng/sai">
            <input type="checkbox" checked={computational} onChange={(e) => setComputational(e.target.checked)} /> Chỉ câu tính
            toán
          </label>
        </div>
        <div className="toolbar">
          <button className="primary" disabled={!canFind} onClick={findSources}>
            Tìm câu gốc
          </button>
        </div>
      </section>

      {error && <div className="alert error">{error}</div>}

      {plan && (
        <section className="section-card">
          <div className="toolbar">
            <b>
              {plan.sources.length} câu gốc
              {plan.sources.length >= plan.max_sources && ` (tối đa ${plan.max_sources} mỗi đợt)`}
            </b>
            <label className="inline">
              <input
                type="checkbox"
                checked={plan.sources.length > 0 && chosen.size === plan.sources.length}
                onChange={(e) => setChosen(new Set(e.target.checked ? plan.sources.map((q) => q.code) : []))}
              />{" "}
              Chọn tất cả
            </label>
            {plan.skipped.length > 0 && <span className="muted small">bỏ qua {plan.skipped.length} câu (xem dưới bảng)</span>}
          </div>
          {plan.sources.length > 0 && (
            <div className="table-wrap">
              <table className="table variant-plan">
                <thead>
                  <tr>
                    <th />
                    <th>Câu</th>
                    <th>Mức độ · loại</th>
                    <th>Nhóm hiện có</th>
                    <th>Đề bài</th>
                  </tr>
                </thead>
                <tbody>
                  {plan.sources.map((q) => (
                    <tr key={q.code}>
                      <td>
                        <input type="checkbox" checked={chosen.has(q.code)} onChange={(e) => setChosen(toggleSet(chosen, q.code, e.target.checked))} />
                      </td>
                      <td>
                        <Link to={`/cau/${encodeURIComponent(q.code)}`} className="code">
                          {q.code}
                        </Link>
                      </td>
                      <td className="small">
                        {levelLabel(q.level)} · {typeLabel(q.type)}
                      </td>
                      <td className="small">
                        {q.variant_group ? (
                          <Link to={`/?nhom=${encodeURIComponent(q.variant_group)}`}>
                            {q.n_variants} câu{q.variant_label && <> · {q.variant_label}</>}
                          </Link>
                        ) : (
                          <span className="muted">chưa có</span>
                        )}
                      </td>
                      <td className="variant-stem">
                        <Tex source={q.stem} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {plan.skipped.length > 0 && (
            <details>
              <summary className="small">Câu bị bỏ qua ({plan.skipped.length})</summary>
              <ul className="small">
                {plan.skipped.map((s) => (
                  <li key={s.code}>
                    <Link to={`/cau/${encodeURIComponent(s.code)}`}>{s.code}</Link>: {s.reason}
                  </li>
                ))}
              </ul>
            </details>
          )}

          <div className="toolbar">
            <label className="inline">
              Số biến thể mỗi câu gốc
              <input
                type="number"
                className="num"
                min={1}
                max={maxPer}
                value={per}
                onChange={(e) => setPer(Math.max(1, Math.min(maxPer, Number(e.target.value) || 1)))}
              />
            </label>
            <span className="muted small">
              {codes.length} câu gốc × {per} = <b>{codes.length * per} biến thể</b>, khoảng {calls} lần gọi Claude (mỗi lần{" "}
              {pack} câu gốc)
            </span>
          </div>
          <label className="gen-notes">
            Yêu cầu thêm (tuỳ chọn)
            <textarea rows={2} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Ví dụ: số liệu nguyên, không quá 20" />
          </label>
          <div className="toolbar">
            <button className="primary" disabled={busy || !codes.length || !cur?.api} onClick={generate}>
              Sinh bằng Claude ({calls} lần gọi)
            </button>
            <button disabled={busy || !codes.length} onClick={getPrompts}>
              Lấy prompt để tự dán vào Claude
            </button>
            {cur && !cur.api && (
              <span className="muted small">Máy chủ chưa có ANTHROPIC_API_KEY nên chưa sinh trực tiếp được; dùng cách lấy prompt.</span>
            )}
          </div>
        </section>
      )}

      {saved.length > 0 && (
        <div className="alert ok">
          {pending ? (
            <>
              Đã xếp {saved.length} lần sinh vào hàng đợi, Claude soạn lần lượt. Xem tiến độ ở{" "}
              <Link to="/sinh">Các lần sinh</Link>.
            </>
          ) : (
            <>
              Đã lưu {saved.length} phần, {savedAdded} biến thể mới.{" "}
              {savedAdded > 0 && <Link to={bankLink(saved.map((b) => b.source).join("|"))}>Duyệt các biến thể</Link>}
            </>
          )}
        </div>
      )}

      {parts && (
        <div className="manual">
          {partIdx >= parts.length ? (
            <div className="alert ok">Đã xong cả {parts.length} phần.</div>
          ) : (
            <>
              <div className="alert">
                <b>
                  Phần {partIdx + 1}/{parts.length}
                </b>{" "}
                ({part!.codes.join(", ")}, {part!.count} biến thể). Lưu xong phần này thì sang phần sau; các phần chung một đợt.
              </div>
              <div className="manual-step">
                <b>1.</b> Chép prompt này, dán vào một cuộc trò chuyện mới với Claude.{" "}
                <button onClick={copy}>{copied ? "Đã chép" : "Chép prompt"}</button>
              </div>
              <textarea className="mono" rows={8} readOnly value={part!.combined} />
              <div className="manual-step">
                <b>2.</b> Dán toàn bộ câu trả lời của Claude vào đây rồi bấm Kiểm tra. Mỗi biến thể được xếp về câu gốc theo
                dòng <code>@bienthe</code>.
              </div>
              <textarea
                className="mono"
                rows={8}
                value={output}
                onChange={(e) => {
                  setOutput(e.target.value);
                  setChecked(null);
                }}
                placeholder="% @bienthe: ... % @tags: ... \begin{ex} ... \end{ex}"
              />
              <div className="toolbar">
                <button disabled={busy || !output.trim()} onClick={check}>
                  Kiểm tra
                </button>
                <button className="primary" disabled={busy || !checked || nNew === 0} onClick={savePart}>
                  Lưu {nNew} biến thể (nháp){partIdx + 1 < parts.length ? ", sang phần sau" : ""}
                </button>
                {partIdx + 1 < parts.length && (
                  <button className="link" onClick={() => (setPartIdx(partIdx + 1), setOutput(""), setChecked(null))}>
                    Bỏ qua phần này
                  </button>
                )}
              </div>
              {checked && <GenItems items={checked} />}
            </>
          )}
        </div>
      )}
    </div>
  );
}
