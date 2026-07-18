#!/bin/bash

######################################################################
#           Auto Install & Optimize LEMP Stack on Ubuntu             #
#                Author: Sanvv - HOSTVN Technical                    #
#              Please do not remove copyright. Thank!                #
######################################################################
#
# Telegram bot dieu khien server bang MENU NUT BAM (inline keyboard),
# MIRROR toan bo cay menu 'hostvn' de dung ngay tren Telegram (khong can SSH).
# Cau hinh: /var/hostvn/.telegram_bot.conf (BOT_TOKEN, ALLOWED_CHAT_IDS, BOT_MODE)
# Che do: notify (chi xem) | menu (nut dieu khien) | shell (them lenh shell).

export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
CONF="/var/hostvn/.telegram_bot.conf"
[ -f "${CONF}" ] || { echo "Thieu ${CONF}"; exit 1; }
# shellcheck disable=SC1090
source "${CONF}"
[ -f /var/hostvn/menu/helpers/environment ] && source /var/hostvn/menu/helpers/environment 2>/dev/null

API="https://api.telegram.org/bot${BOT_TOKEN}"
OFFSET_FILE="/var/hostvn/.telegram_bot.offset"
STATE_DIR="/var/hostvn/.tgbot"
mkdir -p "${STATE_DIR}"
FILE_INFO="/var/hostvn/.hostvn.conf"
VHOST_DIR="/etc/nginx/conf.d"

# ============================================================ Telegram API
tg_send() {   # chat text [keyboard_json]
    local chat="$1" text="${2:0:3900}" kb="$3" args=(--data-urlencode "chat_id=${chat}" --data-urlencode "text=${text}" --data-urlencode "parse_mode=HTML")
    [ -n "${kb}" ] && args+=(--data-urlencode "reply_markup=${kb}")
    curl -s --max-time 20 -o /dev/null "${API}/sendMessage" "${args[@]}" >/dev/null 2>&1
}
tg_edit() {   # chat msg text kb
    curl -s --max-time 20 -o /dev/null "${API}/editMessageText" \
        --data-urlencode "chat_id=$1" --data-urlencode "message_id=$2" \
        --data-urlencode "text=${3:0:3900}" --data-urlencode "parse_mode=HTML" \
        --data-urlencode "reply_markup=$4" >/dev/null 2>&1
}
tg_answer() { curl -s --max-time 15 -o /dev/null "${API}/answerCallbackQuery" --data-urlencode "callback_query_id=$1" --data-urlencode "text=${2:-}" >/dev/null 2>&1; }
btn() { jq -cn --arg t "$1" --arg d "$2" '{text:$t,callback_data:$d}'; }
kb_rows() { printf '{"inline_keyboard":[%s]}' "$(IFS=,; echo "$*")"; }
esc() { local s="$1"; s="${s//&/&amp;}"; s="${s//</&lt;}"; s="${s//>/&gt;}"; printf '%s' "$s"; }

_is_allowed() { local id="$1" a; IFS=',' read -ra allow <<< "${ALLOWED_CHAT_IDS}"; for a in "${allow[@]}"; do [ "$(echo "$a" | tr -d ' ')" == "${id}" ] && return 0; done; return 1; }
_broadcast() { local a; IFS=',' read -ra allow <<< "${ALLOWED_CHAT_IDS}"; for a in "${allow[@]}"; do tg_send "$(echo "$a" | tr -d ' ')" "$1"; done; }
_can() { [ "${BOT_MODE}" != "notify" ]; }

