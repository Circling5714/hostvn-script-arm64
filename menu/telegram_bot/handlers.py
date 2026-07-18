"""Handler + dinh tuyen trung tam (hostvn bot).

- /start, /menu, /cancel
- on_menu_text: nut menu chinh (ReplyKeyboard gui text) + nhap lieu cho conversation
- on_callback: tach callback_data bang split("|") -> dinh tuyen theo <mien>
- Cac tac vu he thong chay qua asyncio.to_thread (khong chan event loop)
"""
from __future__ import annotations

import asyncio
from pathlib import Path

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import ContextTypes

import config as C
import hostvn
import menus
import progress
import texts
from permissions import can_write, get_user_features, has_feature, is_allowed

HTML = ParseMode.HTML
E = C.E
title = texts.title
pre = texts.pre

WRITE_ACTIONS = {"dom_add", "db_add", "cache_clear", "opcache_clear", "php_restart",
                 "bk_run", "bk_restore", "bk_del",
                 "dom_rename", "dom_rewrite", "dom_php", "dom_alias", "dom_redirect",
                 "dom_sftp", "dom_protect", "dom_http3", "dom_clone", "dom_dbinfo",
                 "ssl_create", "ssl_wildcard", "ssl_remove", "ssl_alias",
                 "ssl_renew", "ssl_cfapi"}


# --------------------------------------------------------------------------- #
# Tien ich gui / sua tin
# --------------------------------------------------------------------------- #
async def _show(update: Update, text: str, kb, edit: bool) -> None:
    if edit and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=HTML, reply_markup=kb)
    else:
        await update.effective_message.reply_text(text, parse_mode=HTML, reply_markup=kb)


def _features(chat_id: int):
    return get_user_features(chat_id)


async def _make_editor(update: Update, edit_existing: bool):
    """Tra ve async editor(text, kb=None) nham vao tin can cap nhat.

    - callback: sua chinh tin nhan vua bam (edit_existing=True).
    - text tap: gui 1 tin '⏳' roi sua dan (edit_existing=False).
    Dung cho ca khung animate (goi editor(text)) lan ket qua (editor(text, kb)).
    """
    if edit_existing and update.callback_query:
        q = update.callback_query

        async def _edit_cb(text, kb=None):
            try:
                await q.edit_message_text(text, parse_mode=HTML, reply_markup=kb)
            except Exception:  # noqa: BLE001
                pass
        return _edit_cb

    msg = await update.effective_message.reply_text(
        f"⏳ <b>Đang tải…</b>\n<code>{progress.bar(3)}</code>", parse_mode=HTML)

    async def _edit_msg(text, kb=None):
        try:
            await msg.edit_text(text, parse_mode=HTML, reply_markup=kb)
        except Exception:  # noqa: BLE001
            pass
    return _edit_msg


async def _progress_op(update, edit_existing, loading_title, work, render, est=5.0, stages=None):
    """Hien thanh tien trinh khi chay 'work' (awaitable) roi hien ket qua.

    render(result) -> (text, keyboard).
    """
    editor = await _make_editor(update, edit_existing)
    result = await progress.run(editor, loading_title, work, est=est, stages=stages)
    text, kb = render(result)
    await editor(text, kb)
    return result


# --------------------------------------------------------------------------- #
# Lenh
# --------------------------------------------------------------------------- #
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_allowed(update.effective_chat.id):
        return await update.message.reply_text("🚫 Bạn không có quyền dùng bot này.")
    user = update.effective_user
    host = await asyncio.to_thread(hostvn.sh, "hostname", 5)
    await update.message.reply_text(
        texts.greeting(user.first_name or "bạn", host, C.BOT_MODE),
        parse_mode=HTML,
        reply_markup=menus.build_keyboard(_features(update.effective_chat.id)),
    )


