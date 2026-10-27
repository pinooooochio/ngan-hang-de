# Ngân hàng đề

Ngân hàng câu hỏi Toán soạn bằng LaTeX: import câu hỏi theo định dạng `ex_test`, gắn thẻ theo cây
Lớp > Chủ đề > Dạng bài và mức độ (NB, TH, VD, VDC), sinh nhiều mã đề có đảo câu và đảo đáp án,
xuất PDF đề, lời giải và bảng đáp án.

Hiện có: lõi + dòng lệnh `nhd` (giai đoạn 1), giao diện web soạn, import, tìm câu hỏi (giai đoạn 2),
ghép đề và tải PDF trên web (giai đoạn 3), luyện đề có chấm điểm (giai đoạn 4), sinh câu hỏi bằng AI theo lớp / chủ đề / mức độ (giai đoạn 5).
Kiến trúc tổng thể và lộ trình nằm trong tài liệu "Kiến trúc ngân hàng đề LaTeX".

## Chạy bằng Docker (khuyên dùng)

```bash
docker compose up -d --build
```

Mở http://localhost:8000. Lệnh này chạy PostgreSQL và máy chủ web (có sẵn XeLaTeX để xem trước PDF).
Dữ liệu nằm trong volume `pgdata`, PDF của các đề trong volume `files`; tắt máy chủ không mất, nhưng
`docker compose down -v` hoặc gỡ Docker thì mất, nên hãy sao lưu (mục **Sao lưu** bên dưới). Dùng dòng lệnh bên trong container:

```bash
docker compose exec app nhd import examples/vecto-khong-gian.tex
docker compose exec app nhd build examples/de-vecto.toml    # PDF ra thư mục ./out
```

Để sinh câu hỏi trực tiếp bằng Claude, tạo file `.env` cạnh `docker-compose.yml` với dòng
`ANTHROPIC_API_KEY=...` rồi chạy lại `docker compose up -d`.

Giao diện web chưa có đăng nhập (giai đoạn này chỉ một người dùng), nên cổng 8000 chỉ mở cho chính máy đó.

## Sao lưu và khôi phục

Trang **Sao lưu** (`/sao-luu`) có nút **Tải bản sao lưu**: một file `.zip` chứa toàn bộ dữ liệu (câu hỏi kể cả nháp, thẻ,
khung đề, kho đề cùng mã đề và đáp án, lượt luyện, lịch sử sinh AI) và tuỳ chọn kèm các PDF đã biên dịch. **Khôi phục từ
file** đọc thử file, cho xem số câu / đề / lượt luyện bên trong, rồi mới thay toàn bộ dữ liệu hiện có; trước khi ghi đè máy
chủ tự lưu một bản dữ liệu hiện tại (`truoc-khoi-phuc-*.zip`). Khôi phục chạy trong một giao dịch: file hỏng hay lỗi giữa
chừng thì dữ liệu cũ còn nguyên. File sao lưu dùng được giữa PostgreSQL và SQLite, và giữa các máy.

Các bản lưu trên máy chủ nằm trong thư mục `./backups` cạnh `docker-compose.yml` (trên ổ máy thật, không nằm trong Docker).
Nút **Xuất câu hỏi ra .tex** cho file định dạng soạn, đọc được bằng mắt và import lại ở trang Import (chỉ gồm câu hỏi).

Dòng lệnh:

```bash
docker compose exec -T app nhd backup                    # lưu vào ./backups/nhd-saoluu-<ngày giờ>.zip
docker compose exec -T app nhd backup --giu 14 --khong-pdf   # chỉ giữ 14 bản gần nhất, không kèm PDF
docker compose exec -T app nhd restore /app/backups/nhd-saoluu-20261027-020000.zip
```

Sao lưu định kỳ: hẹn giờ chạy lệnh trên bằng công cụ của máy (máy chủ phải đang chạy).

- macOS / Linux: `crontab -e`, thêm dòng (2 giờ sáng hằng ngày, sửa đường dẫn thư mục):
  `0 2 * * * cd /đường/dẫn/ngan-hang-de && docker compose exec -T app nhd backup --giu 14`
- Windows: Task Scheduler → Create Basic Task → Daily → Start a program `docker`, arguments
  `compose exec -T app nhd backup --giu 14`, Start in: thư mục `ngan-hang-de`.

Nên cho thư mục `backups` đồng bộ lên Google Drive / OneDrive (hoặc chép ra ổ ngoài) để còn dữ liệu khi hỏng máy.

## Giao diện web

- **Ngân hàng câu hỏi**: cây thẻ bên trái kèm số câu mỗi nhánh; lọc theo mức độ, loại câu, trạng thái
  (nháp / đã duyệt) và tìm theo nội dung hoặc mã câu. Chọn nhiều câu để gắn thêm thẻ, đổi thẻ (bỏ thẻ cũ),
  đặt mức độ, duyệt hoặc xoá (câu đã nằm trong đề được giữ lại).
- **Quản lý thẻ** (link dưới cây thẻ, `/the`): chuyển mọi câu của một nhánh thẻ sang thẻ khác, nhánh trống tự xoá.
  Có sẵn bảng chuyển câu từ khung đại học cũ (`Đại học / Giải tích / ...`) sang khung mới theo các quy tắc
  `[[doi_the]]` trong `chuong-trinh.toml`; câu cũ chỉ chuyển được tới tầng chương, sau đó lọc theo chương trong
  ngân hàng và **Đổi thẻ** sang chủ đề chi tiết.
- **Soạn câu**: ô soạn LaTeX đúng định dạng bên dưới, bên phải xem trước công thức ngay khi gõ (MathJax)
  cùng lỗi và cảnh báo; nút **Xem PDF** biên dịch câu bằng XeLaTeX để thấy đúng như khi in.
  Câu mới lưu ở trạng thái nháp, bấm **Lưu và duyệt** để dùng được khi sinh đề.
