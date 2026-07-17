<#
================================================================================
  HostVN Script ARM64 - Bo khoi tao tu dau tren Android (PC-side, PowerShell)
================================================================================
  Tu dong hoa toan bo chuoi:
    adb (USB hoac TCP) -> cai APK Linux Deploy -> deploy Ubuntu 24.04 arm64
    -> cau hinh SSH -> tai & chay hostvn-script-arm64 (install)

  YEU CAU:
    - May Android DA ROOT (Magisk), bat "USB debugging" (Settings > Developer).
    - PC co adb (Android platform-tools) trong PATH, hoac dat qua -AdbPath.
    - Ket noi Internet tren ca PC lan dien thoai.

  VI DU:
    # Qua USB (cam cap):
    .\setup-android.ps1 -AdbMode usb

    # Qua WiFi/TCP (da bat adb tcpip tu truoc):
    .\setup-android.ps1 -AdbMode tcp -DeviceAddr 10.10.17.31:30555

  LUU Y: co 1-2 buoc phai CHAM TAY tren dien thoai (cap quyen root cho Linux
  Deploy, cap nhat ENV) - script se DUNG va huong dan ro rang khi toi cac buoc do.
================================================================================
#>

[CmdletBinding()]
param(
    [ValidateSet('usb','tcp')]
    [string]$AdbMode = 'tcp',

    # Dia chi adb khi -AdbMode tcp (IP:port). Bo qua khi USB.
    [string]$DeviceAddr = '',

    # Duong dan adb.exe (mac dinh: tim trong PATH)
    [string]$AdbPath = 'adb',

    # Cau hinh container
    [string]$Profile      = 'noble',
    [string]$Suite        = 'noble',                      # Ubuntu 24.04
    [string]$ImagePath    = '/data/local/ubuntu24.img',   # PHAI o /data (block that), KHONG o /sdcard (FUSE)
    [int]   $ImageSizeMB  = 12000,
    [int]   $SshPort      = 2233,
    [string]$RootfsUrl    = 'https://cdimage.ubuntu.com/ubuntu-base/releases/24.04/release/ubuntu-base-24.04.2-base-arm64.tar.gz',

    # Nguon APK Linux Deploy (GitHub release). Co the tai san roi tro qua -ApkLocal.
    [string]$ApkUrl   = 'https://github.com/meefik/linuxdeploy/releases/download/2.6.0/linuxDeploy-arm64-v8a-2.6.0-5216.apk',
    [string]$ApkLocal = '',

    # Repo hostvn-script-arm64 (clone trong container). Hoac dung -RepoLocal de day tu PC.
    [string]$RepoUrl   = 'https://github.com/Circling5714/hostvn-script-arm64.git',
    [string]$RepoLocal = '',

    # SSH key (private) de cai vao container cho user root. Tao moi neu chua co.
    [string]$SshKey = "$PSScriptRoot\..\.ssh\id_ed25519",

    # Chi lam toi buoc nao (all|adb|apk|deploy|ssh|install)
    [ValidateSet('all','adb','apk','deploy','ssh','install')]
    [string]$Stop = 'all'
)

$ErrorActionPreference = 'Stop'
$LD = 'ru.meefik.linuxdeploy'
$LDFILES = "/data/data/$LD/files"
$CLI = "$LDFILES/cli.sh"

function Info($m){ Write-Host "[*] $m" -ForegroundColor Cyan }
function Ok($m){ Write-Host "[OK] $m" -ForegroundColor Green }
function Warn($m){ Write-Host "[!] $m" -ForegroundColor Yellow }
function Die($m){ Write-Host "[X] $m" -ForegroundColor Red; exit 1 }
function Pause-Manual($m){
    Write-Host ""
    Write-Host "  >>> CAN THAO TAC TREN DIEN THOAI <<<" -ForegroundColor Magenta
    Write-Host "  $m" -ForegroundColor Magenta
    Read-Host "  Xong thi nhan Enter de tiep tuc"
}

# --- adb helpers (chay lenh, chay lenh root qua su) ---
function Adb { & $AdbPath @args }
function AdbSh([string]$cmd){ & $AdbPath shell $cmd }
function AdbSu([string]$cmd){ & $AdbPath shell "su -c '$cmd'" }

