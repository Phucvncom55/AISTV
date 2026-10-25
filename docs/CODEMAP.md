# CODEMAP — bản đồ code AISTV

> Tự sinh bởi `scripts/code_map.py` · 24 file Python · 22404 dòng. Đừng sửa tay: chỉnh code rồi chạy lại `python scripts/code_map.py`.

## Cách dùng cho agent

1. Đọc bảng module bên dưới để biết file cần mở.
2. `grep -n "def tên_hàm" <file>` để lấy đúng vùng dòng.
3. Chỉ đọc 60–150 dòng quanh symbol, không đọc cả file.
4. Sửa xong chạy `python scripts/verify.py`.

## Module

| File | Dòng | Mục đích |
|---|---:|---|
| `aistv_bot.py` | 8291 | AI STV AGENT — Telegram × OpenCode (dán 1 ô Colab là chạy) |
| `aistv_browser.py` | 251 | aistv_browser.py — Điều khiển trình duyệt thật bằng Playwright. |
| `aistv_cloudflare.py` | 506 | aistv_cloudflare.py — Cloudflare API wrapper cho bot AI STV. |
| `aistv_config.py` | 738 | AI STV - đồng bộ cấu hình (token / API key) cho MỌI môi trường. |
| `aistv_docs.py` | 259 | aistv_docs.py — Đọc PDF / DOCX / ảnh scan (OCR) hoàn toàn LOCAL. |
| `aistv_email.py` | 505 | Kết nối email IMAP/SMTP cho AI STV — chỉ dùng thư viện chuẩn. |
| `aistv_facebook.py` | 468 | AI STV Facebook helper: đọc bài viết, xem/tải video, tìm kiếm. |
| `aistv_github_docs.py` | 1214 | AI STV GitHub docs helper: xem repo, cây tệp, đọc README/tài liệu, tìm trong docs và mã. |
| `aistv_harness2.py` | 433 | aistv_harness2.py — Cầu nối AI STV ↔ Harness² (google-research/harness2). |
| `aistv_image.py` | 1446 | aistv_image.py — Tạo ảnh & sơ đồ tư duy cho bot AI STV. |
| `aistv_mcp.py` | 139 | aistv_mcp.py — Quản lý MCP server trong opencode.json của workspace. |
| `aistv_memory_index.py` | 240 | aistv_memory_index.py — Tìm kiếm trí nhớ & lịch sử chat bằng SQLite FTS5. |
| `aistv_planner.py` | 533 | aistv_planner.py — kế hoạch tự trị, checkpoint/hoàn tác và kiểm chứng. |
| `aistv_railway.py` | 406 | aistv_railway.py — wrapper Railway CLI cho bot AI STV. |
| `aistv_skills.py` | 880 | Cài / quản lý Agent Skills cho AISTV. |
| `aistv_tiktok.py` | 863 | AI STV TikTok helper: xem thông tin, tải video không watermark, tìm kiếm. |
| `aistv_voice.py` | 210 | aistv_voice.py — Nghe (STT) và nói (TTS) hoàn toàn local. |
| `aistv_watch.py` | 2364 | AI STV Watch: xem video bằng transcript + frames + Gemini (tuỳ chọn). |
| `aistv_web2api.py` | 1707 | AI STV - Gemini Web2API: server nội bộ + đồng bộ cookie dạng chữ. |
| `aistv_youtube.py` | 293 | AI STV YouTube helper: search, info, transcript. |
| `scripts/code_map.py` | 207 | code_map.py — sinh bản đồ code (CODEMAP) để agent định vị nhanh. |
| `scripts/verify.py` | 155 | verify.py — một lệnh kiểm chứng repo trước khi báo "xong". |
| `tests/test_media.py` | 97 | Kiểm tra chọn nguồn media cho Web2API (voice/video) và nhận diện patch. |
| `tests/test_planner.py` | 199 | Smoke test cho scripts/code_map.py và aistv_planner.py. |

## aistv_bot.py

_AI STV AGENT — Telegram × OpenCode (dán 1 ô Colab là chạy)_

