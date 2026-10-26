# Ngân hàng đề

Ngân hàng câu hỏi Toán soạn bằng LaTeX: import câu hỏi theo định dạng `ex_test`, gắn thẻ theo cây
Lớp > Chủ đề > Dạng bài và mức độ (NB, TH, VD, VDC), sinh nhiều mã đề có đảo câu và đảo đáp án,
xuất PDF đề, lời giải và bảng đáp án.

Hiện có: lõi + dòng lệnh `nhd` (giai đoạn 1) và giao diện web soạn, import, tìm câu hỏi (giai đoạn 2).
Kiến trúc tổng thể và lộ trình nằm trong tài liệu "Kiến trúc ngân hàng đề LaTeX".

## Chạy bằng Docker (khuyên dùng)

```bash
docker compose up -d --build
```

Mở http://localhost:8000. Lệnh này chạy PostgreSQL và máy chủ web (có sẵn XeLaTeX để xem trước PDF).
Dữ liệu nằm trong volume `pgdata`, không mất khi tắt máy chủ. Dùng dòng lệnh bên trong container:

```bash
docker compose exec app nhd import examples/vecto-khong-gian.tex
docker compose exec app nhd build examples/de-vecto.toml    # PDF ra thư mục ./out
```

Giao diện web chưa có đăng nhập (giai đoạn này chỉ một người dùng), nên cổng 8000 chỉ mở cho chính máy đó.

## Giao diện web

- **Ngân hàng câu hỏi**: cây thẻ bên trái kèm số câu mỗi nhánh; lọc theo mức độ, loại câu, trạng thái
  (nháp / đã duyệt) và tìm theo nội dung hoặc mã câu. Chọn nhiều câu để gắn thêm thẻ, đặt mức độ hoặc duyệt.
- **Soạn câu**: ô soạn LaTeX đúng định dạng bên dưới, bên phải xem trước công thức ngay khi gõ (MathJax)
  cùng lỗi và cảnh báo; nút **Xem PDF** biên dịch câu bằng XeLaTeX để thấy đúng như khi in.
  Câu mới lưu ở trạng thái nháp, bấm **Lưu và duyệt** để dùng được khi sinh đề.
- **Import**: dán nội dung hoặc chọn file `.tex`, bấm **Kiểm tra** để xem từng câu là mới, trùng hay lỗi;
  có thể gắn thêm một thẻ cho mọi câu, đặt mức độ cho câu chưa có, rồi chỉ lưu những câu đã chọn.

Xem trước trên web là gần đúng (hình TikZ và ảnh chỉ hiện ở PDF).

## Cài đặt

Phần này dành cho dùng dòng lệnh trực tiếp trên máy. Cần Python 3.11+ và TeX Live có XeLaTeX, latexmk (Ubuntu/Debian:
`apt install texlive-xetex texlive-latex-extra latexmk`).

```bash
uv venv && uv pip install -e '.[dev]'   # hoặc: pip install -e '.[dev]'
source .venv/bin/activate
```

Cơ sở dữ liệu mặc định là file SQLite `nganhang.db` ở thư mục hiện tại; đổi bằng biến `NHD_DB`
(ví dụ `NHD_DB=postgresql+psycopg://...`).

## Dùng thử

```bash
nhd import examples/vecto-khong-gian.tex --thu   # chỉ kiểm tra, chưa lưu
nhd import examples/vecto-khong-gian.tex         # lưu vào ngân hàng
nhd tags                                         # cây thẻ và số câu
nhd list --the lop-12/vecto-trong-khong-gian --muc TH
nhd show 12V-007
nhd build examples/de-vecto.toml                 # sinh 4 mã đề + PDF vào out/
```

`nhd build` tạo trong `out/<tên-đề>-<ngày>/`: `de-101.pdf` (đề cho học sinh), `loigiai-101.pdf`
(đáp án tô đỏ + lời giải) cho từng mã đề, và `dapan.pdf` (bảng đáp án mọi mã đề).

## Định dạng soạn câu hỏi

```latex
% @tags: Lớp 12 / Vectơ trong không gian / Tích vô hướng ; @level: TH ; @id: 12V-004
\begin{ex}
  Cho $\vec a=(1;m;2)$ và $\vec b=(2;-1;1)$. Giá trị của $m$ để $\vec a\perp\vec b$ là
  \choice
    {\True $m=4$}
    {$m=-4$}
    {$m=2$}
    {$m=0$}
  \loigiai{$2-m+2=0 \Leftrightarrow m=4$.}
\end{ex}
```

| Loại câu | Cách viết |
| --- | --- |
| Trắc nghiệm 4 lựa chọn | `\choice{..}{..}{..}{..}`, đúng 1 lựa chọn có `\True` |
| Đúng/sai 4 ý | `\choiceTF{..}{..}{..}{..}`, `\True` trước mỗi mệnh đề đúng |
| Trả lời ngắn | `\shortans{đáp án}` |
| Tự luận | chỉ có `\loigiai{..}` |

- Dòng `% @...` ngay trên khối khai báo `@tags` (nhiều đường dẫn cách nhau bằng dấu phẩy),
  `@level` (NB, TH, VD, VDC hoặc tên đầy đủ), `@id` (mã câu; bỏ trống thì tự sinh), `@source`.
- Mã ID kiểu ex_test như `%[2H3N1-1]` ngay sau `\begin{ex}` được nhận: chữ số đầu cho lớp,
  chữ cái thứ tư cho mức độ (N/H/V/C), dùng khi không khai báo `@tags`/`@level`.
- `\Pin` trong một lựa chọn giữ nguyên vị trí khi đảo (ví dụ "Cả ba đáp án trên").
- Lời giải không nên ghi "chọn B": chữ cái sẽ sai sau khi đảo. Import sẽ cảnh báo những câu như vậy.
- Câu trùng nội dung với câu đã có sẽ bị bỏ qua khi import.

## Cấu hình đề

Xem `examples/de-vecto.toml`. Mỗi `[[section]]` là một phần của đề, chọn câu theo ma trận
(`pick = [{ tag, level, count }]`) hoặc chọn tay (`ids = [...]`). Thiếu câu ở ô nào thì lệnh báo rõ ô đó.

Khi sinh mã đề: câu được đảo trong từng phần; lựa chọn trắc nghiệm được đảo sao cho số đáp án
A/B/C/D trong mỗi mã đề chênh nhau tối đa 1 và không quá 3 câu liên tiếp cùng chữ; mệnh đề đúng/sai
được đảo thứ tự. Mỗi mã đề lưu seed và bản chụp nội dung, nên sửa câu trong ngân hàng không làm
đổi đề đã sinh.

## Chạy không dùng Docker

```bash
cd web && npm install && npm run build && cd ..   # build giao diện vào src/nganhangde/web
nhd serve                                         # http://127.0.0.1:8000
```

Khi sửa giao diện: chạy `nhd serve` và `cd web && npm run dev` (Vite tự chuyển `/api` sang cổng 8000).

## Kiểm thử

```bash
python -m pytest
NHD_TEST_DB=postgresql+psycopg://user:pass@localhost/testdb python -m pytest   # chạy trên PostgreSQL
```
