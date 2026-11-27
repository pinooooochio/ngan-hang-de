import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type TheoryTopicSummary } from "../api";
import { useAuth } from "../auth";
import { TheoryGenList } from "../components/TheoryGenPanel";

type Grade = { ten: string; slug: string; bac: string; topics: TheoryTopicSummary[] };

const OPEN_KEY = "nhd.theory.open";

function norm(s: string) {
  return s.normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/đ/gi, "d").toLowerCase();
}

/** Lý thuyết theo khung chương trình: lớp / học phần, mỗi chủ đề kèm số khối đã duyệt và nháp. */
export default function TheoryHomePage() {
  const { me } = useAuth();
  const staff = me.role !== "student";
  const [grades, setGrades] = useState<Grade[] | null>(null);
  const [error, setError] = useState("");
  const [q, setQ] = useState("");
  const [only, setOnly] = useState<"" | "missing" | "draft">("");
  const [apiOk, setApiOk] = useState(false);
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [examples, setExamples] = useState(2);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [open, setOpen] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(OPEN_KEY) ?? "[]"));
    } catch {
      return new Set();
    }
  });

  const load = () =>
    api
      .theoryTopics()
      .then((r) => setGrades(r.grades))
      .catch((e: Error) => setError(e.message));

  useEffect(() => {
    load();
    if (staff) api.theoryGenList().then((r) => setApiOk(r.api)).catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pick = (path: string) => {
    const next = new Set(picked);
    if (next.has(path)) next.delete(path);
    else next.add(path);
    setPicked(next);
  };

  const send = async () => {
    setBusy(true);
    setError("");
    try {
      const r = await api.theoryGen({ paths: [...picked], examples, mode: "api" });
      setMessage(
        `Đã gửi Claude soạn phần còn thiếu của ${r.length} chủ đề${
          r.length < picked.size ? ` (${picked.size - r.length} chủ đề đã đủ, bỏ qua)` : ""
        }. Theo dõi ở bảng "Các lần Claude soạn" bên dưới; lý thuyết mới vào dạng nháp.`,
      );
      setPicked(new Set());
      setPicking(false);
      setRefresh((x) => x + 1);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const toggle = (slug: string, isOpen: boolean) => {
    const next = new Set(open);
    if (isOpen) next.add(slug);
    else next.delete(slug);
    setOpen(next);
    try {
      localStorage.setItem(OPEN_KEY, JSON.stringify([...next]));
    } catch {
      /* không lưu được thì lần sau mở lại như cũ */
    }
  };

  const shown = useMemo(() => {
    if (!grades) return [];
    const k = norm(q.trim());
    return grades
      .map((g) => ({
        ...g,
        topics: g.topics.filter(
          (t) =>
            (!k || norm(`${g.ten} ${t.chuong} ${t.ten}`).includes(k)) &&
            (only !== "missing" || t.approved + t.draft === 0) &&
            (only !== "draft" || t.draft > 0),
        ),
      }))
      .filter((g) => g.topics.length);
  }, [grades, q, only]);

  const total = grades?.reduce(
    (a, g) => {
      for (const t of g.topics) {
        a.topics += 1;
        if (t.approved + t.draft) a.done += 1;
        a.draft += t.draft;
      }
      return a;
    },
    { topics: 0, done: 0, draft: 0 },
  );

  return (
    <div className="theory-home">
      <div className="toolbar">
        <h2>Lý thuyết theo chủ đề</h2>
        <span className="spacer" />
        {staff && apiOk && (
          <button onClick={() => (setPicking(!picking), setPicked(new Set()))}>
            {picking ? "Thôi chọn" : "Chọn chủ đề cho Claude soạn"}
          </button>
        )}
        {staff && (
          <Link className="button" to="/ly-thuyet/import">
            Import file lý thuyết
          </Link>
        )}
      </div>
      {staff && total && (
        <p className="muted small">
          {total.done}/{total.topics} chủ đề đã có lý thuyết
          {total.draft > 0 && <>, {total.draft} khối đang nháp chờ duyệt</>}. Bấm vào chủ đề để xem và soạn.
        </p>
      )}
      {!staff && <p className="muted small">Các chủ đề đã có lý thuyết. Bấm vào chủ đề để xem.</p>}
      <div className="toolbar">
        <input placeholder="Tìm chủ đề…" value={q} onChange={(e) => setQ(e.target.value)} />
        {staff && (
          <select value={only} onChange={(e) => setOnly(e.target.value as typeof only)}>
            <option value="">Tất cả chủ đề</option>
            <option value="missing">Chưa có lý thuyết</option>
            <option value="draft">Có khối nháp</option>
          </select>
        )}
      </div>
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert ok">{message}</div>}
      {picking && (
        <div className="toolbar sticky-bar">
          <span>
            Đã chọn <b>{picked.size}</b> chủ đề. Claude soạn phần còn thiếu (kiến thức chung, các dạng bài chưa có) của mỗi
            chủ đề, vào dạng nháp.
          </span>
          <span className="spacer" />
          <label>
            Ví dụ mỗi dạng{" "}
            <select value={examples} onChange={(e) => setExamples(Number(e.target.value))}>
              {[0, 1, 2, 3, 4].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </label>
          <button className="primary" disabled={busy || !picked.size || picked.size > 40} onClick={send}>
            Gửi Claude soạn
          </button>
          {picked.size > 40 && <span className="error-text small">Tối đa 40 chủ đề mỗi đợt</span>}
        </div>
      )}
      {staff && <TheoryGenList refresh={refresh} onDone={load} />}
      {grades && !shown.length && <p className="muted">Không có chủ đề nào{!staff && " có lý thuyết"}.</p>}
      {shown.map((g) => {
        const isOpen = open.has(g.slug) || !!q.trim() || !!only;
        const done = g.topics.filter((t) => t.approved + t.draft).length;
        let chuong = "";
        return (
          <details key={g.slug} className="theory-grade" open={isOpen} onToggle={(e) => toggle(g.slug, (e.target as HTMLDetailsElement).open)}>
            <summary>
              <b>{g.ten}</b>{" "}
              <span className="muted small">
                {staff ? `${done}/${g.topics.length} chủ đề có lý thuyết` : `${g.topics.length} chủ đề`}
              </span>
            </summary>
            <table className="theory-topics">
              <tbody>
                {g.topics.map((t) => {
                  const head = t.chuong && t.chuong !== chuong;
                  chuong = t.chuong;
                  return [
                    head && (
                      <tr key={`c-${t.path}`} className="theory-chapter">
                        <td colSpan={2}>{t.chuong}</td>
                      </tr>
                    ),
                    <tr key={t.path}>
                      <td>
                        {picking && (
                          <input type="checkbox" checked={picked.has(t.path)} onChange={() => pick(t.path)} />
                        )}{" "}
                        <Link to={`/ly-thuyet/cd/${t.path}`}>{t.ten}</Link>
                      </td>
                      <td className="small nowrap">
                        {t.approved + t.draft === 0 ? (
                          <span className="muted">chưa có</span>
                        ) : (
                          <>
                            {t.approved > 0 && <span className="badge approved">{t.approved} khối</span>}
                            {t.draft > 0 && <span className="badge draft">{t.draft} nháp</span>}
                          </>
                        )}
                      </td>
                    </tr>,
                  ];
                })}
              </tbody>
            </table>
          </details>
        );
      })}
    </div>
  );
}