```text
L62    def _env_files()
L101   def _load_env_path(path: Path)  — Nạp KEY=VALUE từ một file, không ghi đè biến môi trường đã có.
L122   def _load_dotenv()
L154   def _write_env_var(path: Path, name: str, value: str)  — Ghi/ cập nhật một biến trong file .env kiểu KEY=VALUE.
L183   def save_env_var(name: str, value: str)  — Lưu biến vào .env của repo VÀ config.env dùng chung.
L208   def _persist_shared_config()  — Lưu token + bí mật đang có vào config.env dùng chung (chỉ thêm, không ghi đè).
L340   def _shell_prefix()  — Lệnh shell phù hợp hệ điều hành: bash trên Linux/macOS, PowerShell/cmd trên Windows.
L352   def _sh(cmd: str, timeout: int=900)
L359   def _safe_is_dir(p: Path)  — is_dir() nhưng không nổ khi gặp thư mục không có quyền (vd /root trên Colab/VPS).
L367   def _opencode_dirs()
L388   def _opencode_version(binary: str)  — Chuỗi phiên bản của binary (vd "1.19.4", "opencode v2.1.4"); "" nếu không chạy được.
L404   def _opencode_major(ver: str)
L409   def find_opencode()  — Tìm binary OpenCode, ưu tiên bản v2.
L458   def _npm_cli_targets()  — Tên gói npm chứa binary v2 cho nền tảng hiện tại (khớp CPU/libc trước).
L472   def _install_opencode_npm_tarball()  — Dự phòng khi không có npm/script cài: tải thẳng binary v2 từ gói npm.
L532   def _install_opencode_windows()  — Windows: npm (gói v2) → tải binary v2 từ npm.
L545   def _install_opencode_unix()  — Linux/macOS: tải thẳng binary v2 từ npm (dự phòng khi script cài bị chặn).
L551   def _reset_opencode_cache()
L557   def _upgrade_opencode()  — Nâng OpenCode lên v2 đè lên bản cũ, GIỮ nguyên dữ liệu phiên.
L579   def _opencode_ver_tuple(ver: str)  — Chuỗi phiên bản ("2.1.4" / "opencode v2.1.4") → (2, 1, 4); () nếu không đọc được.
L585   def _opencode_latest_version()  — Bản OpenCode 2 mới nhất trên npm ("" nếu không kiểm tra được).
L595   def _best_opencode(cands: list)  — Chọn binary v2 có phiên bản cao nhất trong danh sách.
L607   def _maybe_update_opencode(binary: str)  — Tự nâng OpenCode 2 lên bản mới nhất trên npm, giữ nguyên phiên.
L638   def setup_environment()
L720   def now()
L724   def esc(s)
L728   def oneline(s: str, n: int)
L736   def _default_home()
L828   def _load_state()
L847   def save_state()
L851   def opencode_model()  — Chuỗi --model đúng cú pháp OpenCode: provider/model#variant.
L876   def get_secret(name: str)  — Đọc từ biến môi trường, nếu không có thì thử 🔑 Secrets của Colab.
L906   def vision_ready()  — Có nguồn đọc ảnh/video/audio: Gemini API hoặc Web2API đã vá media.
L918   def owner_id()
L922   def is_owner(uid: int)
L926   def authorized(uid: int, chat_type: str)
L939   def _addressed_to_bot(msg, context, text: str='')  — Trong nhóm: chỉ coi là gửi cho bot khi @tên bot hoặc reply vào tin của bot.
L949   def _strip_bot_mention(text: str, context)
L962   async def _deny_guest(update: Update, context: ContextTypes.DEFAULT_TYPE)  — Từ chối người lạ dùng lệnh/nút/ảnh/video (chat chữ vẫn được nếu GUEST_CHAT bật).
L986   def guard(owner_only: bool=False)
L1361  def bootstrap_workspace()
L1520  def read_text(p: Path)
L1527  def memory_items()
L1531  def write_memory(items: list)
L1541  def _skill_text_meta(text: str)  — Trả về (frontmatter, body, description). Hỗ trợ chuẩn Agent Skills.
L1559  def _skill_root(path: Path)
L1569  def _skill_name(path: Path)
L1574  def _skill_paths()  — Tìm skill trong skills/, .agents/skills/ và .cursor/skills/ (mọi cấp),
L1614  def _skill_map()
L1618  def list_skills()
L1632  def skill_details(name: str)
L1655  def find_skill(name: str)  — Trả về nội dung skill kèm thư mục/tài nguyên để agent đọc đúng chỗ.
L1695  def log_daily(q: str, a: str)
L1704  def hist_path(chat_id: int)
L1708  def load_history(chat_id: int)
L1721  def rewrite_history(chat_id: int, items: list)
L1727  def append_history(chat_id: int, role: str, content: str)
L1737  def archive_history(chat_id: int)
L1743  def pop_last_exchange(chat_id: int)  — Lấy ra cặp (câu hỏi, câu trả lời) cuối cùng khỏi lịch sử; trả None nếu không có.
L1759  def _ask_pop(ask_id: str, answer: Optional[str]=None, cancelled: bool=False)  — Đánh dấu yêu cầu đã có câu trả lời và đánh thức luồng HTTP đang chờ.
L1774  def _cancel_chat_asks(chat_id: int)
L1781  def _ask_pending(chat_id: int)
L1786  def _ask_keyboard(rec: dict)
L1803  async def _deliver_ask(rec: dict)  — Gửi câu hỏi của agent sang Telegram kèm bảng nút bấm.
L1821  async def _gh_login_notice(chat_id: int, text: str)
L1831  def _sync_config_after_login()  — Sau khi đăng nhập GitHub: kéo token/API key còn thiếu từ repo private.
L1852  async def _deliver_github_login(chat_id: int, rid: str, device: dict)
L1872  async def _gh_login_wait(chat_id: int, rid: str, device: dict)
L1915  class _AskHandler
  L1918  def log_message(self, *args)
  L1921  def _json(self, code: int, payload: dict)
  L1934  def do_POST(self)
  L1944  def _handle_post(self)
  L2042  def _handle_github_login(self, path: str, data: dict)  — Bắt đầu / kiểm tra phiên đăng nhập GitHub bằng mã cho agent.
L2102  class _AskServer
  L2106  def handle_error(self, request, client_address)
L2114  def start_ask_server()  — Mở HTTP server 127.0.0.1 để tool ask_user gọi vào bot.
L2133  def _gh_http(url: str, data: Optional[dict]=None, token: str='', timeout: int=30)
L2148  def _gh_device_start()
L2153  def _gh_device_poll(device_code: str)
L2159  def github_token()  — Token theo thứ tự: env/Colab Secrets → file bền vững → gh CLI.
L2186  def github_token_source()
L2206  def apply_github_config(token: str)  — Cấu hình git credential + gh CLI + user.name/email từ token.
L2253  def save_github_token(token: str)  — Lưu token (chmod 600) + bản sao trên Google Drive nếu đang mount.
L2275  def clear_github_token()
L2304  def _gh_api(path: str, token: str, method: str='GET', payload: Optional[dict]=None, timeout: int=30)
L2330  def gh_all_repos(token: str, refresh: bool=False)  — Toàn bộ repo token nhìn thấy (chủ, cộng tác, tổ chức), mới đẩy lên trước.
L2359  def gh_repo_meta(slug: str, token: str)
L2367  def gh_repo_has_bot(slug: str, token: str)
L2375  def current_repo_slug()  — Repo đích: env → file .secrets/github_repo → state → origin của bản clone.
L2393  def repo_remote_slug()
L2401  def set_repo_slug(slug: str)
L2416  def gh_repo_picker(chat_id: int, token: str, page: int=0, refresh: bool=False)
L2453  def gh_repo_detail(chat_id: int, idx: int)
L2483  def _gh_set_origin(rd: Path, slug: str)
L2491  def gh_switch_repo(slug: str)  — Đổi origin sang repo đã chọn rồi fetch/pull fast-forward.
L2509  def gh_push_code(slug: str)  — Đặt origin về repo đã chọn rồi đẩy code hiện tại lên.
L2527  def gh_create_repo(name: str, token: str, private: bool=False)
L2541  def repo_access(slug: str, token: str)
L2545  def repo_can_push(slug: str, token: str)
L2550  def repo_dir()
L2558  def _git(args: list, cwd: Path, timeout: int=180)
L2567  def restart_bot()  — Thay tiến trình hiện tại bằng bản mới. Không làm trong notebook Colab.
L2604  def _msg_brief(m)  — Nội dung ngắn gọn của một tin nhắn Telegram (chữ, chú thích, loại tệp).
L2621  def reply_context(msg)  — Phân tích tin nhắn đang được trả lời/trích dẫn (Reply Message / Quoting).
L2664  def build_prompt(chat_id: int, user_text: str, skill: Optional[tuple]=None, quote: str='')
L2740  def _redact(s)
L2757  def clean_output(s: str)
L2766  def _clip(s, n: int=PROGRESS_DETAIL)
L2771  def _rel(path)
L2778  def _int(x)
L2785  def _fmt_tok(n: int)  — 1234 -> '1,2k' cho footer gọn trên điện thoại.
L2792  def _note_usage(chat_id: int, tokens: dict, cost=None)  — Cộng dồn token thật OpenCode báo ở mỗi bước (sự kiện step_finish).
L2820  def _headroom_fn()  — Nạp Headroom một lần; máy chưa cài thì trả None (bot vẫn chạy bình thường).
L2835  def _headroom_warm()  — Gọi thử một lần cho Headroom nạp sẵn pipeline (lần đầu mất vài giây).
L2850  def _headroom_shrink(text: str)  — Nén phần ngữ cảnh của prompt (giữ nguyên yêu cầu mới của người dùng).
L2878  async def _headroom_prompt(prompt: str)  — Chạy nén ở luồng riêng, tối đa 2,5 giây — quá giờ thì dùng prompt gốc.
L2888  def _token_footer(chat_id: int, saved: int=0)  — Cụm token cuối tin nhắn: token gốc và phần còn lại sau khi qua Headroom.
L2929  def _tool_entry(part: dict)  — Đổi 1 sự kiện tool_use của OpenCode thành dòng tiến độ gọn cho Telegram.
L3001  def _keep_tool_timing(old: dict, new: dict)  — Cập nhật cùng callID: giữ mốc quan sát đầu tiên để đo thời gian chạy.
L3009  def _dur_text(sec: float)
L3020  def _tool_dur(e: dict, live: bool=True)  — Thời gian tool đang/đã chạy: ' · 35s' (rỗng nếu chưa đo được).
L3038  def _status_rows(chat_id: int, limit: int=PROGRESS_KEEP)
L3052  def _model_base(name: str='')  — Tên model bỏ phần #variant để so sánh.
L3057  def _model_has_no_thinking()  — Model hiện tại đã từng chạy mà không trả reasoning (vd bản flash free).
L3062  def _thinking_text(chat_id: int)
L3069  def _thinking_tail(chat_id: int, n: int=600)
L3074  def _last_action(chat_id: int)
L3085  def _push_live(chat_id: int, kind: str, payload, call: Optional[str]=None)  — Ghi 1 sự kiện vào dòng thời gian để tin nhắn tiến độ cuộn như terminal.
L3108  def _wrap_live(text: str, width: int=44)
L3119  def _code_block(text: str, lang: str='')  — Khối mã kiểu ```lang … ``` để lệnh/code dễ đọc trên Telegram.
L3125  def _live_blocks(chat_id: int, detailed: bool=False)  — Đổi dòng thời gian thành các khối HTML gọn, mới nhất ở cuối.
L3168  def _tail_blocks(blocks: list, max_lines: int=PROGRESS_LINES, max_chars: int=PROGRESS_CHARS)  — Giữ các khối cuối vừa khung; khối cũ rơi khỏi đỉnh (cuộn xuống).
L3184  def _render_status(chat_id: int, started: float, frame: str='🧠')
L3203  async def _iter_lines(stream, max_line: int=4 * 1024 * 1024)  — Đọc theo chunk và tự cắt dòng.
L3240  async def _talk(proc, data: Optional[bytes], chat_id: int, err_lines: list)  — Gửi prompt qua stdin, đọc stdout từng dòng.
L3359  def _is_opencode_error_output(text: str)  — CLI in help/lỗi cú pháp thay vì câu trả lời — đừng gửi nguyên văn cho người dùng.
L3365  def _is_error_payload(text: str)  — OpenCode đôi khi in nguyên JSON/lỗi (UnknownError...) như 'câu trả lời'.
L3413  def _is_error_history(content: str)  — Lọc bỏ nội dung lỗi từng bị lưu nhầm vào lịch sử hội thoại.
L3440  def _is_quota_error(text: str)  — Lỗi hết hạn mức / hết token (không phải lỗi cấu hình model).
L3462  def _is_server_error(text: str)  — Lỗi từ nhà cung cấp model (UnknownError, 5xx...) — cũng nên thử dự phòng.
L3473  def _human_secs(sec: float)  — Đổi số giây thành chuỗi ngắn kiểu '18 giờ 20 phút'.
L3491  def _pretty_error(text: str)  — Rút gọn JSON lỗi của OpenCode thành một dòng dễ đọc.
L3520  def agent_model_chain()  — Model chính + model dự phòng (Gemini Web2API) khi hết hạn mức.
L3539  def _fallback_hint()  — Gợi ý ngắn khi model dự phòng không trả lời được (dựa trên trạng thái thật).
L3561  def _agent_failure(err_text: str, quota: bool=False, tools: bool=False, server: bool=False)
L3587  async def _run_opencode_once(chat_id: int, prompt: str, env: dict, model: str)  — Chạy một lượt OpenCode. Trả (ok, text/lỗi, đã_chạy_tool).
L3648  def _drop_fake_files(text: str)  — Bỏ dòng 'File kết quả: …' khi câu trả lời đến từ đường không có công cụ.
L3659  async def _run_web2api_direct(prompt: str, model: str)  — Gọi thẳng server Web2API, không qua OpenCode.
L3690  def make_checkpoint(chat_id: int, label: str='')  — Chụp repo trước khi agent sửa. Trả checkpoint id ('' nếu không làm được).
L3710  def review_markup(chat_id: int)
L3719  async def _autopush_after_agent(chat_id: int)  — Sau lượt agent: tự push (nếu bật) hoặc hiện diff + nút duyệt.
L3769  async def run_agent(chat_id: int, prompt: str, retries: int=1)  — Trả về (ok, text).
L3843  def snapshot()
L3876  def md_to_tg_html(md: str)
L3911  def split_markdown(text: str, limit: int=SPLIT_LIMIT)  — Chia theo đoạn văn; luôn đóng/mở lại khối code để không vỡ định dạng.
L3955  async def _reply(message, body: str, fallback: str, **kw)
L3966  async def send_rich(message, text: str, footer: str='', markup=None)
L3982  async def send_thinking(message, chat_id: int)  — Gửi phần reasoning của model dưới dạng blockquote mở rộng được.
L4016  async def _ticker(bot, chat_id: int, status, started: float, stop: asyncio.Event)
L4055  async def _finish_status(status, chat_id: int, started: float, ok: bool)  — Chốt tin nhắn tiến độ; ở chế độ gọn thì xoá hẳn để nhường chỗ cho câu trả lời.
L4086  async def send_new_files(message, before: dict)
L4104  async def respond(message, context, chat_id: int, text: str, skill: Optional[tuple]=None, quoted_msg=None, store_text: Optional...
L4159  def plan_keyboard(plan: dict)
L4178  def plans_list_text()
L4195  async def _plan_edit(msg, plan: dict, note: str='')
L4205  async def create_plan(chat_id: int, request: str, msg)
L4234  async def run_plan(chat_id: int, plan_id: str)
L4366  async def push_repo_now()
L4378  async def _q_edit(q, text: str, markup='keep')
L4388  async def _on_review_button(q, data: str)  — Nút ⬆️ Push / ↩️ Hoàn tác / 📄 Xem thay đổi của cổng duyệt.
L4455  async def _on_plan_button(q, data: str)
L4545  @guard() async def cmd_plan(update: Update, context: ContextTypes.DEFAULT_TYPE)
L4587  @guard() async def cmd_undo(update: Update, context: ContextTypes.DEFAULT_TYPE)
L4619  def email_line()
L4631  def image_provider_line()
L4649  def web2api_line()  — Một dòng trạng thái cho /status (không chặn lâu).
L4665  def build_status(chat_id: int)
L4696  def build_skills_index(exclude: Optional[str]=None, limit: int=60)  — Danh sách gọn để agent tự chọn skill phù hợp (progressive disclosure).
L4737  def build_skills_pages(limit: int=3600)
L4765  def build_skills()  — Giữ hàm cũ cho tương thích; nội dung có thể dài hơn 1 tin nhắn Telegram.
L4770  def build_memory()
L4778  def welcome_text()
L4852  @guard() async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE)
L4857  @guard() async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE)
L4862  @guard() async def cmd_new(update: Update, context: ContextTypes.DEFAULT_TYPE)
L4868  @guard() async def cmd_stop(update: Update, context: ContextTypes.DEFAULT_TYPE)
L4884  @guard() async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE)
L4889  @guard() async def cmd_model(update: Update, context: ContextTypes.DEFAULT_TYPE)
L4907  @guard() async def cmd_models(update: Update, context: ContextTypes.DEFAULT_TYPE)
L4930  @guard() async def cmd_think(update: Update, context: ContextTypes.DEFAULT_TYPE)
L4955  @guard() async def cmd_activity(update: Update, context: ContextTypes.DEFAULT_TYPE)
L4976  @guard() async def cmd_variant(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5001  async def _github_connected(bot, chat_id: int, info: dict, tok: str)  — Sau khi có token: kiểm tra repo đích; không truy cập được thì quét repo cho chọn.
L5044  async def _github_repo_cmd(msg, sub: str, args: list, tok: str)  — Xử lý /github repo|repos [list|use owner/name|create tên [private]].
L5129  async def _gh_poll_task(bot, chat_id: int, device: dict)
L5171  @guard(owner_only=True) async def cmd_github(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5264  @guard(owner_only=True) async def cmd_update(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5319  @guard(owner_only=True) async def cmd_push(update: Update, context: ContextTypes.DEFAULT_TYPE)  — Đẩy code hiện tại lên GitHub để Windows CMD chạy run.bat là có bản mới.
L5346  @guard(owner_only=True) async def cmd_restart(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5355  @guard() async def cmd_remember(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5369  @guard() async def cmd_memory(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5374  @guard(owner_only=True) async def cmd_forget(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5388  async def _reply_skills(message)
L5393  def _parse_skill_add_args(args: list)
L5421  def _format_skill_install(result: dict)
L5452  async def _cmd_skill_add(update: Update, context: ContextTypes.DEFAULT_TYPE, source: str, force: bool, name: Optional[str], ref...
L5497  @guard() async def cmd_skills(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5502  @guard() async def cmd_skill(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5548  @guard() async def cmd_files(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5558  @guard() async def cmd_get(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5575  @guard(owner_only=True) async def cmd_allow(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5587  @guard(owner_only=True) async def cmd_deny(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5614  def _mask_secret(value: str)
L5620  @guard(owner_only=True) async def cmd_key(update: Update, context: ContextTypes.DEFAULT_TYPE)  — Xem / đặt API key ngay trong chat — không cần mở terminal.
L5692  async def _guest_typing(bot, chat_id: int, stop: asyncio.Event)
L5704  async def _guest_answer(msg, context, chat, user, text: str)  — Khách (không phải chủ bot): chỉ trả lời bằng chữ qua Web2API, không tool, không lịch sử của chủ.
L5770  async def _dispatch_text(msg, context, chat, text: str)  — Dùng chung cho tin nhắn gõ tay và tin nhắn thoại đã chép lời (chỉ chủ bot).
L5798  async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE)
L5822  @guard() async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE)  — Tin nhắn thoại / file âm thanh → chép lời bằng Gemini → xử lý như tin nhắn chữ.
L5881  def _redact_secrets(text: str)
L5893  def _watch_cli(args: list, timeout: int=900)  — Chạy aistv_watch.py bằng đúng Python của bot; trả về (code, stdout, stderr).
L5910  def _image_cli(args: list, timeout: int=300)  — Chạy aistv_image.py bằng đúng Python của bot.
L5927  def _resolve_media_source(source: str)
L5949  def _vision_question(kind: str, question: str)
L5955  def _vision_cli_args(source: str, question: str, kind: str)
L5964  def _vision_timeout(kind: str)
L5969  def _vision_parse(out: str)  — (text, model) từ JSON của aistv_watch.py.
L5979  def _vision_followup(source: str, question: str, kind: str)  — DeepSeek hỏi lại Gemini ngay trên media đã gửi → (ok, answer, error).
L5997  def _vision_handoff_prompt(kind: str, source: str, question: str, report: str, model: str)
L6026  async def gemini_media_reply(message, context, chat_id: int, source, question: str, kind: str)  — Gemini đọc ảnh/video → DeepSeek (model chính) đối chiếu, hỏi lại nếu cần → trả lời.
L6095  async def generate_image_job(prompt: str, style: str='', aspect: str='1:1', kind: str='image', ref: str='', model: str='')
L6133  def _photo_for_telegram(path: Path)  — Ảnh > 9MB → thu nhỏ sang JPEG (photo Telegram tối đa 10MB).
L6148  def _image_caption(data: dict)
L6167  async def send_generated_image(chat_id: int, data: dict)
L6181  async def _tool_image_job(chat_id: int, prompt: str, style: str='', aspect: str='1:1', kind: str='image', model: str='')  — Chạy nền khi agent gọi tool generate_image (HTTP nội bộ).
L6209  async def _download_telegram_file(message, file_obj, name: str, mime: str='')
L6225  @guard() async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE)
L6245  @guard() async def handle_video(update: Update, context: ContextTypes.DEFAULT_TYPE)
L6270  @guard() async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE)
L6296  async def _cmd_gemini_media(update: Update, context: ContextTypes.DEFAULT_TYPE, kind: str)
L6335  def _parse_image_args(args)
L6402  async def _image_generate_reply(update, prompt: str, style: str='', aspect: str='1:1', kind: str='image', model: str='')
L6434  @guard() async def cmd_image(update: Update, context: ContextTypes.DEFAULT_TYPE)  — Mặc định tạo ảnh; nếu tham số đầu là file/URL ảnh thì đọc ảnh (như cũ).
L6451  @guard() async def cmd_see(update: Update, context: ContextTypes.DEFAULT_TYPE)
L6456  @guard() async def cmd_mindmap(update: Update, context: ContextTypes.DEFAULT_TYPE)
L6466  @guard() async def cmd_video(update: Update, context: ContextTypes.DEFAULT_TYPE)
L6470  async def _on_ask_button(q, data: str)
L6511  async def _on_gh_repo_button(q, data: str)
L6618  @guard() async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE)
L6689  async def on_error(update, context: ContextTypes.DEFAULT_TYPE)
L6717  def _cloud_path(path: str)
L6721  def _fb_url(path: str)
L6728  def fb_call(method: str, path: str, data=None, timeout: int=20)  — REST tới Firebase RTDB (đồng bộ). Không bao giờ ném lỗi ra ngoài.
L6749  async def fb(method: str, path: str, data=None)
L6753  def _save_json(path: Path, data)
L6760  def _load_json(path: Path)
L6771  def _secret_master_key()
L6778  def _keystream(key: bytes, nonce: bytes, size: int)
L6787  def encrypt_secrets(data: dict)
L6798  def decrypt_secrets(blob: str)
L6813  def _local_secret_values()
L6833  async def cloud_push_secrets()
L6854  async def cloud_restore_secrets()  — Máy mới: giải mã bí mật trên cloud và ghi vào config.env (không ghi đè cái đã có).
L6907  async def cloud_merge_memory()  — Gộp MEMORY.md cục bộ với bản trên cloud (giữ thứ tự, không trùng).
L6927  async def cloud_push_memory()
L6932  async def cloud_push_history(chat_id: int)
L6937  async def cloud_pull_history(chat_id: int)
L6949  async def ensure_history(chat_id: int)  — Máy mới / Colab reset: lấy lại hội thoại của chat này từ cloud.
L6958  async def cloud_restore_all()
L6986  async def cloud_loop()  — Gom thay đổi rồi đẩy lên Firebase (tránh gọi mạng mỗi lần append).
L7009  def add_memory_lines(lines: list)
L7028  async def ask_model_once(prompt: str, timeout: int=300)  — Gọi OpenCode 1 lần, không tool, không đụng state hội thoại.
L7051  async def summarize_chat(chat_id: int, force: bool=False)  — Cô đọng các lượt cũ thành gạch đầu dòng trong MEMORY.md rồi cắt lịch sử.
L7090  def maybe_schedule_summary(chat_id: int)
L7116  def _new_id(prefix: str)
L7120  def _when_str(ts)
L7128  def _in_str(ts)
L7142  def _next_at(hh: int, mm: int, add_days: int=0)
L7152  def parse_schedule(text: str)  — Trả (epoch|None, kiểu lặp, phần nội dung còn lại).
L7188  async def rem_save(push: bool=True)
L7194  async def rem_restore()
L7210  def build_reminders()
L7228  async def send_plain(app, chat_id: int, text: str, html_ok: bool=False, markup=None)
L7250  async def _run_scheduled_task_guarded(app, rec: dict)
L7264  async def _run_scheduled_task(app, rec: dict)
L7279  async def tick_reminders(app)
L7326  def _norm_repo(s: str)
L7331  def _path_digest(p: Path)
L7348  async def watch_save()
L7354  async def watch_restore()
L7364  async def _watch_git(app, w: dict)
L7388  async def _watch_log(app, w: dict)
L7423  async def _watch_file(app, w: dict)
L7434  async def tick_watches(app)
L7451  def build_watches()
L7468  async def install_self_watch()
L7483  async def _scheduler_loop(app)
L7501  @guard() async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE)
L7506  @guard() async def cmd_task(update: Update, context: ContextTypes.DEFAULT_TYPE)
L7510  async def _add_schedule(update, context, kind: str)
L7535  @guard() async def cmd_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE)
L7540  @guard() async def cmd_unremind(update: Update, context: ContextTypes.DEFAULT_TYPE)
L7558  @guard() async def cmd_watch(update: Update, context: ContextTypes.DEFAULT_TYPE)
L7616  @guard() async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE)
L7626  def build_cloud(chat_id: int)
L7652  @guard() async def cmd_cloud(update: Update, context: ContextTypes.DEFAULT_TYPE)
L7671  def _email_fp(cfg: dict)  — Vân tay cấu hình: đổi email/mật khẩu/host → kết quả test cũ không còn giá trị.
L7678  def _clean_app_password(parts)  — Gmail hiển thị App Password dạng 'abcd efgh ijkl mnop' — bỏ hết khoảng trắng.
L7686  def _email_pw_label(cfg: dict)
L7695  def build_email()
L7728  def _parse_email_read(chat_id: int, key: str)
L7741  @guard() async def cmd_email(update: Update, context: ContextTypes.DEFAULT_TYPE)
L7866  async def _web2api_loop()  — Giữ cookie/server luôn mới: dán cookie.txt là tự chạy, máy mới tự kéo.
L7886  @guard() async def cmd_web2api(update: Update, context: ContextTypes.DEFAULT_TYPE)  — Quản lý server Gemini Web2API dự phòng (chỉ chủ bot).
L7992  def _merge_env_file(path: Path, text: str)  — Thêm các biến còn thiếu từ text vào path; không ghi đè giá trị đang có.
L8035  def _remote_config_text()  — Tải config.env từ AISTV_ENV_URL hoặc repo private (dự phòng cho bản cũ).
L8082  def _bootstrap_remote_config()  — Máy mới: tự nạp token/API key từ config.env dùng chung trên GitHub.
L8103  def _valid_bot_token(value: str)  — Token BotFather: 123456789:AAH... — chan dan nham lenh khac vao prompt.
L8108  def get_token()
L8166  def _startup_github()
L8177  async def post_init(app)
L8221  def main()
```

