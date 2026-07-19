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
    .\setup-android.ps1 -AdbMode tcp -DeviceAddr 192.168.1.50:30555

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

    # Phien ban Ubuntu: 24.04 (on dinh) hoac 26.04 (experimental - PPA ondrej/php co the
    # chua ho tro -> script se dung PHP mac dinh cua distro)
    [ValidateSet('24.04','26.04')]
    [string]$UbuntuVersion = '24.04',

    # Cau hinh container
    [string]$Profile      = 'noble',
    [string]$Suite        = 'noble',                      # nhan cho Linux Deploy (rootfs tu quyet dinh OS that)
    [string]$ImagePath    = '/data/local/ubuntu24.img',   # PHAI o /data (block that), KHONG o /sdcard (FUSE)
    [int]   $ImageSizeMB  = 12000,
    [int]   $SshPort      = 2233,

    # Nguon binary: MAC DINH tai tu GitHub Release CUA DU AN (khong phai nguon ngoai).
    # De trong de tu lay tu Release; hoac tro *Local toi file da tai san de chay OFFLINE.
    [string]$RootfsUrl   = '',
    [string]$RootfsLocal = '',
    [string]$ApkUrl      = '',
    [string]$ApkLocal    = '',

    # Repo hostvn-script-arm64 (clone trong container). Hoac dung -RepoLocal de day tu PC.
    [string]$RepoUrl   = 'https://github.com/Circling5714/hostvn-script-arm64.git',
    [string]$RepoLocal = '',

    # SSH key (private) - dung cho buoc cai tu dong (van cai vao root, song song mat khau)
    [string]$SshKey = "$PSScriptRoot\..\.ssh\id_ed25519",

    # Mat khau root: de TRONG (mac dinh) de tu SINH NGAU NHIEN moi lan cai. Se in ra
    # cuoi qua trinh de ban luu lai. Chi dat thu cong khi ban thuc su muon dung mat khau
    # co dinh: -RootPassword '...'
    [string]$RootPassword = '',

    # Mat khau tai khoan 'hostvn' trong container: cung de TRONG de sinh ngau nhien.
    [string]$UserPassword = '',

    # Chi lam toi buoc nao (all|adb|apk|deploy|ssh|install)
    [ValidateSet('all','adb','apk','deploy','ssh','install')]
    [string]$Stop = 'all'
)

$ErrorActionPreference = 'Stop'
$LD = 'ru.meefik.linuxdeploy'
$LDFILES = "/data/data/$LD/files"
$CLI = "$LDFILES/cli.sh"

# GitHub Release CUA DU AN - nguon binary mac dinh (khong phai nguon ngoai)
$ReleaseBase = 'https://github.com/Circling5714/hostvn-script-arm64/releases/download/assets-v1'
if (-not $ApkUrl)    { $ApkUrl    = "$ReleaseBase/linuxdeploy-2.6.0.apk" }
if (-not $RootfsUrl) { $RootfsUrl = "$ReleaseBase/ubuntu-base-$UbuntuVersion-arm64.tar.gz" }
$AdbZipUrl = "$ReleaseBase/platform-tools-adb-windows.zip"
$ToolsDir  = Join-Path $PSScriptRoot 'tools'

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

# Sinh mat khau ngau nhien manh bang crypto RNG (khong dung Get-Random - khong an toan).
function New-RandomPassword([int]$len = 20){
    $chars = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789'
    $bytes = New-Object 'System.Byte[]' $len
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    -join ($bytes | ForEach-Object { $chars[$_ % $chars.Length] })
}

# Neu user khong tu dat mat khau -> SINH NGAU NHIEN moi lan cai (tranh mat khau mac dinh
# cung, ai co repo cung biet). Cac mat khau sinh ra se duoc IN RA CUOI qua trinh (Show-Credentials)
# de user luu lai - khong luu tu dong o dau ca.
$script:RootPwGenerated = $false
$script:UserPwGenerated = $false
if (-not $RootPassword) { $RootPassword = New-RandomPassword 20; $script:RootPwGenerated = $true }
if (-not $UserPassword) { $UserPassword = New-RandomPassword 16; $script:UserPwGenerated = $true }