# ============================================================ Data helpers
_php_ver() { ls /etc/php 2>/dev/null | grep -E '^[0-9]' | sort -V | tail -1; }
_ico() { [ "$(_svc is-active "$1" 2>/dev/null)" = "active" ] && echo "🟢" || echo "🔴"; }
_domains() { ls "${VHOST_DIR}"/*.conf 2>/dev/null | xargs -n1 basename 2>/dev/null | sed 's/\.conf$//' | grep -vE '^(default|web_apps)$'; }
_dbs() { mysql -N --socket=/run/mysqld/mysqld.sock -e 'show databases;' 2>/dev/null | grep -vE '^(information_schema|performance_schema|mysql|sys|phpmyadmin)$'; }
_docroot() { grep -hoE "root [^;]+" "${VHOST_DIR}/$1.conf" 2>/dev/null | head -1 | awk '{print $2}'; }
_run() { timeout 40 bash -c "$1" 2>&1; }

# ============================================================ Persistent Menu button
setup_menu_button() {
    # Nut lenh (goc trai input) + commands
    curl -s --max-time 15 -o /dev/null "${API}/setMyCommands" --data-urlencode 'commands=[{"command":"menu","description":"Mo menu HOSTVN"},{"command":"start","description":"Bat dau"}]' >/dev/null 2>&1
    curl -s --max-time 15 -o /dev/null "${API}/setChatMenuButton" --data-urlencode 'menu_button={"type":"commands"}' >/dev/null 2>&1
}
# Ban phim co dinh (luon hien nut Menu duoi khung chat)
persist_kb() { printf '{"keyboard":[[{"text":"📋 MENU HOSTVN"}]],"resize_keyboard":true,"is_persistent":true}'; }

# ============================================================ Man hinh (TEXT + KB)
# Moi ham dat 2 bien: TEXT, KB
BACK() { echo "[$(btn '⬅️ Quay lai' "$1"),$(btn '🏠 Menu chinh' main)]"; }

scr_main() {
    local pv; pv=$(_php_ver)
    TEXT="🖥️ <b>HOSTVN Control</b> — $(hostname)
Nginx $(_ico nginx) MariaDB $(_ico mariadb) PHP $(_ico "php${pv}-fpm") | Che do: <b>${BOT_MODE}</b>

Chon nhom chuc nang (giong menu <code>hostvn</code>):"
    KB=$(kb_rows \
      "[$(btn '🌐 Domain' m:domain),$(btn '🗄️ Database' m:db)]" \
      "[$(btn '📝 WordPress' m:wp),$(btn '🔒 SSL' m:ssl)]" \
      "[$(btn '⚡ Cache' m:cache),$(btn '💾 Backup' m:backup)]" \
      "[$(btn '🛡️ Firewall' m:fw),$(btn '🐘 PHP' m:php)]" \
      "[$(btn '🔧 Dich vu' m:svc),$(btn '🖥️ He thong' m:sys)]" \
      "[$(btn '⚙️ VPS' m:vps),$(btn '🛠️ Cong cu' m:tool)]" \
      "[$(btn '📊 Trang thai nhanh' a:status)]")
}

# ---- DOMAIN ----
scr_m_domain() {
    TEXT="🌐 <b>Quan ly Domain</b>"
    KB=$(kb_rows \
      "[$(btn '📋 Danh sach domain' a:dom_list)]" \
      "[$(btn '➕ Them domain' a:dom_add)]" \
      "[$(btn 'ℹ️ Thong tin 1 domain' a:dom_info)]" \
      "[$(btn '🗑️ Xoa domain' a:dom_del)]" \
      "[$(btn '🔀 Bat/Tat HTTP3' a:dom_http3)]" \
      "$(BACK main)")
}
# ---- DATABASE ----
scr_m_db() {
    TEXT="🗄️ <b>Quan ly Database</b>"
    KB=$(kb_rows \
      "[$(btn '📋 Danh sach DB' a:db_list)]" \
      "[$(btn '➕ Tao DB' a:db_add)]" \
      "[$(btn '🗑️ Xoa DB' a:db_del)]" \
      "[$(btn '🔑 Doi mat khau DB' a:db_pass)]" \
      "$(BACK main)")
}
# ---- WORDPRESS ----
scr_m_wp() {
    TEXT="📝 <b>Quan ly WordPress</b> (chon site o buoc sau)"
    KB=$(kb_rows \
      "[$(btn '📋 Site WordPress' a:wp_list)]" \
      "[$(btn '🛠️ Bao tri On/Off' a:wp_maint)]" \
      "[$(btn '🔑 Doi pass wp-admin' a:wp_pass)]" \
      "[$(btn '🧹 Xoa cache plugin' a:wp_cache)]" \
      "[$(btn '🔄 Cap nhat plugin/core' a:wp_update)]" \
      "$(BACK main)")
}
# ---- SSL ----
scr_m_ssl() {
    TEXT="🔒 <b>Quan ly SSL</b>"
    KB=$(kb_rows \
      "[$(btn '📅 Kiem tra han SSL' a:ssl_check)]" \
      "[$(btn '➕ Cap SSL Lets Encrypt' a:ssl_le)]" \
      "[$(btn '🔄 Gia han tat ca' a:ssl_renew)]" \
      "$(BACK main)")
}
# ---- CACHE ----
scr_m_cache() {
    TEXT="⚡ <b>Cache</b>
Redis $(_ico redis) | Memcached $(_ico memcached)"
    KB=$(kb_rows \
      "[$(btn '🧹 Xoa FastCGI cache' a:cache_clear)]" \
      "[$(btn '🔄 Restart Redis' do:redis:restart),$(btn '🔄 Restart Memcached' do:memcached:restart)]" \
      "[$(btn '🧹 Clear OPcache' a:opcache_clear)]" \
      "$(BACK main)")
}
# ---- BACKUP ----
scr_m_backup() {
    TEXT="💾 <b>Backup</b>
Remote da cau hinh (rclone):"
    local r rows=() n=0
    while read -r r; do [ -z "$r" ] && continue; r="${r%:}"; rows+=("[$(btn "☁️ ${r}" noop)]"); n=$((n+1)); done < <(rclone listremotes 2>/dev/null)
    [ $n -eq 0 ] && TEXT="${TEXT}
(chua co remote)"
    rows+=("[$(btn '💾 Backup 1 website' a:bk_run)]")
    rows+=("$(BACK main)")
    KB=$(kb_rows "${rows[@]}")
}
# ---- FIREWALL ----
scr_m_fw() {
    TEXT="🛡️ <b>Firewall / Fail2ban</b>
Fail2ban: $(_svc is-active fail2ban 2>/dev/null) $(_ico fail2ban)"
    KB=$(kb_rows \
      "[$(btn '📊 Thong ke Fail2ban' a:f2b_stats)]" \
      "[$(btn '🔄 Restart Fail2ban' do:fail2ban:restart)]" \
      "$(BACK main)")
}
# ---- PHP ----
scr_m_php() {
    local pv; pv=$(_php_ver)
    TEXT="🐘 <b>PHP</b> (hien tai: ${pv})
$(php${pv} -v 2>/dev/null | head -1)"
    KB=$(kb_rows \
      "[$(btn 'ℹ️ php.ini settings' a:php_info)]" \
      "[$(btn '🔄 Restart PHP-FPM' "do:php${pv}-fpm:restart")]" \
      "[$(btn '📊 Process manager' a:php_pm)]" \
      "$(BACK main)")
}
# ---- SERVICES ----
scr_m_svc() {
    TEXT="🔧 <b>Dich vu</b> — bam de dieu khien:"
    local s rows=(); local pv; pv=$(_php_ver)
    for s in nginx mariadb "php${pv}-fpm" redis-server memcached fail2ban cloudflared cron; do
        rows+=("[$(btn "$(_ico "$s") ${s}" "s:${s}")]")
    done
    rows+=("$(BACK main)")
    KB=$(kb_rows "${rows[@]}")
}
scr_svc_one() {
    local s="$1"
    TEXT="🔧 <b>${s}</b> — trang thai: <b>$(_svc is-active "$s" 2>/dev/null)</b> $(_ico "$s")"
    if _can; then
        KB=$(kb_rows \
          "[$(btn '🔄 Restart' "do:${s}:restart"),$(btn '▶️ Start' "do:${s}:start")]" \
          "[$(btn '⏹ Stop' "do:${s}:stop"),$(btn 'ℹ️ Lam moi' "s:${s}")]" \
          "$(BACK m:svc)")
    else
        KB=$(kb_rows "[$(btn 'ℹ️ Lam moi' "s:${s}")]" "$(BACK m:svc)")
    fi
}
# ---- SYSTEM ----
scr_m_sys() {
    local pv; pv=$(_php_ver)
    TEXT="🖥️ <b>Trang thai he thong</b>
<pre>
Nginx      : $(_svc is-active nginx)
MariaDB    : $(_svc is-active mariadb)
PHP-FPM    : $(_svc is-active "php${pv}-fpm")
Redis      : $(_svc is-active redis 2>/dev/null)
Memcached  : $(_svc is-active memcached 2>/dev/null)
Fail2ban   : $(_svc is-active fail2ban 2>/dev/null)
Cloudflared: $(_svc is-active cloudflared 2>/dev/null)
Disk : $(df -h / | awk 'NR==2{print $3" / "$2" ("$5")"}')
RAM  : $(free -h | awk '/Mem:/{print $3" / "$2}')
Load : $(cut -d' ' -f1-3 /proc/loadavg)
Uptime: $(uptime -p 2>/dev/null | sed 's/up //')
</pre>"
    KB=$(kb_rows "[$(btn '🔄 Lam moi' m:sys)]" "$(BACK main)")
}
# ---- VPS ----
scr_m_vps() {
    TEXT="⚙️ <b>Quan ly VPS</b>
<pre>Kernel: $(uname -r) ($(uname -m))
CPU: $(nproc) core | $(df -h / | awk 'NR==2{print "Disk "$5}') | $(free -h|awk '/Mem/{print "RAM "$3"/"$2}')</pre>"
    KB=$(kb_rows \
      "[$(btn 'ℹ️ Thong tin VPS' a:vps_info)]" \
      "[$(btn '💽 Dung luong thu muc' a:vps_disk)]" \
      "[$(btn '🔄 Restart tat ca dich vu' cf:restartall)]" \
      "[$(btn '♻️ Reboot server' cf:reboot)]" \
      "$(BACK main)")
}
# ---- TOOLS ----
scr_m_tool() {
    TEXT="🛠️ <b>Cong cu</b>"
    KB=$(kb_rows \
      "[$(btn '🔗 Link Admin phpMyAdmin/Opcache' a:links)]" \
      "[$(btn '📁 Tim file/thu muc lon' a:largefiles)]" \
      "[$(btn '🟩 Cai NodeJS' a:nodejs_note)]" \
      "$(BACK main)")
}

# ============================================================ Actions
scr_confirm() { TEXT="⚠️ <b>Xac nhan</b>: $2?"; KB=$(kb_rows "[$(btn '✅ Dong y' "yes:$1"),$(btn '❌ Huy' main)]"); }
note_ssh() { # action label ssh_path
    TEXT="🔧 <b>$1</b>
Chuc nang nay can nhap lieu nhieu buoc — dang duoc hoan thien tren bot.
Tam thoi chay qua SSH: <code>hostvn</code> → $2"
    KB=$(kb_rows "$(BACK main)")
}

# hien danh sach domain de chon (callback pick:<act>:<domain>)
pick_domain() { # act title
    local act="$1"; TEXT="$2"; local d rows=() n=0
    while read -r d; do [ -z "$d" ] && continue; rows+=("[$(btn "🌐 ${d}" "pick:${act}:${d}")]"); n=$((n+1)); [ $n -ge 20 ] && break; done < <(_domains)
    [ $n -eq 0 ] && TEXT="${TEXT}
(chua co domain)"
    rows+=("$(BACK main)"); KB=$(kb_rows "${rows[@]}")
}
pick_db() { local act="$1"; TEXT="$2"; local d rows=() n=0
    while read -r d; do [ -z "$d" ] && continue; rows+=("[$(btn "🗄️ ${d}" "pick:${act}:${d}")]"); n=$((n+1)); [ $n -ge 20 ] && break; done < <(_dbs)
    [ $n -eq 0 ] && TEXT="${TEXT}
(chua co DB)"; rows+=("$(BACK main)"); KB=$(kb_rows "${rows[@]}")
}

do_action() {  # chat mid act cbid  -> dat TEXT/KB (edit) hoac gui truc tiep
    local chat="$1" mid="$2" act="$3" cbid="$4"
    case "${act}" in
        status)
            local pv; pv=$(_php_ver)
            TEXT="📊 Nginx $(_ico nginx) | MariaDB $(_ico mariadb) | PHP $(_ico "php${pv}-fpm") | Redis $(_ico redis) | F2B $(_ico fail2ban) | CF $(_ico cloudflared)
Disk $(df -h /|awk 'NR==2{print $5}') | RAM $(free -h|awk '/Mem/{print $3"/"$2}')"
            KB=$(kb_rows "[$(btn '🔄' a:status)]" "$(BACK main)") ;;
        dom_list)
            local d out=""; while read -r d; do [ -n "$d" ] && out="${out}🌐 ${d} — $(curl -sS -H "Host: ${d}" -o /dev/null -w '%{http_code}' --max-time 5 http://127.0.0.1/ 2>/dev/null)
"; done < <(_domains)
            TEXT="🌐 <b>Domain</b>
${out:-（chua co）}"; KB=$(kb_rows "$(BACK m:domain)") ;;
        dom_info) pick_domain dominfo "ℹ️ Chon domain xem thong tin:" ;;
        dom_add)  _can || { note_ssh "Them domain" "Domain > Them domain"; }; _can && start_flow "${chat}" dom_add "Nhap <b>ten mien</b> muon them (vd: test.com):" ;;
        dom_del)  _can && pick_domain domdel "🗑️ Chon domain de XOA:" || note_ssh "Xoa domain" "Domain" ;;
        dom_http3) pick_domain http3 "🔀 Chon domain bat/tat HTTP3:" ;;
        db_list)
            local d out=""; while read -r d; do out="${out}🗄️ ${d}
"; done < <(_dbs)
            TEXT="🗄️ <b>Database</b>
${out:-（chua co）}"; KB=$(kb_rows "$(BACK m:db)") ;;
        db_add)   _can && start_flow "${chat}" db_add "Nhap <b>ten database</b> muon tao:" || note_ssh "Tao DB" "LEMP > Database" ;;
        db_del)   _can && pick_db dbdel "🗑️ Chon DB de XOA:" || note_ssh "Xoa DB" "LEMP > Database" ;;
        db_pass)  note_ssh "Doi mat khau DB" "LEMP > Database > Doi mat khau" ;;
        wp_list)  pick_domain wpinfo "📝 Chon site WordPress:" ;;
        wp_maint) pick_domain wpmaint "🛠️ Chon site bat/tat bao tri:" ;;
        wp_pass)  note_ssh "Doi pass wp-admin" "WordPress > Doi mat khau admin" ;;
        wp_cache) pick_domain wpcache "🧹 Chon site xoa cache:" ;;
        wp_update) note_ssh "Cap nhat WordPress" "WordPress > Update" ;;
        ssl_check)
            local out; out=$(for d in $(_domains); do e=$(echo | timeout 8 openssl s_client -connect "${d}:443" -servername "$d" 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null | cut -d= -f2); echo "🔒 ${d}: ${e:-?}"; done)
            TEXT="📅 <b>Han SSL</b>
${out:-（chua co）}"; KB=$(kb_rows "$(BACK m:ssl)") ;;
        ssl_le)   pick_domain sslle "➕ Chon domain cap Let's Encrypt:" ;;
        ssl_renew) note_ssh "Gia han SSL" "SSL > Gia han tat ca" ;;
        cache_clear) local o; o=$(_run 'rm -rf /var/cache/nginx/* 2>/dev/null; _svc reload nginx 2>/dev/null; echo done'); TEXT="🧹 Da xoa FastCGI cache + reload nginx."; KB=$(kb_rows "$(BACK m:cache)") ;;
        opcache_clear) local pv; pv=$(_php_ver); _svc restart "php${pv}-fpm" >/dev/null 2>&1; TEXT="🧹 Da clear OPcache - restart php-fpm."; KB=$(kb_rows "$(BACK m:cache)") ;;
        f2b_stats)
            local out; out=$(fail2ban-client status 2>/dev/null | tr -d '\t'); local jails; jails=$(fail2ban-client status 2>/dev/null | grep 'Jail list' | sed 's/.*://')
            local det=""; for j in $(echo "$jails" | tr ',' ' '); do det="${det}$(fail2ban-client status "$j" 2>/dev/null | grep -E 'Currently banned|Total banned' | tr -d '\t' | sed "s/^/${j}: /")
"; done
            TEXT="📊 <b>Fail2ban</b>
${out}
${det}"; KB=$(kb_rows "$(BACK m:fw)") ;;
        php_info) local pv; pv=$(_php_ver); TEXT="🐘 <b>PHP ${pv}</b>
<pre>$(php${pv} -i 2>/dev/null | grep -iE '^memory_limit|^upload_max|^post_max|^max_execution' | head -6)</pre>"; KB=$(kb_rows "$(BACK m:php)") ;;
        php_pm) local pv; pv=$(_php_ver); TEXT="📊 php-fpm pool:
<pre>$(grep -E '^pm|^pm\.' /etc/php/${pv}/fpm/pool.d/www.conf 2>/dev/null | head -8)</pre>"; KB=$(kb_rows "$(BACK m:php)") ;;
        vps_info) TEXT="⚙️ <b>VPS</b>
<pre>Host: $(hostname)
Kernel: $(uname -r) ($(uname -m))
CPU: $(nproc) core
Uptime: $(uptime -p|sed 's/up //')
$(df -h / | awk 'NR==2{print "Disk: "$3"/"$2" ("$5")"}')
$(free -h | awk '/Mem/{print "RAM: "$3"/"$2}')</pre>"; KB=$(kb_rows "$(BACK m:vps)") ;;
        vps_disk) TEXT="💽 <b>Dung luong /home</b>
<pre>$(du -sh /home/* 2>/dev/null | sort -rh | head -10)</pre>"; KB=$(kb_rows "$(BACK m:vps)") ;;
        bk_run)   note_ssh "Backup website" "Backup/Restore > Backup" ;;
        links)
            local ap ip; ap=$(grep -m1 '^admin_port=' "${FILE_INFO}"|cut -d= -f2)
            ip=$(hostname -I 2>/dev/null | awk '{print $1}'); [ -z "$ip" ] && ip=$(ip route get 1 2>/dev/null | awk '{print $7; exit}')
            TEXT="🔗 <b>Link Admin</b> (port ${ap})
phpMyAdmin: http://${ip}:${ap}/phpmyadmin
Opcache: http://${ip}:${ap}/opcache
Nginx status: http://${ip}:${ap}/status"; KB=$(kb_rows "$(BACK m:tool)") ;;
        largefiles) TEXT="📁 <b>File lon nhat /home</b>
<pre>$(find /home -type f -printf '%s %p\n' 2>/dev/null | sort -rn | head -8 | awk '{printf "%.0fMB %s\n",$1/1048576,$2}')</pre>"; KB=$(kb_rows "$(BACK m:tool)") ;;
        nodejs_note) note_ssh "Cai NodeJS" "Cong cu > Cai NodeJS" ;;
        *) scr_main ;;
    esac
    tg_answer "${cbid}"
    [ -n "${TEXT}" ] && tg_edit "${chat}" "${mid}" "${TEXT}" "${KB}"
}

# picked domain/db -> hanh dong cu the
do_pick() { # chat mid act target cbid
    local chat="$1" mid="$2" act="$3" tgt="$4" cbid="$5"
    case "${act}" in
        dominfo)
            local dr code up; dr=$(_docroot "$tgt"); code=$(curl -sS -H "Host: ${tgt}" -o /dev/null -w '%{http_code}' --max-time 8 http://127.0.0.1/ 2>/dev/null); up=$(du -sh "$(dirname "${dr}" 2>/dev/null)" 2>/dev/null|cut -f1)
            TEXT="🌐 <b>${tgt}</b>
<pre>HTTP: ${code}
Dung luong: ${up:-?}
Docroot: ${dr:-?}</pre>"; KB=$(kb_rows "$(BACK m:domain)") ;;
        wpinfo)
            local dr; dr=$(_docroot "$tgt"); local wp="khong"; [ -f "${dr}/wp-config.php" ] && wp="co"
            TEXT="📝 <b>${tgt}</b>
WordPress: ${wp}
$([ "$wp" = "co" ] && cd "$dr" && wp core version --allow-root 2>/dev/null | sed 's/^/WP version: /')"; KB=$(kb_rows "$(BACK m:wp)") ;;
        wpmaint) note_ssh "Bao tri ${tgt}" "WordPress > Maintenance" ;;
        wpcache) local dr; dr=$(_docroot "$tgt"); ( cd "$dr" && wp cache flush --allow-root 2>/dev/null ); TEXT="🧹 Da xoa cache WP cho ${tgt} neu co."; KB=$(kb_rows "$(BACK m:wp)") ;;
        http3) note_ssh "HTTP/3 ${tgt}" "Domain > HTTP/3" ;;
        sslle) note_ssh "Cap SSL ${tgt}" "SSL > Let's Encrypt" ;;
        domdel) scr_confirm "domdel:${tgt}" "XOA domain ${tgt} (mat toan bo du lieu)" ;;
        dbdel)  scr_confirm "dbdel:${tgt}" "XOA database ${tgt}" ;;
        *) scr_main ;;
    esac
    tg_answer "${cbid}"; [ -n "${TEXT}" ] && tg_edit "${chat}" "${mid}" "${TEXT}" "${KB}"
}

# ============================================================ Conversation (nhap lieu)
start_flow() { local chat="$1" flow="$2" prompt="$3"; echo "${flow}" > "${STATE_DIR}/${chat}.flow"; : > "${STATE_DIR}/${chat}.data"; tg_send "${chat}" "${prompt}
(go /huy de dung)"; }
clear_flow() { rm -f "${STATE_DIR}/$1.flow" "${STATE_DIR}/$1.data"; }
handle_flow() { # chat text
    local chat="$1" text="$2" flow; flow=$(cat "${STATE_DIR}/${chat}.flow" 2>/dev/null)
    [ -z "${flow}" ] && return 1
    [ "${text}" = "/huy" ] && { clear_flow "${chat}"; tg_send "${chat}" "Da huy."; return 0; }
    case "${flow}" in
        db_add)
            local db="${text//[^a-zA-Z0-9_]/}"
            [ -z "$db" ] && { tg_send "${chat}" "Ten DB khong hop le, nhap lai:"; return 0; }
            if mysql -N --socket=/run/mysqld/mysqld.sock -e "show databases like '${db}';" 2>/dev/null | grep -qx "${db}"; then
                tg_send "${chat}" "⚠️ Database <b>${db}</b> da ton tai. Chon ten khac:"; return 0; fi
            local pass; pass=$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c16)
            local err; err=$(mysql --socket=/run/mysqld/mysqld.sock -e "CREATE DATABASE IF NOT EXISTS \`${db}\`; CREATE USER IF NOT EXISTS '${db}'@'localhost' IDENTIFIED BY '${pass}'; GRANT ALL ON \`${db}\`.* TO '${db}'@'localhost'; FLUSH PRIVILEGES;" 2>&1 | grep -viE 'deprecated program name')
            if mysql -N --socket=/run/mysqld/mysqld.sock -e "show databases like '${db}';" 2>/dev/null | grep -qx "${db}"; then
                tg_send "${chat}" "✅ Da tao DB:
<pre>DB   : ${db}
User : ${db}
Pass : ${pass}
Host : localhost</pre>"
            else tg_send "${chat}" "❌ Loi tao DB: ${err:-khong ro}"; fi
            clear_flow "${chat}" ;;
        dom_add)
            local d="${text// /}"; d="${d,,}"; d="${d#www.}"
            echo "${d}" | grep -qE '^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$' || { tg_send "${chat}" "Ten mien khong hop le, nhap lai:"; return 0; }
            [ -f "${VHOST_DIR}/${d}.conf" ] && { tg_send "${chat}" "⚠️ Domain <b>${d}</b> da ton tai."; clear_flow "${chat}"; return 0; }
            clear_flow "${chat}"
            tg_send "${chat}" "🌐 Domain: <b>${d}</b>
Chon loai website:" "$(kb_rows "[$(btn '🐘 Website PHP/tinh' "nd:def:${d}"),$(btn '📝 WordPress' "nd:wp:${d}")]" "[$(btn '❌ Huy' main)]")" ;;
        *) clear_flow "${chat}" ;;
    esac
    return 0
}

# Chay 1 controller hostvn voi day du moi truong menu (TEMPLATE_DIR, lang, VHOST_DIR...)
# va vo hieu hoa cac ham menu_* de khong ket o menu cuoi. Nhan input canned qua stdin.
_run_ctl() { # seq_input  controller_path  [timeout]
    printf '%s\n' "$1" | timeout "${3:-180}" /bin/bash -c '
        export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin DEBIAN_FRONTEND=noninteractive TERM=dumb
        source /var/hostvn/.hostvn.conf 2>/dev/null
        source /var/hostvn/menu/route/parent 2>/dev/null
        source /var/hostvn/menu/helpers/variable_common 2>/dev/null
        source /var/hostvn/ipaddress 2>/dev/null
        source /var/hostvn/menu/lang/"${lang:-vi}" 2>/dev/null
        for _m in $(compgen -A function 2>/dev/null | grep -E "^menu_"); do eval "${_m}(){ :; }"; done
        source "$0"
    ' "$2" 2>&1
}

# Tao domain thuc su qua controller add_domain (chuoi tra loi canned)
_create_domain() { # chat type domain
    local chat="$1" typ="$2" d="$3" seq out
    [ -f "${VHOST_DIR}/${d}.conf" ] && { tg_send "${chat}" "⚠️ Domain ${d} da ton tai."; return; }
    if [ "${typ}" = "wp" ]; then
        tg_send "${chat}" "⏳ Dang tao <b>${d}</b> + cai WordPress (~30-60s)..."
        local wpuser wpmail wpsite
        wpuser="hvadmin$(tr -dc 0-9 </dev/urandom | head -c4)"       # >=5 ky tu, khac 'admin'
        wpmail=$(grep -m1 '^admin_email=' "$FILE_INFO" 2>/dev/null|cut -d= -f2); [ -z "$wpmail" ] && wpmail="admin@${d}"
        wpsite="${d}"
        # domain, source=WordPress, DB=y, random-name=y, random-pass=y, WPinstall=Yes, prefix=n, admin_user, email, site_name
        seq=$(printf '%s\n1\ny\ny\ny\n1\nn\n%s\n%s\n%s\n' "${d}" "${wpuser}" "${wpmail}" "${wpsite}")
    else
        tg_send "${chat}" "⏳ Dang tao website <b>${d}</b> (~15s)..."
        seq=$(printf '%s\n20\nn\n' "${d}")              # domain, source=Other(default), DB=n
    fi
    out=$(_run_ctl "${seq}" /var/hostvn/menu/controller/domain/add_domain 180)
    if [ -f "${VHOST_DIR}/${d}.conf" ]; then
        local uc="/var/hostvn/users/.${d}.conf" u p dbn dbu dbp sp msg
        u=$(grep -m1 '^username=' "$uc" 2>/dev/null|cut -d= -f2); p=$(grep -m1 '^user_pass=' "$uc" 2>/dev/null|cut -d= -f2)
        dbn=$(grep -m1 '^db_name=' "$uc" 2>/dev/null|cut -d= -f2); dbu=$(grep -m1 '^db_user=' "$uc" 2>/dev/null|cut -d= -f2); dbp=$(grep -m1 '^db_password=' "$uc" 2>/dev/null|cut -d= -f2)
        sp=$(grep -m1 '^ssh_port=' "$FILE_INFO" 2>/dev/null|cut -d= -f2)
        msg="Docroot   : $(_docroot "$d")
SFTP user : ${u}
SFTP pass : ${p}
SFTP port : ${sp}"
        [ -n "$dbn" ] && msg="${msg}
DB name   : ${dbn}
DB user   : ${dbu}
DB pass   : ${dbp}"
        if [ -d "$(_docroot "$d")/wp-admin" ]; then
            local wu wp2; wu=$(echo "$out"|grep -m1 'User dang nhap wp-admin'|sed 's/.*: *//'|tr -d '\r'); wp2=$(echo "$out"|grep -m1 'khau dang nhap wp-admin'|sed 's/.*: *//'|tr -d '\r')
            msg="${msg}
WP admin  : ${wu}
WP pass   : ${wp2}
WP login  : http://${d}/wp-admin"
        fi
        tg_send "${chat}" "✅ Da tao domain <b>${d}</b>
<pre>$(esc "${msg}")</pre>
⚠️ Luu lai thong tin nay!"
    else
        tg_send "${chat}" "⚠️ Chua tao duoc <b>${d}</b>. Chi tiet:
<pre>$(esc "$(echo "$out" | tail -4)")</pre>"
    fi
}