## aistv_browser.py

_aistv_browser.py — Điều khiển trình duyệt thật bằng Playwright._

```text
L35    class BrowserError
L39    def _pw()
L48    def check()
L73    def _deps_hint(exc: Exception)
L87    def _launch(p, headless: bool, slow: int=0)
L99    def _context(p, headless: bool, slow: int=0)
L108   def _run_steps(page, steps: list, outdir: Path)
L149   def cmd_install(args)
L170   def main(argv=None)
```

## aistv_cloudflare.py

_aistv_cloudflare.py — Cloudflare API wrapper cho bot AI STV._

```text
L44    class CFError
L48    def _secure(path: Path)
L63    def load_token()
L75    def save_token(token: str)
L85    def _format_errors(payload)
L95    def api(method: str, path: str, data=None, timeout=None, raw=False)
L133   def emit(data, as_json: bool, human: str)
L140   def accounts()
L145   def get_account_id(explicit=None, save=True)
L168   def zone_id(value: str)
L179   def _record_line(r: dict)
L184   def cmd_check(a)
L201   def cmd_accounts(a)
L208   def cmd_zones(a)
L221   def cmd_dns_list(a)
L239   def cmd_dns_add(a)
L255   def cmd_dns_delete(a)
L264   def cmd_ai_models(a)
L282   def cmd_ai_run(a)
L317   def _npx()
L324   def run_wrangler(args, cwd=None, timeout=600)
L354   def cmd_pages_projects(a)
L360   def cmd_pages_deploy(a)
L377   def cmd_workers_deploy(a)
L391   def cmd_r2_buckets(a)
L400   def cmd_token_save(a)
L414   def build_parser()
L490   def main(argv=None)
```

