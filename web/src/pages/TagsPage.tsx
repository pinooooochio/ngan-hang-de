import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Curriculum, type TagMove, type TagNode } from "../api";

/** Chuyển câu giữa các thẻ: theo quy tắc chuyển khung cũ trong khung chương trình, hoặc tự chọn. */
export default function TagsPage() {
  const [tags, setTags] = useState<TagNode[]>([]);
  const [moves, setMoves] = useState<TagMove[]>([]);
  const [cur, setCur] = useState<Curriculum | null>(null);
  const [source, setSource] = useState("");
  const [target, setTarget] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");

  const load = () => {
    api.tags().then(setTags);
    api.tagMoves().then(setMoves);
  };
  useEffect(() => {
    load();
    api.genCurriculum().then(setCur);
  }, []);

  const run = async (fn: () => Promise<string>) => {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      setMessage(await fn());
      load();
    } catch (e) {
      setError(String((e as Error).message));
    } finally {
      setBusy(false);
    }
  };

  // Gợi ý thẻ đích: các chương, chủ đề, dạng trong khung chương trình và thẻ đang có
  const suggestions = [
    ...new Set([
      ...(cur?.grades.flatMap((g) => [
        g.ten,
        ...g.chuong.map((c) => `${g.ten} / ${c.ten}`),
        ...g.chu_de.flatMap((t) => [t.names.join(" / "), ...t.dang.map((d) => [...t.names, d].join(" / "))]),
      ]) ?? []),
      ...tags.map((t) => t.names.join(" / ")),
    ]),
  ];
  const pending = moves.filter((m) => m.count > 0);
  const src = tags.find((t) => t.path === source);

  return (
    <div className="tags-page">
      <h2>Quản lý thẻ</h2>
      <p className="hint">
        Chuyển câu hỏi từ thẻ này sang thẻ khác. Câu được thay thẻ trong nhánh nguồn, các thẻ khác của câu giữ nguyên; nhánh
        không còn câu nào thì tự xoá. Đề đã ghép giữ nguyên nội dung.
      </p>
      {error && <div className="alert error">{error}</div>}
      {message && <div className="alert ok">{message}</div>}

      <section className="section-card">
        <h3>Chuyển từ khung đại học cũ</h3>
        {pending.length === 0 ? (
          <div className="muted">Không còn câu nào ở thẻ của khung cũ.</div>
        ) : (
          <>
            <table className="table">
              <thead>
                <tr>
                  <th>Thẻ cũ</th>
                  <th>Chuyển sang</th>
                  <th>Số câu</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {pending.map((m) => (
                  <tr key={m.from}>
                    <td>{m.from}</td>
                    <td>{m.to}</td>
                    <td>{m.count}</td>
                    <td>
                      <button
                        className="link"
                        disabled={busy}
                        onClick={() => run(async () => `Đã chuyển ${(await api.moveTag(m.from, m.to)).moved} câu sang ${m.to}.`)}
                      >
                        Chuyển
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="hint">
              Số câu của dòng "Đại học / môn" gồm cả các dòng cụ thể hơn; bấm "Chuyển tất cả" thì dòng cụ thể được áp dụng trước.
              Câu chuyển tới tầng chương thì vào <Link to="/">Ngân hàng</Link>, lọc theo chương, chọn câu rồi "Đổi thẻ" sang chủ đề
              chi tiết; câu không cần nữa thì chọn rồi "Xoá".
            </p>
            <button
              className="primary"
              disabled={busy}
              onClick={() => run(async () => `Đã chuyển ${(await api.applyTagMoves()).moved} câu theo khung mới.`)}
            >
              Chuyển tất cả
            </button>
          </>
        )}
      </section>

      <section className="section-card">
        <h3>Chuyển một nhánh thẻ</h3>
        <div className="move-form">
          <label>
            Thẻ nguồn (cả các thẻ con)
            <select value={source} onChange={(e) => setSource(e.target.value)}>
              <option value="">Chọn thẻ…</option>
              {tags.map((t) => (
                <option key={t.path} value={t.path}>
                  {"  ".repeat(t.depth) + t.name} ({t.count})
                </option>
              ))}
            </select>
          </label>
          <label>
            Thẻ đích
            <input list="tag-targets" value={target} onChange={(e) => setTarget(e.target.value)} placeholder="Giải tích 1 / Chương 1. Hàm số một biến số" />
            <datalist id="tag-targets">
              {suggestions.map((x) => (
                <option key={x} value={x} />
              ))}
            </datalist>
          </label>
          <button
            className="primary"
            disabled={busy || !source || !target.trim()}
            onClick={() =>
              run(async () => {
                const r = await api.moveTag(source, target);
                setSource("");
                return `Đã chuyển ${r.moved} câu sang ${target}.`;
              })
            }
          >
            Chuyển{src ? ` ${src.count} câu` : ""}
          </button>
        </div>
        <p className="hint">Nếu thẻ đích nằm trong thẻ nguồn (ví dụ chương sang một chủ đề của chương) thì chỉ chuyển câu gắn đúng thẻ nguồn.</p>
      </section>
    </div>
  );
}
