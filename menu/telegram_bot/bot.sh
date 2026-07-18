#!/bin/bash

######################################################################
#           Auto Install & Optimize LEMP Stack on Ubuntu             #
#                Author: Sanvv - HOSTVN Technical                    #
#              Please do not remove copyright. Thank!                #
######################################################################
#
# Telegram bot dieu khien server bang MENU NUT BAM (inline keyboard).
# Cau hinh: /var/hostvn/.telegram_bot.conf
#   BOT_TOKEN          - token cua bot
#   ALLOWED_CHAT_IDS   - chat id duoc phep (cach nhau dau phay)
#   BOT_MODE           - notify | menu | shell
#
# BAO MAT: chi chat id trong ALLOWED_CHAT_IDS moi duoc xu ly. Che do notify =
# chi xem (khong dieu khien). Che do shell = cho chay lenh bat ky (rui ro cao).

CONF="/var/hostvn/.telegram_bot.conf"
[ -f "${CONF}" ] || { echo "Thieu ${CONF}"; exit 1; }
# shellcheck disable=SC1090
source "${CONF}"

# Lop truu tuong service (_svc) - chay ca khi khong co systemd
if [ -f /var/hostvn/menu/helpers/environment ]; then
    # shellcheck disable=SC1091
    source /var/hostvn/menu/helpers/environment
fi

API="https://api.telegram.org/bot${BOT_TOKEN}"
OFFSET_FILE="/var/hostvn/.telegram_bot.offset"
SHELL_WAIT_FILE="/var/hostvn/.telegram_bot.shellwait"
FILE_INFO="/var/hostvn/.hostvn.conf"

# ------------------------------------------------------------------ Telegram API
tg_send() {   # chat text [keyboard_json]
    local chat="$1" text="${2:0:3900}" kb="$3"
    if [ -n "${kb}" ]; then
        curl -s --max-time 20 -o /dev/null "${API}/sendMessage" \
            --data-urlencode "chat_id=${chat}" --data-urlencode "text=${text}" \
            --data-urlencode "parse_mode=HTML" --data-urlencode "reply_markup=${kb}" >/dev/null 2>&1
    else
        curl -s --max-time 20 -o /dev/null "${API}/sendMessage" \
            --data-urlencode "chat_id=${chat}" --data-urlencode "text=${text}" \
            --data-urlencode "parse_mode=HTML" >/dev/null 2>&1
    fi
}
tg_edit() {   # chat msg_id text keyboard_json
    curl -s --max-time 20 -o /dev/null "${API}/editMessageText" \
        --data-urlencode "chat_id=$1" --data-urlencode "message_id=$2" \
        --data-urlencode "text=${3:0:3900}" --data-urlencode "parse_mode=HTML" \
        --data-urlencode "reply_markup=$4" >/dev/null 2>&1
}
tg_answer() { # callback_id [text]
    curl -s --max-time 15 -o /dev/null "${API}/answerCallbackQuery" \
        --data-urlencode "callback_query_id=$1" --data-urlencode "text=${2:-}" >/dev/null 2>&1
}
btn() { jq -cn --arg t "$1" --arg d "$2" '{text:$t,callback_data:$d}'; }
kb_rows() { printf '{"inline_keyboard":[%s]}' "$(IFS=,; echo "$*")"; }

_is_allowed() {
    local id="$1" a
    IFS=',' read -ra allow <<< "${ALLOWED_CHAT_IDS}"
    for a in "${allow[@]}"; do [ "$(echo "$a" | tr -d ' ')" == "${id}" ] && return 0; done
    return 1
}
_broadcast() {
    local a; IFS=',' read -ra allow <<< "${ALLOWED_CHAT_IDS}"
    for a in "${allow[@]}"; do tg_send "$(echo "$a" | tr -d ' ')" "$1"; done
}
_can_control() { [ "${BOT_MODE}" != "notify" ]; }

