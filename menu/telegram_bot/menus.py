"""Khai bao menu bang DU LIEU + ham dung ban phim (hostvn bot).

- MENU CHINH (tang 1): ReplyKeyboardMarkup co dinh, khai bao bang MAIN_MENU (data),
  cap 2 nut/hang, loc theo quyen bang build_keyboard(features).
- SUB-MENU (tang 2): InlineKeyboardMarkup, callback_data = "<mien>|<hanh_dong>|<tham_so>".
- cancel_keyboard(): ban phim rieng chi co "❌ Hủy".
"""
from __future__ import annotations

from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

import config as C
from permissions import can_see

# --------------------------------------------------------------------------- #
# MENU CHINH - khai bao bang DU LIEU (feature_key, "emoji nhan"), cap 2 nut/hang
# --------------------------------------------------------------------------- #
MAIN_MENU: list[list[tuple[str, str]]] = [
    [(C.F_DOMAIN, f"{C.E['domain']} Domain"),   (C.F_DB,   f"{C.E['db']} Database")],
    [(C.F_WP,     f"{C.E['wp']} WordPress"),    (C.F_SSL,  f"{C.E['ssl']} SSL")],
    [(C.F_CACHE,  f"{C.E['cache']} Cache"),     (C.F_BACKUP, f"{C.E['backup']} Backup")],
    [(C.F_FW,     f"{C.E['fw']} Firewall"),     (C.F_PHP,  f"{C.E['php']} PHP")],
    [(C.F_SVC,    f"{C.E['svc']} Dịch vụ"),     (C.F_SYS,  f"{C.E['sys']} Hệ thống")],
    [(C.F_VPS,    f"{C.E['vps']} VPS"),         (C.F_TOOL, f"{C.E['tool']} Công cụ")],
]

LABEL_TO_FEATURE: dict[str, str] = {label: key for row in MAIN_MENU for (key, label) in row}


def build_keyboard(features: set[str] | None) -> ReplyKeyboardMarkup:
    rows: list[list[KeyboardButton]] = []
    for row in MAIN_MENU:
        visible = [KeyboardButton(label) for key, label in row if can_see(key, features)]
        if visible:
            rows.append(visible)
    if not rows:
        rows = [[KeyboardButton(C.LBL_MENU)]]
    return ReplyKeyboardMarkup(rows, resize_keyboard=True)


def cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup([[KeyboardButton(C.LBL_CANCEL)]],
                               resize_keyboard=True, one_time_keyboard=True)


# --------------------------------------------------------------------------- #
# Tien ich dung ban phim inline
# --------------------------------------------------------------------------- #
def back_row(target: str = C.CB_HOME) -> list[InlineKeyboardButton]:
    return [InlineKeyboardButton(C.LBL_BACK, callback_data=target)]


def rows_menu(rows: list[list[tuple[str, str]]], back: str = C.CB_HOME) -> InlineKeyboardMarkup:
    """rows: list cac hang, moi hang list (label, callback_data). Tu them nut Quay lai."""
    kb = [[InlineKeyboardButton(lbl, callback_data=cb) for (lbl, cb) in row] for row in rows]
    kb.append(back_row(back))
    return InlineKeyboardMarkup(kb)


def back_only(target: str = C.CB_HOME) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([back_row(target)])


def confirm_menu(what: str, param: str = "") -> InlineKeyboardMarkup:
    data = f"yes|{what}" + (f"|{param}" if param else "")
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(f"{C.E['confirm']} Đồng ý", callback_data=data),
        InlineKeyboardButton(C.LBL_CANCEL, callback_data=C.CB_HOME),
    ]])


# --------------------------------------------------------------------------- #
# SUB-MENU tinh (callback "<mien>|<hanh_dong>")
# --------------------------------------------------------------------------- #
def domain_menu() -> InlineKeyboardMarkup:
    return rows_menu([
        [(f"{C.E['list']} Danh sách domain", "a|dom_list")],
        [(f"{C.E['add']} Thêm domain", "a|dom_add")],
        [(f"{C.E['info']} Thông tin domain", "a|dom_info")],
        [(f"{C.E['del']} Xoá domain", "a|dom_del")],
    ])