async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE, note: str = "") -> None:
    if not is_allowed(update.effective_chat.id):
        return
    hint = note or "Chọn chức năng từ <b>menu bên dưới</b>."
    await update.effective_message.reply_text(
        title(E["home"], "Menu chính", hint),
        parse_mode=HTML,
        reply_markup=menus.build_keyboard(_features(update.effective_chat.id)),
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    context.user_data.pop("flow", None)
    await update.effective_message.reply_text(
        title(E["cancel"], "Đã huỷ", "Chọn lại từ <b>menu bên dưới</b>."),
        parse_mode=HTML,
        reply_markup=menus.build_keyboard(_features(update.effective_chat.id)),
    )


# --------------------------------------------------------------------------- #
# Nut menu chinh + nhap lieu conversation
# --------------------------------------------------------------------------- #
async def on_menu_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    chat = update.effective_chat.id
    if not is_allowed(chat):
        return
    text = (update.message.text or "").strip()

    if text == C.LBL_CANCEL:
        return await cancel(update, context)
    if text == C.LBL_MENU:
        return await show_menu(update, context)

    feature = menus.LABEL_TO_FEATURE.get(text)
    flow = context.user_data.get("flow")
    if flow and feature is None:
        return await handle_flow(update, context, flow, text)
    if feature is None:
        return await show_menu(update, context, "Vui lòng chọn từ <b>menu bên dưới</b>.")

    context.user_data.pop("flow", None)  # dieu huong sang nhom khac -> huy flow
    if not has_feature(chat, feature):
        return await update.message.reply_text(texts.DENY, parse_mode=HTML)
    await open_group(update, context, feature, edit=False)


# --------------------------------------------------------------------------- #
# Man hinh nhom (sync builder -> chay trong thread)
# --------------------------------------------------------------------------- #
def _screen_domain():
    return title(E["domain"], "Quản lý Domain", ""), menus.domain_menu()


def _screen_db():
    return title(E["db"], "Quản lý Database", ""), menus.db_menu()


def _screen_wp():
    return title(E["wp"], "WordPress", "Chọn thao tác:"), menus.wp_menu()


def _screen_ssl():
    return title(E["ssl"], "Quản lý SSL", ""), menus.ssl_menu()


def _screen_cache():
    return (title(E["cache"], "Cache",
                  f"Redis {hostvn.icon('redis')} · Memcached {hostvn.icon('memcached')}"),
            menus.cache_menu())


def _screen_backup():
    return title(E["backup"], "Backup", ""), menus.backup_menu()


def _screen_fw():
    return (title(E["fw"], "Firewall / Fail2ban", f"Fail2ban {hostvn.icon('fail2ban')}"),
            menus.fw_menu())


def _screen_php():
    return title(E["php"], f"PHP {hostvn.php_version()}", ""), menus.php_menu()


def _screen_svc():
    pv = hostvn.php_version()
    names = ["nginx", "mariadb", f"php{pv}-fpm", "redis", "memcached",
             "fail2ban", "cloudflared", "cron"]
    stat = hostvn.services_status(names)
    items = [((E["on"] if stat.get(n) == "active" else E["off"]) + f" {n}", n) for n in names]
    return title(E["svc"], "Dịch vụ", "Bấm để điều khiển:"), menus.services_menu(items)


def _screen_sys():
    st = hostvn.status()
    pv = st["php_ver"]
    body = (
        f"Nginx      : {st['nginx']}\n"
        f"MariaDB    : {st['mariadb']}\n"
        f"PHP-FPM    : {st['php' + pv + '-fpm']}\n"
        f"Redis      : {st['redis']}\n"
        f"Memcached  : {st['memcached']}\n"
        f"Fail2ban   : {st['fail2ban']}\n"
        f"Cloudflared: {st['cloudflared']}\n"
        f"Disk : {st['disk']}\n"
        f"RAM  : {st['ram']}\n"
        f"Load : {st['load']}\n"
        f"Uptime: {st['uptime']}"
    )
    return title(E["sys"], "Trạng thái hệ thống", pre(body)), menus.sys_menu()


def _screen_vps():
    return title(E["vps"], "Quản lý VPS", ""), menus.vps_menu()


def _screen_tool():
    return title(E["tool"], "Công cụ", ""), menus.tool_menu()


GROUP_SCREENS = {
    C.F_DOMAIN: _screen_domain, C.F_DB: _screen_db, C.F_WP: _screen_wp,
    C.F_SSL: _screen_ssl, C.F_CACHE: _screen_cache, C.F_BACKUP: _screen_backup,
    C.F_FW: _screen_fw, C.F_PHP: _screen_php, C.F_SVC: _screen_svc,
    C.F_SYS: _screen_sys, C.F_VPS: _screen_vps, C.F_TOOL: _screen_tool,
}


# Nhan hien thi cua tung nhom (dung cho tieu de thanh tien trinh)
FEATURE_LABEL = {k: lbl for row in menus.MAIN_MENU for k, lbl in row}


async def open_group(update: Update, context: ContextTypes.DEFAULT_TYPE, feature: str, edit: bool) -> None:
    builder = GROUP_SCREENS.get(feature)
    if builder is None:
        return await show_menu(update, context)
    label = FEATURE_LABEL.get(feature, "")
    await _progress_op(
        update, edit,
        f"⏳ <b>Đang tải</b> {texts.esc(label)}…",
        asyncio.to_thread(builder),
        lambda r: r,          # builder da tra (text, keyboard)
        est=4.0,
    )


# --------------------------------------------------------------------------- #
# Router callback trung tam
# --------------------------------------------------------------------------- #
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    chat = update.effective_chat.id
    if not is_allowed(chat):
        return

    parts = (query.data or "").split("|")
    domain = parts[0] if parts else ""
    action = parts[1] if len(parts) > 1 else ""
    params = parts[2:]

    route = CALLBACK_ROUTES.get(domain)
    if route is None:
        return await query.edit_message_text("⚠️ Lựa chọn không hợp lệ.", parse_mode=HTML)
    await route(update, context, action, params)


async def cb_nav(update, context, action, params):
    if action == "home":
        await update.callback_query.edit_message_text(
            title(E["home"], "Menu chính", "Dùng <b>menu bên dưới</b> để chọn chức năng."),
            parse_mode=HTML,
        )


async def cb_open(update, context, feature, params):
    if not has_feature(update.effective_chat.id, feature):
        return await update.callback_query.edit_message_text(texts.DENY, parse_mode=HTML)
    await open_group(update, context, feature, edit=True)


# ---- Dich vu ---------------------------------------------------------------- #
async def cb_svc(update, context, service, params):
    chat = update.effective_chat.id
    if not has_feature(chat, C.F_SVC):
        return await update.callback_query.edit_message_text(texts.DENY, parse_mode=HTML)

    def render(state):
        ic = E["on"] if state == "active" else E["off"]
        return (title(E["svc"], service, f"Trạng thái: <b>{texts.esc(state)}</b> {ic}"),
                menus.service_one_menu(service, can_write(chat)))

    await _progress_op(update, True, f"⏳ <b>Đang kiểm tra</b> {texts.esc(service)}…",
                       asyncio.to_thread(hostvn.svc_status, service), render, est=3.0)


def _svc_act_then_status(act: str, service: str) -> str:
    hostvn.svc(act, service)
    return hostvn.svc_status(service)


async def cb_do(update, context, service, params):
    q = update.callback_query
    act = params[0] if params else ""
    if not can_write(update.effective_chat.id):
        return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                         reply_markup=menus.back_only("m|svc"))

    def render(state):
        ic = E["on"] if state == "active" else E["off"]
        return (title(E["confirm"], f"{act} {service}",
                      f"Trạng thái: <b>{texts.esc(state)}</b> {ic}"),
                menus.service_one_menu(service, True))

    await _progress_op(
        update, True,
        f"{E['refresh']} <b>Đang {texts.esc(act)}</b> {texts.esc(service)}…",
        asyncio.to_thread(_svc_act_then_status, act, service),
        render, est=5.0,
        stages=[(45, f"{E['refresh']} <b>Đang khởi động lại</b> {texts.esc(service)}…"),
                (80, f"{E['refresh']} <b>Đang kiểm tra trạng thái</b>…")],
    )


