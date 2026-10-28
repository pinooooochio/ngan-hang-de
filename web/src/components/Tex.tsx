import { useEffect, useRef } from "react";
import { api, type FigureResult } from "../api";
import { latexToHtml } from "../latex";

declare global {
  interface Window {
    MathJax?: {
      typesetPromise?: (els: HTMLElement[]) => Promise<void>;
      typesetClear?: (els: HTMLElement[]) => void;
      startup?: { promise?: Promise<void> };
    };
  }
}

// Gom các lần vẽ công thức lại, MathJax không chạy song song tốt
let queue: Promise<void> = Promise.resolve();

function typeset(el: HTMLElement) {
  queue = queue.then(async () => {
    const mj = window.MathJax;
    if (!mj?.startup?.promise) return;
    await mj.startup.promise;
    mj.typesetClear?.([el]);
    await mj.typesetPromise?.([el]).catch(() => undefined);
  });
}

// Mỗi mã hình chỉ hỏi máy chủ một lần trong phiên làm việc
const figureCache = new Map<string, Promise<FigureResult>>();

function loadFigure(code: string): Promise<FigureResult> {
  let p = figureCache.get(code);
  if (!p) {
    p = api.figure(code).catch((e: Error) => {
      figureCache.delete(code);
      return { id: "", ok: false, error: e.message };
    });
    figureCache.set(code, p);
  }
  return p;
}

/** Thay các chỗ trống hình vẽ bằng ảnh SVG (hoặc thông báo lỗi biên dịch hình). */
function drawFigures(el: HTMLElement, figures: string[]) {
  el.querySelectorAll<HTMLElement>("[data-fig]").forEach((span) => {
    const code = figures[Number(span.dataset.fig)];
    loadFigure(code).then((r) => {
      if (!el.contains(span)) return; // nội dung đã đổi
      if (r.ok) {
        const img = document.createElement("img");
        img.src = `/api/figures/${r.id}.svg`;
        img.alt = "Hình vẽ";
        img.className = "tex-figure-img";
        // SVG tính theo pt; phóng lên cho bằng cỡ chữ trên màn hình (1pt ≈ 1,33px)
        img.onload = () => (img.style.width = `${Math.round(img.naturalWidth * 1.33)}px`);
        span.replaceWith(img);
      } else {
        span.className = "tex-figure error";
        span.textContent = `[Hình vẽ lỗi: ${r.error}]`;
      }
    });
  });
}

/** Hiển thị một đoạn nội dung LaTeX (chữ + công thức + hình TikZ). */
export default function Tex({ source, inline = false }: { source: string; inline?: boolean }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const figures: string[] = [];
    el.innerHTML = latexToHtml(source, figures);
    typeset(el);
    if (figures.length) drawFigures(el, figures);
  }, [source]);
  return inline ? <span ref={ref} className="tex" /> : <div ref={ref as React.RefObject<HTMLDivElement>} className="tex" />;
}
