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

WRITE_ACTIONS = {"dom_add", "db_add", "cache_clear", "opcache_clear", "php_restart"}


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
        return title(E["ssl"], "Hạn SSL", pre(hostvn.ssl_expiry())), "m|ssl"
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
        out = hostvn.sh("rclone listremotes 2>/dev/null", 10) or "(chưa cấu hình remote)"
        return title(E["backup"], "Remote rclone", pre(out)), "m|backup"
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
    "pick": cb_pick, "nd": cb_nd, "cf": cb_cf, "yes": cb_yes,
}