## aistv_config.py

_AI STV - đồng bộ cấu hình (token / API key) cho MỌI môi trường._

```text
L70    def repo_dir()
L74    def config_dir()  — Thư mục cấu hình dùng chung (giống run.sh / bot).
L93    def shared_config_path()
L97    def env_files(repo: Path=None)
L127   def valid_bot_token(value: str)  — Token BotFather có dạng 123456789:AAH... — chặn dán nhầm lệnh khác.
L132   def parse_env_text(text: str)
L153   def read_files(repo: Path=None)  — Trả về (values, sources). Repo .env thắng config.env.
L168   def format_value(value: str)
L175   def write_env_var(path: Path, name: str, value: str)  — Ghi/cập nhật một biến, giữ nguyên comment và thứ tự file.
L211   def save_values(values: dict, repo: Path=None, protected=None)  — Ghi các giá trị vào config.env + .env của repo.
L250   def _colab_available()
L254   def colab_secret(name: str)
L264   def _pick(name: str, values: dict)
L270   def stored_github_token()  — Token bot đã lưu sau /github login — dùng được cả khi máy không có gh.
L291   def github_tokens(values: dict=None)  — Các cặp (nguồn, token) có thể dùng để đọc repo private.
L321   def _http_get(url: str, headers: dict=None)
L327   def _post_form(url: str, data: dict)
L339   def _copy_to_clipboard(text: str)
L349   def github_device_login(timeout: int=None, log=None)  — Đăng nhập GitHub bằng mã (device flow) và trả về token.
L411   def _remember_config_token(token: str, values: dict=None)  — Lưu token vừa đăng nhập để lần chạy sau không phải đăng nhập lại.
L423   def normalize_repo(repo: str)
L433   def fetch_url(url: str)
L440   def fetch_github_status(repo: str, path: str, token: str='')  — Tải file trong repo → (nội dung, mã HTTP). Mã 0 = lỗi mạng.
L473   def fetch_github(repo: str, path: str=DEFAULT_PATH, token: str='')
L477   def fetch_remote(values: dict=None, log=None)  — Tải cấu hình từ xa → (values, nhãn nguồn).
L541   def _have_token(values: dict=None)
L549   def sync(quiet: bool=False, repo: Path=None, offline: bool=False, protected=None)  — Đọc file + tải cấu hình từ xa (nếu có) và ghi lại.
L603   def get_value(name: str, repo: Path=None)
L612   def set_value(name: str, value: str, repo: Path=None)
L625   def _mask(value: str)
L631   def cmd_doctor(repo: Path=None)
L668   def main(argv=None)
```