# ---- Hanh dong "a|..." ------------------------------------------------------ #
async def cb_action(update, context, action, params):
    q = update.callback_query
    chat = update.effective_chat.id

    if action in WRITE_ACTIONS and not can_write(chat):
        return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                         reply_markup=menus.back_only())

    # ----- Cac hanh dong mo flow / picker -----
    if action == "dom_add":
        return await start_flow(update, context, "dom_add", "m|domain",
                                E["domain"], "Thêm domain",
                                "Nhập <b>tên miền</b> (vd: shop.com):")
    if action == "db_add":
        return await start_flow(update, context, "db_add", "m|db",
                                E["db"], "Tạo database",
                                "Nhập <b>tên database</b> (chỉ chữ/số/gạch dưới):")
    # ----- SSL: cac buoc rieng -----
    if action == "ssl_cfapi":
        return await _progress_op(
            update, True, "⏳ <b>Đang đọc cấu hình CF API…</b>",
            asyncio.to_thread(hostvn.cf_api_status),
            lambda st: (title("☁️", "CloudFlare DNS API", pre(st) +
                              "\n\nDùng cho <b>Wildcard SSL</b> (xác thực DNS-01)."),
                        menus.rows_menu([[("☁️ Nhập/Cập nhật token", "ssl|cfset")]], back="m|ssl")),
            est=3.0)
    if action == "ssl_renew":
        return await q.edit_message_text(
            title(E["warn"], "Gia hạn tất cả SSL",
                  "Chạy gia hạn cho <b>toàn bộ</b> chứng chỉ? Có thể mất vài phút."),
            parse_mode=HTML, reply_markup=menus.confirm_menu("sslrenew", back="m|ssl"))

    # ----- Backup: cac buoc rieng -----
    if action == "bk_del":
        return await _progress_op(
            update, True, "⏳ <b>Đang quét bản backup…</b>",
            asyncio.to_thread(hostvn.list_backups),
            lambda rows: (
                title(E["del"], "Xoá bản backup",
                      "Chọn bản muốn xoá:" if rows else "Chưa có bản backup nào."),
                menus.backup_entry_menu(
                    [(r["domain"], r["date"], f"{E['del']} {r['domain']} · {r['date']} ({r['size']})")
                     for r in rows], "del")),
            est=4.0)
    if action == "bk_remotes":
        return await _progress_op(
            update, True, "⏳ <b>Đang đọc cấu hình rclone…</b>",
            asyncio.to_thread(hostvn.rclone_remotes),
            lambda rs: (title("☁️", "Remote đã kết nối",
                              (pre("\n".join(rs)) + "\nBấm để <b>xoá</b> kết nối.") if rs
                              else "Chưa kết nối remote nào."),
                        menus.remotes_menu(rs)),
            est=3.0)

    # ----- Cac picker (tai danh sach) -----
    PICKERS = {
        "dom_info": (hostvn.list_domains, "dominfo", E["domain"], "m|domain",
                     (E["domain"], "Chọn domain", "Xem thông tin:")),
        "dom_del":  (hostvn.list_domains, "domdel", E["domain"], "m|domain",
                     (E["del"], "Xoá domain", "Chọn domain để XOÁ:")),
        "db_del":   (hostvn.list_dbs, "dbdel", E["db"], "m|db",
                     (E["del"], "Xoá database", "Chọn DB để XOÁ:")),
        "wp_cache": (hostvn.list_domains, "wpcache", E["wp"], "m|wp",
                     (E["wp"], "Xoá cache WP", "Chọn site:")),
        "bk_run":   (hostvn.list_domains, "bkdom", E["backup"], "m|backup",
                     (E["backup"], "Backup website", "Chọn website cần backup:")),
        "bk_restore": (hostvn.list_domains, "rsdom", E["domain"], "m|backup",
                       ("♻️", "Khôi phục dữ liệu", "Chọn website cần khôi phục:")),
        # --- Quan ly domain nang cao ---
        "dom_rename":   (hostvn.list_domains, "dmrename", E["domain"], "m|domain",
                         ("✏️", "Đổi tên miền", "Chọn domain cần đổi:")),
        "dom_rewrite":  (hostvn.list_domains, "dmrw", E["domain"], "m|domain",
                         ("🧱", "Rewrite vHost", "Chọn domain cần tạo lại vHost:")),
        "dom_php":      (hostvn.list_domains, "dmphp", E["domain"], "m|domain",
                         (E["php"], "Đổi phiên bản PHP", "Chọn domain:")),
        "dom_alias":    (hostvn.list_domains, "dmalias", E["domain"], "m|domain",
                         ("🔗", "Alias/Parked domain", "Chọn domain chính:")),
        "dom_redirect": (hostvn.list_domains, "dmredir", E["domain"], "m|domain",
                         ("↪️", "Redirect domain", "Chọn domain đích:")),
        "dom_sftp":     (hostvn.list_domains, "dmsftp", E["domain"], "m|domain",
                         (E["key"], "Đổi mật khẩu SFTP", "Chọn domain:")),
        "dom_protect":  (hostvn.list_domains, "dmprot", E["domain"], "m|domain",
                         ("🔐", "Bảo vệ thư mục", "Chọn domain:")),
        "dom_http3":    (hostvn.list_domains, "dmhttp3", E["domain"], "m|domain",
                         ("🚀", "HTTP/3 (QUIC)", "Chọn domain:")),
        # --- SSL ---
        "ssl_create":   (hostvn.list_domains, "sslnew", E["ssl"], "m|ssl",
                         (E["ssl"], "Cấp/Gia hạn Let's Encrypt", "Chọn domain:")),
        "ssl_wildcard": (hostvn.list_domains, "sslwild", E["ssl"], "m|ssl",
                         ("🌟", "Wildcard SSL", "Chọn domain gốc:")),
        "ssl_remove":   (hostvn.list_domains, "ssldel", E["ssl"], "m|ssl",
                         (E["del"], "Gỡ Let's Encrypt", "Chọn domain:")),
        "ssl_alias":    (hostvn.list_domains, "sslalias", E["ssl"], "m|ssl",
                         ("🔗", "SSL cho Alias domain", "Chọn domain chính:")),
    }
    if action in PICKERS:
        loader, pick_act, emo, back, (t_emo, t_head, t_hint) = PICKERS[action]
        return await _progress_op(
            update, True, "⏳ <b>Đang tải danh sách…</b>",
            asyncio.to_thread(loader),
            lambda items: (title(t_emo, t_head, t_hint),
                           menus.picker_menu(pick_act, items, emo, back)),
            est=3.0,
        )

    # ----- Cac hanh dong tra ket qua -----
    await _progress_op(
        update, True, "⏳ <b>Đang xử lý…</b>",
        asyncio.to_thread(_run_action, action, chat),
        lambda r: (r[0], menus.back_only(r[1])),
        est=6.0,
        stages=[(60, "⚙️ <b>Đang thu thập dữ liệu…</b>")],
    )


