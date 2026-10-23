# AI STV — Bot Telegram × OpenCode

Bot Telegram dạng agent: nhận yêu cầu, chạy **OpenCode** trong workspace, trả kết quả về chat. Có trí nhớ dài hạn, nhật ký theo ngày, skills, gửi/nhận file, lịch sử hội thoại bền vững và **lướt YouTube, Facebook, TikTok, xem video + đọc ảnh bằng Gemini, đọc tài liệu GitHub** (tìm, đọc nội dung, tải video).

**Model:** **DeepSeek v4.1** là model chính (trả lời, viết code, dùng tool). **Gemini 3.8 Flash** là mắt + tai: đọc ảnh (vật thể, OCR, biểu đồ) và xem video dưới 45 phút; sau đó hai model thảo luận (DeepSeek có thể hỏi lại Gemini bằng tool `ask_gemini`) và DeepSeek viết câu trả lời cuối cùng.

Chạy được trên **Colab, VPS, Linux/macOS và Windows (cmd/PowerShell)** — chỉ cần Python 3.10+ và mạng.

## ⚡ 3 bước

1. `bash push.sh` → quét repo của tài khoản GitHub, cho **chọn repo có sẵn** hoặc tạo mới, rồi push.
2. Thêm `TELEGRAM_BOT_TOKEN` (và `ALLOWED_USER_IDS`) vào 🔑 Secrets của Colab. Muốn bot đọc ảnh/video bằng Gemini thì thêm `GEMINI_API_KEY` (lấy tại [AI Studio](https://aistudio.google.com/apikey)).
3. Dán lệnh này vào ô Colab:

```python
!bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=3)
```

## 1. Tạo bot Telegram

1. Nhắn [@BotFather](https://t.me/BotFather) → `/newbot` → lấy **token** dạng `123456:ABC…`.
2. (Nên làm) Nhắn [@userinfobot](https://t.me/userinfobot) để lấy **user id** của bạn → khoá bot.

## 2. Đưa code lên GitHub

```bash
cd AISTV
bash push.sh                     # quét repo của tài khoản → chọn hoặc tạo mới
bash push.sh owner/repo public   # hoặc chỉ định đúng repo
```

`push.sh` lấy token theo thứ tự: `GITHUB_TOKEN` / `GH_TOKEN` → `.secrets/github_token`
(bot lưu sau `/github login`) → `gh auth token` nếu có. **Không cần cài `gh`.**

> Trên Windows, dùng lệnh git ở dưới hoặc `/github` trong bot (repo chưa có `push.ps1`).

Trong bot Telegram (chủ bot):

```text
/github login                  # kết nối bằng mã, token lưu lâu dài
/github repos                  # quét repo của tài khoản, bấm nút chọn repo đích
/github repo use owner/name    # đặt repo đích bằng chữ
/github repo create ten private  # tạo repo mới rồi tự push code
```

Đổi token sang tài khoản khác: `/github token <PAT>` — nếu repo đang dùng không
truy cập được, bot tự quét repo của tài khoản mới và hiện bảng chọn.

Không có token? Tạo repo trống trên GitHub rồi:

```bash
cd AISTV
git init -b main && git add -A
git commit -m "AI STV — bot Telegram chạy OpenCode"
git remote add origin https://github.com/Phucvncom55/AISTV.git
git push -u origin main
```

> **Không commit `.env`** (đã nằm trong `.gitignore`). Repo public là an toàn vì token chỉ nằm trên máy chạy.

## 3. Chạy bot bằng MỘT lệnh

`bootstrap.sh` luôn cập nhật repo rồi mới chạy `run.sh` bên trong, nên **không bị kẹt bản cũ do cache GitHub**:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=3)
```

Muốn dùng repo khác, truyền link GitHub trực tiếp:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=3) https://github.com/Phucvncom55/AISTV
```

Lần đầu script sẽ: tải repo → đồng bộ token/API key → tạo `.venv` → cài thư viện → cài OpenCode → chạy bot.
Nguồn token: biến môi trường → `.env` của repo → `config.env` dùng chung → repo private
`Phucvncom55/AISTV-secrets` (qua `gh auth`, `AISTV_CONFIG_TOKEN` hoặc Colab Secrets) → chỉ hỏi
trực tiếp khi tất cả đều chưa có.

### Chạy trên Google Colab

1. Dán link repo của bạn vào ô dưới (thay `Phucvncom55/AISTV`), **hoặc** dùng
   `bash <(curl -fsSL .../bootstrap.sh) https://github.com/Phucvncom55/AISTV`.
2. Mở 🔑 **Secrets** (cột trái) → thêm `TELEGRAM_BOT_TOKEN` (và `ALLOWED_USER_IDS`),
   bật **Notebook access**. Tuỳ chọn: thêm `AISTV_CONFIG_TOKEN` (PAT đọc repo
   `AISTV-secrets`) để tự lấy toàn bộ token/API key còn lại.
3. Dán vào một ô code rồi Run:

```python
!bash <(curl -fsSL https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=3)
```

Script tự: clone/cập nhật repo → đồng bộ config từ Colab Secrets / GitHub → chọn Python (venv → hệ thống → uv) → cài thư viện → cài OpenCode → chạy bot.
Không có token ở bất kỳ nguồn nào thì script báo rõ cách thêm, không cài lan man.

> Colab không có terminal tương tác nên **không nhập token bằng tay** được — hãy dùng Secrets
> hoặc `AISTV_CONFIG_TOKEN`, hoặc `!TELEGRAM_BOT_TOKEN=123:abc bash <(curl ...)` nếu không ngại
> lộ token trong notebook. Các giá trị lấy từ Secrets được lưu vào Drive `config.env`, nên các
> phiên sau không cần bật lại quyền đọc Secrets.

### Chạy trên DataCamp (log không nhập được gì)

DataCamp Workspace là notebook, **không có stdin** — mọi prompt bị bỏ qua, script không bao giờ
chờ nhập liệu. Chỉ cần truyền bí mật bằng biến môi trường, một dòng duy nhất:

```bash
TELEGRAM_BOT_TOKEN=123456:ABC... GEMINI_API_KEY=AQ... ALLOWED_USER_IDS=123456789 \
  bash -c "curl -fsSL 'https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=9' | bash"
```

Hoặc chỉ truyền PAT một lần — `run.sh` tự lấy token/API key từ repo private và lưu vào
`~/.config/aistv/config.env` cho các lần sau:

```bash
AISTV_CONFIG_TOKEN=github_pat_xxx \
  bash -c "curl -fsSL 'https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=9' | bash"
```

Trong ô code của DataCamp thì thêm `!` ở đầu:

```python
!TELEGRAM_BOT_TOKEN=123456:ABC... GEMINI_API_KEY=AQ... ALLOWED_USER_IDS=123456789 bash -c "curl -fsSL 'https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=9' | bash"
```

Lưu ý:

- **Chỉ cần `TELEGRAM_BOT_TOKEN`** nếu bí mật đã đồng bộ lên cloud (mặc định bot tự đẩy lên):
  `GEMINI_API_KEY`, GitHub token, email… sẽ tự khôi phục khi khởi động, không phải nhập lại.
- Dùng `curl | bash`, **không** dùng `bash <(curl ...)` — notebook chạy bằng `sh` nên
  process substitution bị lỗi cú pháp.
- Script tự lưu token vào `~/.config/aistv/config.env`; workspace còn file thì lần sau chỉ cần
  `!bash -c "curl -fsSL ... | bash"`.
- Không có TTY nên bước "xác nhận chủ bot" tự bỏ qua (không treo 180s). Muốn khoá bot thì
  đặt `ALLOWED_USER_IDS` — nếu để trống, người nhắn riêng đầu tiên sẽ thành chủ bot.

### Chạy trên Termux (Android)?

**Không nên chạy bot trực tiếp trong Termux.** OpenCode chỉ phát hành binary cho Linux
(glibc/musl), macOS và Windows — **không có bản Android**. Termux dùng libc riêng (bionic) nên
`npm install -g opencode-ai` cài xong sẽ báo lỗi kiểu `cannot execute: required file not found`,
và `aistv_bot.py` sẽ dừng ở bước `Không tìm thấy lệnh opencode`.

Nếu vẫn muốn dùng điện thoại làm server, phải chạy trong **proot-distro Ubuntu**:

```bash
pkg update && pkg install -y proot-distro
proot-distro install ubuntu
proot-distro login ubuntu
# trong Ubuntu: cài python3, git, curl, ffmpeg rồi chạy như Linux bình thường
```

Kèm `termux-wake-lock` và tắt tối ưu pin cho Termux. Tuy vậy Android vẫn hay kill tiến trình
nền, tốn pin/nóng máy — không phù hợp cho bot chạy 24/7.

Cách đúng: bot chạy trên **VPS/cloud free** (Oracle Cloud ARM free tier, Google Cloud e2-micro…),
còn điện thoại chỉ mở Telegram để **ra lệnh bằng giọng nói** — không cần Termux.

### Chạy trên Windows (cmd / PowerShell)

**Cách nhanh — dán 1 dòng vào cmd (không cần PowerShell):**

```bat
curl -fsSL -o "%TEMP%\aistv.bat" "https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.bat?v=1" && call "%TEMP%\aistv.bat"
```

Hoặc trong thư mục repo: nhấp đôi `run.bat` (dùng `bootstrap.bat` nếu muốn tự cập nhật code trước).

`run.bat` / `bootstrap.bat` viết bằng **cmd thuần**, tự tải/cập nhật repo, tạo `.venv`,
cài thư viện, **tự lấy token từ GitHub** (nếu máy đã đăng nhập `gh` hoặc có `AISTV_CONFIG_TOKEN`)
rồi chạy bot — không phụ thuộc PowerShell 5.1/7, chỉ hỏi token khi thật sự chưa có.
Bản PowerShell (`bootstrap.ps1`, `run.ps1`) dùng **cùng logic đồng bộ** với `run.bat` và `run.sh`.

**Cần có sẵn:**

- Python 3.10+: `winget install --id Python.Python.3.12 -e` (nhớ chọn *Add python.exe to PATH*)
- Git: `winget install --id Git.Git -e`
- OpenCode: script tự cài (npm nếu có, không thì tải bản Windows chính thức từ GitHub Releases)

Script tự tạo `.venv`, cài thư viện, tự đồng bộ token/API key từ `.env`, `config.env`
hoặc repo private trên GitHub, rồi chạy bot. Chỉ hỏi token khi cả ba nguồn đều chưa có.
Dữ liệu vẫn ở `%USERPROFILE%\stv_agent` (đổi bằng `STV_HOME`).

> OpenCode khuyến nghị WSL2 để đầy đủ tính năng; bản Windows native (cmd/PowerShell) vẫn chạy được.
> Nếu dùng WSL thì làm theo hướng dẫn Linux ở trên.

### Token bot: tự đồng bộ, không phải nhập lại

Có **3 nơi** lưu bí mật, đều bị `.gitignore` nên không bị push:

| Nơi lưu | Khi nào dùng |
|---|---|
| `.env` cạnh `aistv_bot.py` | riêng cho bản clone đó (ưu tiên cao nhất trong các file) |
| `~/.config/aistv/config.env` (`%USERPROFILE%\.config\aistv\config.env` trên Windows) | **dùng chung** — clone lại repo, đổi `AISTV_DIR` vẫn còn. Trên Colab: `MyDrive/aistv/config.env` |
| repo private `Phucvncom55/AISTV-secrets` | **nguồn chuẩn** để mọi máy đồng bộ; cần `gh` đã đăng nhập, `AISTV_CONFIG_TOKEN` hoặc `AISTV_ENV_URL` |

Thứ tự đọc: biến môi trường → `.env` của repo → `config.env` dùng chung → tải từ GitHub/URL.
Nếu GitHub có key mới hơn, `aistv_config.py sync` cập nhật lại `.env` + `config.env` (trừ biến
môi trường đang được đặt tay).

```dotenv
TELEGRAM_BOT_TOKEN=123456:ABC...
ALLOWED_USER_IDS=123456789
GEMINI_API_KEY=...
```

- **Mọi đường chạy dùng chung một bộ đồng bộ** `aistv_config.py`: `run.bat` (cmd),
  `run.ps1` (PowerShell), `run.sh` (Linux/macOS/Colab/DataCamp) và cả `aistv_bot.py`.
  Sửa `config.env` trên GitHub là máy nào chạy cũng thấy — không còn cảnh cmd hỏi token
  dù token đã có trên GitHub.
- Chỉ **hỏi token khi** cả biến môi trường, `.env`, `config.env` và GitHub/URL đều không có;
  token nhập tay được lưu vào cả hai file.
- Token GitHub để tải repo private lấy theo thứ tự: `AISTV_CONFIG_TOKEN` → `GH_TOKEN` /
  `GITHUB_TOKEN` / `AISTV_GITHUB_TOKEN` → `gh auth token` → Colab Secrets.
  Không cần cài `gh` nếu đã có PAT.
- Trên Colab: thêm `TELEGRAM_BOT_TOKEN` và (tuỳ chọn) `AISTV_CONFIG_TOKEN` vào 🔑 **Secrets**,
  bật *Notebook access*. Lần đầu `run.sh` lưu các giá trị vào Drive `config.env`; các phiên sau
  không cần quyền đọc Secrets nữa.
- Prompt có **giới hạn thời gian** (`AISTV_PROMPT_TIMEOUT`, mặc định 180s) — không bao giờ treo chờ vô hạn.
- Kiểm tra nguồn cấu hình (không in bí mật): `python aistv_config.py doctor`.
- Tắt tự đồng bộ: `AISTV_CONFIG_SYNC=0`. Tắt tải repo private: `AISTV_CONFIG_REPO=0`.
- Khi bot khởi động, token/API key đang có được tự thêm vào `config.env` dùng chung
  (chỉ thêm, không ghi đè giá trị cũ) và các key còn lại khôi phục từ cloud.

### Xác nhận chủ bot kiểu "device flow"

Không cần tự tìm `user id` rồi chép vào `.env`. Khi chưa có `ALLOWED_USER_IDS`, script:

1. Gọi `getMe` → in link dạng `https://t.me/<bot>?start=<mã>`;
2. **Chờ bạn bấm Start** (long-poll `getUpdates`), hiện đếm ngược;
3. Nhận đúng mã → lưu `ALLOWED_USER_IDS` vào `config.env` + `.env` rồi chạy tiếp.

Giống luồng `github.com/login/device`: bạn làm bên ngoài, script đợi rồi tự đi tiếp.

```bash
python aistv_pair.py                      # chạy riêng bước xác nhận
python aistv_pair.py --timeout 300        # chờ lâu hơn (mặc định 180s)
AISTV_PAIR=0 bash run.sh                  # bỏ qua, người nhắn đầu tiên thành chủ bot
```

Hết thời gian chờ → bot vẫn khởi động bình thường (không treo ở bước này).

### Gemini key: không bắt nhập khi chạy

Gemini là **tuỳ chọn** — thiếu key thì bot vẫn chạy, chỉ mất phần đọc ảnh/xem video không phụ đề. `run.sh` **không hỏi** key nữa; có 3 cách thêm:

```bash
# 1. Ngay trong chat Telegram (nhanh nhất, tin nhắn chứa key tự bị xoá)
/key gemini AIza...

# 2. Một dòng lệnh trên máy chủ
echo 'GEMINI_API_KEY=AIza...' >> ~/.config/aistv/config.env

# 3. Truyền lúc chạy — script tự lưu lại
GEMINI_API_KEY=AIza... bash run.sh
```

Muốn buộc script hỏi trong terminal: `AISTV_ASK_GEMINI=1 bash run.sh`.

Trên Colab, nếu đã mount Drive (`/content/drive/MyDrive`), `run.sh` tự dùng `MyDrive/aistv/config.env` → token + key sống qua các phiên, không phải nhập lại. Đổi bằng `AISTV_CONFIG_DIR=/duong/dan/khac`.

### Chạy 1 lệnh, không nhập gì (config trong repo private)

**GitHub Actions secrets không dùng được** cho `bash <(curl ...)`: chúng chỉ tồn tại bên trong runner của Actions, script chạy trên VPS/Colab không đọc được.

Cách chạy được: để `config.env` trong một **repo private**, cho runner tải về bằng PAT chỉ-đọc.
`run.sh`, `run.bat`, `run.ps1` và `aistv_bot.py` đều dùng **cùng một logic** (`aistv_config.py`):

```bash
AISTV_CONFIG_TOKEN=github_pat_xxx \
  bash <(curl -fsSL 'https://raw.githubusercontent.com/Phucvncom55/AISTV/main/bootstrap.sh?v=9')
```

- Repo private đã có sẵn: **`Phucvncom55/AISTV-secrets`** — chứa token bot, Gemini, Groq/OpenAI,
  Cloudflare, email… Sửa `config.env` trên web GitHub là **mọi máy** (Windows cmd, PowerShell,
  Colab, DataCamp, VPS) nhận thay đổi ở lần chạy sau.
- **Máy đã đăng nhập `gh` thì không cần PAT**: cả `run.bat` và `run.sh` tự dùng `gh auth token`.
  Windows chỉ cần dán lệnh `bootstrap.bat` ở trên — không hỏi token nếu repo private đã có.
- **Colab / DataCamp không có `gh`**: đặt `AISTV_CONFIG_TOKEN` một lần (Colab Secrets hoặc biến
  môi trường). Trên Colab, `run.sh` lưu luôn PAT + config vào Drive để các phiên sau không cần nhập lại.
- PAT: *Settings → Developer settings → Fine-grained tokens* → chỉ chọn repo `AISTV-secrets`,
  quyền **Contents: Read-only**.
- Lưu lệnh trên vào ghi chú/alias → các lần sau chạy là bot lên, không hỏi gì.
  Chỉ PAT nằm trong lệnh, không phải token bot.
- Nếu để config ở nơi khác: `AISTV_ENV_URL=https://.../config.env` (tải trực tiếp, không cần token).

Đổi lại: lệnh có chứa PAT. Ai đọc được lệnh thì đọc được đúng repo đó — nên đặt *Contents: Read-only* và chỉ chọn 1 repo.

### Chạy lại / VPS

```bash
cd ~/AISTV && bash run.sh          # đã có .env thì chạy thẳng
```

Windows:

```bat
cd /d "%USERPROFILE%\AISTV"
run.bat
```

Muốn chạy nền trên VPS:

```bash
cd ~/AISTV && nohup bash run.sh > aistv.log 2>&1 &
```

## 4. Dùng bot

| Lệnh | Tác dụng |
|---|---|
| `/start` `/help` | Giới thiệu, hướng dẫn |
| `/new` | Cuộc trò chuyện mới (giữ trí nhớ dài hạn) |
| `/stop` | Huỷ tác vụ đang chạy |
| `/status` | Trạng thái bot, model, thời gian chạy |
| `/model` `/models` | Xem / đổi model OpenCode |
| `/remember` `/memory` `/forget` | Trí nhớ dài hạn |
| `/skills` `/skill <tên> <yêu cầu>` | Kỹ năng chuyên biệt |
| `/skill add <github-url\|owner/repo/path>` | Cài skill chuẩn Agent Skills (chủ bot); thêm `--force`, `--name`, `--ref`, `--allow-restricted` |
| `/files` `/get <đường dẫn>` | Liệt kê / tải file agent tạo |
| `/allow <id>` `/deny <id>` | Cấp / thu hồi quyền (chủ bot) |
| `/key [gemini\|groq\|openai\|jina] [giá trị]` | Xem / đặt API key ngay trong chat (chủ bot); tin nhắn chứa key tự xoá |

**Chủ động & trí nhớ**

| Lệnh | Tác dụng |
|---|---|
| `/remind +30m uống nước` | Hẹn nhắc việc (`+2h`, `20:30`, `mai 8:00`, `25/12 20:00`, `daily 8:00`) |
| `/task daily 9:00 kiểm tra repo` | Để **agent tự chạy** yêu cầu theo lịch rồi gửi kết quả |
| `/reminders` · `/unremind <mã\|all>` | Xem / xoá nhắc việc |
| `/watch git owner/repo [nhánh]` | Báo khi repo có commit mới |
| `/watch log <file> [regex]` | Báo dòng lỗi mới trong log (bot tự theo dõi log của nó) |
| `/watch file <đường dẫn>` | Báo khi file/thư mục thay đổi |
| `/cloud [sync]` | Trạng thái trí nhớ đám mây / đẩy ngay lên Firebase |
| `/summary` | Cô đọng hội thoại hiện tại vào `MEMORY.md` |
| `/email` | Trạng thái kết nối email |
| `/email test` | Kiểm tra đăng nhập IMAP |
| `/email inbox [n]` · `/email unread [n]` | Xem hộp thư / thư chưa đọc |
| `/email read <số\|uid>` | Đọc nội dung một thư |
| `/email send a@b.c \| Tiêu đề \| Nội dung` | Gửi thư |
| `/email setup <email> <app-password>` | Lưu cấu hình (chủ bot) |
| `/email reset` | Xoá cấu hình đã lưu |

- **Trí nhớ đám mây (Firebase RTDB):** `MEMORY.md`, lịch sử chat, nhắc việc và watch được lưu trên cloud nên **restart bot / Colab reset vẫn còn**. Mỗi bot dùng namespace riêng `AISTV_CLOUD_NS/<bot id>`.
- **Bí mật đồng bộ, không phải đăng nhập lại:** Gemini/Groq/OpenAI/Jina key, GitHub token, email, `ALLOWED_USER_IDS`, cấu hình model… được **mã hoá** (PBKDF2-HMAC-SHA256 từ token bot + HMAC-SHA256 + keystream) rồi lưu ở `aistv/<bot id>/secrets`. Chạy bot ở terminal/máy khác chỉ cần đúng bot token là tự khôi phục. Đổi bot token thì blob cũ không giải mã được và bot tự bỏ qua. Đồng bộ ngay: `/cloud sync`.
- **Tự tóm tắt:** sau ~20 lượt hỏi–đáp, bot tự cô đọng phần cũ thành gạch đầu dòng trong `MEMORY.md` rồi cắt bớt lịch sử (giữ ngữ cảnh gần).
- **Nhắc việc/việc định kỳ** sống qua restart; việc định kỳ dùng đúng model và workspace hiện tại.

**Skills (Agent Skills):** bot dùng chuẩn [Agent Skills](https://agentskills.io) — mỗi skill là thư mục có `SKILL.md` (YAML frontmatter `name`, `description`) cùng `scripts/`, `references/`, `assets/` tuỳ chọn. Bot đọc được định dạng [Cursor Agent Skills](https://cursor.com/docs/skills) ở `workspace/skills/`, `workspace/.agents/skills/` và `workspace/.cursor/skills/` (thư mục lồng nhau cũng được; `paths`/`icon`/`color` chưa hỗ trợ). Bot tự đọc danh sách mô tả và chọn skill phù hợp; `/skill <tên> <yêu cầu>` ép dùng một skill, `/skill <tên>` xem thông tin. Skill có `disable-model-invocation: true` chỉ chạy khi gọi bằng `/skill`, không tự gợi ý.

- **Đã cài sẵn** một bộ chọn lọc từ [mattpocock/skills](https://github.com/mattpocock/skills) (MIT) và [anthropics/skills](https://github.com/anthropics/skills) (Apache-2.0): debug, TDD, thiết kế codebase, domain model, PR, prototype, spec/ticket, retro, phản biện kế hoạch, viết lách, dạy học, tạo skill, frontend design, web artifact/testing, MCP server, algorithmic art, theme… Xem `/skills` và `seed/skills/THIRD_PARTY.md`.
- **Cài thêm** ngay trong chat (chủ bot):
  ```text
  /skill add mattpocock/skills/skills/engineering/tdd
  /skill add anthropics/skills/skills/skill-creator
  /skill add https://github.com/owner/repo/tree/main/path/to/skill
  /skill add owner/repo --ref v1.2.0 --force
  ```
  Hỗ trợ `owner/repo`, `owner/repo/path`, URL GitHub (`tree`/`blob`), raw `SKILL.md`, hoặc zip. Nếu trỏ vào repo/thư mục có nhiều skill, bot cài tất cả (tối đa 40). Mặc định **không ghi đè** skill đã có; `--force` để thay.
- **CLI** (dùng khi không mở Telegram):
  ```bash
  python3 aistv_skills.py install mattpocock/skills/skills/engineering/tdd
  python3 aistv_skills.py install anthropics/skills/skills/skill-creator --force
  python3 aistv_skills.py list
  ```
  Mặc định cài vào `$STV_HOME/workspace/skills` (hoặc `~/stv_agent/workspace/skills`).
- **Giới hạn & an toàn:** chỉ tải file, không chạy script khi cài; chặn path traversal/symlink; giới hạn dung lượng. Chỉ cài skill từ nguồn tin cậy — nội dung skill là hướng dẫn cho agent, không được phép ghi đè quy tắc bảo mật hay đọc `.secrets`.
- **Giấy phép:** các skill tài liệu `docx`, `pdf`, `pptx`, `xlsx` của Anthropic dùng giấy phép source-available riêng, **không được nhúng sẵn** trong repo này. Installer mặc định chặn 4 skill này; chỉ dùng `--allow-restricted` sau khi bạn tự đọc và tuân thủ điều khoản. Các skill Anthropic còn lại là Apache-2.0, giữ nguyên `LICENSE.txt`. `doc-coauthoring` (thiếu `LICENSE.txt`) và `canvas-design` (font nặng) cũng không nhúng sẵn; cài riêng nếu cần.

**Email (IMAP/SMTP):** thêm 2 Colab Secret `AISTV_EMAIL_ADDRESS` + `AISTV_EMAIL_PASSWORD` (mật khẩu ứng dụng) rồi bật Notebook access; hoặc `/email setup <email> <app-password>`. Gmail cần bật 2FA và tạo App Password 16 ký tự. Agent cũng gọi được `aistv_email.py` để đọc/gửi thư trong lúc làm việc; mật khẩu không bao giờ bị in ra.

**YouTube (tìm / thông tin / transcript):** agent tự dùng khi bạn gửi link hoặc nhờ tìm video, không cần lệnh riêng. Có thể gọi trực tiếp:

```bash
python3 /root/AISTV/aistv_youtube.py search "từ khoá" -n 5
python3 /root/AISTV/aistv_youtube.py info "URL"
python3 /root/AISTV/aistv_youtube.py transcript "URL" --timestamps
```

Lấy tiêu đề, kênh, thời lượng, lượt xem, mô tả, chương và phụ đề (ưu tiên tiếng Việt, fallback tiếng Anh). Chỉ tải metadata + phụ đề, không tải video.

**Gemini 3.8 Flash — mắt + tai cho ảnh/video (miễn phí):** thêm `GEMINI_API_KEY` vào `.env` hoặc Colab Secrets. Gemini đọc ảnh (nhận diện vật thể, OCR chữ, phân tích biểu đồ) và xem video **dưới 45 phút** (hình ảnh + âm thanh, context 1M token); model dự phòng `gemini-3.7-flash` → `gemini-3.5-flash`. Hạn mức miễn phí tham khảo: **10 RPM, 1500 RPD**; bot tự giữ nhịp và báo khi chạm giới hạn, không treo.

**Luồng 2 model (mặc định):** DeepSeek v4.1 vẫn là **model chính** trả lời người dùng. Khi bạn gửi ảnh/video, Gemini đọc trước và trả về báo cáo thị giác; DeepSeek đối chiếu, phản biện, có thể hỏi lại Gemini bằng tool `ask_gemini` (tối đa `AISTV_VISION_FOLLOWUPS` lần), rồi mới trả lời. Muốn Gemini trả lời trực tiếp như bản cũ: `AISTV_VISION_HANDOFF=0`.

```bash
python3 /root/AISTV/aistv_watch.py doctor
python3 /root/AISTV/aistv_watch.py doctor --json
```

Gửi **ảnh** cho bot kèm câu hỏi → Gemini mô tả, đọc chữ (OCR), phân tích chi tiết; gửi **video** hoặc link YouTube → Gemini xem cả hình ảnh + âm thanh và trả về báo cáo kèm mốc thời gian, sau đó DeepSeek tổng hợp và trả lời. Có thể gọi trực tiếp:

```bash
python3 /root/AISTV/aistv_watch.py image "inbox/anh.jpg" --question "Ảnh này có gì?"
python3 /root/AISTV/aistv_watch.py image "https://.../anh.png" --question "Đọc chữ trong ảnh"
python3 /root/AISTV/aistv_watch.py info "URL"
python3 /root/AISTV/aistv_watch.py watch "URL" --question "Tóm tắt video" --detail balanced
python3 /root/AISTV/aistv_watch.py watch "inbox/video.mp4" --question "..." --detail balanced
python3 /root/AISTV/aistv_watch.py transcript "URL" --timestamps
python3 /root/AISTV/aistv_watch.py frames "URL" --max-frames 24 --at "1:23,4:56"
```

Hoặc dùng lệnh trong chat: `/see <url|đường dẫn> [câu hỏi]` và `/video <url|đường dẫn> [câu hỏi]`.

**Tạo ảnh & sơ đồ tư duy:** `/image <mô tả>` tạo ảnh và gửi thẳng vào chat; thêm `--style anime|3d|watercolor|oil|pixel|minimal|comic|sketch|cyberpunk|poster|logo|infographic|cartoon|fantasy` và `--aspect 16:9`. Reply vào một ảnh rồi gõ `/image --style anime ...` để vẽ lại theo ảnh đó (Gemini). Agent cũng tự gọi tool `generate_image` khi bạn nhờ vẽ/tạo ảnh, poster, logo, infographic hoặc khi một hình ảnh/sơ đồ giúp giải thích rõ hơn.

- `/mindmap <chủ đề>` (hoặc `/image --mindmap <chủ đề>`) → Gemini lập dàn ý, bot vẽ sơ đồ tư duy bằng **Pillow**: chữ tiếng Việt sắc nét, không lỗi font, không cần API ảnh.
- Nguồn tạo ảnh (tự chọn theo key có sẵn): **Gemini** (`gemini-3.1-flash-image`; API free tier hiện cấp **0 lượt** nên cần bật billing), **Cloudflare Workers AI** (`CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN`, có free tier), **Together AI** (`TOGETHER_API_KEY`, model `FLUX.1-schnell-Free`) hoặc **Hugging Face** (`HF_TOKEN`).
- Gọi trực tiếp:

```bash
python3 /root/AISTV/aistv_image.py "mèo phi hành gia" --style anime --aspect 16:9 --json
python3 /root/AISTV/aistv_image.py --mindmap "Kế hoạch học Python" --json
python3 /root/AISTV/aistv_image.py --list-styles
```

Ảnh lưu ở `~/stv_agent/generated/` và được gửi dạng photo (ảnh > 9MB tự thu nhỏ).

**Tin nhắn thoại (nói thay vì gõ):** gửi voice message (hoặc file âm thanh) cho bot → Gemini chép lời
ngay, bot hiện `🎙️ Nghe được: …` rồi xử lý y như tin nhắn chữ (kể cả khi agent đang hỏi lại).
Không cần Whisper, không cần cài thêm gì; `audio/ogg` của Telegram được Gemini đọc trực tiếp,
nếu định dạng lạ thì tự chuyển sang WAV bằng ffmpeg. Giới hạn 20MB/lần của Telegram Bot API.

```bash
python3 /root/AISTV/aistv_watch.py voice "inbox/voice.ogg" --json
python3 /root/AISTV/aistv_watch.py voice "inbox/ghi-am.m4a" -l vi
```

**Watch (xem video bằng hình ảnh + âm thanh):** agent tự dùng khi bạn gửi link hoặc file video và hỏi nội dung. Tải video, lấy phụ đề (hoặc Whisper dự phòng), cắt frames theo cảnh/mốc thời gian rồi tạo `report.md` + `report.json` để agent đọc. Có `GEMINI_API_KEY` thì Gemini 3.8 Flash xem toàn bộ video **dưới 45 phút** (hình ảnh + âm thanh) và trả về báo cáo kèm mốc thời gian; DeepSeek v4.1 đối chiếu, hỏi lại nếu cần (`ask_gemini`) rồi trả lời. Video gửi trực tiếp qua Telegram tối đa **20MB**; video dài/nặng hơn hãy gửi bằng link (YouTube, Drive, URL công khai). Không có key thì agent đọc từng frame bằng công cụ Read và kết hợp transcript. `--start/--end` giới hạn đoạn, `--resolution 1024` để đọc chữ, `--ocr` cho video quay màn hình. Video riêng tư cần `--cookies`; không tải video/audio lên chat.

**Facebook (bài công khai / video / reel):** agent tự dùng khi bạn gửi link Facebook hoặc nhờ tìm. Có thể gọi trực tiếp:

```bash
python3 /root/AISTV/aistv_facebook.py info "URL"
python3 /root/AISTV/aistv_facebook.py read "URL" --comments
python3 /root/AISTV/aistv_facebook.py download "URL" -q sd
python3 /root/AISTV/aistv_facebook.py search "từ khoá" -n 8
```

Đọc được bài viết công khai, tiêu đề/mô tả video, reel, watch; tải video về workspace (bot tự gửi nếu ≤ 45MB). Trang cá nhân, nhóm kín và feed cần đăng nhập nên không xem được.

**TikTok (thông tin / tải video / tìm kiếm / TikTok Lite):** agent tự dùng khi bạn gửi link TikTok hoặc nhờ tìm. Có thể gọi trực tiếp:

```bash
python3 /root/AISTV/aistv_tiktok.py info "URL"
python3 /root/AISTV/aistv_tiktok.py download "URL" -q hd
python3 /root/AISTV/aistv_tiktok.py download "URL" --audio -o .
python3 /root/AISTV/aistv_tiktok.py search "từ khoá" -n 8
python3 /root/AISTV/aistv_tiktok.py resolve "URL"
```

Lấy tiêu đề, tác giả, thời lượng, lượt xem/thích/bình luận/chia sẻ/lưu, nhạc nền; tải video **không watermark** (mặc định bản nét nhất, `-q h264` cho máy cũ) hoặc tách âm thanh MP3. Hỗ trợ link thường, link rút gọn `vt.`/`vm.` và **TikTok Lite** (`lite.tiktok.com/t/...`); link Lite dạng mời/nhận thưởng sẽ báo rõ là không phải video. Video công khai; video riêng tư/giới hạn vùng có thể cần cookie `TIKTOK_COOKIES`. Bài ảnh/slideshow chưa hỗ trợ tải. Gói `curl_cffi` (đã có trong `requirements.txt`) giúp TikTok không chặn IP máy chủ.

Gửi file cho bot → lưu vào `workspace/inbox/` để agent đọc.

**GitHub docs (đọc tài liệu / mã nguồn):** agent dùng token `/github login` sẵn có để đọc repo, README, thư mục `docs/`, tìm trong tài liệu hoặc mã nguồn — không cần clone. Có thể gọi trực tiếp:

```bash
python3 /root/AISTV/aistv_github_docs.py info owner/repo
python3 /root/AISTV/aistv_github_docs.py docs owner/repo -n 40
python3 /root/AISTV/aistv_github_docs.py read owner/repo docs/install.md --section "Quick Start"
python3 /root/AISTV/aistv_github_docs.py search owner/repo "rate limit"
python3 /root/AISTV/aistv_github_docs.py code owner/repo "def handler"
python3 /root/AISTV/aistv_github_docs.py find "vector database" -n 5
python3 /root/AISTV/aistv_github_docs.py releases owner/repo -n 5
```

Đọc được repo công khai và private (nếu token có quyền), hỗ trợ `--ref` để xem đúng tag/nhánh, `--outline`/`--section`/`--lines` cho tài liệu dài và `--json` cho dữ liệu có cấu trúc. Skill `github-docs` hướng dẫn agent chọn đúng tệp, trích nguồn và tránh đổ cả tài liệu vào chat.

**Reply / trích dẫn tin nhắn:** trả lời (reply) một tin nhắn rồi nhắn yêu cầu — agent hiểu các cụm như "cái này", "đoạn trên", "sửa chỗ đó" là chỉ tin nhắn vừa reply. Nếu bôi đen một phần trước khi reply, agent ưu tiên đúng phần được trích dẫn. Reply một tin rồi gõ `/remember` (không kèm nội dung) sẽ lưu chính tin đó vào trí nhớ dài hạn. Ngữ cảnh trích dẫn cũng được ghi vào lịch sử hội thoại kèm nhãn `↪︎ trả lời “…”`.

**Tiến độ kiểu terminal:** trong lúc chạy, tin nhắn "Đang làm việc" tự cập nhật ~1 giây/lần trong một **trích dẫn thu gọn/mở rộng** (`blockquote expandable`); lệnh và code nằm trong khối mã nên dễ đọc trên điện thoại. Dòng cũ rơi khỏi đỉnh khi đầy. `/think off` ẩn suy nghĩ; `/activity on` hiện thêm output chi tiết.

## 5. Biến môi trường

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | — | Token từ BotFather (bắt buộc) |
| `ALLOWED_USER_IDS` | trống | Danh sách user id được phép, cách nhau `,` |
| `AISTV_CONFIG_DIR` | `~/.config/aistv` | Nơi lưu `config.env` dùng chung + hạn mức Gemini |
| `AISTV_PAIR` | `1` | `0` = bỏ bước chờ bấm Start xác nhận chủ bot |
| `AISTV_PAIR_TIMEOUT` | `180` | Số giây chờ xác nhận chủ bot trước khi chạy tiếp |
| `AISTV_PROMPT_TIMEOUT` | `180` | Số giây chờ nhập token/key (chống treo) |
| `AISTV_ASK_GEMINI` | `0` | `1` = hỏi Gemini key trong terminal; mặc định không hỏi |
| `AISTV_CONFIG_REPO` | `Phucvncom55/AISTV-secrets` | `user/repo` private chứa `config.env`; `0` = tắt |
| `AISTV_CONFIG_TOKEN` | tự lấy từ `gh` | PAT chỉ-đọc; cũng nhận `GH_TOKEN` / `GITHUB_TOKEN` / Colab Secrets |
| `AISTV_CONFIG_PATH` | `config.env` | Đường dẫn file cấu hình trong repo private |
| `AISTV_CONFIG_SYNC` | `1` | `0` = không tự tải/đồng bộ config từ xa |
| `AISTV_ENV_URL` | trống | URL tải thẳng `config.env` (không cần token) |
| `STV_HOME` | `~/stv_agent` (`%USERPROFILE%\stv_agent`) | Nơi lưu `workspace/`, `sessions/`, `archive/` |
| `OPENCODE_BIN` | tự tìm | Đường dẫn `opencode` |
| `AISTV_CLEAN_INSTALL` | `1` | `0` = không xoá & cài lại OpenCode mỗi lần chạy |
| `AISTV_VENV` | `1` | `0` = dùng Python hệ thống, không tạo `.venv` |
| `AISTV_REPO` | URL trong `run.sh` / `run.bat` | Repo khác để tải mã nguồn |
| `AISTV_DIR` | `~/AISTV` (`%USERPROFILE%\AISTV`) | Nơi clone khi chạy one-liner |
| `AISTV_BRANCH` | `main` | Nhánh cần tải |
| `AISTV_FIREBASE_URL` | RTDB mặc định | URL Firebase Realtime Database cho trí nhớ đám mây |
| `AISTV_CLOUD` | `1` | `0` = tắt đồng bộ cloud (chỉ lưu cục bộ) |
| `AISTV_CLOUD_NS` | `aistv` | Namespace gốc trên Firebase |
| `AISTV_FIREBASE_SECRET` | trống | `?auth=` nếu Rules yêu cầu xác thực |
| `AISTV_AUTO_SUMMARY` | `1` | `0` = tắt tự tóm tắt hội thoại |
| `AISTV_SUMMARY_ITEMS` / `AISTV_SUMMARY_KEEP` | `40` / `16` | Ngưỡng kích hoạt / số lượt giữ lại |
| `AISTV_PROACTIVE` | `1` | `0` = tắt nhắc việc & theo dõi |
| `AISTV_REMIND_TICK` | `15` | Nhịp kiểm tra nhắc việc (giây) |
| `AISTV_WATCH_INTERVAL` / `AISTV_WATCH_GIT_INTERVAL` | `60` / `300` | Nhịp theo dõi log/file · git |
| `AISTV_WATCH_SELF` | `1` | Tự báo lỗi trong log của chính bot |
| `AISTV_PROGRESS_TICK` | `1` | Giây giữa 2 lần cập nhật khung tiến độ |
| `AISTV_PROGRESS_LINES` | `14` | Số dòng cuộn trong khung tiến độ (dòng cũ rơi khỏi đỉnh) |
| `FB_COOKIES` | trống | File cookie Facebook cho nội dung cần đăng nhập |
| `TIKTOK_COOKIES` | trống | File cookie TikTok cho video riêng tư/giới hạn vùng |
| `YT_COOKIES` | trống | File `cookies.txt` cho YouTube khi bị chặn "confirm you're not a bot" |
| `GEMINI_API_KEY` | trống | Gemini đọc ảnh + xem video (AI Studio, miễn phí) |
| `AISTV_IMAGE_MODEL` / `AISTV_IMAGE_FALLBACKS` | `gemini-3.1-flash-image` / `gemini-3-pro-image,gemini-2.5-flash-image` | Model tạo ảnh Gemini (API free tier = 0 lượt, cần bật billing) |
| `AISTV_IMAGE_PROVIDER` | `auto` | Nguồn tạo ảnh: `gemini`, `cloudflare`, `together`, `hf`, `auto` |
| `CLOUDFLARE_ACCOUNT_ID` + `CLOUDFLARE_API_TOKEN` | trống | Tạo ảnh bằng Cloudflare Workers AI (`FLUX.1-schnell`, có free tier) |
| `TOGETHER_API_KEY` | trống | Tạo ảnh bằng Together AI (`FLUX.1-schnell-Free`) |
| `HF_TOKEN` | trống | Tạo ảnh qua Hugging Face Inference |
| `AISTV_GEN_IMAGE_TIMEOUT` | `300` | Thời gian tối đa một lần tạo ảnh (giây) |
| `GROQ_API_KEY` / `OPENAI_API_KEY` | trống | Transcript dự phòng cho video không có phụ đề |
| `WATCH_GEMINI_MODEL` | `gemini-3.8-flash` | Model Gemini chính: đọc ảnh + xem video (context 1M token) |
| `WATCH_GEMINI_FALLBACKS` | `gemini-3.7-flash,gemini-3.5-flash` | Model dự phòng khi model chính lỗi/hết hạn mức |
| `WATCH_GEMINI_THINKING` | `low` | Mức suy nghĩ khi đọc ảnh/video: `low` (nhanh) hoặc `high` (kỹ hơn) |
| `OPENCODE_MODEL` | `opencode/deepseek-v4.1-flash-free` | Model chính của agent (DeepSeek v4.1); đổi trực tiếp bằng `/model` |
| `GEMINI_RPM` / `GEMINI_RPD` | `10` / `1500` | Tự giữ nhịp request/phút và request/ngày |
| `AISTV_VISION_HANDOFF` | `1` | `1` = Gemini đọc → DeepSeek đối chiếu/hỏi lại → DeepSeek trả lời; `0` = Gemini trả lời trực tiếp |
| `AISTV_VISION_FOLLOWUPS` | `2` | Số lần DeepSeek được hỏi lại Gemini (tool `ask_gemini`) cho mỗi ảnh/video |
| `AISTV_VISION_FOLLOWUP_TIMEOUT` | `240` | Giới hạn thời gian mỗi lần hỏi lại Gemini qua tool (giây) |
| `GEMINI_MAX_RETRIES` | `2` | Số lần thử lại khi Gemini trả 429 |
| `GEMINI_TIMEOUT` | `240` | Thời gian tối đa cho **một** lần gọi Gemini (giây; đủ cho video dài) |
| `GEMINI_DEADLINE` | `600` | Tổng thời gian tối đa cho cả chuỗi model + retry (giây) |
| `GEMINI_QUOTA_DISABLE` | `0` | `1` = tắt theo dõi hạn mức cục bộ |
| `WATCH_MAX_IMAGE_MB` | `50` | Giới hạn ảnh tải từ URL |
| `AISTV_IMAGE_TIMEOUT` / `AISTV_VIDEO_TIMEOUT` | `600` / `900` | Giới hạn thời gian đọc ảnh/video trong chat (giây) |
| `WATCH_MAX_MB` | `600` | Giới hạn dung lượng video tải về |
| `JINA_API_KEY` | trống | Tăng hạn mức đọc web khi tìm kiếm |
| `AISTV_EMAIL_ADDRESS` | trống | Địa chỉ email nhận/gửi |
| `AISTV_EMAIL_PASSWORD` | trống | Mật khẩu ứng dụng (App Password), không phải mật khẩu đăng nhập |
| `AISTV_EMAIL_IMAP_HOST` / `AISTV_EMAIL_IMAP_PORT` | tự nhận / `993` | Máy chủ IMAP |
| `AISTV_EMAIL_SMTP_HOST` / `AISTV_EMAIL_SMTP_PORT` | tự nhận / `587` | Máy chủ SMTP |

Cấu hình nâng cao nằm ở đầu `aistv_bot.py` (model, timeout, số lịch sử, `FULL_ACCESS`, `USE_GOOGLE_DRIVE`).

## 6. Cấu trúc

```
AISTV/
├── aistv_bot.py      bot hoàn chỉnh (cài đặt, agent, Telegram, định dạng)
├── aistv_email.py    đọc/gửi email IMAP·SMTP + CLI cho agent
├── aistv_youtube.py  tìm video, thông tin, transcript YouTube
├── aistv_facebook.py đọc bài công khai, video/reel, tải video Facebook
├── aistv_tiktok.py   thông tin, tải video không watermark, tìm kiếm TikTok
├── aistv_watch.py    đọc ảnh + xem video bằng Gemini, transcript + frames
├── aistv_image.py    tạo ảnh (Gemini/Cloudflare/Together/HF) + vẽ sơ đồ tư duy Pillow
├── aistv_skills.py   cài skill chuẩn Agent Skills từ GitHub/zip
├── aistv_github_docs.py  đọc README/docs, tìm trong tài liệu và mã GitHub
├── aistv_config.py   đồng bộ config/token dùng chung cho mọi runner (sync/check/get/set/doctor)
├── bootstrap.sh      lấy/cập nhật repo rồi chạy run.sh (Linux/macOS/Colab)
├── run.sh            chạy 1 lệnh: clone → cài → chạy (Linux/macOS/Colab)
├── bootstrap.bat     như bootstrap.sh nhưng cho Windows (cmd thuần, khuyên dùng)
├── run.bat           như run.sh nhưng cho Windows (cmd thuần, khuyên dùng)
├── bootstrap.ps1     bản PowerShell của bootstrap.bat (tuỳ chọn)
├── run.ps1           bản PowerShell của run.bat (tuỳ chọn)
├── push.sh           tạo repo GitHub và push (Linux/macOS)
├── requirements.txt
├── .env.example
├── seed/             SOUL.md, AGENTS.md, skills mặc định
├── logs/             (tạo lúc chạy) aistv.log xoay vòng 2MB × 3
└── workspace/        (tạo lúc chạy) trí nhớ, skills, inbox, file agent tạo
```

Dữ liệu chạy nằm ngoài repo tại `STV_HOME` (mặc định `~/stv_agent`), nên cập nhật code không mất trí nhớ.

## 7. Bảo mật

- Luôn đặt `ALLOWED_USER_IDS` nếu bot ở nơi công cộng.
- Token chỉ đọc từ biến môi trường / Colab Secrets / `.env`; agent không nhìn thấy token (đã xoá khỏi môi trường tiến trình con).
- `FULL_ACCESS = False` mặc định: agent chỉ ghi trong workspace và bị OpenCode chặn thao tác cần quyền.
- Repo public **không chứa bí mật**; đừng commit `.env`.
- **Firebase Rules:** mặc định bot chỉ lưu URL database, không nhúng API key. Nếu Rules đang `true` (mở), **ai biết URL cũng đọc/ghi/xoá được** — hãy siết Rules và chỉ cho phép đúng namespace `aistv/<bot id>`, hoặc bật `AISTV_FIREBASE_SECRET`. Không lưu dữ liệu nhạy cảm (mật khẩu, token) vào trí nhớ.
- **Bí mật đồng bộ luôn được mã hoá trước khi gửi cloud** (PBKDF2 + HMAC-SHA256, khoá suy ra từ token bot), nên kể cả Rules mở thì token/API key cũng không đọc được nếu không có token bot. Hội thoại/trí nhớ thì vẫn là văn bản thô — đừng dán mật khẩu vào chat.

## Giấy phép

MIT — xem `LICENSE`.