# ============================================================ Router
route() { # chat mid data cbid
    local chat="$1" mid="$2" data="$3" cbid="$4"; TEXT=""; KB=""
    case "${data}" in
        main) scr_main ;;
        m:domain) scr_m_domain ;; m:db) scr_m_db ;; m:wp) scr_m_wp ;; m:ssl) scr_m_ssl ;;
        m:cache) scr_m_cache ;; m:backup) scr_m_backup ;; m:fw) scr_m_fw ;; m:php) scr_m_php ;;
        m:svc) scr_m_svc ;; m:sys) scr_m_sys ;; m:vps) scr_m_vps ;; m:tool) scr_m_tool ;;
        noop) tg_answer "${cbid}" "—"; return ;;
        s:*) scr_svc_one "${data#s:}" ;;
        a:*) do_action "${chat}" "${mid}" "${data#a:}" "${cbid}"; return ;;
        pick:*) local rest="${data#pick:}"; do_pick "${chat}" "${mid}" "${rest%%:*}" "${rest#*:}" "${cbid}"; return ;;
        nd:*)
            _can || { tg_answer "${cbid}" "Che do notify"; return; }
            local nd="${data#nd:}"; tg_answer "${cbid}" "Dang xu ly..."
            tg_edit "${chat}" "${mid}" "🌐 Dang tao domain <b>${nd#*:}</b>..." "$(kb_rows "[$(btn '🏠 Menu' main)]")"
            _create_domain "${chat}" "${nd%%:*}" "${nd#*:}"; return ;;
        do:*)
            _can || { tg_answer "${cbid}" "Che do notify"; return; }
            local sd="${data#do:}"; local svc="${sd%:*}"; local act="${sd##*:}"
            tg_answer "${cbid}" "Dang ${act} ${svc}..."; _svc "${act}" "${svc}" >/dev/null 2>&1; sleep 1
            scr_svc_one "${svc}"; TEXT="✅ ${act} ${svc} → $(_svc is-active "${svc}")