## aistv_docs.py

_aistv_docs.py — Đọc PDF / DOCX / ảnh scan (OCR) hoàn toàn LOCAL._

```text
L31    class DocError
L35    def _run(cmd, timeout=300)
L40    def _which(name)
L45    def _pdf_pdftotext(path: Path)
L55    def _pdf_fitz(path: Path)
L65    def _pdf_pdfminer(path: Path)
L73    def pdf_text(path: Path)
L86    def pdf_is_scanned(path: Path)
L95    def _docx_python_docx(path: Path)
L110   def _docx_raw_xml(path: Path)  — Không cần python-docx: đọc trực tiếp word/document.xml.
L124   def docx_text(path: Path)
L138   def ocr_image(path: Path, lang: str='vie+eng')
L155   def extract(path: str | Path, lang: str='vie+eng')
L177   def check()
L189   def _importable(name: str)
L197   def _has_tessdata(lang: str)
L208   def main(argv=None)
```

## aistv_email.py

_Kết nối email IMAP/SMTP cho AI STV — chỉ dùng thư viện chuẩn._

```text
L81    class EmailError
L85    def configure(home)
L97    def _secret(name: str)
L108   def get_secret(name: str)  — Đọc secret từ env hoặc Colab Secrets (dùng cho cảnh báo ghi đè).
L113   def _file_cfg()
L123   def load(force: bool=False)  — Trả về cấu hình email đã chuẩn hoá (không bao giờ in mật khẩu).
L149   def ready()
L154   def password()
L158   def save(address: str, pw: str, **extra)
L176   def clear()
L187   def _friendly(e: Exception)
L204   def _imap(cfg: dict)
L222   def _decode(value)
L231   def _clean(text: str)
L237   def _html_to_text(raw: str)
L244   def list_messages(limit: int=10, unread: bool=False)
L285   def read_message(uid: str, max_chars: int=6000)
L339   def send(to: str, subject: str, body: str)
L370   def test()
L394   def mask(address: str)
L402   def _load_cli_env()  — Nạp .env / config.env dùng chung để CLI chạy độc lập cũng có cấu hình.
L434   def _cli()
```

## aistv_facebook.py

_AI STV Facebook helper: đọc bài viết, xem/tải video, tìm kiếm._

```text
L44    def ytdlp()
L59    def run_yt(args, timeout=TIMEOUT)
L78    def load_yt_json(args)
L88    def clean_url(url)
L100   def is_fb(url)
L105   def is_video(url)
L110   def fetch(url, timeout=TIMEOUT)
L129   def read_reader(page_url)
L142   def unwrap_links(text)
L157   def clean_body(body)
L191   def parse_reader(raw, page_url, comments=False)
L229   def fmt_duration(sec)
L237   def fmt_views(n)
L247   def video_info(url)
L271   def info(url)
L288   def search(query, limit, site)
L323   def download(url, quality, out_dir, max_mb)
L348   def print_post(data, limit=None)
L358   def main()
```

## aistv_github_docs.py

_AI STV GitHub docs helper: xem repo, cây tệp, đọc README/tài liệu, tìm trong docs và mã._

```text
L66    class Target
  L67    def __init__(self, owner, repo, ref='', path='')
  L74    @property def slug(self)
L78    def err(msg)
L82    def oneline(text, n)
L87    def fmt_num(n)
L99    def fmt_size(n)
L111   def fmt_date(raw)
L120   def token_fingerprint(token)
L124   def load_token()
L157   def configured_repo()
L189   def parse_target(raw, ref_override='')
L238   def cache_file(url, accept)
L248   def cache_read(path)
L262   def cache_write(path, **kw)
L270   def api_url(path, params=None)
L277   def http_get(url, headers, timeout=TIMEOUT)
L295   def api_get(path, params=None, accept='application/vnd.github+json', raw=False)
L341   def repo_info(t)
L369   def default_ref(t)
L378   def get_tree(t, ref)
L394   def fetch_raw(url)
L404   def file_url(t, ref, path)
L409   def fetch_file(t, path, ref)
L461   def parse_headings(text)
L477   def norm_heading(s)
L481   def section_text(text, name)
L504   def truncate_text(text, limit)
L515   def is_probably_dir(path)
L522   def list_dir(t, path, ref)
L533   def pick_doc_in_dir(items)
L550   def read_target(t, path, ref)
L604   def doc_files(entries, prefix='', include_all=False)
L632   def doc_rank(item)
L658   def search_files(t, ref, items, query, max_matches, context, case_sensitive, workers=8)
L707   def parse_lines(value)
L724   def print_info(info)
L754   def print_tree(entries, base, max_lines)
L778   def main()
```

## aistv_harness2.py

_aistv_harness2.py — Cầu nối AI STV ↔ Harness² (google-research/harness2)._

```text
L55    def h2()  — Import harness2 từ source tree (core không cần dependency ngoài).
L66    def read_text(p: Path)
L73    def first_doc_line(p: Path)  — Dòng mô tả đầu tiên trong docstring của một script AI STV (bỏ banner ASCII).
L94    def skill_script_names(tree: dict)  — Tên script nằm trong skills/*/scripts/ — SKILL.md tham chiếu chúng theo đường dẫn
L100   def skill_files()  — Chỉ copy phần surface của OpenCode chấp nhận: SKILL.md + scripts/*.
L119   def tool_guidance()
L132   def fit_memory(text: str, budget: int)  — Cắt MEMORY.md theo ngân sách always-on, giữ phần MỚI nhất (entry nằm cuối file).
L151   def build_tree()
L190   def trigger_desc(tree: dict, name: str)  — Mô tả ngắn (<=140 ký tự) cho trigger line của một skill.
L202   def cmd_export(a)
L230   def cmd_check(a)
L252   def cmd_diff(a)
L270   def h2_commit()
L279   def creds()
L287   def cmd_setup(a)  — Cài Harness² lần đầu (hoặc bổ sung venv) — chạy lại nhiều lần vẫn an toàn.
L327   def cmd_status(a)
L364   def cmd_demo(a)
L377   def cmd_run(a)
L391   def main()
```

## aistv_image.py

_aistv_image.py — Tạo ảnh & sơ đồ tư duy cho bot AI STV._