# In thong tin dang nhap noi bat de user luu lai. Goi 1 lan o cuoi (hoac khi -Stop ssh).
function Show-Credentials {
    Write-Host ""
    Write-Host "================= LUU LAI THONG TIN DANG NHAP (QUAN TRONG) =================" -ForegroundColor Yellow
    if ($script:RootPwGenerated) {
        Write-Host ("  Mat khau root (tu sinh):  {0}" -f $RootPassword) -ForegroundColor Yellow
    } else {
        Write-Host  "  Mat khau root:            (do ban tu dat qua -RootPassword)" -ForegroundColor Yellow
    }
    if ($script:UserPwGenerated) {
        Write-Host ("  Mat khau user 'hostvn':   {0}" -f $UserPassword) -ForegroundColor Yellow
    }
    Write-Host "  >> Luu NGAY vao trinh quan ly mat khau. Mat khau tu sinh KHONG duoc luu o dau khac." -ForegroundColor Yellow
    Write-Host "  >> Doi mat khau bat cu luc nao: passwd root" -ForegroundColor Yellow
    Write-Host "===========================================================================" -ForegroundColor Yellow
    Write-Host ""
}

# --- adb helpers (chay lenh, chay lenh root qua su) ---
function Adb { & $AdbPath @args }
function AdbSh([string]$cmd){ & $AdbPath shell $cmd }
function AdbSu([string]$cmd){ & $AdbPath shell "su -c '$cmd'" }

# Tai asset: uu tien file local (offline); khong thi tai tu URL (Release cua du an)
function Get-Asset([string]$local, [string]$url, [string]$dest){
    if ($local -and (Test-Path $local)) { Info "Dung file da co: $local"; Copy-Item $local $dest -Force; return $dest }
    Info "Tai: $url"
    Invoke-WebRequest -Uri $url -OutFile $dest
    return $dest
}

# Dam bao co adb: neu -AdbPath/PATH khong co adb -> tu tai platform-tools tu Release du an.
# (Che do WiFi/TCP chi can adb.exe; che do USB con can driver OEM cua hang - khong nhung chung duoc.)
function Resolve-Adb {
    $found = $false
    try { $null = & $AdbPath version 2>$null; if ($LASTEXITCODE -eq 0) { $found = $true } } catch {}
    if ($found) { Ok "Da co adb: $AdbPath"; return }
    Warn "May chua co adb. Tai adb (platform-tools) tu Release cua du an..."
    New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null
    $zip = Join-Path $ToolsDir 'platform-tools-adb-windows.zip'
    Invoke-WebRequest -Uri $AdbZipUrl -OutFile $zip
    Expand-Archive -Path $zip -DestinationPath $ToolsDir -Force
    $script:AdbPath = Join-Path $ToolsDir 'adb.exe'
    if (-not (Test-Path $script:AdbPath)) { Die "Tai adb that bai." }
    try { $null = & $script:AdbPath version 2>$null } catch { Die "adb tai ve khong chay duoc." }
    Ok "Da co adb (tu Release): $script:AdbPath"
}