def _run_action(action: str, chat: int):
    """Sync: thuc hien 1 hanh dong read/write -> (text, back_target)."""
    if action == "dom_list":
        ds = hostvn.list_domains()
        body = "\n".join(f"{E['domain']} {d} — {hostvn.http_code(d)}" for d in ds) or "(chưa có)"
        return title(E["domain"], "Domain", pre(body)), "m|domain"
    if action == "db_list":
        body = "\n".join(f"{E['db']} {d}" for d in hostvn.list_dbs()) or "(chưa có)"
        return title(E["db"], "Database", pre(body)), "m|db"
    if action == "wp_list":
        lines = []
        for d in hostvn.list_domains():
            dr = hostvn.docroot(d)
            tag = "WP" if dr and (Path(dr) / "wp-admin").is_dir() else "—"
            lines.append(f"{E['wp']} {d} [{tag}]")
        return title(E["wp"], "Site WordPress", pre("\n".join(lines) or "(chưa có)")), "m|wp"
    if action == "ssl_check":
        note = ""
        if hostvn.is_tunnel_mode():
            note = ("\n<i>Lưu ý: qua Cloudflare Tunnel, chứng chỉ người dùng thấy là của "
                    "Cloudflare — không phản ánh chứng chỉ trên server.</i>")
        return (title(E["month"], "Đối chiếu chứng chỉ",
                      pre(hostvn.ssl_report()) + note), "m|ssl")
    if action == "f2b_stats":
        return title(E["fw"], "Fail2ban", pre(hostvn.fail2ban_stats())), "m|fw"
    if action == "php_info":
        return title(E["php"], f"PHP {hostvn.php_version()}", pre(hostvn.php_info())), "m|php"
    if action == "vps_info":
        return title(E["vps"], "Thông tin VPS", pre(hostvn.vps_info())), "m|vps"
    if action == "vps_disk":
        return title(E["vps"], "Dung lượng /home", pre(hostvn.vps_disk())), "m|vps"
    if action == "links":
        return title(E["tool"], "Link Admin", pre(hostvn.admin_links())), "m|tool"
    if action == "largefiles":
        return title(E["tool"], "File lớn /home", pre(hostvn.largefiles())), "m|tool"
    if action == "bk_list":
        rows = hostvn.list_backups()
        if not rows:
            body = "(chưa có bản backup nào)"
        else:
            body = "\n".join(f"{r['date']}  {r['domain']}  {r['size']}\n   " +
                             ", ".join(r["files"]) for r in rows[:15])
        return (title(E["backup"], "Danh sách bản backup",
                      pre(body) + f"\nThư mục: <code>{hostvn.BACKUP_ROOT}</code>"), "m|backup")
    if action == "bk_auto":
        return (title("⏰", "Auto backup", pre(hostvn.autobackup_info()) +
                      "\n<i>Đặt lịch chi tiết ở menu Cronjob trong shell.</i>"), "m|backup")
    if action == "ssl_list":
        rows = hostvn.ssl_list()
        icon = {"letsencrypt": "🔒", "self-signed": "🟡", "none": "🔓"}
        label = {"letsencrypt": "Let's Encrypt", "self-signed": "tự ký (hostvn)", "none": "không có"}
        body = "\n".join(
            f"{icon[r['kind']]} {r['domain']} — {label[r['kind']]}"
            + (f"\n   hết hạn: {r['expire']}" if r["expire"] else "")
            for r in rows) or "(chưa có domain)"
        note = ""
        if hostvn.is_tunnel_mode():
            note = ("\n\n<i>Đang chạy Cloudflare Tunnel: TLS được Cloudflare xử lý ở biên, "
                    "đoạn cloudflared→Cloudflare đã mã hoá sẵn. Chứng chỉ tự ký ở đây là bình "
                    "thường và <b>không cần</b> cấp Let's Encrypt.</i>")
        return title(E["ssl"], "Chứng chỉ trên server", pre(body) + note), "m|ssl"
    if action == "ssl_paid":
        return (title("📜", "SSL trả phí",
                      "Quy trình này cần tạo CSR (nhập quốc gia, tỉnh, tổ chức…) rồi "
                      "<b>dán nội dung file CRT/CA/Private Key</b> nhiều dòng — không phù hợp "
                      "để nhập qua chat.\n\nChạy qua SSH: <code>hostvn</code> → "
                      "<b>2. Quan ly SSL</b> → <b>2. SSL tra phi</b>."), "m|ssl")
    if action == "dom_clone":
        return (title("🧬", "Clone website",
                      "Clone gồm nhiều bước hỏi ghi đè dữ liệu nguồn/đích nên "
                      "<b>chưa đưa lên bot</b> để tránh mất dữ liệu.\n\n"
                      "Chạy qua SSH: <code>hostvn</code> → <b>1. Quan ly ten mien</b> → "
                      "<b>9. Clone website</b>."), "m|domain")
    if action == "dom_dbinfo":
        return (title(E["db"], "Đổi thông tin Database",
                      "Đổi tên DB/user/mật khẩu sẽ làm site lỗi nếu file cấu hình "
                      "(wp-config.php…) không được sửa khớp, nên <b>chưa đưa lên bot</b>.\n\n"
                      "Chạy qua SSH: <code>hostvn</code> → <b>1. Quan ly ten mien</b> → "
                      "<b>10. Doi thong tin Database</b>."), "m|domain")
    if action == "bk_connect":
        return (title("🔗", "Kết nối kho lưu trữ",
                      "Google Drive và OneDrive cần đăng nhập OAuth qua trình duyệt, "
                      "còn S3 cần nhập access key/secret — <b>không an toàn khi gõ qua chat</b>.\n\n"
                      "Vui lòng chạy qua SSH:\n<code>hostvn</code> → <b>8. Sao luu/Khoi phuc</b> → "
                      "mục 4 (GDrive) / 6 (OneDrive) / 7 (S3).\n\n"
                      "Sau khi kết nối xong, remote sẽ hiện ở <b>☁️ Remote đã kết nối</b>."), "m|backup")
    # write:
    if action == "cache_clear":
        return title(E["cache"], "Xoá cache", hostvn.clear_fastcgi()), "m|cache"
    if action == "opcache_clear":
        return title(E["cache"], "OPcache", hostvn.clear_opcache()), "m|cache"
    if action == "php_restart":
        pv = hostvn.php_version()
        hostvn.svc("restart", f"php{pv}-fpm")
        return title(E["php"], "PHP-FPM", f"Đã restart php{pv}-fpm."), "m|php"
    return title(E["warn"], "Chưa hỗ trợ", ""), C.CB_HOME