${TEXT}" ;;
        cf:*)
            _can || { tg_answer "${cbid}" "Che do notify"; return; }
            case "${data#cf:}" in restartall) scr_confirm restartall "Restart tat ca dich vu";; reboot) scr_confirm reboot "Reboot server";; esac ;;
        yes:*)
            _can || { tg_answer "${cbid}" "Che do notify"; return; }
            local y="${data#yes:}"
            case "${y}" in
                restartall) tg_answer "${cbid}" "Restarting..."; local pv; pv=$(_php_ver); _svc restart mariadb>/dev/null 2>&1;sleep 1;_svc restart "php${pv}-fpm">/dev/null 2>&1;sleep 1;_svc restart nginx>/dev/null 2>&1; scr_main; TEXT="✅ Da restart cac dich vu.

${TEXT}" ;;
                reboot) tg_answer "${cbid}" "Rebooting..."; tg_edit "${chat}" "${mid}" "♻️ Server dang reboot..." "$(kb_rows "[$(btn '🏠 Menu' main)]")"; ( sleep 2; reboot ) & return ;;
                domdel:*) tg_answer "${cbid}" "..."; local dd="${y#domdel:}"; local o; o=$(timeout 60 bash -c "printf '%s\ny\n' '${dd}' | . /var/hostvn/menu/controller/domain/delete_domain" 2>&1|tail -2); [ ! -f "${VHOST_DIR}/${dd}.conf" ] && TEXT="✅ Da xoa domain ${dd}." || TEXT="⚠️ Kiem tra lai: ${o}"; KB=$(kb_rows "$(BACK m:domain)") ;;
                dbdel:*) tg_answer "${cbid}" "..."; local db="${y#dbdel:}"; mysql --socket=/run/mysqld/mysqld.sock -e "DROP DATABASE IF EXISTS \`${db}\`;" 2>/dev/null; TEXT="✅ Da xoa DB ${db}."; KB=$(kb_rows "$(BACK m:db)") ;;
            esac ;;
        *) scr_main ;;
    esac
    [ -n "${cbid}" ] && tg_answer "${cbid}"
    [ -n "${TEXT}" ] && tg_edit "${chat}" "${mid}" "${TEXT}" "${KB}"
}

