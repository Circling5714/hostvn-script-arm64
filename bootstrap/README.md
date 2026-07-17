# HostVN ARM64 — Bootstrap từ đầu trên Android

`setup-android.ps1` tự động hóa toàn bộ chuỗi cài đặt **từ máy tính (Windows/PowerShell)**:

```
adb (USB hoặc TCP) → cài APK Linux Deploy → deploy Ubuntu 24.04 arm64
    → cấu hình SSH → tải & chạy hostvn-script-arm64 (install)
```

## Yêu cầu

- Điện thoại Android **đã root** (Magisk), bật **USB debugging** (Settings → Developer options).
- PC có **adb** (Android platform-tools) trong PATH — hoặc trỏ qua `-AdbPath`.
- Có `ssh`/`scp`/`ssh-keygen` (Windows 10+ có sẵn OpenSSH client).
- Internet trên cả PC lẫn điện thoại.

## Cách dùng

### Qua USB (khuyến nghị cho lần đầu)
```powershell
.\setup-android.ps1 -AdbMode usb
```

### Qua WiFi/TCP (đã bật `adb tcpip` từ trước)
```powershell
# Nếu chưa bật: cắm USB một lần rồi chạy  adb tcpip 5555
.\setup-android.ps1 -AdbMode tcp -DeviceAddr 192.168.1.50:5555
```

## Các pha (dừng sớm bằng `-Stop <pha>`)

| Pha | Việc làm |
|-----|----------|
| `adb`     | Kết nối adb (USB/TCP), kiểm tra quyền root + kiến trúc arm64 |
| `apk`     | Cài APK Linux Deploy, mở app để giải nén ENV |
| `deploy`  | Tải rootfs ubuntu-base, viết profile, `cli.sh deploy` (tạo image ext4 **trên `/data`**) |
| `ssh`     | Start container, cài SSH key root, mở port, khởi động sshd |
| `install` | Clone/đẩy repo, chạy `bash install` trong container |

Ví dụ chỉ tới bước deploy: `.\setup-android.ps1 -AdbMode usb -Stop deploy`

## ⚠️ Các bước phải chạm tay trên điện thoại

Script sẽ **tạm dừng và hướng dẫn** khi tới các bước này (không thể tự động vì cần UI/Magisk):

1. **Cấp quyền root cho adb/shell** — khi Magisk hiện popup.
2. **Cấp quyền root cho Linux Deploy** + vào app **Menu → Update** (cập nhật ENV) một lần.

Sau đó script tự động hoàn tất phần còn lại.

## ⚠️ Bắt buộc về vị trí image

Tham số `-ImagePath` mặc định `/data/local/ubuntu24.img` — image **PHẢI nằm trên `/data`** (block storage thật), **KHÔNG** đặt trên `/sdcard` (`/storage/emulated/0`, là FUSE). Xem mục "vold-reboot" trong `../README.md`: đặt sai chỗ sẽ làm thiết bị tự reboot khi I/O nặng.

## Tham số hữu ích

| Tham số | Mặc định | Ý nghĩa |
|---------|----------|---------|
| `-AdbMode` | `tcp` | `usb` hoặc `tcp` |
| `-DeviceAddr` | (trống) | `IP:port` khi dùng tcp |
| `-SshPort` | `2233` | Port sshd trong container |
| `-ImagePath` | `/data/local/ubuntu24.img` | Vị trí image (phải ở `/data`) |
| `-ImageSizeMB` | `12000` | Dung lượng image (MB) |
| `-RootfsUrl` | ubuntu-base 24.04 arm64 | Nguồn rootfs (cập nhật point-release nếu 404) |
| `-ApkUrl` / `-ApkLocal` | LD 2.6.0 | Nguồn APK Linux Deploy |
| `-RepoUrl` / `-RepoLocal` | repo GitHub | Nguồn code hostvn-script-arm64 |
| `-Stop` | `all` | Dừng sau pha chỉ định |

## Sau khi xong

SSH vào container và quản trị bằng menu:
```powershell
ssh -i ..\.ssh\id_ed25519 -p 2233 root@<IP-điện-thoại>
# trong container:
hostvn
```
