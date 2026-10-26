// Chép MathJax vào public/ để giao diện chạy được không cần mạng
import { copyFileSync, mkdirSync } from "node:fs";
mkdirSync("public/mathjax", { recursive: true });
copyFileSync("node_modules/mathjax/es5/tex-svg-full.js", "public/mathjax/tex-svg-full.js");