# ------------------------------------------------------------------ Helpers
_php_ver() { ls /etc/php 2>/dev/null | grep -E '^[0-9]' | sort -V | tail -1; }
_svc_icon() { [ "$(_svc is-active "$1" 2>/dev/null)" = "active" ] && echo "🟢" || echo "🔴"; }
_domains() { ls /etc/nginx/conf.d/*.conf 2>/dev/null | xargs -n1 basename 2>/dev/null | sed 's/\.conf$//' | grep -vE '^(default|web_apps)$'; }

SERVICES_LIST() {
    local pv; pv=$(_php_ver)
    echo "nginx mariadb ${pv:+php${pv}-fpm} redis-server memcached fail2ban cloudflared cron"
}

# ------------------------------------------------------------------ Man hinh (text + keyboard)
scr_main() {
    local pv; pv=$(_php_ver)
    TEXT="🖥️ <b>HOSTVN Control</b> — $(hostname)
Che do: <b>${BOT_MODE}</b> | Uptime: $(uptime -p 2>/dev/null | sed 's/up //')

Nginx $(_svc_icon nginx)  MariaDB $(_svc_icon mariadb)  PHP $(_svc_icon "php${pv}-fpm")
Chon chuc nang:"
    local r1 r2 r3 r4
    r1="[$(btn '📊 Trang thai' sys),$(btn '🔧 Dich vu' svc)]"
    r2="[$(btn '🌐 Website' web),$(btn '💾 Backup' backup)]"
    r3="[$(btn '🖥️ He thong' vps),$(btn '🔄 Khoi dong lai' power)]"
    if [ "${BOT_MODE}" = "shell" ]; then
        r4="[$(btn '💻 Chay lenh shell' shell)]"
        KB=$(kb_rows "$r1" "$r2" "$r3" "$r4")
    else
        KB=$(kb_rows "$r1" "$r2" "$r3")
    fi
}
scr_sys() {
    local pv; pv=$(_php_ver)
    TEXT="📊 <b>Trang thai he thong</b>
<pre>
Nginx      : $(_svc is-active nginx)
MariaDB    : $(_svc is-active mariadb)
PHP-FPM    : $(_svc is-active "php${pv}-fpm")
Redis      : $(_svc is-active redis 2>/dev/null)
Memcached  : $(_svc is-active memcached 2>/dev/null)
Fail2ban   : $(_svc is-active fail2ban 2>/dev/null)
Cloudflared: $(_svc is-active cloudflared 2>/dev/null)
--- Tai nguyen ---
Disk : $(df -h / | awk 'NR==2{print $3" / "$2" ("$5")"}')
RAM  : $(free -h | awk '/Mem:/{print $3" / "$2}')
Load : $(cut -d' ' -f1-3 /proc/loadavg)
</pre>"
    KB=$(kb_rows "[$(btn '🔄 Lam moi' sys)]" "[$(btn '⬅️ Ve menu' main)]")
}
scr_vps() {
    TEXT="🖥️ <b>Thong tin he thong</b>
<pre>
Host   : $(hostname)
Kernel : $(uname -r)  ($(uname -m))
Uptime : $(uptime -p 2>/dev/null | sed 's/up //')
CPU    : $(nproc) core
--- Disk ---
$(df -h / | awk 'NR==2{print "Used "$3" / "$2"  ("$5")"}')
--- RAM ---
$(free -h | awk '/Mem:/{print "Used "$3" / "$2}')
--- Top RAM ---
$(ps -eo comm,%mem --sort=-%mem 2>/dev/null | head -4 | tail -3 | awk '{print $1"  "$2"%"}')
</pre>"
    KB=$(kb_rows "[$(btn '🔄 Lam moi' vps)]" "[$(btn '⬅️ Ve menu' main)]")
}
scr_svc() {
    TEXT="🔧 <b>Dich vu</b> — chon de xem/dieu khien:"
    local rows=() s icon nm
    for s in $(SERVICES_LIST); do
        [ -z "$s" ] && continue
        icon=$(_svc_icon "$s")
        rows+=("[$(btn "${icon} ${s}" "s:${s}")]")
    done
    rows+=("[$(btn '⬅️ Ve menu' main)]")
    KB=$(kb_rows "${rows[@]}")
}
scr_svc_one() {   # $1 = service
    local s="$1"
    TEXT="🔧 <b>${s}</b>
Trang thai: <b>$(_svc is-active "$s" 2>/dev/null)</b> $(_svc_icon "$s")

Chon thao tac:"
    if _can_control; then
        KB=$(kb_rows \
          "[$(btn '🔄 Restart' "do:${s}:restart"),$(btn '▶️ Start' "do:${s}:start")]" \
          "[$(btn '⏹ Stop' "do:${s}:stop"),$(btn 'ℹ️ Trang thai' "s:${s}")]" \
          "[$(btn '⬅️ Danh sach' svc),$(btn '🏠 Menu' main)]")
    else
        KB=$(kb_rows "[$(btn 'ℹ️ Lam moi' "s:${s}")]" "[$(btn '⬅️ Danh sach' svc),$(btn '🏠 Menu' main)]")
    fi
}
scr_web() {
    local ap; ap=$(grep -m1 '^admin_port=' "${FILE_INFO}" 2>/dev/null | cut -d= -f2)
    local ip; ip=$(grep -m1 '^ip_address=' "${FILE_INFO}" 2>/dev/null | cut -d= -f2)
    TEXT="🌐 <b>Website</b>
phpMyAdmin: http://${ip}:${ap}/phpmyadmin
Danh sach domain:"
    local rows=() d n=0
    while read -r d; do
        [ -z "$d" ] && continue
        rows+=("[$(btn "🌐 ${d}" "w:${d}")]")
        n=$((n+1)); [ $n -ge 20 ] && break
    done < <(_domains)
    [ $n -eq 0 ] && TEXT="${TEXT}
(Chua co website nao)"
    rows+=("[$(btn '⬅️ Ve menu' main)]")
    KB=$(kb_rows "${rows[@]}")
}
scr_web_one() {   # $1 = domain
    local d="$1" dr up code
    dr=$(grep -hoE "root [^;]+" /etc/nginx/conf.d/"${d}".conf 2>/dev/null | head -1 | awk '{print $2}')
    up=$(du -sh "$(dirname "${dr}" 2>/dev/null)" 2>/dev/null | cut -f1)
    code=$(curl -sS -H "Host: ${d}" -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1/ 2>/dev/null)
    TEXT="🌐 <b>${d}</b>
<pre>
HTTP local : ${code:-?}
Dung luong : ${up:-?}
Docroot    : ${dr:-?}
</pre>"
    KB=$(kb_rows "[$(btn '🔄 Lam moi' "w:${d}")]" "[$(btn '⬅️ Danh sach' web),$(btn '🏠 Menu' main)]")
}
scr_backup() {
    TEXT="💾 <b>Backup</b>
Cac remote da cau hinh (rclone):"
    local rows=() r n=0
    while read -r r; do
        [ -z "$r" ] && continue
        r="${r%:}"; rows+=("[$(btn "☁️ ${r}" "noop")]"); n=$((n+1))
    done < <(rclone listremotes 2>/dev/null)
    [ $n -eq 0 ] && TEXT="${TEXT}
(Chua co remote nao — tao trong menu hostvn > Backup)"
    TEXT="${TEXT}

Chay backup thu cong trong menu 'hostvn' de an toan."
    rows+=("[$(btn '⬅️ Ve menu' main)]")
    KB=$(kb_rows "${rows[@]}")
}
scr_power() {
    if _can_control; then
        TEXT="🔄 <b>Khoi dong lai</b>
Chon thao tac (can xac nhan):"
        KB=$(kb_rows \
          "[$(btn '🔄 Restart tat ca dich vu' "cf:restartall")]" \
          "[$(btn '♻️ Reboot server' "cf:reboot")]" \
          "[$(btn '⬅️ Ve menu' main)]")
    else
        TEXT="🔄 Che do <b>notify</b> khong cho phep dieu khien."
        KB=$(kb_rows "[$(btn '⬅️ Ve menu' main)]")
    fi
}
scr_confirm() {   # $1=action $2=label
    TEXT="⚠️ <b>Xac nhan</b>: ${2}?"
    KB=$(kb_rows "[$(btn '✅ Dong y' "yes:${1}"),$(btn '❌ Huy' main)]")
}

# ------------------------------------------------------------------ Thuc thi hanh dong
do_svc_action() {  # svc action -> tra ve text ket qua
    local s="$1" a="$2"
    _svc "$a" "$s" >/dev/null 2>&1
    sleep 1
    echo "✅ ${a} ${s} → trang thai: $(_svc is-active "$s" 2>/dev/null)"
}
do_restart_all() {
    local pv; pv=$(_php_ver)
    _svc restart mariadb >/dev/null 2>&1; sleep 1
    _svc restart "php${pv}-fpm" >/dev/null 2>&1; sleep 1
    _svc restart nginx >/dev/null 2>&1; sleep 1
    echo "✅ Da restart: MariaDB=$(_svc is-active mariadb) PHP=$(_svc is-active "php${pv}-fpm") Nginx=$(_svc is-active nginx)"
}

# ------------------------------------------------------------------ Router callback
route() {   # chat msg_id data cbid
    local chat="$1" mid="$2" data="$3" cbid="$4"
    local key="${data%%:*}" arg="${data#*:}"
    TEXT=""; KB=""
    case "${data}" in
        main)   scr_main ;;
        sys)    scr_sys ;;
        vps)    scr_vps ;;
        svc)    scr_svc ;;
        web)    scr_web ;;
        backup) scr_backup ;;
        power)  scr_power ;;
        noop)   tg_answer "${cbid}" "—"; return ;;
        shell)
            [ "${BOT_MODE}" = "shell" ] || { tg_answer "${cbid}" "Chi che do shell"; return; }
            : > "${SHELL_WAIT_FILE}"; echo "${chat}" > "${SHELL_WAIT_FILE}"
            tg_answer "${cbid}"; tg_send "${chat}" "💻 Gui lenh shell trong tin nhan tiep theo (timeout 30s moi lenh)."
            return ;;
        s:*)    scr_svc_one "${arg}" ;;
        w:*)    scr_web_one "${arg}" ;;
        do:*)
            _can_control || { tg_answer "${cbid}" "Che do notify"; return; }
            local sname="${data#do:}"; local svc="${sname%%:*}"; local act="${sname##*:}"
            tg_answer "${cbid}" "Dang ${act} ${svc}..."
            local res; res=$(do_svc_action "${svc}" "${act}")
            scr_svc_one "${svc}"; TEXT="${res}

${TEXT}"
            ;;
        cf:*)
            _can_control || { tg_answer "${cbid}" "Che do notify"; return; }
            case "${arg}" in
                restartall) scr_confirm "restartall" "Restart tat ca dich vu" ;;
                reboot)     scr_confirm "reboot" "Reboot server" ;;
            esac ;;
        yes:*)
            _can_control || { tg_answer "${cbid}" "Che do notify"; return; }
            case "${arg}" in
                restartall)
                    tg_answer "${cbid}" "Dang restart..."
                    local res; res=$(do_restart_all); scr_main; TEXT="${res}

${TEXT}" ;;
                reboot)
                    tg_answer "${cbid}" "Server reboot..."
                    tg_edit "${chat}" "${mid}" "♻️ Server dang khoi dong lai..." "$(kb_rows "[$(btn '🏠 Menu' main)]")"
                    ( sleep 2; reboot ) & return ;;
            esac ;;
        *) scr_main ;;
    esac
    [ -n "${cbid}" ] && tg_answer "${cbid}"
    [ -n "${TEXT}" ] && tg_edit "${chat}" "${mid}" "${TEXT}" "${KB}"
}

# ------------------------------------------------------------------ Xu ly tin nhan text
handle_text() {  # chat text
    local chat="$1" text="$2"
    # Dang cho lenh shell?
    if [ "${BOT_MODE}" = "shell" ] && [ -s "${SHELL_WAIT_FILE}" ] && [ "$(cat "${SHELL_WAIT_FILE}")" = "${chat}" ]; then
        rm -f "${SHELL_WAIT_FILE}"
        local out; out=$(timeout 30 bash -c "${text}" 2>&1)
        tg_send "${chat}" "$ ${text}
<pre>${out:-(khong co output)}</pre>"
        return
    fi
    case "${text}" in
        /start|/menu|/help) scr_main; tg_send "${chat}" "${TEXT}" "${KB}" ;;
        *) scr_main; tg_send "${chat}" "Dung menu nut bam ben duoi:" "${KB}" ;;
    esac
}

# ------------------------------------------------------------------ Monitor (canh bao)
_monitor_loop() {
    local disk_alerted=0; declare -A svc_down; local pv
    while true; do
        pv=$(_php_ver)
        for svc in nginx mariadb "php${pv}-fpm"; do
            [ -z "${svc}" ] && continue
            if [ "$(_svc is-active "${svc}" 2>/dev/null)" != "active" ]; then
                [ -z "${svc_down[$svc]}" ] && { _broadcast "⚠️ CANH BAO: dich vu <b>${svc}</b> KHONG hoat dong tren $(hostname)."; svc_down[$svc]=1; }
            else svc_down[$svc]=""; fi
        done
        local usage; usage=$(df / | awk 'NR==2{print $5}' | tr -d '%')
        if [ "${usage}" -ge 90 ]; then
            [ "${disk_alerted}" -eq 0 ] && { _broadcast "⚠️ CANH BAO: o dia da dung ${usage}% tren $(hostname)."; disk_alerted=1; }
        else disk_alerted=0; fi
        sleep 300
    done
}

# ============================== MAIN ==============================
rm -f "${SHELL_WAIT_FILE}"
scr_main
_broadcast "🤖 HOSTVN Bot da khoi dong (che do: ${BOT_MODE}). Go /menu."

_monitor_loop &
trap 'kill %1 2>/dev/null' EXIT

offset=$(cat "${OFFSET_FILE}" 2>/dev/null || echo 0)
while true; do
    resp=$(curl -s --max-time 60 "${API}/getUpdates?timeout=50&offset=${offset}&allowed_updates=%5B%22message%22%2C%22callback_query%22%5D")
    [ -z "${resp}" ] && { sleep 3; continue; }
    echo "${resp}" | jq -e '.ok == true' >/dev/null 2>&1 || { sleep 3; continue; }
    count=$(echo "${resp}" | jq '.result | length')
    [ "${count}" -eq 0 ] && continue

    for i in $(seq 0 $((count - 1))); do
        update_id=$(echo "${resp}" | jq -r ".result[$i].update_id")
        offset=$((update_id + 1)); echo "${offset}" > "${OFFSET_FILE}"

        # callback_query (nut bam)?
        cb_id=$(echo "${resp}" | jq -r ".result[$i].callback_query.id // empty")
        if [ -n "${cb_id}" ]; then
            cb_chat=$(echo "${resp}" | jq -r ".result[$i].callback_query.message.chat.id // empty")
            cb_mid=$(echo "${resp}" | jq -r ".result[$i].callback_query.message.message_id // empty")
            cb_data=$(echo "${resp}" | jq -r ".result[$i].callback_query.data // empty")
            _is_allowed "${cb_chat}" || { tg_answer "${cb_id}" "Khong duoc phep"; continue; }
            route "${cb_chat}" "${cb_mid}" "${cb_data}" "${cb_id}"
            continue
        fi

        # message text
        chat_id=$(echo "${resp}" | jq -r ".result[$i].message.chat.id // empty")
        text=$(echo "${resp}" | jq -r ".result[$i].message.text // empty")
        [ -z "${chat_id}" ] && continue
        _is_allowed "${chat_id}" || continue
        [ -n "${text}" ] && handle_text "${chat_id}" "${text}"
    done
done