# ---- Picker (chon domain/db) ------------------------------------------------ #
async def cb_pick(update, context, action, params):
    q = update.callback_query
    chat = update.effective_chat.id
    target = params[0] if params else ""

    if action == "dominfo":
        return await _progress_op(
            update, True, f"⏳ <b>Đang đọc</b> {texts.esc(target)}…",
            asyncio.to_thread(_domain_info, target),
            lambda t: (t, menus.back_only("m|domain")), est=5.0)
    if action == "wpcache":
        if not can_write(chat):
            return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                             reply_markup=menus.back_only("m|wp"))
        return await _progress_op(
            update, True, f"{E['cache']} <b>Đang xoá cache</b> {texts.esc(target)}…",
            asyncio.to_thread(_wp_cache_flush, target),
            lambda _: (title(E["wp"], target, "Đã xoá cache WordPress (nếu có)."),
                       menus.back_only("m|wp")), est=6.0)
    # ----- SSL: sau khi chon domain -> xac nhan roi chay -----
    if action in ("sslnew", "sslwild", "ssldel", "sslalias"):
        if not can_write(chat):
            return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                             reply_markup=menus.back_only("m|ssl"))
        what = {"sslnew": ("Cấp/Gia hạn Let's Encrypt cho", "sslnew"),
                "sslwild": ("Cấp Wildcard SSL cho *.", "sslwild"),
                "ssldel": ("GỠ chứng chỉ Let's Encrypt của", "ssldel"),
                "sslalias": ("Cấp SSL cho Alias domain của", "sslalias")}[action]
        extra = ""
        if action in ("sslnew", "sslalias") and await asyncio.to_thread(hostvn.is_tunnel_mode):
            extra = ("\n\n⚠️ Đang chạy <b>Cloudflare Tunnel</b>: TLS đã do Cloudflare xử lý nên "
                     "chứng chỉ này thường <b>không cần</b>, và xác thực HTTP-01 có thể thất bại "
                     "vì port 80 không mở trực tiếp ra Internet.\n"
                     "Muốn có chứng chỉ thật trên server thì dùng <b>Wildcard SSL (CF DNS)</b>.")
        return await q.edit_message_text(
            title(E["warn"], "Xác nhận", f"{what[0]}<b>{texts.esc(target)}</b>?" + extra),
            parse_mode=HTML,
            reply_markup=menus.confirm_menu(what[1], target, back="m|ssl"))

    # ----- Quan ly domain nang cao: sau khi chon domain -----
    if action in ("dmrename", "dmrw", "dmphp", "dmalias", "dmredir",
                  "dmsftp", "dmprot", "dmhttp3"):
        if not can_write(chat):
            return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                             reply_markup=menus.back_only("m|domain"))
        context.user_data["dom"] = target
        if action == "dmhttp3":
            return await q.edit_message_text(
                title("🚀", f"HTTP/3 — {target}", "Bật hay tắt HTTP/3 (QUIC)?"),
                parse_mode=HTML, reply_markup=menus.onoff_menu(target, "h3"))
        if action == "dmrw":
            return await q.edit_message_text(
                title("🧱", f"Rewrite vHost — {target}",
                      "Chọn loại mã nguồn để tạo lại file cấu hình:"),
                parse_mode=HTML, reply_markup=menus.source_menu(target))
        if action == "dmphp":
            vers = await asyncio.to_thread(hostvn.php_versions)
            if len(vers) < 2:
                return await q.edit_message_text(
                    title(E["php"], "Đổi phiên bản PHP",
                          f"Máy chỉ cài <b>một</b> phiên bản PHP ({', '.join(vers) or '?'}).\n"
                          "Cài thêm PHP thứ hai qua SSH rồi mới đổi được."),
                    parse_mode=HTML, reply_markup=menus.back_only("m|domain"))
            return await q.edit_message_text(
                title(E["php"], f"Đổi PHP — {target}", "Chọn phiên bản:"),
                parse_mode=HTML, reply_markup=menus.php_choice_menu(target, vers))
        if action == "dmsftp":
            return await q.edit_message_text(
                title(E["key"], "Đổi mật khẩu SFTP",
                      f"Tạo mật khẩu SFTP mới ngẫu nhiên cho <b>{texts.esc(target)}</b>?"),
                parse_mode=HTML,
                reply_markup=menus.confirm_menu("sftp", target, back="m|domain"))
        # Cac thao tac can nhap lieu
        prompts = {
            "dmrename": ("✏️", "Đổi tên miền", "Nhập <b>tên miền mới</b> (vd: moi.com):"),
            "dmalias":  ("🔗", "Alias/Parked", "Nhập <b>domain alias</b> (vd: alias.com):"),
            "dmredir":  ("↪️", "Redirect", f"Nhập <b>domain nguồn</b> sẽ chuyển hướng về {texts.esc(target)}:"),
            "dmprot":   ("🔐", "Bảo vệ thư mục",
                         "Nhập <b>đường_dẫn user mật_khẩu</b> cách nhau bởi dấu cách.\n"
                         "Ví dụ: <code>/upload admin MatKhau123</code>"),
        }
        emo, head, prompt = prompts[action]
        flow = {"dmrename": "dom_rename", "dmalias": "dom_alias",
                "dmredir": "dom_redirect", "dmprot": "dom_protect"}[action]
        return await start_flow(update, context, flow, "m|domain", emo,
                                f"{head} — {target}", prompt)

    if action == "bkdom":     # chon website -> chon loai backup
        if not can_write(chat):
            return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                             reply_markup=menus.back_only("m|backup"))
        return await q.edit_message_text(
            title(E["backup"], f"Backup {target}", "Chọn nội dung cần backup:"),
            parse_mode=HTML, reply_markup=menus.backup_type_menu(target))
    if action == "rsdom":     # chon website -> chon ngay backup
        if not can_write(chat):
            return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                             reply_markup=menus.back_only("m|backup"))
        return await _progress_op(
            update, True, f"⏳ <b>Đang tìm bản backup của</b> {texts.esc(target)}…",
            asyncio.to_thread(hostvn.backup_dates, target),
            lambda dates: (title("♻️", f"Khôi phục {target}",
                                 "Chọn ngày backup:" if dates
                                 else "Website này chưa có bản backup nào."),
                           menus.backup_date_menu(target, dates)),
            est=3.0)
    if action == "domdel":
        if not can_write(chat):
            return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                             reply_markup=menus.back_only("m|domain"))
        return await q.edit_message_text(
            title(E["warn"], "Xác nhận xoá domain",
                  f"Xoá <b>{texts.esc(target)}</b> và toàn bộ dữ liệu?"),
            parse_mode=HTML, reply_markup=menus.confirm_menu("domdel", target))
    if action == "dbdel":
        if not can_write(chat):
            return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                             reply_markup=menus.back_only("m|db"))
        return await q.edit_message_text(
            title(E["warn"], "Xác nhận xoá database", f"Xoá <b>{texts.esc(target)}</b>?"),
            parse_mode=HTML, reply_markup=menus.confirm_menu("dbdel", target))


def _domain_info(d: str) -> str:
    dr = hostvn.docroot(d)
    code = hostvn.http_code(d)
    size = hostvn.sh(f"du -sh {Path(dr).parent} 2>/dev/null | cut -f1", 15) if dr else "?"
    wp = "có" if dr and (Path(dr) / "wp-admin").is_dir() else "không"
    body = f"HTTP: {code}\nWordPress: {wp}\nDung lượng: {size}\nDocroot: {dr}"
    return title(E["domain"], d, pre(body))


def _wp_cache_flush(d: str) -> None:
    dr = hostvn.docroot(d)
    if dr:
        hostvn.sh(f"cd {dr} && wp cache flush --allow-root 2>/dev/null", 30)


# ---- Tao domain (nd|def|<d> / nd|wp|<d>) ------------------------------------ #
async def cb_nd(update, context, typ, params):
    q = update.callback_query
    chat = update.effective_chat.id
    domain = params[0] if params else ""
    if not can_write(chat):
        return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                         reply_markup=menus.back_only("m|domain"))
    is_wp = typ == "wp"
    kind = "WordPress" if is_wp else "website PHP"
    base = f"{E['domain']} <b>Đang tạo {kind}</b> {texts.esc(domain)}…"
    if is_wp:
        est = 40.0
        stages = [
            (12, f"{E['domain']} <b>Tạo user &amp; thư mục</b> {texts.esc(domain)}…"),
            (32, f"{E['db']} <b>Tạo database &amp; user MySQL</b>…"),
            (52, f"{E['wp']} <b>Đang tải mã nguồn WordPress</b>…"),
            (76, f"{E['wp']} <b>Đang cài đặt WordPress</b>…"),
            (90, f"{E['refresh']} <b>Tạo vHost &amp; reload nginx</b>…"),
        ]
    else:
        est = 14.0
        stages = [
            (25, f"{E['domain']} <b>Tạo user &amp; thư mục</b>…"),
            (55, f"{E['php']} <b>Cấu hình PHP-FPM pool</b>…"),
            (82, f"{E['refresh']} <b>Tạo vHost &amp; reload nginx</b>…"),
        ]

    def render(res):
        ok, info, err = res
        if not ok:
            return (title(E["warn"], f"Chưa tạo được {domain}", pre(err)),
                    menus.back_only("m|domain"))
        lines = [f"Docroot   : {info['docroot']}",
                 f"SFTP user : {info['sftp_user']}",
                 f"SFTP pass : {info['sftp_pass']}"]
        if info.get("db_name"):
            lines += [f"DB name   : {info['db_name']}",
                      f"DB user   : {info['db_user']}",
                      f"DB pass   : {info['db_pass']}"]
        if info.get("wp_user"):
            lines += [f"WP admin  : {info['wp_user']}",
                      f"WP pass   : {info['wp_pass']}",
                      f"WP login  : http://{domain}/wp-admin"]
        return (title(E["confirm"], f"Đã tạo {domain}",
                      f"<code>{progress.bar(100)}</code>\n" + pre("\n".join(lines)) +
                      "\n⚠️ <b>Lưu lại thông tin này!</b>"),
                menus.back_only("m|domain"))

    await _progress_op(update, True, base,
                       asyncio.to_thread(hostvn.create_domain, typ, domain),
                       render, est=est, stages=stages)


