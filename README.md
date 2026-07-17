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

**Cách khắc phục (đã tích hợp sẵn, đã kiểm chứng)** — cần **ba lớp bổ trợ nhau**, vì mỗi lớp chặn một loại I/O đồng bộ khác nhau:

1. **`eatmydata`** — `LD_PRELOAD` biến `fsync/fdatasync/sync/msync` của **ứng dụng** thành no-op. Áp cho toàn bộ `hostvn.run` lúc cài và cho `mysqld_safe`/`mariadb-install-db` lúc chạy. → xử lý bão fsync của InnoDB.
2. **`nobarrier` + `vm.dirty_bytes` thấp** (hàm `_hostvn_harden_android_io` trong `menu/helpers/environment`, chạy mỗi lần source):
   - `mount -o remount,nobarrier /` — chặn **barrier/FLUSH của chính ext4 journal** (do *kernel* phát khi tạo/xoá nhiều file — composer, `wp package install`, giải nén). eatmydata **không** chặn được lớp này.
   - `vm.dirty_bytes=8MB`, `dirty_background_bytes=4MB` — ép writeback **nhỏ giọt** thay vì để kernel dồn ~1GB (mặc định `dirty_ratio=20%`) rồi flush một cục làm nghẽn storage.
3. **Cấu hình InnoDB an toàn cho Android** — `innodb_flush_method=fsync` (không O_DIRECT), `innodb_doublewrite=0`, `innodb_flush_neighbors=0`, `innodb_flush_log_at_trx_commit=0`, io_capacity thấp.
4. **Chống OOM (hết RAM cũng gây `vold-failed`)** — Android đã chiếm ~3/5.4GB nên không thể cấp phát theo tổng RAM vật lý. Trên Android: cap `innodb_buffer_pool_size=128M`, `max_connections=50`, php-fpm `pm.max_children≤8`, và **bỏ qua `wp package install`** (Composer giải dependency + `memory_limit=-1` là thủ phạm làm bung RAM → `lmkd` giết `vold` → reboot). Hai package wp-cli đó không bắt buộc, cài thủ công sau nếu cần.

> **Kiểm chứng:** (a) ghi **3.200.000 dòng InnoDB** liên tục dưới eatmydata; (b) **3 vòng tạo+xoá 30.000 file + `dd` 2GB** dưới nobarrier+vm.dirty — **đều không reboot** (cùng workload này reboot ngay khi chưa có fix); (c) reboot cuối cùng đúng tại bước Composer → xác nhận là OOM. Chẩn đoán: `bootreason` luôn là `reboot,vold-failed`, máy **mát** (không phải nhiệt).

**Đánh đổi (cần biết):** khử fsync + nobarrier làm **giảm bảo đảm bền vững (durability)** khi mất điện đột ngột — có cửa sổ mất dữ liệu vài giây và rủi ro hỏng InnoDB/FS nếu cúp điện đúng lúc ghi. Với một node web chạy trên điện thoại (edge/thử nghiệm), đây là đánh đổi chấp nhận được để máy không reboot. Khuyến nghị: **cắm nguồn ổn định** (hoặc pin còn tốt) và **backup định kỳ** (menu backup Rclone/S3 có sẵn).

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
