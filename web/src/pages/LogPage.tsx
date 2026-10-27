import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type LogEntry, type UserRow } from "../api";

const PAGE = 100;
const fmt = (s: string) => s.replace("T", " ").slice(0, 16);

/** Nhật ký sửa câu của mọi người (admin). Nhật ký từng câu xem ở trang sửa câu. */
export default function LogPage() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [who, setWho] = useState("");
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState<{ total: number; items: LogEntry[] } | null>(null);

  useEffect(() => {
    api.listUsers().then(setUsers);
  }, []);
  useEffect(() => {
    api.allLogs(offset, who || undefined).then(setData);
  }, [offset, who]);

  return (
    <div>
      <h2>Nhật ký sửa câu</h2>
      <div className="filters">
        <select
          value={who}
          onChange={(e) => {
            setWho(e.target.value);
            setOffset(0);
          }}
        >
          <option value="">Mọi người</option>
          {users.map((u) => (
            <option key={u.id} value={u.username}>
              {u.display_name} ({u.username})
            </option>
          ))}
        </select>
        {data && <span className="muted">{data.total} mục</span>}
      </div>
      {data && <LogTable items={data.items} showCode />}
      {data && data.total > PAGE && (
        <div className="pager">
          <button disabled={offset === 0} onClick={() => setOffset(offset - PAGE)}>
            Trước
          </button>
          <button disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>
            Sau
          </button>
        </div>
      )}
    </div>
  );
}

export function LogTable({ items, showCode = false }: { items: LogEntry[]; showCode?: boolean }) {
  const [open, setOpen] = useState<{ id: number; before: string | null } | null>(null);
  if (items.length === 0) return <div className="muted">Chưa có thay đổi nào được ghi.</div>;
  return (
    <table className="table log-table">
      <tbody>
        {items.map((e) => (
          <tr key={e.id}>
            <td className="muted nowrap">{fmt(e.at)}</td>
            {showCode && (
              <td>
                <Link to={`/cau/${encodeURIComponent(e.code)}`} className="code">
                  {e.code}
                </Link>
              </td>
            )}
            <td>{e.username ?? <span className="muted">(không rõ)</span>}</td>
            <td>
              {e.action_name}
              {e.detail && <span className="muted"> · {e.detail}</span>}
              {e.has_before && (
                <>
                  {" "}
                  <button
                    className="link small"
                    onClick={async () =>
                      setOpen(open?.id === e.id ? null : { id: e.id, before: (await api.logEntry(e.id)).before })
                    }
                  >
                    {open?.id === e.id ? "Ẩn bản trước" : "Xem bản trước"}
                  </button>
                  {open?.id === e.id && <pre className="log-before">{open.before}</pre>}
                </>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