# ---- SSL (mien "ssl") ------------------------------------------------------- #
async def cb_ssl(update, context, action, params):
    q = update.callback_query
    chat = update.effective_chat.id
    if not has_feature(chat, C.F_SSL):
        return await q.edit_message_text(texts.DENY, parse_mode=HTML)
    if not can_write(chat):
        return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                         reply_markup=menus.back_only("m|ssl"))
    if action == "cfset":
        return await start_flow(
            update, context, "ssl_cfapi", "m|ssl", "☁️", "CloudFlare DNS API",
            "Gửi <b>token</b> và <b>email</b> cách nhau bởi dấu cách.\n"
            "Ví dụ: <code>cfut_xxxxx you@mail.com</code>\n\n"
            "⚠️ <b>Hãy xoá tin nhắn đó sau khi gửi</b> — token nằm trong lịch sử chat.")


# ---- Quan ly domain nang cao (mien "dm") ------------------------------------ #
async def cb_dm(update, context, action, params):
    q = update.callback_query
    chat = update.effective_chat.id
    if not has_feature(chat, C.F_DOMAIN):
        return await q.edit_message_text(texts.DENY, parse_mode=HTML)
    if not can_write(chat):
        return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                         reply_markup=menus.back_only("m|domain"))
    domain = params[0] if params else ""

    if action in ("h3on", "h3off"):
        on = action == "h3on"
        return await _progress_op(
            update, True,
            f"🚀 <b>Đang {'bật' if on else 'tắt'} HTTP/3</b> cho {texts.esc(domain)}…",
            asyncio.to_thread(hostvn.dom_http3, domain, on),
            lambda r: ((title(E["confirm"], "HTTP/3", texts.esc(r[1])) if r[0]
                        else title(E["warn"], "Không đổi được HTTP/3", texts.esc(r[1]))),
                       menus.back_only("m|domain")),
            est=20.0)

    if action == "rw":       # dm|rw|<domain>|<source_idx>
        src = int(params[1]) if len(params) > 1 and params[1].isdigit() else 20
        return await _progress_op(
            update, True, f"🧱 <b>Đang tạo lại vHost</b> cho {texts.esc(domain)}…",
            asyncio.to_thread(hostvn.dom_rewrite_config, domain, src),
            lambda r: ((title(E["confirm"], "Rewrite vHost", texts.esc(r[1])) if r[0]
                        else title(E["warn"], "Rewrite thất bại", texts.esc(r[1]))),
                       menus.back_only("m|domain")),
            est=25.0)

    if action == "php":      # dm|php|<domain>|<1|2>
        choice = int(params[1]) if len(params) > 1 and params[1].isdigit() else 1
        return await _progress_op(
            update, True, f"{E['php']} <b>Đang đổi phiên bản PHP</b> cho {texts.esc(domain)}…",
            asyncio.to_thread(hostvn.dom_change_php, domain, choice),
            lambda r: (title(E["confirm"] if r[0] else E["warn"], "Đổi phiên bản PHP",
                             texts.esc(r[1])), menus.back_only("m|domain")),
            est=30.0)


# ---- Backup / Restore (mien "bk") ------------------------------------------ #
async def cb_bk(update, context, action, params):
    q = update.callback_query
    chat = update.effective_chat.id
    if not has_feature(chat, C.F_BACKUP):
        return await q.edit_message_text(texts.DENY, parse_mode=HTML)
    if not can_write(chat):
        return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                         reply_markup=menus.back_only("m|backup"))

    # bk|run|<type>|<domain>  -> chay backup ngay
    if action == "run":
        btype = params[0] if params else "full"
        domain = params[1] if len(params) > 1 else ""
        names = {"full": "full (mã nguồn + DB)", "source": "mã nguồn", "db": "database"}
        return await _progress_op(
            update, True,
            f"{E['backup']} <b>Đang backup</b> {texts.esc(domain)} — {names.get(btype, btype)}…",
            asyncio.to_thread(hostvn.backup_site, domain, btype),
            lambda r: ((title(E["confirm"], f"Backup {domain}",
                              f"<code>{progress.bar(100)}</code>\n{r[1]}\n"
                              f"Thư mục: <code>{texts.esc(r[2])}</code>") if r[0]
                        else title(E["warn"], f"Backup {domain} thất bại", texts.esc(r[1]))),
                       menus.back_only("m|backup")),
            est=45.0,
            stages=[(30, f"📁 <b>Đang nén mã nguồn</b> {texts.esc(domain)}…"),
                    (70, f"{E['db']} <b>Đang dump database</b>…"),
                    (90, "🔄 <b>Đang hoàn tất</b>…")])

    # bk|rsd|<domain>|<date> -> chon loai khoi phuc
    if action == "rsd":
        domain = params[0] if params else ""
        date = params[1] if len(params) > 1 else ""
        return await q.edit_message_text(
            title("♻️", f"Khôi phục {domain}", f"Bản ngày <b>{texts.esc(date)}</b>. Chọn nội dung:"),
            parse_mode=HTML, reply_markup=menus.restore_type_menu(domain, date))

    # bk|rst|<type>|<domain>|<date> -> XAC NHAN (ghi de du lieu hien tai)
    if action == "rst":
        rtype = params[0] if params else "full"
        domain = params[1] if len(params) > 1 else ""
        date = params[2] if len(params) > 2 else ""
        what = {"full": "mã nguồn + database", "source": "mã nguồn", "db": "database"}.get(rtype, rtype)
        return await q.edit_message_text(
            title(E["warn"], "Xác nhận khôi phục",
                  f"Khôi phục <b>{what}</b> cho <b>{texts.esc(domain)}</b> "
                  f"từ bản <b>{texts.esc(date)}</b>?\n\n"
                  f"⚠️ Dữ liệu hiện tại sẽ bị <b>GHI ĐÈ</b>."),
            parse_mode=HTML,
            reply_markup=menus.confirm_menu("rst", rtype, domain, date, back="m|backup"))

    # bk|del|<domain>|<date> -> XAC NHAN xoa ban backup
    if action == "del":
        domain = params[0] if params else ""
        date = params[1] if len(params) > 1 else ""
        return await q.edit_message_text(
            title(E["warn"], "Xác nhận xoá backup",
                  f"Xoá bản backup <b>{texts.esc(domain)}</b> ngày <b>{texts.esc(date)}</b>?"),
            parse_mode=HTML,
            reply_markup=menus.confirm_menu("bkdel", domain, date, back="m|backup"))

    # bk|rmdel|<remote> -> XAC NHAN xoa ket noi rclone
    if action == "rmdel":
        remote = params[0] if params else ""
        return await q.edit_message_text(
            title(E["warn"], "Xác nhận xoá kết nối",
                  f"Xoá remote <b>{texts.esc(remote)}</b> khỏi rclone?\n"
                  f"<i>Chỉ xoá cấu hình kết nối, không xoá dữ liệu trên cloud.</i>"),
            parse_mode=HTML,
            reply_markup=menus.confirm_menu("rmdel", remote, back="m|backup"))


# ---- Xac nhan thao tac nguy hiem (cf / yes) --------------------------------- #
async def cb_cf(update, context, action, params):
    q = update.callback_query
    if not can_write(update.effective_chat.id):
        return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                         reply_markup=menus.back_only("m|vps"))
    if action == "restartall":
        await q.edit_message_text(
            title(E["warn"], "Xác nhận", "Restart tất cả dịch vụ (MariaDB/PHP/Nginx)?"),
            parse_mode=HTML, reply_markup=menus.confirm_menu("restartall"))
    elif action == "reboot":
        await q.edit_message_text(
            title(E["warn"], "Xác nhận", "Reboot server?"),
            parse_mode=HTML, reply_markup=menus.confirm_menu("reboot"))


