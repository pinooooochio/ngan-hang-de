import { Component, type ReactNode } from "react";

interface Props {
  /** Đổi giá trị (ví dụ địa chỉ trang) thì xoá lỗi và vẽ lại. */
  resetKey: string;
  children: ReactNode;
}

/** Lỗi khi vẽ một trang: hiện thông báo thay vì trang trắng; chuyển trang khác (hoặc Quay lại) là dùng tiếp được. */
export default class ErrorBoundary extends Component<Props, { error: Error | null; key: string }> {
  state = { error: null as Error | null, key: this.props.resetKey };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  static getDerivedStateFromProps(props: Props, state: { error: Error | null; key: string }) {
    return props.resetKey !== state.key ? { error: null, key: props.resetKey } : null;
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="alert error">
        Trang gặp lỗi khi hiển thị: {this.state.error.message}.{" "}
        <button className="link" onClick={() => window.location.reload()}>
          Tải lại trang
        </button>
      </div>
    );
  }
}