# ============================================================================
# PHASE 1: adb connection + kiem tra root
# ============================================================================
function Phase-Adb {
    Info "Phase 1: ket noi adb (che do: $AdbMode)"
    try { $null = & $AdbPath version } catch { Die "Khong tim thay adb. Cai Android platform-tools hoac dat -AdbPath." }

    if ($AdbMode -eq 'tcp') {
        if (-not $DeviceAddr) { Die "Che do tcp can -DeviceAddr IP:port (vd 10.10.17.31:30555). Neu chua bat, cam USB va chay: adb tcpip 5555" }
        Info "adb connect $DeviceAddr"
        Adb disconnect 2>$null | Out-Null
        Adb connect $DeviceAddr | Out-Null
        Start-Sleep 2
    } else {
        Info "Dung thiet bi USB. Dam bao da cam cap + 'USB debugging' bat + cap phep tren dien thoai."
    }

    $state = (& $AdbPath get-state 2>&1) -join ''
    if ($state -notmatch 'device') { Die "adb chua thay thiet bi (state=$state). Kiem tra ket noi/USB debugging." }
    Ok "adb da ket noi."

    Info "Kiem tra quyen root (su)..."
    $id = (AdbSu 'id') -join ''
    if ($id -notmatch 'uid=0') {
        Pause-Manual "Cap quyen ROOT (superuser) cho 'shell'/adb qua Magisk khi co popup, roi chay lai."
        $id = (AdbSu 'id') -join ''
        if ($id -notmatch 'uid=0') { Die "Khong co quyen root. May phai da root (Magisk) va cap quyen cho shell." }
    }
    Ok "Co quyen root: $id"

    $arch = (AdbSu 'getprop ro.product.cpu.abi') -join ''
    Info "Kien truc thiet bi: $arch"
    if ($arch -notmatch 'arm64|aarch64') { Warn "Thiet bi khong phai arm64 ($arch) - ban ARM64 huong toi arm64." }
}

# ============================================================================
# PHASE 2: cai APK Linux Deploy + chuan bi ENV
# ============================================================================
function Phase-Apk {
    Info "Phase 2: cai Linux Deploy"
    $installed = (AdbSh "pm path $LD") -join ''
    if ($installed -match 'package:') {
        Ok "Linux Deploy da cai san."
    } else {
        $apk = $ApkLocal
        if (-not $apk) {
            $apk = Join-Path $env:TEMP 'linuxdeploy.apk'
            Info "Tai APK Linux Deploy: $ApkUrl"
            Invoke-WebRequest -Uri $ApkUrl -OutFile $apk
        }
        if (-not (Test-Path $apk)) { Die "Khong thay APK: $apk" }
        Info "adb install $apk"
        Adb install -r $apk | Out-Null
        Ok "Da cai Linux Deploy."
    }

    # ENV cua Linux Deploy (cli.sh, busybox) chi duoc giai nen khi mo app lan dau
    $hasCli = (AdbSu "[ -f $CLI ] && echo yes || echo no") -join ''
    if ($hasCli -notmatch 'yes') {
        Info "Mo app Linux Deploy de giai nen ENV..."
        AdbSh "monkey -p $LD -c android.intent.category.LAUNCHER 1" | Out-Null
        Pause-Manual "Trong app Linux Deploy: cap quyen ROOT khi co popup, roi vao Menu > 'Update' (cap nhat ENV) va cho xong."
        $hasCli = (AdbSu "[ -f $CLI ] && echo yes || echo no") -join ''
        if ($hasCli -notmatch 'yes') { Die "ENV Linux Deploy chua san sang ($CLI khong ton tai). Hay 'Update' ENV trong app roi chay lai." }
    }
    Ok "ENV Linux Deploy san sang."
}

# ============================================================================
# PHASE 3: cau hinh profile + deploy Ubuntu (rootfs -> image tren /data)
# ============================================================================
function Phase-Deploy {
    Info "Phase 3: deploy Ubuntu 24.04 arm64 (image tren /data - block that, tranh vold reboot)"

    # Tai rootfs ubuntu-base va day len /sdcard de Linux Deploy import
    $rootfsLocal = $ApkLocal
    $rootfsTmp = Join-Path $env:TEMP 'ubuntu-base-arm64.tar.gz'
    Info "Tai ubuntu-base rootfs: $RootfsUrl"
    Invoke-WebRequest -Uri $RootfsUrl -OutFile $rootfsTmp
    $rootfsDev = '/storage/emulated/0/ubuntu-rootfs.tar.gz'
    Info "Day rootfs len dien thoai: $rootfsDev"
    Adb push $rootfsTmp $rootfsDev | Out-Null

    # Viet profile .conf (dua tren cau hinh da kiem chung)
    $conf = @"
ARCH="arm64"
DISTRIB="ubuntu"
SUITE="$Suite"
FS_TYPE="ext4"
DISK_SIZE="$ImageSizeMB"
TARGET_TYPE="file"
TARGET_PATH="$ImagePath"
SOURCE_TYPE="file"
SOURCE_PATH="$rootfsDev"
INCLUDE="bootstrap extra/ssh init"
INIT="run-parts"
INIT_PATH="/etc/rc.local"
INIT_USER="root"
LOCALE="C.UTF-8"
DNS="1.1.1.1"
MOUNTS="/system /sdcard:/mnt/sdcard"
SSH_PORT="$SshPort"
USER_NAME="hostvn"
USER_PASSWORD="hostvn2026"
"@
    $confLocal = Join-Path $env:TEMP "$Profile.conf"
    # LF line endings
    [IO.File]::WriteAllText($confLocal, ($conf -replace "`r`n","`n"))
    $confDev = "$LDFILES/config/$Profile.conf"
    Info "Day profile: $confDev"
    Adb push $confLocal "/sdcard/$Profile.conf" | Out-Null
    AdbSu "mkdir -p $LDFILES/config; cp /sdcard/$Profile.conf $confDev; chmod 600 $confDev"

    Info "Deploy container (co the mat vai phut - tai goi + tao image ext4)..."
    AdbSu "sh $CLI -p $Profile deploy"
    Ok "Deploy xong."
}