# ============================================================================
# PHASE 1: adb connection + kiem tra root
# ============================================================================
function Phase-Adb {
    Info "Phase 1: ket noi adb (che do: $AdbMode)"
    Resolve-Adb   # tu tai adb tu Release neu may chua co

    if ($AdbMode -eq 'tcp') {
        if (-not $DeviceAddr) { Die "Che do tcp can -DeviceAddr IP:port (vd 192.168.1.50:30555). Neu chua bat, cam USB va chay: adb tcpip 5555" }
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
        $apk = Get-Asset $ApkLocal $ApkUrl (Join-Path $env:TEMP 'linuxdeploy.apk')
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
    Info "Phase 3: deploy Ubuntu $UbuntuVersion arm64 (image tren /data - block that, tranh vold reboot)"
    if ($UbuntuVersion -eq '26.04') { Warn "Ubuntu 26.04 dang experimental (PPA ondrej/php co the chua ho tro -> dung PHP distro)." }

    # Lay rootfs ubuntu-base: uu tien -RootfsLocal (offline), khong thi tai tu Release du an
    $rootfsTmp = Get-Asset $RootfsLocal $RootfsUrl (Join-Path $env:TEMP "ubuntu-base-$UbuntuVersion-arm64.tar.gz")
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
USER_PASSWORD="$UserPassword"
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
    Info "Phase 4: start container + cau hinh SSH (root + mat khau mac dinh)"
    AdbSu "sh $CLI -p $Profile mount; sh $CLI -p $Profile start" | Out-Null
    Start-Sleep 3
    $mnt = '/data/local/mnt'

    # Tao SSH key neu chua co (dung cho buoc cai tu dong; song song voi mat khau)
    if (-not (Test-Path $SshKey)) {
        Info "Tao SSH key: $SshKey"
        New-Item -ItemType Directory -Force -Path (Split-Path $SshKey) | Out-Null
        & ssh-keygen -t ed25519 -N '""' -f $SshKey | Out-Null
    }
    $pub = Get-Content "$SshKey.pub" -Raw
    AdbSu "mkdir -p $mnt/root/.ssh; echo '$($pub.Trim())' > $mnt/root/.ssh/authorized_keys; chmod 700 $mnt/root/.ssh; chmod 600 $mnt/root/.ssh/authorized_keys"

    # Cho phep root dang nhap bang MAT KHAU (mac dinh) + van giu key
    AdbSu "sed -i 's/^#*PermitRootLogin.*/PermitRootLogin yes/' $mnt/etc/ssh/sshd_config"
    AdbSu "sed -i 's/^#*PasswordAuthentication.*/PasswordAuthentication yes/' $mnt/etc/ssh/sshd_config"
    AdbSu "grep -q '^PasswordAuthentication yes' $mnt/etc/ssh/sshd_config || echo 'PasswordAuthentication yes' >> $mnt/etc/ssh/sshd_config"
    AdbSu "grep -q '^Port $SshPort' $mnt/etc/ssh/sshd_config || echo 'Port $SshPort' >> $mnt/etc/ssh/sshd_config"

    # Dat mat khau root + khoi dong lai sshd: ghi script vao container (base64 -> tranh quoting),
    # chay qua chroot. chpasswd + sshd doc cau hinh moi.
    $sh = "#!/bin/bash`nexport PATH=/usr/sbin:/usr/bin:/sbin:/bin`necho 'root:$RootPassword' | chpasswd`nmkdir -p /run/sshd`npkill -x sshd 2>/dev/null`nsleep 1`n/usr/sbin/sshd -p $SshPort`n"
    $b64 = [Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes(($sh -replace "`r`n","`n")))
    AdbSu "echo $b64 | base64 -d > $mnt/root/.hvn-sshsetup.sh; chmod +x $mnt/root/.hvn-sshsetup.sh"
    AdbSu "sh $CLI -p $Profile shell /bin/bash /root/.hvn-sshsetup.sh" | Out-Null
    Start-Sleep 2

    # Xac dinh IP dien thoai de ssh
    $ip = ($DeviceAddr -split ':')[0]
    if (-not $ip) { $ip = (AdbSu "ip route get 1 2>/dev/null | awk '{print \$7; exit}'") -join '' }
    $global:PhoneIp = $ip.Trim()

    Ok "SSH san sang:"
    Ok "  >> Bang MAT KHAU: ssh -p $SshPort root@$($global:PhoneIp)"
    Ok "  >> Bang key:      ssh -i $SshKey -p $SshPort root@$($global:PhoneIp)"
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
Phase-Ssh;     if ($Stop -eq 'ssh')     { Show-Credentials; return }
Phase-Install
Show-Credentials
Write-Host "==== XONG ====" -ForegroundColor Green