- **Import**: dán nội dung hoặc chọn file `.tex`, bấm **Kiểm tra** để xem từng câu là mới, trùng hay lỗi;
  có thể gắn thêm một thẻ cho mọi câu, đặt mức độ cho câu chưa có, rồi chỉ lưu những câu đã chọn.

- **Ghép đề**: nhập tiêu đề, ngày, thời gian, số mã đề; nút **Điền cấu trúc THPT 2025** tạo sẵn 3 phần
  (12 câu trắc nghiệm, 4 câu đúng/sai, 6 câu trả lời ngắn). Mỗi phần chọn câu theo ma trận (thẻ × mức độ × số câu,
  bên cạnh hiện số câu đã duyệt ngân hàng đang có) và/hoặc chọn tay từng câu. Thiếu câu thì nút **Tạo đề** bị khoá
  và hiện rõ dòng nào thiếu.

  **Khung đề**: lưu các phần, loại câu, điểm, ma trận, thời gian và số mã đề thành khung có tên để lần sau chọn lại;
  sửa rồi **Lưu đè khung** hoặc **Lưu thành khung mới**; **Xuất file** / **Nhập file** (.json) để chuyển khung giữa các
  máy. Câu chọn tay không lưu vào khung. Trang một đề trong kho có nút **Ghép đề theo khung này**.
- **Kho đề**: danh sách đề đã tạo. Trang mỗi đề có file PDF từng mã đề (đề, đáp án + lời giải, bảng đáp án),
  tải tất cả dạng .zip, bảng đáp án, xem lại đề từng mã đề.

- **Luyện đề**: làm một mã đề trong kho (có thể tính giờ theo thời gian của đề), hoặc luyện nhanh N câu
  ngẫu nhiên theo thẻ và mức độ. Khi làm bài có đồng hồ đếm ngược, bảng số câu, tự lưu câu trả lời (tải lại
  trang vẫn còn) và tự nộp khi hết giờ. Nộp xong thấy điểm, câu nào đúng sai, đáp án và lời giải; có nút
  luyện lại các câu chưa đúng. Trang luyện đề có lịch sử và tỉ lệ điểm theo mức độ, theo lớp và chủ đề.

  Chấm theo thang đề THPT 2025: trắc nghiệm 0,25 điểm mỗi câu; đúng/sai 4 ý được 0,1 / 0,25 / 0,5 / 1 điểm
  khi đúng 1 / 2 / 3 / 4 ý; trả lời ngắn 0,5 điểm (so theo giá trị số, chấp nhận dấu phẩy thập phân);
  tự luận không chấm tự động. Phần nào đặt "điểm mỗi câu" khi ghép đề thì dùng điểm đó.

- **Sinh câu AI**: bảng độ phủ chủ đề × mức độ của từng lớp hoặc học phần (theo khung chương trình trong
  `src/nganhangde/templates/chuong-trinh.toml`, cộng các chủ đề đã có trong ngân hàng), tô màu theo mục tiêu số câu
  mỗi ô. Đại học theo khung Bách khoa, mỗi học phần một nhánh thẻ bốn tầng
  `Giải tích 1 / Chương 1. Hàm số một biến số / <chủ đề> / <dạng>`; bảng độ phủ chia theo chương. Giải tích 1 lấy
  theo đề cương (kiến thức trọng tâm và định hướng câu trắc nghiệm / tự luận được đưa vào prompt); Giải tích 2, 3,
  Đại số, Xác suất thống kê là bản nháp, sửa trong file khung chương trình. Bấm một ô để điền yêu cầu (dạng bài, loại câu, số câu, yêu cầu thêm), rồi:
  - **Sinh bằng Claude**: máy chủ gọi Claude API chạy nền, cần biến `ANTHROPIC_API_KEY` (mô hình đổi bằng `NHD_MODEL`,
    mặc định `claude-opus-5-5`). Prompt hệ thống cố định nên được cache giữa các lần gọi.
  - **Lấy prompt**: chép prompt dán vào Claude, dán câu trả lời lại để kiểm tra rồi lưu. Không cần khoá API.

  Prompt gồm định dạng ex_test, quy tắc từng loại câu theo đề THPT 2025 (trả lời ngắn tối đa 4 kí tự, đúng/sai 4 ý
  có cả đúng lẫn sai...), định nghĩa mức độ, câu mẫu đã duyệt cùng chủ đề và danh sách câu đã có để tránh trùng.
  Kết quả được kiểm tra tự động: đúng định dạng, đúng loại câu, đúng một đáp án, trùng với ngân hàng; thẻ và mức độ
  được ép theo ô đã chọn. Câu hợp lệ vào ngân hàng ở trạng thái **nháp**, nguồn `AI #<số lần sinh>`; nút **Duyệt**
  mở ngân hàng lọc đúng các câu đó để đọc lại, sửa và duyệt. AI có thể sai, nên luôn đọc lời giải trước khi duyệt.

  Dòng lệnh: `nhd prompt --lop "Lớp 12" --chu-de "Nguyên hàm và tích phân" --muc TH --loai mcq --so 10` in prompt;
  `nhd sinh ...` (cùng tham số) gọi Claude API và lưu câu nháp.

PDF được biên dịch nền ngay trong máy chủ (`nhd serve`), trang đề tự cập nhật khi xong. File nào nội dung không
đổi thì dùng lại PDF đã có. Nếu LaTeX lỗi, trang đề chỉ ra câu gây lỗi và dẫn tới trang sửa câu đó.
PDF lưu trong thư mục `files/` (đổi bằng biến `NHD_FILES`).

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
