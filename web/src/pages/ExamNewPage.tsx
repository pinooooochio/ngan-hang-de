import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import {
  api,
  type ExamTemplate,
  type TemplateIn,
  LEVELS,
  TYPES,
  typeLabel,
  type Level,
  type PickRow,
  type QType,
  type QuestionSummary,
  type SectionSpec,
  type TagNode,
} from "../api";
import { TagSelect } from "../components/TagTree";
import { useAuth } from "../auth";
import Tex from "../components/Tex";

const SECTION_NAMES: Record<QType, string> = {
  mcq: "Câu trắc nghiệm nhiều phương án lựa chọn",
  tf: "Câu trắc nghiệm đúng sai",
  short: "Câu trắc nghiệm trả lời ngắn",
  essay: "Tự luận",
};

const ROMAN = ["I", "II", "III", "IV", "V", "VI"];

// Cấu trúc đề tốt nghiệp THPT môn Toán từ 2025
const THPT_2025: SectionSpec[] = [
  { name: `PHẦN I. ${SECTION_NAMES.mcq}`, type: "mcq", points: 0.25, pick: [{ count: 12 }], ids: [] },
  { name: `PHẦN II. ${SECTION_NAMES.tf}`, type: "tf", pick: [{ count: 4 }], ids: [] },
  { name: `PHẦN III. ${SECTION_NAMES.short}`, type: "short", points: 0.5, pick: [{ count: 6 }], ids: [] },
];

const today = () => new Date().toISOString().slice(0, 10);

/** Phần của khung đề: bỏ câu chọn tay và dòng ma trận trống, để so sánh và lưu. */
const frameOf = (sections: SectionSpec[]) =>
  sections.map(({ name, type, points, pick }) => ({
    name,
    type,
    ...(points !== undefined ? { points } : {}),
    pick: pick.filter((r) => r.count > 0).map(({ tag, level, count }) => ({ ...(tag ? { tag } : {}), ...(level ? { level } : {}), count })),
  }));

const toSections = (sections: { name?: string; type: QType; points?: number; pick?: PickRow[] }[]): SectionSpec[] =>
  sections.map((s) => ({ name: s.name ?? "", type: s.type, points: s.points ?? undefined, pick: s.pick ?? [], ids: [] }));

const FILE_KIND = "nhd-khung-de";

