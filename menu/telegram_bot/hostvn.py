"""Lop thao tac he thong hostvn (dong bo, goi qua asyncio.to_thread o handler).

Bao subprocess quanh cac lenh he thong + tai su dung _svc (menu/helpers/environment)
va cac controller hostvn (add_domain...) qua run_ctl.
"""
from __future__ import annotations

import os
import re
import secrets
import shlex
import string
import subprocess
import tempfile
from pathlib import Path

import config as C

DOMAIN_RE = re.compile(r"^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
_SKIP_DB = {"information_schema", "performance_schema", "mysql", "sys", "phpmyadmin"}


def _env() -> dict[str, str]:
    return {**os.environ, "PATH": C.PATH_ENV, "DEBIAN_FRONTEND": "noninteractive", "TERM": "dumb"}


def sh(script: str, timeout: int = 40, source_env: bool = False, merge: bool = False) -> str:
    """Chay 'bash -c script'. source_env: nap menu/helpers/environment (co _svc)."""
    prefix = f"source {C.ENVIRONMENT} 2>/dev/null; " if source_env else ""
    try:
        p = subprocess.run(
            ["bash", "-c", prefix + script],
            capture_output=True, text=True, timeout=timeout, env=_env(),
        )
        out = p.stdout + (p.stderr if merge else "")
        return out.strip()
    except subprocess.TimeoutExpired:
        return "⏱️ Quá thời gian thực thi."
    except Exception as e:  # noqa: BLE001
        return f"Lỗi: {e}"


def genpw(n: int = 16) -> str:
    return "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(n))


# --------------------------------------------------------------------------- #
# Dich vu (_svc)
# --------------------------------------------------------------------------- #
def svc(action: str, service: str, timeout: int = 40) -> str:
    return sh(f"_svc {shlex.quote(action)} {shlex.quote(service)}", timeout, source_env=True, merge=True)


def svc_status(service: str) -> str:
    return sh(f"_svc is-active {shlex.quote(service)}", 15, source_env=True) or "unknown"


def icon(service: str) -> str:
    return C.E["on"] if svc_status(service) == "active" else C.E["off"]


def services_status(names: list[str]) -> dict[str, str]:
    """Trang thai nhieu dich vu trong 1 lan goi bash (nhanh hon goi tung cai)."""
    script = "; ".join(f'printf "%s:%s\\n" {shlex.quote(n)} "$(_svc is-active {shlex.quote(n)} 2>/dev/null)"'
                       for n in names)
    out = sh(script, 25, source_env=True)
    result: dict[str, str] = {}
    for line in out.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            result[k.strip()] = v.strip()
    return result


def php_version() -> str:
    out = sh("ls /etc/php 2>/dev/null", 10)
    vers = sorted((x for x in out.split() if x[:1].isdigit()),
                  key=lambda s: [int(p) for p in s.split(".") if p.isdigit()] or [0])
    return vers[-1] if vers else "8.4"


# --------------------------------------------------------------------------- #
# Domain / Database
# --------------------------------------------------------------------------- #
def list_domains() -> list[str]:
    out = sh(f"ls {C.VHOST_DIR} 2>/dev/null", 10)
    doms = [f[:-5] for f in out.split() if f.endswith(".conf")]
    return sorted(d for d in doms if d not in ("default", "web_apps"))


def docroot(domain: str) -> str:
    conf = Path(C.VHOST_DIR) / f"{domain}.conf"
    if not conf.exists():
        return ""
    m = re.search(r"root\s+([^;]+);", conf.read_text(errors="replace"))
    return m.group(1).strip() if m else ""


def http_code(domain: str) -> str:
    return sh(f"curl -sS -H 'Host: {shlex.quote(domain)}' -o /dev/null -w '%{{http_code}}' "
              f"--max-time 6 http://127.0.0.1/", 10) or "?"


def mysql_e(query: str, timeout: int = 15, numeric: bool = True) -> str:
    """Query don gian (khong chua dau nháy kép/backtick) qua mysql -e (chi stdout)."""
    flag = "-N " if numeric else ""
    return sh(f'mysql {flag}--socket={C.MYSQL_SOCK} -e "{query}"', timeout)


def _mysql_file(sql: str, timeout: int = 25) -> str:
    """Chay SQL phuc tap (co backtick) qua file tam de tranh quoting."""
    fd, path = tempfile.mkstemp(suffix=".sql", dir="/tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(sql)
        return sh(f"mysql --socket={C.MYSQL_SOCK} < {path}", timeout, merge=True)
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


def list_dbs() -> list[str]:
    out = mysql_e("show databases;")
    return [x for x in out.splitlines() if x.strip() and x.strip() not in _SKIP_DB]


def db_exists(name: str) -> bool:
    return mysql_e(f"show databases like '{name}';").strip() == name


def create_db(name: str) -> tuple[bool, str, dict | None]:
    db = re.sub(r"[^a-zA-Z0-9_]", "", name)
    if not db:
        return False, "Tên database không hợp lệ (chỉ chữ/số/gạch dưới).", None
    if db_exists(db):
        return False, f"Database <b>{db}</b> đã tồn tại.", None
    pw = genpw()
    _mysql_file(
        f"CREATE DATABASE IF NOT EXISTS `{db}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
        f"CREATE USER IF NOT EXISTS '{db}'@'localhost' IDENTIFIED BY '{pw}';"
        f"GRANT ALL ON `{db}`.* TO '{db}'@'localhost';FLUSH PRIVILEGES;"
    )
    if db_exists(db):
        return True, "", {"db": db, "user": db, "pass": pw, "host": "localhost"}
    return False, "Lỗi tạo database.", None


def delete_db(name: str) -> bool:
    _mysql_file(f"DROP DATABASE IF EXISTS `{name}`;DROP USER IF EXISTS '{name}'@'localhost';FLUSH PRIVILEGES;")
    return not db_exists(name)


# --------------------------------------------------------------------------- #
# Chay controller hostvn voi day du moi truong (nhu menu chinh)
# --------------------------------------------------------------------------- #
def run_ctl(seq: str, controller: str, timeout: int = 180) -> str:
    script = (
        'source /var/hostvn/.hostvn.conf 2>/dev/null;'
        'source /var/hostvn/menu/route/parent 2>/dev/null;'
        'source /var/hostvn/menu/helpers/variable_common 2>/dev/null;'
        'source /var/hostvn/ipaddress 2>/dev/null;'
        'source /var/hostvn/menu/lang/"${lang:-vi}" 2>/dev/null;'
        'for _m in $(compgen -A function 2>/dev/null | grep -E "^menu_"); do eval "${_m}(){ :; }"; done;'
        f'source {shlex.quote(controller)}'
    )
    try:
        p = subprocess.run(["bash", "-c", script], input=seq + "\n",
                           capture_output=True, text=True, timeout=timeout, env=_env())
        return p.stdout + p.stderr
    except subprocess.TimeoutExpired:
        return "⏱️ Quá thời gian tạo."


def read_user_conf(domain: str) -> dict[str, str]:
    conf = Path(C.USERS_DIR) / f".{domain}.conf"
    data: dict[str, str] = {}
    if conf.exists():
        for line in conf.read_text(errors="replace").splitlines():
            if "=" in line and not line.startswith("["):
                k, v = line.split("=", 1)
                data[k.strip()] = v.strip()
    return data


def _domain_user(domain: str) -> str:
    u = read_user_conf(domain).get("username", "")
    if u:
        return u
    out = sh(f"find /home -maxdepth 2 -type d -name {shlex.quote(domain)} 2>/dev/null | head -1", 10)
    parts = out.strip().split("/")
    return parts[2] if len(parts) > 2 else ""


def create_domain(typ: str, domain: str) -> tuple[bool, dict, str]:
    """typ = 'def' (PHP) hoac 'wp' (WordPress). Tra (ok, info_dict, raw_output)."""
    d = domain.strip().lower()
    if d.startswith("www."):
        d = d[4:]
    if (Path(C.VHOST_DIR) / f"{d}.conf").exists():
        return False, {}, "Domain đã tồn tại."
    if typ == "wp":
        wpuser = "hvadmin" + "".join(secrets.choice("0123456789") for _ in range(4))
        wpmail = ""
        fi = Path(C.FILE_INFO)
        if fi.exists():
            m = re.search(r"^admin_email=(.*)$", fi.read_text(errors="replace"), re.M)
            wpmail = m.group(1).strip() if m else ""
        wpmail = wpmail or f"admin@{d}"
        seq = f"{d}\n1\ny\ny\ny\n1\nn\n{wpuser}\n{wpmail}\n{d}"
    else:
        seq = f"{d}\n20\nn"
    out = run_ctl(seq, "/var/hostvn/menu/controller/domain/add_domain", 200)
    if not (Path(C.VHOST_DIR) / f"{d}.conf").exists():
        tail = "\n".join(out.strip().splitlines()[-4:])
        return False, {}, tail
    uc = read_user_conf(d)
    info = {
        "domain": d,
        "docroot": docroot(d),
        "sftp_user": uc.get("username", ""),
        "sftp_pass": uc.get("user_pass", ""),
        "db_name": uc.get("db_name", ""),
        "db_user": uc.get("db_user", ""),
        "db_pass": uc.get("db_password", ""),
    }
    dr = info["docroot"]
    if dr and (Path(dr) / "wp-admin").is_dir():
        mu = re.search(r"User dang nhap wp-admin\s*:\s*(.+)", out)
        mp = re.search(r"khau dang nhap wp-admin\s*:\s*(.+)", out)
        info["wp_user"] = (mu.group(1).strip() if mu else "")
        info["wp_pass"] = (mp.group(1).strip() if mp else "")
    return True, info, ""


def delete_domain(domain: str) -> bool:
    d = domain.strip().lower()
    if not (Path(C.VHOST_DIR) / f"{d}.conf").exists():
        return False
    info = read_user_conf(d)
    user = _domain_user(d)
    dbn, dbu = info.get("db_name", ""), info.get("db_user", "")
    qd = shlex.quote(d)
    # An toan: chi userdel/rm /home khi user KHONG rong.
    script = (
        f"rm -f /etc/nginx/conf.d/{qd}.conf;"
        f"rm -rf /etc/nginx/php/{qd};"
        f"find /etc/php -name {qd}.conf -delete 2>/dev/null;"
        f"rm -f {shlex.quote(str(Path(C.USERS_DIR) / ('.' + d + '.conf')))};"
    )
    if user:
        qu = shlex.quote(user)
        script += f"userdel -f -r {qu} 2>/dev/null; rm -rf /home/{qu};"
    script += "nginx -t >/dev/null 2>&1 && _svc reload nginx >/dev/null 2>&1"
    sh(script, 60, source_env=True, merge=True)
    if dbn:
        _mysql_file(f"DROP DATABASE IF EXISTS `{dbn}`;DROP USER IF EXISTS '{dbu}'@'localhost';FLUSH PRIVILEGES;")
    return not (Path(C.VHOST_DIR) / f"{d}.conf").exists()


# --------------------------------------------------------------------------- #
# Cac khoi thong tin (read-only)
# --------------------------------------------------------------------------- #
def status() -> dict[str, str]:
    pv = php_version()
    keys = {
        "nginx": "nginx", "mariadb": "mariadb", f"php{pv}-fpm": f"php{pv}-fpm",
        "redis": "redis", "memcached": "memcached", "fail2ban": "fail2ban",
        "cloudflared": "cloudflared",
    }
    st = {name: svc_status(svcname) for name, svcname in keys.items()}
    st["disk"] = sh("df -h / | awk 'NR==2{print $3\" / \"$2\" (\"$5\")\"}'", 10)
    st["ram"] = sh("free -h | awk '/Mem:/{print $3\" / \"$2}'", 10)
    st["load"] = sh("cut -d' ' -f1-3 /proc/loadavg", 5)
    st["uptime"] = sh("uptime -p 2>/dev/null | sed 's/up //'", 5)
    st["php_ver"] = pv
    return st


def ssl_expiry() -> str:
    lines = []
    for d in list_domains():
        e = sh(f"echo | timeout 8 openssl s_client -connect {shlex.quote(d)}:443 "
               f"-servername {shlex.quote(d)} 2>/dev/null | openssl x509 -noout -enddate 2>/dev/null "
               f"| cut -d= -f2", 12)
        lines.append(f"{C.E['ssl']} {d}: {e or '?'}")
    return "\n".join(lines) or "(chưa có domain)"


def fail2ban_stats() -> str:
    base = sh("fail2ban-client status 2>/dev/null | tr -d '\t'", 15)
    jails = sh("fail2ban-client status 2>/dev/null | grep 'Jail list' | sed 's/.*://'", 10)
    det = []
    for j in (x.strip() for x in jails.split(",") if x.strip()):
        d = sh(f"fail2ban-client status {shlex.quote(j)} 2>/dev/null | grep -E "
               f"'Currently banned|Total banned' | tr -d '\t'", 10)
        if d:
            det.append(f"[{j}]\n{d}")
    return (base + "\n" + "\n".join(det)).strip() or "(fail2ban chưa chạy)"


def php_info() -> str:
    pv = php_version()
    return sh(f"php{pv} -i 2>/dev/null | grep -iE "
              f"'^memory_limit|^upload_max|^post_max|^max_execution' | head -6", 15) or "(không đọc được)"


def vps_info() -> str:
    return sh("printf 'Host: %s\\nKernel: %s (%s)\\nCPU: %s core\\nUptime: %s\\n' "
              "\"$(hostname)\" \"$(uname -r)\" \"$(uname -m)\" \"$(nproc)\" \"$(uptime -p|sed 's/up //')\"; "
              "df -h / | awk 'NR==2{print \"Disk: \"$3\"/\"$2\" (\"$5\")\"}'; "
              "free -h | awk '/Mem/{print \"RAM: \"$3\"/\"$2}'", 15)


def vps_disk() -> str:
    return sh("du -sh /home/* 2>/dev/null | sort -rh | head -10", 20) or "(trống)"


def largefiles() -> str:
    return sh("find /home -type f -printf '%s %p\\n' 2>/dev/null | sort -rn | head -8 "
              "| awk '{printf \"%.0fMB %s\\n\",$1/1048576,$2}'", 20) or "(trống)"


def admin_links() -> str:
    port = sh(f"grep -m1 '^admin_port=' {C.FILE_INFO} 2>/dev/null | cut -d= -f2", 8)
    ip = sh("hostname -I 2>/dev/null | awk '{print $1}'", 8) or "127.0.0.1"
    return (f"phpMyAdmin: http://{ip}:{port}/phpmyadmin\n"
            f"OPcache   : http://{ip}:{port}/opcache\n"
            f"Nginx st  : http://{ip}:{port}/status")


def clear_fastcgi() -> str:
    sh("rm -rf /var/cache/nginx/* 2>/dev/null; _svc reload nginx 2>/dev/null; echo ok", 20, source_env=True)
    return "Đã xoá FastCGI cache + reload nginx."


def clear_opcache() -> str:
    pv = php_version()
    svc("restart", f"php{pv}-fpm")
    return "Đã clear OPcache (restart php-fpm)."


def restart_stack() -> str:
    pv = php_version()
    for s in ("mariadb", f"php{pv}-fpm", "nginx"):
        svc("restart", s)
    return "Đã restart MariaDB → PHP-FPM → Nginx."


def reboot() -> None:
    subprocess.Popen(["bash", "-c", "sleep 2; reboot"], env=_env())