async def cb_yes(update, context, what, params):
    q = update.callback_query
    chat = update.effective_chat.id
    if not can_write(chat):
        return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                         reply_markup=menus.back_only())
    param = params[0] if params else ""

    if what == "restartall":
        return await _progress_op(
            update, True, f"{E['refresh']} <b>Đang restart toàn bộ dịch vụ</b>…",
            asyncio.to_thread(hostvn.restart_stack),
            lambda msg: (title(E["confirm"], "Hoàn tất",
                               f"<code>{progress.bar(100)}</code>\n{msg}"),
                         menus.back_only("m|vps")),
            est=12.0,
            stages=[(30, f"{E['db']} <b>Đang restart MariaDB</b>…"),
                    (60, f"{E['php']} <b>Đang restart PHP-FPM</b>…"),
                    (85, f"{E['svc']} <b>Đang restart Nginx</b>…")],
        )
    if what == "reboot":
        await q.edit_message_text(
            title(E["reboot"], "Server đang reboot…",
                  f"<code>{progress.bar(100)}</code>\nBot sẽ tự chạy lại sau khi khởi động."),
            parse_mode=HTML)
        await asyncio.to_thread(hostvn.reboot)
        return
    if what == "domdel":
        return await _progress_op(
            update, True, f"{E['del']} <b>Đang xoá domain</b> {texts.esc(param)}…",
            asyncio.to_thread(hostvn.delete_domain, param),
            lambda ok: ((title(E["confirm"], "Đã xoá domain",
                               f"<code>{progress.bar(100)}</code>\n{texts.esc(param)}") if ok
                         else title(E["warn"], "Không xoá được", texts.esc(param))),
                        menus.back_only("m|domain")),
            est=10.0,
            stages=[(40, f"{E['del']} <b>Xoá vHost &amp; PHP pool</b>…"),
                    (70, f"{E['del']} <b>Xoá user, thư mục &amp; database</b>…")],
        )
    # ----- SSL -----
    _SSL_OPS = {
        "sslnew":   (hostvn.ssl_create,   "Cấp SSL", 90.0),
        "sslwild":  (hostvn.ssl_wildcard, "Wildcard SSL", 180.0),
        "ssldel":   (hostvn.ssl_remove,   "Gỡ SSL", 30.0),
    }
    if what in _SSL_OPS:
        fn, label, est = _SSL_OPS[what]
        return await _progress_op(
            update, True, f"{E['ssl']} <b>{label}</b> — {texts.esc(param)}…",
            asyncio.to_thread(fn, param),
            lambda r: ((title(E["confirm"], label,
                              f"<code>{progress.bar(100)}</code>\n{texts.esc(r[1])}") if r[0]
                        else title(E["warn"], f"{label} thất bại", texts.esc(r[1]))),
                       menus.back_only("m|ssl")),
            est=est,
            stages=[(40, f"{E['ssl']} <b>Đang xác thực với Let's Encrypt</b>…"),
                    (75, "🔄 <b>Đang cài chứng chỉ &amp; reload nginx</b>…")])
    if what == "sslalias":
        return await _progress_op(
            update, True, f"{E['ssl']} <b>SSL Alias</b> — {texts.esc(param)}…",
            asyncio.to_thread(hostvn.run_ctl, f"{hostvn.domain_index(param)}\n1",
                              f"{hostvn.SSLCTL}/le_alias_domain", 300),
            lambda out: (title(E["info"], "SSL Alias domain",
                               pre(hostvn._ctl_reason(out, "Đã chạy xong."))),
                         menus.back_only("m|ssl")),
            est=90.0)
    if what == "sslrenew":
        return await _progress_op(
            update, True, f"{E['refresh']} <b>Đang gia hạn toàn bộ SSL</b>…",
            asyncio.to_thread(hostvn.ssl_renew_all),
            lambda r: (title(E["confirm"], "Gia hạn SSL",
                             f"<code>{progress.bar(100)}</code>\n{texts.esc(r[1])}"),
                       menus.back_only("m|ssl")),
            est=180.0,
            stages=[(50, f"{E['ssl']} <b>Đang liên hệ Let's Encrypt</b>…")])

    if what == "sftp":      # yes|sftp|<domain> -> doi mat khau SFTP ngau nhien
        return await _progress_op(
            update, True, f"{E['key']} <b>Đang đổi mật khẩu SFTP</b> {texts.esc(param)}…",
            asyncio.to_thread(hostvn.dom_change_sftp_pass, param, ""),
            lambda r: ((title(E["confirm"], "Đã đổi mật khẩu SFTP",
                              pre(f"Domain : {param}\nUser   : xem menu Thông tin domain\n"
                                  f"Pass   : {r[2]}") + "\n⚠️ <b>Lưu lại!</b>") if r[0]
                        else title(E["warn"], "Không đổi được", texts.esc(r[1]))),
                       menus.back_only("m|domain")),
            est=20.0)
    if what == "rst":       # yes|rst|<type>|<domain>|<date>
        rtype = params[0] if params else "full"
        domain = params[1] if len(params) > 1 else ""
        date = params[2] if len(params) > 2 else ""
        return await _progress_op(
            update, True, f"♻️ <b>Đang khôi phục</b> {texts.esc(domain)} ({texts.esc(date)})…",
            asyncio.to_thread(hostvn.restore_site, domain, date, rtype),
            lambda r: ((title(E["confirm"], "Khôi phục xong",
                              f"<code>{progress.bar(100)}</code>\n{texts.esc(r[1])}") if r[0]
                        else title(E["warn"], "Khôi phục thất bại", texts.esc(r[1]))),
                       menus.back_only("m|backup")),
            est=45.0,
            stages=[(35, "📁 <b>Đang giải nén mã nguồn</b>…"),
                    (70, f"{E['db']} <b>Đang import database</b>…"),
                    (90, "🔄 <b>Đang phân quyền lại</b>…")])
    if what == "bkdel":     # yes|bkdel|<domain>|<date>
        domain = params[0] if params else ""
        date = params[1] if len(params) > 1 else ""
        return await _progress_op(
            update, True, f"{E['del']} <b>Đang xoá backup</b> {texts.esc(domain)} {texts.esc(date)}…",
            asyncio.to_thread(hostvn.delete_backup, domain, date),
            lambda ok: ((title(E["confirm"], "Đã xoá bản backup",
                               f"{texts.esc(domain)} · {texts.esc(date)}") if ok
                         else title(E["warn"], "Không xoá được", "Kiểm tra lại bản backup.")),
                        menus.back_only("m|backup")),
            est=6.0)
    if what == "rmdel":     # yes|rmdel|<remote>
        return await _progress_op(
            update, True, f"{E['del']} <b>Đang xoá remote</b> {texts.esc(param)}…",
            asyncio.to_thread(hostvn.rclone_delete_remote, param),
            lambda ok: ((title(E["confirm"], "Đã xoá kết nối", texts.esc(param)) if ok
                         else title(E["warn"], "Không xoá được", texts.esc(param))),
                        menus.back_only("m|backup")),
            est=4.0)
    if what == "dbdel":
        return await _progress_op(
            update, True, f"{E['del']} <b>Đang xoá database</b> {texts.esc(param)}…",
            asyncio.to_thread(hostvn.delete_db, param),
            lambda ok: ((title(E["confirm"], "Đã xoá database",
                               f"<code>{progress.bar(100)}</code>\n{texts.esc(param)}") if ok
                         else title(E["warn"], "Không xoá được", texts.esc(param))),
                        menus.back_only("m|db")),
            est=5.0,
        )