# ============================================================ Text handler
handle_text() { local chat="$1" text="$2"
    handle_flow "${chat}" "${text}" && return
    case "${text}" in
        /start) setup_menu_button; scr_main; tg_send "${chat}" "Da bat menu. Bam nut <b>📋 MENU HOSTVN</b> o duoi khung chat de mo bat cu luc nao." "$(persist_kb)"; tg_send "${chat}" "${TEXT}" "${KB}" ;;
        /menu|"📋 MENU HOSTVN"|"📋 Menu") scr_main; tg_send "${chat}" "${TEXT}" "${KB}" ;;
        /huy) : ;;
        *) scr_main; tg_send "${chat}" "Dung menu:" "${KB}" ;;
    esac
}

# ============================================================ Monitor
_monitor_loop() { local disk=0; declare -A down; local pv
    while true; do pv=$(_php_ver)
        for s in nginx mariadb "php${pv}-fpm"; do [ -z "$s" ] && continue
            if [ "$(_svc is-active "$s" 2>/dev/null)" != active ]; then [ -z "${down[$s]}" ] && { _broadcast "⚠️ Dich vu <b>$s</b> KHONG chay tren $(hostname)."; down[$s]=1; }; else down[$s]=""; fi; done
        local u; u=$(df / | awk 'NR==2{print $5}'|tr -d '%'); if [ "$u" -ge 90 ]; then [ "$disk" -eq 0 ] && { _broadcast "⚠️ O dia ${u}% tren $(hostname)."; disk=1; }; else disk=0; fi
        sleep 300; done
}

