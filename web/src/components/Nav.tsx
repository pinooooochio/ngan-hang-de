import { useEffect, useRef, useState } from "react";
import { Link, useLocation } from "react-router-dom";

interface Page {
  to: string;
  label: string;
  /** Đường dẫn hiện tại có thuộc trang này không (mặc định: trùng khớp). */
  match?: (path: string) => boolean;
}

interface Module {
  key: string;
  label: string;
  /** Trang mở khi bấm vào module. */
  to: string;
  pages: Page[];
  /** Không hiện trên thanh trên cùng (các trang mở từ menu góc phải). */
  hidden?: boolean;
}

const under = (prefix: string) => (p: string) => p === prefix || p.startsWith(prefix + "/");

export const MODULES: Module[] = [
  {
    key: "bank",
    label: "Ngân hàng câu hỏi",
    to: "/",
    pages: [
      { to: "/", label: "Danh sách câu", match: (p) => p === "/" || (p.startsWith("/cau/") && p !== "/cau/moi") },
      { to: "/cau/moi", label: "Soạn câu mới" },
      { to: "/import", label: "Import" },
      { to: "/sinh", label: "Sinh câu AI", match: under("/sinh") },
      { to: "/the", label: "Quản lý thẻ" },
    ],
  },
  {
    key: "exams",
    label: "Đề thi",
    to: "/de",
    pages: [
      { to: "/de", label: "Kho đề", match: (p) => under("/de")(p) && p !== "/de/moi" },
      { to: "/de/moi", label: "Ghép đề" },
    ],
  },
  {
    key: "practice",
    label: "Luyện đề",
    to: "/luyen",
    pages: [
      { to: "/luyen", label: "Chọn đề làm", match: (p) => under("/luyen")(p) && p !== "/luyen/ket-qua" },
      { to: "/luyen/ket-qua", label: "Lịch sử và thống kê" },
    ],
  },
  {
    key: "settings",
    label: "Cài đặt",
    to: "/sao-luu",
    hidden: true,
    pages: [{ to: "/sao-luu", label: "Sao lưu và khôi phục" }],
  },
];

const isPage = (page: Page, path: string) => (page.match ? page.match(path) : page.to === path);
const moduleOf = (path: string) => MODULES.find((m) => m.pages.some((p) => isPage(p, path)));

/** Thanh trên cùng: các module lớn, menu cài đặt bên phải, hàng tab con của module đang mở. */
export default function Nav() {
  const { pathname } = useLocation();
  const current = moduleOf(pathname);

  return (
    <header className="topbar">
      <div className="topbar-main">
        <Link to="/" className="brand">
          Ngân hàng đề
        </Link>
        <nav className="modules">
          {MODULES.filter((m) => !m.hidden).map((m) => (
            <Link key={m.key} to={m.to} className={current?.key === m.key ? "active" : ""}>
              {m.label}
            </Link>
          ))}
        </nav>
        <SettingsMenu />
      </div>
      {current && (
        <nav className="subnav">
          {current.pages.map((p) => (
            <Link key={p.to} to={p.to} className={isPage(p, pathname) ? "active" : ""}>
              {p.label}
            </Link>
          ))}
        </nav>
      )}
    </header>
  );
}

function SettingsMenu() {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  const { pathname } = useLocation();

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

  return (
    <div className="account-menu" ref={box}>
      <button className="account-btn" aria-haspopup="menu" aria-expanded={open} onClick={() => setOpen(!open)}>
        Cài đặt <span className="caret">▾</span>
      </button>
      {open && (
        <div className="menu-pop" role="menu">
          <Link to="/sao-luu" role="menuitem">
            Sao lưu và khôi phục
          </Link>
        </div>
      )}
    </div>
  );
}