export default function ExamNewPage() {
  const { me } = useAuth();
  const navigate = useNavigate();
  const [title, setTitle] = useState("");
  const [date, setDate] = useState(today());
  const [duration, setDuration] = useState<number | "">(90);
  const [variants, setVariants] = useState(4);
  const [firstCode, setFirstCode] = useState(101);
  const [sections, setSections] = useState<SectionSpec[]>(THPT_2025);
  const [tags, setTags] = useState<TagNode[]>([]);
  const [avail, setAvail] = useState<{ rows: number[]; problems: string[] }[]>([]);
  const [picked, setPicked] = useState<Record<string, QuestionSummary>>({});
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [templates, setTemplates] = useState<ExamTemplate[]>([]);
  const [tplId, setTplId] = useState<number | null>(null);
  const [message, setMessage] = useState("");
  const [searchParams] = useSearchParams();

  useEffect(() => {
    api.tags().then(setTags);
    api.listTemplates().then((list) => {
      setTemplates(list);
      const k = Number(searchParams.get("khung"));
      const t = list.find((x) => x.id === k);
      if (t) applyTemplate(t);
    });
    // Ghép đề mới theo khung của một đề trong kho
    const fromExam = Number(searchParams.get("tu_de"));
    if (fromExam)
      api.getExam(fromExam).then((e) => {
        const secs = (e.config.section ?? []) as Parameters<typeof toSections>[0];
        if (secs.length) setSections(toSections(secs));
        if (e.duration) setDuration(e.duration);
        setVariants(e.n_variants || variants);
        setMessage(`Đã lấy khung của đề "${e.title}" (bỏ các câu chọn tay). Có thể lưu thành khung để dùng lại.`);
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const current = templates.find((t) => t.id === tplId) ?? null;
  const dirty =
    !!current &&
    (JSON.stringify(frameOf(sections)) !== JSON.stringify(frameOf(toSections(current.sections))) ||
      (current.duration ?? "") !== duration ||
      (current.variants ?? variants) !== variants);

  function applyTemplate(t: ExamTemplate) {
    setTplId(t.id);
    setSections(toSections(t.sections));
    if (t.duration) setDuration(t.duration);
    if (t.variants) setVariants(t.variants);
    setMessage("");
  }

  const templateBody = (name: string, description: string): TemplateIn => ({
    name,
    description,
    duration: duration === "" ? undefined : duration,
    variants,
    sections: frameOf(sections).map((s) => ({ ...s, ids: [] })),
  });

  const runTpl = async (fn: () => Promise<void>) => {
    setError("");
    setMessage("");
    try {
      await fn();
    } catch (e) {
      setError(String((e as Error).message));
    }
  };

  const saveAsNew = () =>
    runTpl(async () => {
      const name = window.prompt("Tên khung đề mới", current ? `${current.name} (bản sửa)` : title.trim())?.trim();
      if (!name) return;
      const t = await api.createTemplate(templateBody(name, current?.description ?? ""));
      setTemplates([...templates, t].sort((a, b) => a.name.localeCompare(b.name)));
      setTplId(t.id);
      setMessage(`Đã lưu khung "${t.name}".`);
    });

  const saveOver = () =>
    runTpl(async () => {
      if (!current) return;
      const name = window.prompt("Lưu đè khung đề (có thể đổi tên)", current.name)?.trim();
      if (!name) return;
      const t = await api.updateTemplate(current.id, templateBody(name, current.description));
      setTemplates(templates.map((x) => (x.id === t.id ? t : x)));
      setMessage(`Đã cập nhật khung "${t.name}".`);
    });

  const removeTpl = () =>
    runTpl(async () => {
      if (!current || !window.confirm(`Xoá khung "${current.name}"? Các đề đã ghép không bị ảnh hưởng.`)) return;
      await api.deleteTemplate(current.id);
      setTemplates(templates.filter((x) => x.id !== current.id));
      setTplId(null);
    });

  const exportTpl = () => {
    const name = current?.name ?? (title.trim() || "khung-de");
    const data = { kind: FILE_KIND, version: 1, ...templateBody(name, current?.description ?? "") };
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = `${name}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const importTpl = (file: File) =>
    runTpl(async () => {
      let data: TemplateIn & { kind?: string };
      try {
        data = JSON.parse(await file.text());
      } catch {
        throw new Error("File không phải JSON hợp lệ");
      }
      if (data.kind !== FILE_KIND || !Array.isArray(data.sections)) throw new Error("File không phải khung đề xuất từ trang này");
      let name = data.name?.trim() || file.name.replace(/\.json$/i, "");
      while (templates.some((t) => t.name === name)) {
        const next = window.prompt(`Đã có khung tên "${name}". Đặt tên khác cho khung nhập vào:`, `${name} (2)`)?.trim();
        if (!next) return;
        name = next;
      }
      const t = await api.createTemplate({ ...data, name, sections: frameOf(toSections(data.sections)).map((s) => ({ ...s, ids: [] })) });
      setTemplates([...templates, t].sort((a, b) => a.name.localeCompare(b.name)));
      applyTemplate(t);
      setMessage(`Đã nhập khung "${t.name}".`);
    });

  // Kiểm tra số câu còn trong ngân hàng mỗi khi ma trận đổi
  useEffect(() => {
    const t = setTimeout(() => {
      api
        .availability(sections)
        .then((r) => setAvail(r.sections))
        .catch(() => setAvail([]));
    }, 300);
    return () => clearTimeout(t);
  }, [sections]);

  const updateSection = (i: number, patch: Partial<SectionSpec>) =>
    setSections(sections.map((s, k) => (k === i ? { ...s, ...patch } : s)));
  const updateRow = (i: number, r: number, patch: Partial<PickRow>) =>
    updateSection(i, { pick: sections[i].pick.map((row, k) => (k === r ? { ...row, ...patch } : row)) });

  const addSection = () => {
    const type: QType = "essay";
    setSections([...sections, { name: `PHẦN ${ROMAN[sections.length] ?? sections.length + 1}. ${SECTION_NAMES[type]}`, type, pick: [], ids: [] }]);
  };

  const totalOf = (s: SectionSpec) => s.ids.length + s.pick.reduce((n, r) => n + (r.count || 0), 0);
  const total = sections.reduce((n, s) => n + totalOf(s), 0);
  const shortages = sections.flatMap((s, i) =>
    s.pick.flatMap((r, k) => {
      const have = avail[i]?.rows[k];
      return have !== undefined && have < r.count ? [`${s.name || `Phần ${i + 1}`}: dòng ${k + 1} cần ${r.count} câu, chỉ có ${have}`] : [];
    }),
  );
  const problems = [...shortages, ...avail.flatMap((a) => a.problems)];

  const submit = async () => {
    setBusy(true);
    setError("");
    try {
      const exam = await api.createExam({
        title: title.trim(),
        date: date || undefined,
        duration: duration === "" ? undefined : duration,
        variants,
        first_code: firstCode,
        sections: sections.map((s) => ({ ...s, pick: s.pick.filter((r) => r.count > 0) })),
      });
      navigate(`/de/${exam.id}`);
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="exam-new">
      <h2>Ghép đề mới</h2>
      <div className="form-grid">
        <label>
          Tiêu đề (chủ đề)
          <input value={title} onChange={(e) => setTitle(e.target.value)} placeholder="Ví dụ: Kiểm tra giữa kỳ Vectơ trong không gian" />
        </label>
        <label>
          Ngày
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} />
        </label>
        <label>
          Thời gian (phút)
          <input type="number" min={1} value={duration} onChange={(e) => setDuration(e.target.value === "" ? "" : Number(e.target.value))} />
        </label>
        <label>
          Số mã đề
          <input type="number" min={1} max={30} value={variants} onChange={(e) => setVariants(Number(e.target.value))} />
        </label>
        <label>
          Mã đề đầu tiên
          <input type="number" value={firstCode} onChange={(e) => setFirstCode(Number(e.target.value))} />
        </label>
      </div>

      <section className="section-card template-bar">
        <div className="toolbar">
          <b>Khung đề</b>
          <select
            value={tplId ?? ""}
            onChange={(e) => {
              const t = templates.find((x) => x.id === Number(e.target.value));
              if (t) applyTemplate(t);
              else setTplId(null);
            }}
          >
            <option value="">{templates.length ? "Chọn khung đã lưu…" : "Chưa có khung nào"}</option>
            {templates.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({t.n_questions} câu)
              </option>
            ))}
          </select>
          {current && dirty && <span className="muted small">đã sửa so với khung</span>}
          <span className="spacer" />
          {current && (
            <button disabled={!dirty} onClick={saveOver} title="Ghi phần đang sửa vào khung này">
              Lưu đè khung
            </button>
          )}
          <button onClick={saveAsNew}>Lưu thành khung mới</button>
          <button onClick={exportTpl} title="Tải khung hiện tại về máy dưới dạng file .json">
            Xuất file
          </button>
          <label className="button">
            Nhập file
            <input
              type="file"
              accept=".json,application/json"
              hidden
              onChange={(e) => {
                const f = e.target.files?.[0];
                e.target.value = "";
                if (f) importTpl(f);
              }}
            />
          </label>
          {current && me.role === "admin" && (
            <button className="link danger" onClick={removeTpl}>
              Xoá khung
            </button>
          )}
        </div>
        <div className="hint">
          Khung lưu các phần, loại câu, điểm, ma trận thẻ × mức độ × số câu, thời gian và số mã đề; không lưu câu chọn tay.
        </div>
        {message && <div className="alert ok">{message}</div>}
      </section>

      <div className="toolbar">
        <button onClick={() => { setSections(THPT_2025); setTplId(null); }}>Điền cấu trúc THPT 2025</button>
        <button onClick={addSection}>+ Thêm phần</button>
      </div>

      {sections.map((s, i) => (
        <section key={i} className="section-card">
          <div className="section-head">
            <input className="section-name" value={s.name} onChange={(e) => updateSection(i, { name: e.target.value })} />
            <select
              value={s.type}
              onChange={(e) => updateSection(i, { type: e.target.value as QType, ids: [] })}
              title="Loại câu của phần này"
            >
              {TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <label className="inline">
              Điểm mỗi câu
              <input
                type="number"
                step={0.05}
                min={0}
                value={s.points ?? ""}
                onChange={(e) => updateSection(i, { points: e.target.value === "" ? undefined : Number(e.target.value) })}
              />
            </label>
            <span className="muted">{totalOf(s)} câu</span>
            <button className="link danger" onClick={() => setSections(sections.filter((_, k) => k !== i))}>
              Xoá phần
            </button>
          </div>

          <table className="matrix">
            <thead>
              <tr>
                <th>Thẻ (lớp / chủ đề / dạng)</th>
                <th>Mức độ</th>
                <th>Số câu</th>
                <th>Ngân hàng có</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {s.pick.map((r, k) => {
                const have = avail[i]?.rows[k];
                return (
                  <tr key={k}>
                    <td>
                      <TagSelect tags={tags} value={r.tag ?? ""} placeholder="Mọi thẻ" onChange={(p) => updateRow(i, k, { tag: p || undefined })} />
                    </td>
                    <td>
                      <select value={r.level ?? ""} onChange={(e) => updateRow(i, k, { level: (e.target.value || undefined) as Level | undefined })}>
                        <option value="">Mọi mức độ</option>
                        {LEVELS.map((l) => (
                          <option key={l.value} value={l.value}>
                            {l.label}
                          </option>
                        ))}
                      </select>
                    </td>
                    <td>
                      <input type="number" min={1} className="count" value={r.count} onChange={(e) => updateRow(i, k, { count: Number(e.target.value) })} />
                    </td>
                    <td className={have !== undefined && have < r.count ? "short" : "muted"}>
                      {have === undefined ? "…" : `${have} câu ${typeLabel(s.type).toLowerCase()}`}
                    </td>
                    <td>
                      <button className="link" onClick={() => updateSection(i, { pick: s.pick.filter((_, x) => x !== k) })}>
                        Xoá
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <button className="link" onClick={() => updateSection(i, { pick: [...s.pick, { count: 1 }] })}>
            + Thêm dòng ma trận
          </button>

          {s.ids.length > 0 && (
            <div className="picked">
              <div className="muted">Câu chọn tay:</div>
              {s.ids.map((code) => (
                <div key={code} className="picked-item">
                  <span className="code">{code}</span>
                  <span className="picked-stem">{picked[code] ? <Tex source={picked[code].stem} inline /> : null}</span>
                  <button className="link" onClick={() => updateSection(i, { ids: s.ids.filter((c) => c !== code) })}>
                    Bỏ
                  </button>
                </div>
              ))}
            </div>
          )}
          <QuestionPicker
            type={s.type}
            tags={tags}
            exclude={new Set(sections.flatMap((x) => x.ids))}
            onPick={(q) => {
              setPicked({ ...picked, [q.code]: q });
              updateSection(i, { ids: [...s.ids, q.code] });
            }}
          />
        </section>
      ))}

      <div className="submit-bar">
        <div>
          <b>Tổng {total} câu</b>, {variants} mã đề.
          {problems.map((p) => (
            <div key={p} className="alert warn">
              {p}
            </div>
          ))}
          {error && <div className="alert error">{error}</div>}
        </div>
        <button className="primary" disabled={busy || !title.trim() || total === 0 || problems.length > 0} onClick={submit}>
          {busy ? "Đang tạo…" : "Tạo đề"}
        </button>
      </div>
    </div>
  );
}

/** Tìm và chọn tay câu đã duyệt trong ngân hàng cho một phần. */
function QuestionPicker({
  type,
  tags,
  exclude,
  onPick,
}: {
  type: QType;
  tags: TagNode[];
  exclude: Set<string>;
  onPick: (q: QuestionSummary) => void;
}) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [tag, setTag] = useState("");
  const [items, setItems] = useState<QuestionSummary[]>([]);

  useEffect(() => {
    if (!open) return;
    const t = setTimeout(() => {
      api.listQuestions({ type, status: "approved", q, tag, limit: 10 }).then((r) => setItems(r.items));
    }, 250);
    return () => clearTimeout(t);
  }, [open, q, tag, type]);

  if (!open)
    return (
      <button className="link" onClick={() => setOpen(true)}>
        + Chọn tay câu từ ngân hàng
      </button>
    );
  return (
    <div className="picker">
      <div className="picker-head">
        <input placeholder="Tìm theo nội dung hoặc mã câu" value={q} onChange={(e) => setQ(e.target.value)} autoFocus />
        <TagSelect tags={tags} value={tag} placeholder="Mọi thẻ" onChange={setTag} />
        <button className="link" onClick={() => setOpen(false)}>
          Đóng
        </button>
      </div>
      {items
        .filter((it) => !exclude.has(it.code))
        .map((it) => (
          <div key={it.code} className="picker-item" onClick={() => onPick(it)}>
            <span className="code">{it.code}</span>
            <Tex source={it.stem} inline />
          </div>
        ))}
      {items.length === 0 && <div className="muted">Không có câu {typeLabel(type).toLowerCase()} đã duyệt nào khớp.</div>}
    </div>
  );
}