```text
L52    class ImageError
L57    def _env_paths()
L69    def _file_value(path: Path, name: str)
L84    def secret(name: str)
L104   def gemini_key()
L146   def _norm(text: str)
L152   def resolve_style(value: str)
L172   def build_prompt(prompt: str, style: str='', kind: str='image')
L189   def _request(url: str, data=None, headers=None, timeout=180, method=None)
L209   def _json_body(raw: bytes, code: int)
L217   def _error_text(data, code: int)
L245   def _save(raw: bytes, mime: str='', out: str='')
L262   def _gemini_models()
L269   def gemini_image(prompt: str, aspect: str='1:1', ref: str='', size: str='', **_)
L327   def _web2api_ready()
L334   def web2api_image(prompt: str, aspect: str='1:1', ref: str='', size: str='', **_)
L381   def _dims(aspect: str)
L386   def _cf_model_key(value: str)
L408   def _cf_chain(style: str, kind: str, model: str, prompt: str)
L434   def _cf_multipart(model: str, fields: dict)
L451   def _cf_image_bytes(code: int, raw: bytes, headers: dict)
L476   def cloudflare_image(prompt: str, aspect: str='1:1', style: str='', kind: str='image', model: str='', **_)
L512   def together_image(prompt: str, aspect: str='1:1', **_)
L535   def hf_image(prompt: str, aspect: str='1:1', **_)
L556   def pollinations_image(prompt: str, aspect: str='1:1', **_)  — Pollinations.ai — miễn phí, KHÔNG cần API key (lưới an toàn cuối cùng).
L596   def generate(prompt: str, style: str='', aspect: str='1:1', ref: str='', provider: str='', out: str='', size: str='', kin...
L659   def _text_models()
L666   def _extract_json(text: str)
L678   def _gemini_text(prompt: str)
L701   def _cf_text(prompt: str, max_tokens: int=1600, temperature: float=0.45)
L731   def _outline_json(prompt_text: str, cleaner, subject: str)
L741   def mindmap_outline(subject: str)
L745   def _clean_outline(subject: str, data: dict)
L769   def _font(size: int, bold: bool=False)
L794   def _wrap(draw, text: str, font, max_width: int)
L818   def _mix(hex_color: str, white: float)
L827   def _bezier(p0, p1, p2, p3, steps=28)
L838   def render_mindmap(outline: dict, out: str='')
L952   def make_mindmap(subject: str, out: str='')
L988   def _clean_infographic(subject: str, data: dict)
L1009  def _num(value)
L1028  def _clean_chart(subject: str, data: dict)
L1069  def _gradient_bg(img, top='#f7f9ff', bottom='#e9f0fb')
L1082  def render_infographic(data: dict, out: str='')
L1202  def _nice_scale(value: float)
L1216  def _fmt_num(value: float, unit: str='')
L1224  def render_chart(data: dict, out: str='')
L1380  def make_infographic(subject: str, out: str='')
L1388  def make_chart(subject: str, out: str='')
L1397  def main()
```

## aistv_mcp.py

_aistv_mcp.py — Quản lý MCP server trong opencode.json của workspace._

```text
L42    def load()
L51    def save(cfg: dict)
L58    def servers(cfg: dict)
L62    def main(argv=None)
```

## aistv_memory_index.py

_aistv_memory_index.py — Tìm kiếm trí nhớ & lịch sử chat bằng SQLite FTS5._

```text
L27    def db()
L43    def sources()
L64    def _read_chunks(path: Path)
L106   def cmd_index(args)
L151   def _fts_query(q: str)  — Biến câu người dùng thành truy vấn FTS5 an toàn.
L159   def cmd_search(args)
L184   def cmd_stats(args)
L197   def cmd_clear(args)
L206   def main(argv=None)
```

## aistv_planner.py

_aistv_planner.py — kế hoạch tự trị, checkpoint/hoàn tác và kiểm chứng._

```text
L41    def esc(s)
L45    def oneline(s, n: int=200)
L50    def _run(cmd, cwd=None, timeout=180, binary=False)  — Chạy lệnh, trả (returncode, stdout). binary=True → bytes.
L67    def _git(repo, *args, timeout=180, binary=False)
L71    def _write_json(path: Path, data)
L78    def _read_json(path: Path)
L88    def verify_repo(repo, fast: bool=True, timeout: int=420)  — Chạy scripts/verify.py. Trả {ok, summary, checks, elapsed}.
L120   def diff_stat(repo)  — Thống kê thay đổi chưa commit trong repo (dùng cho cổng review).
L152   def _cp_dir(home, cp_id: str)
L156   def create_checkpoint(home, repo, label: str='')  — Chụp trạng thái repo trước khi agent sửa. Trả (meta, error).
L203   def load_checkpoint(home, cp_id: str)
L207   def list_checkpoints(home, limit: int=10)
L220   def _prune_checkpoints(home)
L235   def restore_checkpoint(home, repo, cp_id: str)  — Trả repo về đúng trạng thái lúc chụp. Trả (ok, detail).
L311   def _plans_dir(home)
L315   def new_plan(home, chat_id: int, title: str, request: str, steps: list)
L341   def save_plan(home, plan: dict)
L346   def load_plan(home, plan_id: str)
L351   def list_plans(home, limit: int=10)
L364   def latest_plan(home, chat_id=None)
L371   def set_step(plan, n: int, **fields)
L379   def next_pending(plan)
L386   def progress(plan)
L392   def parse_plan(text: str)  — Bóc JSON kế hoạch khỏi câu trả lời model. Trả (plan_dict, error).
L428   def render_plan(plan: dict, show_request: bool=True)
L449   def render_report(plan: dict)
L477   def plan_prompt(request: str, repo: str='', workspace: str='', context: str='')
L504   def step_prompt(plan: dict, step: dict, repo: str='', workspace: str='', verify_hint: str='')
```

## aistv_railway.py

_aistv_railway.py — wrapper Railway CLI cho bot AI STV._

```text
L32    class RailwayError
L36    def find_cli()
L61    def run(args, timeout=None, cwd=None, stdin=None)
L89    def _clean(text: str)
L94    def _fail(proc)
L103   def _json_arg(proc, what)
L111   def emit(data, as_json: bool, human: str)
L118   def cmd_check(a)
L138   def cmd_projects(a)
L153   def cmd_status(a)
L173   def cmd_logs(a)
L202   def cmd_deployments(a)
L221   def _latest_status(a)
L230   def cmd_deploy(a)
L267   def _load_vars(a)
L279   def cmd_vars(a)
L290   def cmd_var_set(a)
L312   def cmd_domains(a)
L330   def build_parser()
L381   def main()
```

## aistv_skills.py

_Cài / quản lý Agent Skills cho AISTV._

```text
L71    class SkillError  — Lỗi cài skill với thông báo thân thiện.
L78    def oneline(text: str, limit: int=0)
L85    def parse_frontmatter(text: str)  — Đọc YAML frontmatter đơn giản (không cần PyYAML).
L154   def description_of(text: str)
L167   def slugify(value: str)
L174   def choose_name(meta: dict, folder: str)
L191   def _http_get(url: str, timeout: int=45, max_bytes: int=MAX_ZIP_BYTES, token: Optional[str]=None)
L230   def _github_default_branch(owner: str, repo: str, token: Optional[str])
L243   def _github_zip(owner: str, repo: str, ref: Optional[str], token: Optional[str])
L269   def _zip_root(tmpdir: Path, zf: zipfile.ZipFile)  — Giải nén zip, chặn path traversal và file quá lớn.
L327   def _extract_zip(data: bytes, tmpdir: Path)
L339   def parse_source(source: str, ref: Optional[str]=None)
L437   def _raw_url(info: dict)
L444   def _ignored(path: Path)
L448   def _find_candidates(base: Path, whole_repo: bool=False)
L492   def _copy_skill(skill_file: Path, dest: Path, *, force: bool, info: dict, used_names: set[str], repo_license: Optional[Pa...
L621   def _install_raw(text: str, dest: Path, info: dict, force: bool, forced_name: Optional[str], used_names: set[str], allow_...
L640   def install(source: str, dest: str | Path, *, force: bool=False, name: Optional[str]=None, ref: Optional[str]=None, token...  — Cài một hoặc nhiều skill. Trả về dict tóm tắt (không raise nếu chỉ skip).
L775   def default_dest()
L782   def list_installed(dest: str | Path)
L804   def _human(result: dict)
L824   def main(argv: Optional[list[str]]=None)
```

## aistv_tiktok.py

_AI STV TikTok helper: xem thông tin, tải video không watermark, tìm kiếm._

```text
L50    class TikTokError
L54    class HttpResult
  L55    def __init__(self, status, headers, url, content)
  L62    @property def text(self)
L66    def ytdlp()
L81    def run_yt(args, timeout=TIMEOUT)
L100   def load_yt_json(args)
L110   def _request(url, timeout=30, allow_redirects=True)
L131   def _text(url, timeout=60)
L140   def extract_url(text)
L152   def clean_url(url)
L173   def is_tt(url)
L178   def video_id(url)
L192   def photo_id(url)
L197   def is_short(url)
L205   def canonical(vid)
L209   def follow(url, hops=6)
L223   def resolve(url)
L271   def friendly_error(msg)
L285   def explain_missing(url)
L305   def fmt_duration(sec)
L313   def fmt_num(n)
L329   def fmt_date(raw)
L347   def first_line(text, limit=160)
L354   def build_yt(data, url)
L378   def parse_item_html(text)
L405   def web_item(url)
L417   def build_item(item, url)
L450   def info(url)
L484   def pick_play_url(item)
L495   def direct_download(url, out_dir, max_mb)
L573   def download(url, quality, audio, out_dir, max_mb, prefer_h264=False)
L641   def search_one(query, want)
L679   def search(query, limit)
L729   def print_info(data)
L762   def main()
```

## aistv_voice.py

_aistv_voice.py — Nghe (STT) và nói (TTS) hoàn toàn local._

