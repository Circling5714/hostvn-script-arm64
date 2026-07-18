# HostVN ARM64 — Bootstrap từ đầu trên Android

`setup-android.ps1` tự động hóa toàn bộ chuỗi cài đặt **từ máy tính (Windows/PowerShell)**:

```
adb (USB/TCP, tự tải nếu thiếu) → cài APK Linux Deploy → deploy Ubuntu 24.04/26.04 arm64
    → cấu hình SSH → tải & chạy hostvn-script-arm64 (install)
```

## Binary lấy từ đâu (không cần tự tìm nguồn ngoài)

Mọi thứ mặc định lấy từ **GitHub Release của chính dự án** (`assets-v1`) — không phải nguồn bên thứ ba:
- **adb (platform-tools Windows)** — script **tự tải** nếu máy chưa có adb (`platform-tools-adb-windows.zip`).
- **APK Linux Deploy 2.6.0** (`linuxdeploy-2.6.0.apk`).
- **rootfs Ubuntu** `ubuntu-base-24.04-arm64.tar.gz` và `ubuntu-base-26.04-arm64.tar.gz`.

Muốn **chạy offline** (không tải gì): tải sẵn các file rồi trỏ `-AdbPath`, `-ApkLocal`, `-RootfsLocal`.

## Yêu cầu

- Điện thoại Android **đã root** (Magisk), bật **USB debugging** (Settings → Developer options).
- Có `ssh`/`scp`/`ssh-keygen` (Windows 10+ có sẵn OpenSSH client).
- Internet trên PC + điện thoại (trừ khi dùng file `-*Local` offline).
- **Không cần cài sẵn adb** — script tự lo. (Chế độ **USB** vẫn cần driver USB OEM của hãng máy; chế độ **WiFi/TCP** thì chỉ cần adb.exe.)

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

### Chọn Ubuntu 26.04 (experimental)
```powershell
.\setup-android.ps1 -AdbMode usb -UbuntuVersion 26.04
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
| `-AdbPath` | `adb` | Đường dẫn adb; nếu không có, script tự tải từ Release |
| `-UbuntuVersion` | `24.04` | `24.04` (ổn định) hoặc `26.04` (experimental) |
| `-SshPort` | `2233` | Port sshd trong container |
| `-ImagePath` | `/data/local/ubuntu24.img` | Vị trí image (phải ở `/data`) |
| `-ImageSizeMB` | `12000` | Dung lượng image (MB) |
| `-RootfsUrl` / `-RootfsLocal` | Release dự án | Nguồn rootfs; `-RootfsLocal` = file offline |
| `-ApkUrl` / `-ApkLocal` | Release dự án | Nguồn APK Linux Deploy; `-ApkLocal` = file offline |
| `-RepoUrl` / `-RepoLocal` | repo GitHub | Nguồn code hostvn-script-arm64 |
| `-Stop` | `all` | Dừng sau pha chỉ định (`adb`/`apk`/`deploy`/`ssh`/`install`) |

## Sau khi xong — SSH vào bằng root + mật khẩu

Mặc định đăng nhập bằng **tài khoản root + mật khẩu** (không cần key):
```powershell
ssh -p 2233 root@<IP-điện-thoại>
# mật khẩu mặc định: REDACTED   (đổi bằng -RootPassword hoặc `passwd root`)
# trong container:  hostvn
```
Vẫn hỗ trợ đăng nhập bằng key: `ssh -i ..\.ssh\id_ed25519 -p 2233 root@<IP>`

> ⚠️ Mật khẩu mặc định là **công khai** (trong repo). Với môi trường thật, đổi ngay: `-RootPassword '...'` khi chạy bootstrap, hoặc `passwd root` sau khi vào.
