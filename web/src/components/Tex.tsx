import { useEffect, useRef } from "react";
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

/** Hiển thị một đoạn nội dung LaTeX (chữ + công thức). */
export default function Tex({ source, inline = false }: { source: string; inline?: boolean }) {
  const ref = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.innerHTML = latexToHtml(source);
    typeset(el);
  }, [source]);
  return inline ? <span ref={ref} className="tex" /> : <div ref={ref as React.RefObject<HTMLDivElement>} className="tex" />;
}