```text
L34    class VoiceError
L38    def _which(name)
L42    def _ffmpeg()
L53    def _piper_model()
L64    def check()
L76    def _importable(name)
L85    def tts(text: str, out: str='', voice: str='')
L128   def stt(path: str, model: str='')
L157   def main(argv=None)
```

## aistv_watch.py

_AI STV Watch: xem video bằng transcript + frames + Gemini (tuỳ chọn)._

```text
L62    def ep(text: str='')
L66    def err_text(exc)
L70    def run(cmd, timeout=TIMEOUT, cwd=None)
L88    def run_raw(cmd, timeout=TIMEOUT)
L96    def find_ffmpeg()
L126   def find_ffprobe()
L142   def ytdlp_cmd()
L157   def run_ytdlp(args, timeout=TIMEOUT)
L165   def is_url(value: str)
L169   def safe_slug(value: str, limit=60)
L176   def parse_time(value)
L196   def fmt_time(seconds, ms=False)
L209   def fmt_big(n)
L221   def clean_secret(text, secrets)
L233   def read_config()
L276   def config_value(name, default='')  — Đọc biến môi trường, sau đó .env, sau đó giá trị mặc định.
L281   def config_int(name, default=0)
L288   def api_key(name)
L295   def ffmpeg_version()
L304   def ytdlp_version()
L310   def ffprobe_duration(path)
L334   def local_media_info(path: Path)
L373   def video_info(source: str)
L416   def vtt_to_cues(text)
L453   def srt_to_cues(text)
L477   def parse_caption_file(path: Path)
L486   def sidecar_cues(path: Path)
L501   def pick_caption_langs(info, requested)
L523   def yt_hint(text: str)  — Dịch lỗi khó hiểu của YouTube thành hướng dẫn dùng được.
L535   def yt_cookies(value=None)  — Cookie YouTube: ưu tiên --cookies, rồi YT_COOKIES / YOUTUBE_COOKIES.
L546   def grab_captions(source, workdir: Path, langs='auto', cookies=None, info=None)
L604   def cues_text(cues, timestamps=True, max_chars=MAX_TRANSCRIPT, start=None, end=None)
L623   def extract_audio(video: Path, out: Path, start=None, end=None)
L639   def multipart_body(fields, files)
L656   def http_json(url, payload=None, headers=None, timeout=120, method=None)
L678   def cloud_transcribe(audio: Path, provider: str, key: str, language=None)
L717   def local_whisper(audio: Path, language=None)
L734   def whisper_fallback(video: Path, workdir: Path, mode='auto', language=None, start=None, end=None, offset=0.0)
L799   def _has_module(name)
L808   def transcript_result(source, info, workdir, langs='auto', timestamps=True, max_chars=MAX_TRANSCRIPT, whisper='auto', lan...
L840   def file_has_video(path: Path)
L848   def download_media(source, workdir: Path, start=None, end=None, max_height=720, cookies=None)
L907   def frame_signature(path: Path)
L921   def sig_diff(a, b)
L927   def video_codec(path: Path)
L936   def av1_input_args(path: Path)
L940   def scene_candidates(video: Path, workdir: Path, start: float, duration: float, limit: int, width: int, threshold=0.28, i...
L963   def uniform_candidates(video: Path, workdir: Path, start: float, duration: float, count: int, width: int, input_args=None)
L987   def cue_frames(video: Path, workdir: Path, times, width: int, offset=0.0, input_args=None)
L1009  def sample_evenly(items, count)
L1024  def select_frames(cands, max_frames, duration, threshold=4.0, priority=None)
L1067  def ocr_frame(path: Path, langs='vie+eng')
L1078  def contact_sheet(frames, workdir: Path)
L1100  def extract_frames(video: Path, workdir: Path, start=0.0, end=None, max_frames=24, width=512, detail='balanced', at=None,...
L1180  def gemini_model_chain(primary=None)  — Model chính + model dự phòng (bỏ trùng, giữ thứ tự).
L1194  def gemini_quota_path()
L1199  def _read_quota()
L1219  def _write_quota(data: dict)
L1230  def gemini_quota_status()
L1247  def wait_gemini_quota()  — Giữ nhịp RPM/RPD để tránh 429. Chờ tối đa ~65 giây mỗi lượt.
L1279  def web2api_available()  — Web2API bật và không bị tắt bằng WEB2API_FALLBACK=0.
L1289  def web2api_media_ready()  — Server Web2API đã vá để nhận audio/video chưa.
L1299  def voice_engine_order(engine: str, has_key: bool, web2api_ok: bool, local_ok: bool)  — Thứ tự nguồn chép lời; auto ưu tiên Web2API để không tốn request API.
L1313  def web2api_generate(parts, timeout=240, temperature=0.2, max_output_tokens=8192)  — Gọi server Gemini Web2API nội bộ khi API chính hết hạn mức.
L1333  def gemini_generate(parts, timeout=900, temperature=0.2, max_output_tokens=8192, primary_model=None)  — Gọi generateContent, tự đổi model dự phòng và retry khi bị 429.
L1432  def upload_gemini_file(path: Path, key: str, mime=None, default_mime='application/octet-stream')
L1480  def delete_gemini_file(uri: str, key: str)
L1496  def watch_instructions(question: str)
L1513  def gemini_watch(source, question, workdir: Path, start=None, end=None, max_height=720, cookies=None)
L1546  def _shrink_video(path: Path, workdir: Path)  — Giảm video xuống 360p để vừa giới hạn inline của Web2API.
L1562  def web2api_watch(source, question, workdir: Path, start=None, end=None, max_height=720, cookies=None)  — Xem video qua Web2API (gửi thẳng file, không cần GEMINI_API_KEY).
L1585  def image_mime(path: Path)
L1592  def download_image(source: str, workdir: Path, index: int=1)  — Tải ảnh từ URL về workdir; trả về (Path, mime, lỗi).
L1629  def gemini_image(sources, workdir: Path, question='', engine='auto')  — Đọc một hoặc nhiều ảnh bằng Gemini; trả về (answer dict, lỗi).
L1715  def do_image(args)
L1755  def clean_transcript(text: str)
L1766  def _audio_part(path: Path, mime: str)
L1771  def _audio_to_mp3(src: Path)  — Đổi audio sang mono MP3 để Gemini Web nghe ổn định và vừa giới hạn inline.
L1791  def web2api_audio(src: Path, mime: str)  — Chọn file gửi Web2API: MP3/WAV giữ nguyên, còn lại (OGG/Opus/FLAC…) đổi sang MP3.
L1809  def do_voice(args)
L1899  def make_workdir(source, out_dir=None)
L1917  def describe_info(info)
L1939  def build_report(source, info, workdir, media, transcript, frames, sheet, gemini_answer, engine, start, end, errors=None)
L2010  def do_watch(args)
L2142  def do_doctor(args)
L2188  def main()
```

## aistv_web2api.py

_AI STV - Gemini Web2API: server nội bộ + đồng bộ cookie dạng chữ._

