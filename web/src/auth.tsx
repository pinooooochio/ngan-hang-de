import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api, ApiError, type Me, type Role } from "./api";

interface AuthState {
  me: Me;
  reload: () => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthState | null>(null);

/** Người đang đăng nhập (trang chỉ hiện khi đã đăng nhập nên luôn có). */
export function useAuth(): AuthState {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth dùng ngoài AuthProvider");
  return ctx;
}

export const isStaff = (role: Role) => role === "admin" || role === "editor";

/** Trang đầu tiên sau khi đăng nhập theo vai trò. */
export const homeOf = (role: Role) => (role === "student" ? "/luyen" : "/");

interface Props {
  /** Hiện khi chưa đăng nhập; `setup` = chưa có tài khoản nào, cần tạo admin đầu tiên. */
  login: (setup: boolean, done: () => void) => ReactNode;
  children: ReactNode;
}

export function AuthProvider({ login, children }: Props) {
  const [me, setMe] = useState<Me | null>(null);
  const [setup, setSetup] = useState<boolean | null>(null);

  const reload = useCallback(async () => {
    try {
      setMe(await api.me());
      setSetup(false);
    } catch (e) {
      setMe(null);
      const data = e instanceof ApiError ? (e.data as { setup?: boolean } | null) : null;
      setSetup(!!data?.setup);
    }
  }, []);

  useEffect(() => {
    reload();
    const onLost = () => setMe(null);
    window.addEventListener("nhd:unauthorized", onLost);
    return () => window.removeEventListener("nhd:unauthorized", onLost);
  }, [reload]);

  const logout = useCallback(async () => {
    await api.logout().catch(() => undefined);
    setMe(null);
    setSetup(false);
  }, []);

  if (setup === null) return null;
  if (!me) return <>{login(setup, reload)}</>;
  return <AuthContext.Provider value={{ me, reload, logout }}>{children}</AuthContext.Provider>;
}
