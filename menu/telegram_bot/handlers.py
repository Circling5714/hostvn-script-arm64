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


async def open_group(update: Update, context: ContextTypes.DEFAULT_TYPE, feature: str, edit: bool) -> None:
    builder = GROUP_SCREENS.get(feature)
    if builder is None:
        return await show_menu(update, context)
    text, kb = await asyncio.to_thread(builder)
    await _show(update, text, kb, edit)


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
    if not has_feature(update.effective_chat.id, C.F_SVC):
        return await update.callback_query.edit_message_text(texts.DENY, parse_mode=HTML)
    state = await asyncio.to_thread(hostvn.svc_status, service)
    ic = E["on"] if state == "active" else E["off"]
    kb = menus.service_one_menu(service, can_write(update.effective_chat.id))
    await update.callback_query.edit_message_text(
        title(E["svc"], service, f"Trạng thái: <b>{texts.esc(state)}</b> {ic}"),
        parse_mode=HTML, reply_markup=kb,
    )


async def cb_do(update, context, service, params):
    q = update.callback_query
    act = params[0] if params else ""
    if not can_write(update.effective_chat.id):
        return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                         reply_markup=menus.back_only("m|svc"))
    await q.edit_message_text(title(E["refresh"], f"{act} {service}", "Đang xử lý..."),
                              parse_mode=HTML)
    await asyncio.to_thread(hostvn.svc, act, service)
    state = await asyncio.to_thread(hostvn.svc_status, service)
    ic = E["on"] if state == "active" else E["off"]
    await q.edit_message_text(
        title(E["confirm"], f"{act} {service}", f"Trạng thái: <b>{texts.esc(state)}</b> {ic}"),
        parse_mode=HTML, reply_markup=menus.service_one_menu(service, True),
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
    if action == "dom_info":
        doms = await asyncio.to_thread(hostvn.list_domains)
        return await q.edit_message_text(
            title(E["domain"], "Chọn domain", "Xem thông tin:"),
            parse_mode=HTML, reply_markup=menus.picker_menu("dominfo", doms, E["domain"], "m|domain"))
    if action == "dom_del":
        doms = await asyncio.to_thread(hostvn.list_domains)
        return await q.edit_message_text(
            title(E["del"], "Xoá domain", "Chọn domain để XOÁ:"),
            parse_mode=HTML, reply_markup=menus.picker_menu("domdel", doms, E["domain"], "m|domain"))
    if action == "db_del":
        dbs = await asyncio.to_thread(hostvn.list_dbs)
        return await q.edit_message_text(
            title(E["del"], "Xoá database", "Chọn DB để XOÁ:"),
            parse_mode=HTML, reply_markup=menus.picker_menu("dbdel", dbs, E["db"], "m|db"))
    if action == "wp_cache":
        doms = await asyncio.to_thread(hostvn.list_domains)
        return await q.edit_message_text(
            title(E["wp"], "Xoá cache WP", "Chọn site:"),
            parse_mode=HTML, reply_markup=menus.picker_menu("wpcache", doms, E["wp"], "m|wp"))

    # ----- Cac hanh dong tra ket qua -----
    text, back = await asyncio.to_thread(_run_action, action, chat)
    await q.edit_message_text(text, parse_mode=HTML, reply_markup=menus.back_only(back))


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
        text = await asyncio.to_thread(_domain_info, target)
        return await q.edit_message_text(text, parse_mode=HTML, reply_markup=menus.back_only("m|domain"))
    if action == "wpcache":
        if not can_write(chat):
            return await q.edit_message_text(texts.NOTIFY_ONLY, parse_mode=HTML,
                                             reply_markup=menus.back_only("m|wp"))
        await asyncio.to_thread(_wp_cache_flush, target)
        return await q.edit_message_text(
            title(E["wp"], target, "Đã xoá cache WordPress (nếu có)."),
            parse_mode=HTML, reply_markup=menus.back_only("m|wp"))
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
    eta = "~30-60s" if typ == "wp" else "~15s"
    kind = "WordPress" if typ == "wp" else "website PHP"
    await q.edit_message_text(
        title(E["domain"], f"Đang tạo {kind}", f"<b>{texts.esc(domain)}</b> ({eta})..."),
        parse_mode=HTML)
    ok, info, err = await asyncio.to_thread(hostvn.create_domain, typ, domain)
    if ok:
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
        text = title(E["confirm"], f"Đã tạo {domain}", pre("\n".join(lines)) +
                     "\n⚠️ <b>Lưu lại thông tin này!</b>")
    else:
        text = title(E["warn"], f"Chưa tạo được {domain}", pre(err))
    await q.edit_message_text(text, parse_mode=HTML, reply_markup=menus.back_only("m|domain"))


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
        await q.edit_message_text(title(E["refresh"], "Đang restart...", ""), parse_mode=HTML)
        msg = await asyncio.to_thread(hostvn.restart_stack)
        return await q.edit_message_text(title(E["confirm"], "Xong", msg),
                                         parse_mode=HTML, reply_markup=menus.back_only("m|vps"))
    if what == "reboot":
        await q.edit_message_text(title(E["reboot"], "Server đang reboot...", ""), parse_mode=HTML)
        await asyncio.to_thread(hostvn.reboot)
        return
    if what == "domdel":
        await q.edit_message_text(title(E["refresh"], f"Đang xoá {param}...", ""), parse_mode=HTML)
        ok = await asyncio.to_thread(hostvn.delete_domain, param)
        text = (title(E["confirm"], "Đã xoá domain", texts.esc(param)) if ok
                else title(E["warn"], "Không xoá được", texts.esc(param)))
        return await q.edit_message_text(text, parse_mode=HTML, reply_markup=menus.back_only("m|domain"))
    if what == "dbdel":
        ok = await asyncio.to_thread(hostvn.delete_db, param)
        text = (title(E["confirm"], "Đã xoá database", texts.esc(param)) if ok
                else title(E["warn"], "Không xoá được", texts.esc(param)))
        return await q.edit_message_text(text, parse_mode=HTML, reply_markup=menus.back_only("m|db"))


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
        ok, err, info = await asyncio.to_thread(hostvn.create_db, text)
        if info:
            body = (f"DB   : {info['db']}\nUser : {info['user']}\n"
                    f"Pass : {info['pass']}\nHost : {info['host']}")
            await update.message.reply_text(
                title(E["confirm"], "Đã tạo database", pre(body) + "\n⚠️ <b>Lưu lại!</b>"),
                parse_mode=HTML, reply_markup=menus.build_keyboard(_features(chat)))
        else:
            return await update.message.reply_text(f"{E['warn']} {err} Nhập lại hoặc ❌ Hủy.",
                                                   parse_mode=HTML)
        context.user_data.pop("flow", None)
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
