// Chuyển phần chữ của nội dung LaTeX sang HTML để xem nhanh trên web.
// Công thức ($...$, \[...\]) giữ nguyên cho MathJax vẽ. Đây chỉ là xem trước gần đúng;
// bản chính xác là PDF biên dịch bằng XeLaTeX.

const MATH_RE = /(\$\$[\s\S]+?\$\$|\$[^$]+?\$|\\\[[\s\S]+?\\\]|\\\([\s\S]+?\\\))/g;

function escapeHtml(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** Đọc nhóm {...} bắt đầu tại s[i] === "{". Trả về [nội dung, vị trí sau "}"] hoặc null. */
function readGroup(s: string, i: number): [string, number] | null {
  while (i < s.length && /\s/.test(s[i])) i++;
  if (s[i] !== "{") return null;
  let depth = 0;
  for (let j = i; j < s.length; j++) {
    const ch = s[j];
    if (ch === "\\") {
      j++;
      continue;
    }
    if (ch === "{") depth++;
    else if (ch === "}" && --depth === 0) return [s.slice(i + 1, j), j + 1];
  }
  return null;
}

/** Thay mọi lệnh \name{a}{b}... bằng kết quả của fn. */
function replaceCommand(s: string, name: string, nargs: number, fn: (args: string[]) => string): string {
  const re = new RegExp(`\\\\${name}(?![A-Za-z])`, "g");
  let out = "";
  let last = 0;
  let m: RegExpExecArray | null;
  while ((m = re.exec(s))) {
    let pos = m.index + m[0].length;
    // bỏ qua tham số tuỳ chọn [..]
    const opt = /^\s*\[[^\]]*\]/.exec(s.slice(pos));
    if (opt) pos += opt[0].length;
    const args: string[] = [];
    let ok = true;
    for (let k = 0; k < nargs; k++) {
      const g = readGroup(s, pos);
      if (!g) {
        ok = false;
        break;
      }
      args.push(g[0]);
      pos = g[1];
    }
    if (!ok) continue;
    out += s.slice(last, m.index) + fn(args);
    last = pos;
    re.lastIndex = pos;
  }
  return out + s.slice(last);
}

function textToHtml(s: string): string {
  let t = escapeHtml(s);
  t = replaceCommand(t, "includegraphics", 1, () => '<span class="tex-figure">[hình ảnh: xem PDF]</span>');
  t = replaceCommand(t, "textbf", 1, ([a]) => `<b>${a}</b>`);
  t = replaceCommand(t, "textit", 1, ([a]) => `<i>${a}</i>`);
  t = replaceCommand(t, "emph", 1, ([a]) => `<i>${a}</i>`);
  t = replaceCommand(t, "underline", 1, ([a]) => `<u>${a}</u>`);
  t = replaceCommand(t, "immini", 2, ([a, b]) => `<div class="tex-immini"><div>${a}</div><div>${b}</div></div>`);
  t = t.replace(/\\begin\{enumerate\}(\[[^\]]*\])?/g, "<ol>").replace(/\\end\{enumerate\}/g, "</ol>");
  t = t.replace(/\\begin\{itemize\}(\[[^\]]*\])?/g, "<ul>").replace(/\\end\{itemize\}/g, "</ul>");
  t = t.replace(/\\item(?![A-Za-z])\s*/g, "<li>");
  t = t.replace(/\\begin\{center\}/g, '<div class="tex-center">').replace(/\\end\{center\}/g, "</div>");
  t = t.replace(/\\\\/g, "<br>");
  t = t.replace(/\n\s*\n/g, "<br><br>");
  t = t.replace(/~/g, "&nbsp;").replace(/---/g, "—").replace(/--/g, "–");
  t = t.replace(/\\(True|Pin|noindent|medskip|smallskip|bigskip|par)(?![A-Za-z])\s*/g, "");
  return t;
}

const TIKZ_RE = /\\begin\{tikzpicture\}[\s\S]*?\\end\{tikzpicture\}/g;

/** Chuyển nội dung LaTeX sang HTML. Mỗi hình TikZ thành một chỗ trống `<span data-fig="i">`
 *  (i là vị trí trong `figures`) để Tex thay bằng ảnh SVG do máy chủ vẽ. */
export function latexToHtml(src: string, figures: string[] = []): string {
  // Tách hình trước, vì trong hình cũng có $...$
  const marked = src.replace(TIKZ_RE, (code) => {
    figures.push(code);
    return `\u0000FIG${figures.length - 1}\u0000`;
  });
  const parts = marked.split(MATH_RE);
  const html = parts.map((p, i) => (i % 2 === 1 ? escapeHtml(p) : textToHtml(p))).join("");
  return html.replace(/\u0000FIG(\d+)\u0000/g, '<span class="tex-figure" data-fig="$1">[đang vẽ hình…]</span>');
}
