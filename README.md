<p align="center"><strong>HostVN Script ARM64 — Chạy LEMP Stack trên thiết bị Android đã root</strong></p>
<p align="center"><strong>##############################################</strong></p>

Bản **ARM64 / Android** của HostVN Script: cài đặt và tối ưu **LEMP Stack (Nginx – MariaDB – PHP-FPM)** để chạy website **ngay trên điện thoại/thiết bị Android đã root** (qua chroot Linux Deploy), bên cạnh bản VPS gốc.

> Đây là một **sản phẩm riêng**, fork từ [hostvn-script](https://github.com/Circling5714/hostvn-script) (bản rebuild cho Ubuntu mới). Điểm khác cốt lõi: chạy được ở môi trường **không có systemd** và xử lý các đặc thù của storage Android để không làm treo/reboot máy.

<b>Please do not copy or distribute this for commercial purposes. Thank you.</b>

---

## 1. Khác biệt so với bản VPS

- ✅ **Lớp trừu tượng service (`_svc`)** trong `menu/helpers/environment`: tự phát hiện môi trường (`systemd` hay `manual`, Android hay không, container hay không, firewall có sẵn không) và quản lý nginx / php-fpm / mariadb / redis / memcached / fail2ban / cron / cloudflared / supervisor **trực tiếp** khi không có systemd (chroot / Linux Deploy / Android).
- ✅ **Khử fsync bằng `eatmydata`** cho MariaDB trên Android — xem [mục 3](#3-vấn-đề-vold-reboot-và-cách-khắc-phục-quan-trọng-nhất). Đây là thay đổi quan trọng nhất để bản ARM64 hoạt động ổn định.
- ✅ **Giới hạn `make -j` = 2** khi build nginx trên Android (tránh OOM/quá nhiệt).
- ✅ Cấu hình InnoDB an toàn cho loop/dm-crypt: `innodb_flush_method=fsync` (không dùng O_DIRECT), `innodb_doublewrite=0`, `innodb_use_native_aio=0`, `innodb_flush_neighbors=0`, io_capacity thấp.
- ✅ Bỏ phụ thuộc `sudo` (chroot chạy sẵn bằng root); MariaDB manual dùng đúng socket `/run/mysqld/mysqld.sock`.
- ✅ Gate **ImunifyAV** chỉ cho x86_64 (không có bản ARM64) → trên ARM dùng **ClamAV**.
- ✅ Bỏ qua tạo swap / kernel tweak / mở port firewall khi môi trường không hỗ trợ.

Toàn bộ tính năng bản VPS được giữ: Nginx 1.30 (HTTP/2+3, brotli, vts), MariaDB 11.8, PHP đa phiên bản (8.4/8.3/8.2/7.4), phpMyAdmin, FastCGI cache, Fail2ban (+ đồng bộ Cloudflare WAF), SSL acme.sh, WP-CLI, backup Rclone/S3, Telegram bot… — chạy qua menu `hostvn`.

## 2. Yêu cầu môi trường

- Thiết bị Android **đã root** (Magisk), kiến trúc **aarch64/arm64**, RAM ≥ 3GB (khuyến nghị ≥ 4GB để build nginx).
- **Linux Deploy** (hoặc chroot tương đương) với **Ubuntu 22.04 / 24.04** arm64.
- ⚠️ **Image container BẮT BUỘC đặt trên `/data` (block storage thật), KHÔNG đặt trên `/storage/emulated/0` (FUSE/sdcardfs).** Xem mục 3.
- Cho phép exec từ `/data` dưới SELinux (thường có sẵn với Magisk).

## 3. Vấn đề vold-reboot và cách khắc phục (QUAN TRỌNG NHẤT)

**Triệu chứng:** khi cài (đặc biệt lúc MariaDB khởi tạo / import DB nặng) thiết bị **tự khởi động lại**. Kiểm tra: `getprop ro.boot.bootreason` → `reboot,vold-failed`.

**Nguyên nhân gốc:** storage của container là file loop ext4, nằm sau lớp **mã hóa dm-crypt/FBE** do tiến trình **`vold`** (Volume Daemon) của Android quản lý. Bão ghi liên tục của InnoDB (redo-log fsync, checkpoint flush, doublewrite) **làm nghẽn đường I/O mã hóa → watchdog của vold hết giờ → vold chết → Android reboot**. Đây **không** phải do đếm số fsync (thử 800×`dd conv=fsync` + 200×`sync` vẫn sống), mà do **độ trễ ghi tích lũy** dưới tải DB liên tục. Đặt container lên `/data` giúp giảm nhưng **chưa đủ** — vì `/data` cũng bị vold/dm-crypt quản lý.

**Cách khắc phục (đã tích hợp sẵn, đã kiểm chứng):** dùng **`eatmydata`** — thư viện `LD_PRELOAD` biến `fsync/fdatasync/sync/msync` thành no-op:
- Giai đoạn cài: chạy toàn bộ `hostvn.run` dưới `eatmydata`.
- Lúc chạy: `_svc` khởi động `mysqld_safe`/`mariadb-install-db` dưới `LD_PRELOAD=libeatmydata`.

> **Kiểm chứng:** ghi liên tục **3.200.000 dòng InnoDB** (nhân bản + UPDATE toàn bảng, 64s ghi liên tục) dưới eatmydata → **không reboot**, uptime liên tục.

**Đánh đổi (cần biết):** eatmydata làm mất bảo đảm bền vững (durability) khi mất điện đột ngột — có cửa sổ mất dữ liệu vài giây và rủi ro hỏng InnoDB nếu cúp điện đúng lúc ghi. Với một node web chạy trên điện thoại (edge/thử nghiệm), đây là đánh đổi chấp nhận được để máy không reboot. Khuyến nghị: cắm nguồn ổn định và **backup định kỳ** (menu backup Rclone/S3 có sẵn).

## 4. Cài đặt

Bên trong chroot Ubuntu (đã có mạng, đã `apt update`):

```sh
apt install git -y
git clone https://github.com/Circling5714/hostvn-script-arm64.git
cd hostvn-script-arm64 && bash install
```

Script tự phát hiện Android/không-systemd và áp dụng toàn bộ điều chỉnh ở trên. Sau khi cài xong, quản trị bằng lệnh `hostvn`.

**Lưu ý cho dev:** sau khi sửa bất kỳ file nào trong `menu/`, phải đóng gói lại: `tar -czf menu.tar.gz menu` (LF line-ending).

## 5. Nguồn phần mềm

Giống bản VPS (Nginx, MariaDB, PHP ondrej, phpMyAdmin, PECL, Rclone, WP-CLI, ClamAV…) — xem `PROJECT.md`.

## 6. Credits

- Gốc: Sanvv (HOSTVN), f97
- Rebuild Ubuntu mới + bản ARM64/Android: QMV (2026)