# ============================================================ MAIN
# Cho phep source de test cac ham render ma khong chay vong lap: BOT_NORUN=1
[ "${BOT_NORUN}" = "1" ] && return 0 2>/dev/null
setup_menu_button
# Gui tin khoi dong + gan ban phim co dinh (nut 📋 MENU HOSTVN o duoi khung chat)
_boot_notify() { local a; IFS=',' read -ra allow <<< "${ALLOWED_CHAT_IDS}"; for a in "${allow[@]}"; do
    tg_send "$(echo "$a" | tr -d ' ')" "🤖 <b>HOSTVN Bot</b> san sang (che do: ${BOT_MODE}).
Bam nut <b>📋 MENU HOSTVN</b> o duoi khung chat, hoac go /menu." "$(persist_kb)"; done; }
_boot_notify
_monitor_loop &
trap 'kill %1 2>/dev/null' EXIT
offset=$(cat "${OFFSET_FILE}" 2>/dev/null || echo 0)
while true; do
    resp=$(curl -s --max-time 60 "${API}/getUpdates?timeout=50&offset=${offset}&allowed_updates=%5B%22message%22%2C%22callback_query%22%5D")
    [ -z "${resp}" ] && { sleep 3; continue; }
    echo "${resp}" | jq -e '.ok==true' >/dev/null 2>&1 || { sleep 3; continue; }
    count=$(echo "${resp}" | jq '.result|length'); [ "${count}" -eq 0 ] && continue
    for i in $(seq 0 $((count-1))); do
        uid=$(echo "${resp}" | jq -r ".result[$i].update_id"); offset=$((uid+1)); echo "${offset}" > "${OFFSET_FILE}"
        cbid=$(echo "${resp}" | jq -r ".result[$i].callback_query.id // empty")
        if [ -n "${cbid}" ]; then
            cc=$(echo "${resp}" | jq -r ".result[$i].callback_query.message.chat.id // empty")
            cm=$(echo "${resp}" | jq -r ".result[$i].callback_query.message.message_id // empty")
            cd=$(echo "${resp}" | jq -r ".result[$i].callback_query.data // empty")
            _is_allowed "${cc}" || { tg_answer "${cbid}" "Khong duoc phep"; continue; }
            route "${cc}" "${cm}" "${cd}" "${cbid}"; continue
        fi
        chat=$(echo "${resp}" | jq -r ".result[$i].message.chat.id // empty")
        text=$(echo "${resp}" | jq -r ".result[$i].message.text // empty")
        [ -z "${chat}" ] && continue; _is_allowed "${chat}" || continue
        [ -n "${text}" ] && handle_text "${chat}" "${text}"
    done
done