# --------------------------------------------------------------------------- #
# Conversation flow (nhap lieu)
# --------------------------------------------------------------------------- #
async def start_flow(update, context, flow, back, emoji, heading, prompt):
    context.user_data["flow"] = flow
    q = update.callback_query
    await q.edit_message_text(
        title(emoji, heading, f"✍️ {prompt}\nNhập vào ô chat bên dưới, hoặc bấm ❌ Hủy."),
        parse_mode=HTML, reply_markup=menus.back_only(back))
    await context.bot.send_message(update.effective_chat.id, f"{emoji} {prompt}",
                                   parse_mode=HTML, reply_markup=menus.cancel_keyboard())


async def handle_flow(update, context, flow, text):
    chat = update.effective_chat.id

    if flow == "db_add":
        editor = await _make_editor(update, False)
        ok, err, info = await progress.run(
            editor, f"{E['db']} <b>Đang tạo database</b> {texts.esc(text)}…",
            asyncio.to_thread(hostvn.create_db, text), est=6.0,
            stages=[(50, f"{E['db']} <b>Tạo user &amp; cấp quyền</b>…")])
        if info:
            body = (f"DB   : {info['db']}\nUser : {info['user']}\n"
                    f"Pass : {info['pass']}\nHost : {info['host']}")
            await editor(title(E["confirm"], "Đã tạo database",
                               f"<code>{progress.bar(100)}</code>\n" + pre(body) +
                               "\n⚠️ <b>Lưu lại!</b>"))
            context.user_data.pop("flow", None)
            await update.message.reply_text(
                title(E["home"], "Menu chính", "Chọn chức năng từ <b>menu bên dưới</b>."),
                parse_mode=HTML, reply_markup=menus.build_keyboard(_features(chat)))
        else:
            await editor(f"{E['warn']} {err} Nhập lại hoặc bấm ❌ Hủy.")
        return

    if flow == "ssl_cfapi":
        bits = text.split()
        if len(bits) < 2:
            return await update.message.reply_text(
                f"{E['warn']} Cần đủ <b>token</b> và <b>email</b>. Nhập lại:", parse_mode=HTML)
        editor = await _make_editor(update, False)
        ok, msg = await progress.run(
            editor, "☁️ <b>Đang lưu CloudFlare DNS API</b>…",
            asyncio.to_thread(hostvn.ssl_cf_api_set, bits[0], bits[1]), est=10.0)
        await editor(title(E["confirm"] if ok else E["warn"],
                           "CloudFlare DNS API", texts.esc(msg) +
                           ("\n\n⚠️ <b>Nhớ xoá tin nhắn chứa token</b> ở trên." if ok else "")))
        context.user_data.pop("flow", None)
        await update.message.reply_text(
            title(E["home"], "Menu chính", "Chọn chức năng từ <b>menu bên dưới</b>."),
            parse_mode=HTML, reply_markup=menus.build_keyboard(_features(chat)))
        return

    # ----- Cac flow quan ly domain nang cao -----
    if flow in ("dom_rename", "dom_alias", "dom_redirect", "dom_protect"):
        dom = context.user_data.get("dom", "")
        if not dom:
            context.user_data.pop("flow", None)
            return await update.message.reply_text(f"{E['warn']} Mất ngữ cảnh domain, chọn lại.",
                                                   parse_mode=HTML)
        editor = await _make_editor(update, False)

        if flow == "dom_protect":
            bits = text.split()
            if len(bits) < 3:
                return await update.message.reply_text(
                    f"{E['warn']} Cần đủ 3 phần: <code>/đường_dẫn user mật_khẩu</code>. Nhập lại:",
                    parse_mode=HTML)
            path, usr, pwd = bits[0], bits[1], " ".join(bits[2:])
            work = asyncio.to_thread(hostvn.dom_protect_dir, dom, path, usr, pwd)
            titlemsg = f"🔐 <b>Đang bảo vệ thư mục</b> {texts.esc(path)}…"
        elif flow == "dom_rename":
            work = asyncio.to_thread(hostvn.dom_rename, dom, text)
            titlemsg = f"✏️ <b>Đang đổi tên miền</b> {texts.esc(dom)}…"
        elif flow == "dom_alias":
            work = asyncio.to_thread(hostvn.dom_alias_add, dom, text)
            titlemsg = f"🔗 <b>Đang thêm alias</b> {texts.esc(text)}…"
        else:
            work = asyncio.to_thread(hostvn.dom_redirect_add, dom, text)
            titlemsg = f"↪️ <b>Đang thêm redirect</b> {texts.esc(text)}…"

        ok, msg = await progress.run(editor, titlemsg, work, est=25.0,
                                     stages=[(60, "🔄 <b>Đang cập nhật cấu hình nginx</b>…")])
        await editor(title(E["confirm"] if ok else E["warn"],
                           "Hoàn tất" if ok else "Không thành công",
                           f"<code>{progress.bar(100)}</code>\n{texts.esc(msg)}" if ok
                           else texts.esc(msg)))
        context.user_data.pop("flow", None)
        context.user_data.pop("dom", None)
        await update.message.reply_text(
            title(E["home"], "Menu chính", "Chọn chức năng từ <b>menu bên dưới</b>."),
            parse_mode=HTML, reply_markup=menus.build_keyboard(_features(chat)))
        return

    if flow == "dom_add":
        d = text.strip().lower()
        if d.startswith("www."):
            d = d[4:]
        if not hostvn.DOMAIN_RE.match(d):
            return await update.message.reply_text(
                f"{E['warn']} Tên miền không hợp lệ, nhập lại (vd: shop.com):", parse_mode=HTML)
        if (Path(C.VHOST_DIR) / f"{d}.conf").exists():
            context.user_data.pop("flow", None)
            return await update.message.reply_text(
                f"{E['warn']} Domain <b>{texts.esc(d)}</b> đã tồn tại.",
                parse_mode=HTML, reply_markup=menus.build_keyboard(_features(chat)))
        context.user_data.pop("flow", None)
        await update.message.reply_text(
            title(E["domain"], d, "Chọn loại website:"),
            parse_mode=HTML, reply_markup=menus.new_domain_type_menu(d))
        # tra lai ban phim chinh
        await update.message.reply_text("👇", reply_markup=menus.build_keyboard(_features(chat)))
        return

    context.user_data.pop("flow", None)


CALLBACK_ROUTES = {
    "nav": cb_nav, "m": cb_open, "a": cb_action, "svc": cb_svc, "do": cb_do,
    "pick": cb_pick, "nd": cb_nd, "cf": cb_cf, "yes": cb_yes, "bk": cb_bk,
    "dm": cb_dm, "ssl": cb_ssl,
}
