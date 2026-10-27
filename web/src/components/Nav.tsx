import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { roleLabel, type Role } from "../api";
import { useAuth } from "../auth";

interface Page {
  to: string;
  label: string;
  /** Đường dẫn hiện tại có thuộc trang này không (mặc định: trùng khớp). */
  match?: (path: string) => boolean;
  /** Vai trò được mở trang (mặc định: như module). */
  roles?: Role[];
}

interface Module {
  key: string;
  label: string;
  /** Trang mở khi bấm vào module. */
  to: string;
  pages: Page[];
  roles: Role[];
  /** Không hiện trên thanh trên cùng (các trang mở từ menu góc phải). */
  hidden?: boolean;
}

const STAFF: Role[] = ["admin", "editor"];
const ALL: Role[] = ["admin", "editor", "student"];
const ADMIN: Role[] = ["admin"];

const under = (prefix: string) => (p: string) => p === prefix || p.startsWith(prefix + "/");

export const MODULES: Module[] = [
  {
    key: "bank",
    label: "Ngân hàng câu hỏi",
    to: "/",
    roles: STAFF,
    pages: [
      { to: "/", label: "Danh sách câu", match: (p) => p === "/" || (p.startsWith("/cau/") && p !== "/cau/moi") },
      { to: "/cau/moi", label: "Soạn câu mới" },
      { to: "/import", label: "Import" },
      { to: "/sinh", label: "Sinh câu AI", match: under("/sinh") },
      { to: "/the", label: "Quản lý thẻ", roles: ADMIN },
    ],
  },
  {
    key: "exams",
    label: "Đề thi",
    to: "/de",
    roles: STAFF,
    pages: [
      { to: "/de", label: "Kho đề", match: (p) => under("/de")(p) && p !== "/de/moi" },
      { to: "/de/moi", label: "Ghép đề" },
    ],
  },
  {
    key: "practice",
    label: "Luyện đề",
    to: "/luyen",
    roles: ALL,
    pages: [
      { to: "/luyen", label: "Chọn đề làm", match: (p) => under("/luyen")(p) && p !== "/luyen/ket-qua" },
      { to: "/luyen/ket-qua", label: "Lịch sử và thống kê" },
    ],
  },
  {
    key: "account",
    label: "Tài khoản",
    to: "/tai-khoan",
    roles: ALL,
    hidden: true,
    pages: [{ to: "/tai-khoan", label: "Tài khoản của tôi" }],
  },
  {
    key: "settings",
    label: "Cài đặt",
    to: "/cai-dat",
    roles: ADMIN,
    hidden: true,
    pages: [
      { to: "/cai-dat/nguoi-dung", label: "Người dùng và phân quyền" },
      { to: "/cai-dat/yeu-cau", label: "Yêu cầu tải đáp án" },
      { to: "/cai-dat/nhat-ky", label: "Nhật ký sửa câu" },
      { to: "/sao-luu", label: "Sao lưu và khôi phục" },
      { to: "/cai-dat", label: "Cài đặt chung" },
    ],
  },
];

const isPage = (page: Page, path: string) => (page.match ? page.match(path) : page.to === path);
const pageRoles = (m: Module, p: Page) => p.roles ?? m.roles;

/** Vai trò này có được mở đường dẫn này không (đường dẫn không thuộc menu nào thì cho mở). */
export function allowed(role: Role, path: string): boolean {
  for (const m of MODULES) {
    const page = m.pages.find((p) => isPage(p, path));
    if (page) return pageRoles(m, page).includes(role);
  }
  return true;
}

/** Thanh trên cùng: các module lớn, menu tài khoản bên phải, hàng tab con của module đang mở. */
export default function Nav() {
  const { pathname } = useLocation();
  const { me, reload } = useAuth();
  // admin: cập nhật số yêu cầu tải đáp án đang chờ mỗi lần chuyển trang
  useEffect(() => {
    if (me.role === "admin") reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname]);
  const visible = MODULES.filter((m) => m.roles.includes(me.role));
  const current = visible.find((m) => m.pages.some((p) => isPage(p, pathname)));
  const pages = current?.pages.filter((p) => pageRoles(current, p).includes(me.role)) ?? [];
  const top = visible.filter((m) => !m.hidden);

  return (
    <header className="topbar">
      <div className="topbar-main">
        <Link to={top[0]?.to ?? "/"} className="brand">
          Ngân hàng đề
        </Link>
        <nav className="modules">
          {top.map((m) => (
            <Link key={m.key} to={m.to} className={current?.key === m.key ? "active" : ""}>
              {m.label}
            </Link>
          ))}
        </nav>
        <AccountMenu />
      </div>
      {pages.length > 1 && (
        <nav className="subnav">
          {pages.map((p) => (
            <Link key={p.to} to={p.to} className={isPage(p, pathname) ? "active" : ""}>
              {p.label}
              {p.to === "/cai-dat/yeu-cau" && !!me.pending_requests && <span className="dot-count">{me.pending_requests}</span>}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}

function AccountMenu() {
  const { me, logout } = useAuth();
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();
  const pending = me.pending_requests ?? 0;

  useEffect(() => setOpen(false), [pathname]);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent) => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    const esc = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", esc);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", esc);
    };
  }, [open]);

  const settings = MODULES.find((m) => m.key === "settings")!;

  return (
    <div className="account-menu" ref={box}>
      <button className="account-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        <span className="avatar">{me.display_name.trim().charAt(0).toUpperCase()}</span>
        <span className="account-name">{me.display_name}</span>
        {pending > 0 && <span className="dot-count">{pending}</span>}
        <span className="caret">▾</span>
      </button>
      {open && (
        <div className="menu-pop" role="menu">
          <div className="menu-head">
            <b>{me.display_name}</b>
            <div className="muted small">
              {me.username} · {roleLabel(me.role)}
            </div>
          </div>
          <hr />
          <Link to="/tai-khoan" role="menuitem">
            Tài khoản của tôi
          </Link>
          {me.role === "admin" &&
            settings.pages.map((p) => (
              <Link key={p.to} to={p.to} role="menuitem">
                {p.label}
                {p.to === "/cai-dat/yeu-cau" && pending > 0 && <span className="dot-count">{pending}</span>}
              </Link>
            ))}
          <hr />
          <button role="menuitem" onClick={logout}>
            Đăng xuất
          </button>
        </div>
      )}
    </div>
  );
}