# ============================================================================
# PHASE 4: start container + cau hinh SSH (root key + port)
# ============================================================================
function Phase-Ssh {
    Info "Phase 4: start container + cau hinh SSH"
    AdbSu "sh $CLI -p $Profile mount; sh $CLI -p $Profile start" | Out-Null
    Start-Sleep 3

    # Tao SSH key neu chua co
    if (-not (Test-Path $SshKey)) {
        Info "Tao SSH key: $SshKey"
        New-Item -ItemType Directory -Force -Path (Split-Path $SshKey) | Out-Null
        & ssh-keygen -t ed25519 -N '""' -f $SshKey | Out-Null
    }
    $pub = Get-Content "$SshKey.pub" -Raw
    # Cai public key cho root trong container (qua chroot mount tai /data/local/mnt)
    $mnt = '/data/local/mnt'
    AdbSu "mkdir -p $mnt/root/.ssh; echo '$($pub.Trim())' > $mnt/root/.ssh/authorized_keys; chmod 700 $mnt/root/.ssh; chmod 600 $mnt/root/.ssh/authorized_keys"
    # Bat PermitRootLogin + Port trong sshd_config
    AdbSu "sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin prohibit-password/' $mnt/etc/ssh/sshd_config; grep -q '^Port $SshPort' $mnt/etc/ssh/sshd_config || echo 'Port $SshPort' >> $mnt/etc/ssh/sshd_config"
    # Khoi dong lai ssh trong container
    AdbSu "sh $CLI -p $Profile shell 'export PATH=/usr/sbin:/usr/bin:/sbin:/bin; mkdir -p /run/sshd; pkill sshd 2>/dev/null; /usr/sbin/sshd -p $SshPort'" | Out-Null

    # Xac dinh IP dien thoai de ssh
    $ip = ($DeviceAddr -split ':')[0]
    if (-not $ip) { $ip = (AdbSu "ip route get 1 2>/dev/null | awk '{print \$7; exit}'") -join '' }
    $global:PhoneIp = $ip.Trim()
    Ok "SSH san sang: ssh -i $SshKey -p $SshPort root@$($global:PhoneIp)"
}

# ============================================================================
# PHASE 5: tai & chay hostvn-script-arm64 trong container
# ============================================================================
function Phase-Install {
    Info "Phase 5: cai hostvn-script-arm64 trong container"
    $ip = $global:PhoneIp
    $sshBase = "ssh -i `"$SshKey`" -o StrictHostKeyChecking=no -o IdentitiesOnly=yes -p $SshPort root@$ip"

    if ($RepoLocal) {
        Info "Day repo tu PC: $RepoLocal"
        & scp -i "$SshKey" -o StrictHostKeyChecking=no -P $SshPort -r "$RepoLocal" "root@${ip}:/root/hostvn-script-arm64" | Out-Null
        Invoke-Expression "$sshBase `"cd /root/hostvn-script-arm64 && bash install`""
    } else {
        Info "Clone repo trong container: $RepoUrl"
        Invoke-Expression "$sshBase `"export PATH=/usr/sbin:/usr/bin:/sbin:/bin; apt-get update -y && apt-get install -y git; git clone $RepoUrl /root/hostvn-script-arm64; cd /root/hostvn-script-arm64 && bash install`""
    }
    Ok "Hoan tat. Quan tri bang lenh 'hostvn' (SSH vao container)."
}

# ============================================================================
# MAIN
# ============================================================================
Write-Host "==== HostVN ARM64 Bootstrap ====" -ForegroundColor White
Phase-Adb;     if ($Stop -eq 'adb')     { return }
Phase-Apk;     if ($Stop -eq 'apk')     { return }
Phase-Deploy;  if ($Stop -eq 'deploy')  { return }
Phase-Ssh;     if ($Stop -eq 'ssh')     { return }
Phase-Install
Write-Host "==== XONG ====" -ForegroundColor Green