def db_menu() -> InlineKeyboardMarkup:
    return rows_menu([
        [(f"{C.E['list']} Danh sách DB", "a|db_list")],
        [(f"{C.E['add']} Tạo database", "a|db_add")],
        [(f"{C.E['del']} Xoá database", "a|db_del")],
    ])


def wp_menu() -> InlineKeyboardMarkup:
    return rows_menu([
        [(f"{C.E['list']} Site WordPress", "a|wp_list")],
        [(f"{C.E['cache']} Xoá cache WP", "a|wp_cache")],
    ])


def ssl_menu() -> InlineKeyboardMarkup:
    return rows_menu([
        [(f"{C.E['month']} Kiểm tra hạn SSL", "a|ssl_check")],
    ])


def cache_menu() -> InlineKeyboardMarkup:
    return rows_menu([
        [(f"{C.E['cache']} Xoá FastCGI cache", "a|cache_clear")],
        [(f"{C.E['cache']} Clear OPcache", "a|opcache_clear")],
        [(f"{C.E['refresh']} Restart Redis", "do|redis|restart"),
         (f"{C.E['refresh']} Restart Memcached", "do|memcached|restart")],
    ])


def backup_menu() -> InlineKeyboardMarkup:
    return rows_menu([[(f"{C.E['info']} Remote rclone", "a|bk_list")]])


def fw_menu() -> InlineKeyboardMarkup:
    return rows_menu([
        [(f"{C.E['status']} Thống kê Fail2ban", "a|f2b_stats")],
        [(f"{C.E['refresh']} Restart Fail2ban", "do|fail2ban|restart")],
    ])


def php_menu() -> InlineKeyboardMarkup:
    return rows_menu([
        [(f"{C.E['info']} php.ini settings", "a|php_info")],
        [(f"{C.E['refresh']} Restart PHP-FPM", "a|php_restart")],
    ])


def sys_menu() -> InlineKeyboardMarkup:
    return rows_menu([[(f"{C.E['refresh']} Làm mới", "m|sys")]])


def vps_menu() -> InlineKeyboardMarkup:
    return rows_menu([
        [(f"{C.E['info']} Thông tin VPS", "a|vps_info")],
        [(f"{C.E['sys']} Dung lượng thư mục", "a|vps_disk")],
        [(f"{C.E['refresh']} Restart tất cả dịch vụ", "cf|restartall")],
        [(f"{C.E['reboot']} Reboot server", "cf|reboot")],
    ])


def tool_menu() -> InlineKeyboardMarkup:
    return rows_menu([
        [(f"🔗 Link Admin", "a|links")],
        [(f"{C.E['sys']} File lớn trong /home", "a|largefiles")],
    ])


# --------------------------------------------------------------------------- #
# SUB-MENU dong (nhan du lieu tu handler)
# --------------------------------------------------------------------------- #
def services_menu(items: list[tuple[str, str]]) -> InlineKeyboardMarkup:
    """items: list (label, service). Moi service 1 nut svc|<service>."""
    rows = [[(lbl, f"svc|{svc}")] for lbl, svc in items]
    return rows_menu(rows)


def service_one_menu(service: str, can_write: bool) -> InlineKeyboardMarkup:
    if can_write:
        rows = [
            [(f"{C.E['refresh']} Restart", f"do|{service}|restart"),
             (f"{C.E['start']} Start", f"do|{service}|start")],
            [(f"{C.E['stop']} Stop", f"do|{service}|stop"),
             (f"{C.E['info']} Làm mới", f"svc|{service}")],
        ]
    else:
        rows = [[(f"{C.E['info']} Làm mới", f"svc|{service}")]]
    return rows_menu(rows, back="m|svc")


def picker_menu(action: str, items: list[str], emoji: str, back: str = C.CB_HOME) -> InlineKeyboardMarkup:
    """Danh sach chon (domain/db...). callback pick|<action>|<item>."""
    rows = [[(f"{emoji} {it}", f"pick|{action}|{it}")] for it in items[:25]]
    return rows_menu(rows, back=back)


def new_domain_type_menu(domain: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(f"{C.E['php']} Website PHP", callback_data=f"nd|def|{domain}"),
         InlineKeyboardButton(f"{C.E['wp']} WordPress", callback_data=f"nd|wp|{domain}")],
        [InlineKeyboardButton(C.LBL_CANCEL, callback_data="m|domain")],
    ])
