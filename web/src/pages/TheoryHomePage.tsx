import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type TheoryTopicSummary } from "../api";
import { useAuth } from "../auth";

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
  const [open, setOpen] = useState<Set<string>>(() => {
    try {
      return new Set(JSON.parse(localStorage.getItem(OPEN_KEY) ?? "[]"));
    } catch {
      return new Set();
    }
  });

  useEffect(() => {
    api
      .theoryTopics()
      .then((r) => setGrades(r.grades))
      .catch((e: Error) => setError(e.message));
  }, []);

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