```text
L89    def _config_module()
L97    def config_dir()
L107   def runtime_dir()
L114   def app_dir()
L118   def app_script()
L122   def package_dir()
L126   def image_patch_path()  — Patch đóng gói trong repo AISTV (không phụ thuộc bản upstream mới nhất).
L131   def image_files_zip()  — Bản package đã vá, dùng khi máy không có git/patch.
L136   def media_patch_path()
L140   def media_files_zip()
L144   def _read_text(path: Path)
L151   def image_patch_ready()  — Đã vá đủ phần xem ảnh + tạo ảnh của upstream chưa.
L159   def apply_image_patch(quiet: bool=True)  — Áp patch ảnh lên bản clone upstream; chạy lại nhiều lần vẫn an toàn.
L201   def media_patch_ready()  — Server đã nhận được audio/video chưa (không chỉ ảnh).
L211   def apply_media_patch(quiet: bool=True)  — Áp patch audio/video lên bản đã vá ảnh; chạy lại nhiều lần vẫn an toàn.
L252   def app_entry()  — Bản đang chạy: 'package' (đã vá, có ảnh) hoặc 'single' (file đơn cũ).
L259   def app_command()  — Chạy package đã vá khi có (hỗ trợ ảnh), không thì file đơn cũ.
L266   def cookie_path()  — File cookie đang dùng; đổi bằng WEB2API_COOKIE_FILE nếu muốn để chỗ khác.
L272   def export_path()
L276   def config_path()
L280   def state_path()
L284   def log_path()
L288   def value(name: str, default: str='')  — Đọc biến môi trường → config.env dùng chung → mặc định.
L304   def enabled()
L308   def base_url()
L312   def api_key()
L316   def default_model()
L320   def is_local()
L325   def autostart()
L329   def _read_json(path: Path, default)
L336   def _write_json(path: Path, data)
L353   def _strip_cookie_wrapping(text: str)  — Bỏ BOM, dấu nháy và tiền tố `Cookie:` khi người dùng dán nguyên từ trình duyệt.
L371   def _cookie_pairs(raw: str)  — Tách `name=value` từ header / nhiều dòng; giữ giá trị y như người dùng dán.
L393   def _cookie_header(cookies: list)
L414   def _parse_json_cookies(data)
L441   def parse_cookie_input(text: str)  — Nhận JSON export (Cookie-Editor / EditThisCookie), Netscape hoặc header.
L470   def load_cookies()
L474   def save_cookies(cookies: list)
L488   def cookie_header()  — Cookie đang dùng, luôn trả về header sạch dù người dùng dán định dạng nào.
L508   def cleanup_cookie_header(raw: str)  — Chuẩn hoá cookie: nhận header/JSON/Netscape, bỏ xuống dòng, giữ nguyên giá trị.
L525   def refresh_xsrf(quiet: bool=False)  — Lấy SNlM0e + auth_user từ trang Gemini. Trả (ok, thông điệp).
L567   def cookie_sig(header: str='')  — Dấu vân tay ngắn của cookie để biết file vừa được dán mới.
L574   def _state_update(**fields)
L581   def _autosync()
L585   def _gh_tokens()
L596   def _gh_request(url: str, token: str, method: str='GET', payload: dict=None, accept: str='application/vnd.github+json')
L610   def _remote_repo()
L616   def _gh_put_text(path: str, text: str, message: str)
L647   def _gh_get_text(path: str)
L662   def _gh_delete_text(path: str, message: str)  — Xoá file cũ trên repo private (dùng khi chuyển cookie mã hoá → nguyên văn).
L686   def _sibling_secret_path(name: str)
L692   def _legacy_passphrase()
L708   def _decode_legacy_blob(text: str, phrase: str)  — Giải mã blob AES-256-GCM của bản cũ; trả cookie dạng chữ.
L728   def _legacy_local_payload()  — Đọc cookies.enc + passphrase.txt của bản cũ (nếu còn) → cookie dạng chữ.
L748   def _legacy_local_header()
L758   def _apply_legacy_meta(payload: str)  — Giữ XSRF/auth_user cũ nếu blob có sẵn (sẽ refresh lại sau).
L776   def migrate_legacy(quiet: bool=True)  — Chuyển cookie mã hoá cũ (local hoặc repo private) sang cookie.txt nguyên văn.
L838   def push_secrets(quiet: bool=False)  — Đẩy cookie NGUYÊN VĂN lên repo private (một dòng, sửa được trên GitHub).
L854   def pull_secrets(quiet: bool=False)  — Tải cookie nguyên văn từ repo private, ghi cookie.txt + cookies.json.
L886   def pull_if_safe(quiet: bool=True)  — Kéo bản trên GitHub nếu máy này không có sửa đổi chưa đẩy.
L928   def sync_if_changed(quiet: bool=True, push: bool=None)  — Nạp cookie vừa dán trong cookie.txt; tự làm mới XSRF và chạy lại server.
L984   def auto(quiet: bool=True)  — Một lệnh cho máy mới: kéo cookie, nạp cookie vừa dán, bật server.
L999   def import_text(text: str, push: bool=None)  — Nạp cookie từ chuỗi (header/JSON/Netscape), chạy server + đồng bộ GitHub.
L1029  def write_config(force: bool=False)
L1060  def _python()
L1064  def _download_app()  — Clone repo; nếu không có git thì tải zip.
L1090  def ensure_deps()
L1102  def has_curl_cffi()
L1110  def ensure_image_deps(quiet: bool=True)  — curl_cffi cần cho xem ảnh + tạo ảnh qua Gemini Web (TLS kiểu Chrome).
L1122  def setup(force: bool=False)
L1141  def health(timeout: float=2.5)
L1151  def _xsrf_stale(max_age: float=6 * 3600)  — XSRF token sống vài giờ; quá cũ thì lấy lại trước khi dùng.
L1162  def _pid()
L1169  def _alive(pid: int)
L1183  def start(wait: float=25.0, quiet: bool=False)
L1236  def stop()
L1255  def ensure_server(quiet: bool=True)  — Bảo đảm server sẵn sàng; dùng từ bot/watch trước khi fallback.
L1299  def _reload_server()  — Khởi động lại server để nạp XSRF token vừa làm mới.
L1313  def _http_json(url: str, payload: dict, timeout: float=180, headers: dict=None)
L1338  def _clean_reply(text: str)  — Bỏ chú thích [cite: N] mà Gemini Web chèn vào câu trả lời.
L1343  def chat(messages: list, model: str='', timeout: float=180, **extra)
L1358  def _normalise_parts(parts: list)  — Google native: chấp nhận cả inline_data/mime_type (snake_case).
L1382  def generate(parts: list, model: str='', timeout: float=240, temperature: float=0.2, max_tokens: int=8192, system: str='')  — Gọi /v1beta/models/{model}:generateContent, trả (text, lỗi).
L1418  def _image_mime(raw: bytes)
L1432  def generate_image(prompt: str, model: str='', timeout: float=240, response_format: str='b64_json')  — Tạo ảnh qua /v1/images/generations của server đã vá.
L1490  def cmd_import(path: str, push: bool=None)
L1504  def status_report()  — Thông tin ngắn cho bot (không in bí mật).
L1530  def cmd_doctor()
L1557  def cmd_test(prompt: str, image: bool=False, out: str='')
L1577  def cmd_watch(interval: float=5.0)  — Theo dõi cookie.txt: dán cookie mới là tự nạp lại + chạy server.
L1598  def main(argv=None)
```

## aistv_youtube.py

_AI STV YouTube helper: search, info, transcript._

```text
L18    def ytdlp()
L33    def run(args, timeout=TIMEOUT)
L48    def load_json(args)
L58    def fmt_duration(sec)
L66    def fmt_views(n)
L76    def fmt_date(raw)
L82    def search(query, limit)
L105   def info(url)
L129   def vtt_to_cues(text)
L162   def grab_sub(url, lang, workdir)
L192   def transcript(url, langs, timestamps, max_chars)
L215   def main()
```

## scripts/code_map.py

_code_map.py — sinh bản đồ code (CODEMAP) để agent định vị nhanh._

```text
L33    def _docline(node)
L43    def _signature(node)
L55    def _decorators(node)
L65    def _outline(path: Path)
L98    def _py_files(root: Path)
L108   def build(root: Path)
L168   def main()
```

## scripts/verify.py

_verify.py — một lệnh kiểm chứng repo trước khi báo "xong"._

```text
L33    def _walk(suffix: str)
L44    def _python()
L48    def _run(cmd, timeout=180)
L59    def check_compile()
L74    def check_codemap()
L82    def check_tests()
L91    def check_ruff()
L105   def check_bash()
L124   def main()
```

## tests/test_media.py

_Kiểm tra chọn nguồn media cho Web2API (voice/video) và nhận diện patch._

```text
L17    class VoiceEngineOrderTest
  L18    def test_auto_prefers_web2api(self)
  L22    def test_auto_without_web2api(self)
  L26    def test_auto_without_any_source(self)
  L29    def test_explicit_engine_stays_alone(self)
L34    class Web2apiAudioTest
  L35    def setUp(self)
  L40    def tearDown(self)
  L45    def test_native_small_file_is_sent_as_is(self)
  L51    def test_ogg_is_converted_to_mp3(self)
  L59    def test_missing_ffmpeg_reports_error(self)
  L66    def test_large_native_file_requires_conversion(self)
L74    class MediaPatchReadyTest
  L75    def test_marks_ready_only_with_all_markers(self)
  L85    def test_missing_marker_is_not_ready(self)
```

## tests/test_planner.py

_Smoke test cho scripts/code_map.py và aistv_planner.py._

```text
L21    def _git(repo, *args)
L27    class CodeMapTest
  L28    def setUp(self)
  L31    def tearDown(self)
  L34    def test_outline_has_line_numbers_and_docs(self)
  L48    def test_build_and_check(self)
L59    class PlanParseTest
  L60    def test_parse_fenced_json(self)
  L75    def test_parse_rejects_garbage(self)
  L81    def test_prompt_mentions_repo_and_no_push(self)
L93    class PlanStoreTest
  L94    def setUp(self)
  L97    def tearDown(self)
  L100   def test_save_load_and_progress(self)
  L113   def test_render_escapes_html(self)
L121   @unittest.skipUnless(GIT, 'cần git') class CheckpointTest
  L122   def setUp(self)
  L132   def tearDown(self)
  L135   def test_clean_checkpoint_restores_worktree(self)
  L146   def test_dirty_checkpoint_keeps_user_work(self)
  L160   def test_refuses_after_new_commit(self)
  L168   def test_diff_stat_counts(self)
  L176   def test_list_prunes_oldest(self)
L187   class VerifyTest
  L188   def test_verify_missing_script_is_ok(self)
```
