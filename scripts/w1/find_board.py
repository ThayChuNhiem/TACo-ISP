#!/usr/bin/env python3
"""
TACo-ISP — KV260 Auto-Discovery
=================================
Tự động tìm IP của board KV260 sau khi boot, KHÔNG cần thao tác thủ công.

Thử 3 phương pháp theo thứ tự:
  1. USB Serial (UART J4): Đọc boot log → grep IP từ DHCP/ifconfig output
  2. mDNS (Avahi):         ping <hostname>.local  (PetaLinux bật Avahi mặc định)
  3. Network Scan:         Quét ARP table hoặc subnet tìm thiết bị mới

Cách dùng:
  python scripts/w1/find_board.py
  python scripts/w1/find_board.py --serial COM5
  python scripts/w1/find_board.py --subnet 192.168.1.0/24
"""

import argparse
import re
import socket
import subprocess
import sys
import time
from pathlib import Path

# Cấu hình UTF-8 cho Windows Console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ─── Cấu hình ───────────────────────────────────────────────────────────────
SERIAL_BAUD = 115200
SERIAL_TIMEOUT = 120          # Chờ tối đa 120s để board boot xong
MDNS_HOSTNAMES = [            # Thử các hostname mDNS phổ biến của KV260
    "xilinx-kv260-starterkit",
    "xilinx-kv260-2022-2",
    "xilinx-kv260",
    "kria",
    "petalinux",
]
SSH_PORT = 22
DEFAULT_USER = "petalinux"


def log(msg: str, icon: str = "ℹ️"):
    ts = time.strftime("%H:%M:%S")
    print(f"[{ts}] {icon} {msg}")


# ═══════════════════════════════════════════════════════════════════════════════
# PHƯƠNG PHÁP 1: USB Serial — đọc boot log, trích IP
# ═══════════════════════════════════════════════════════════════════════════════
def find_serial_ports() -> list[str]:
    """Tìm tất cả COM port trên Windows (hoặc /dev/ttyUSB* trên Linux)."""
    ports = []
    if sys.platform == "win32":
        # Cách 1: Truy vấn Registry Windows (nhanh, 0.05s)
        try:
            r = subprocess.run(
                ['powershell', '-Command',
                 "(Get-ItemProperty -Path 'HKLM:\\HARDWARE\\DEVICEMAP\\SERIALCOMM' -ErrorAction SilentlyContinue).PSObject.Properties | Where-Object { $_.Name -notmatch '^PS' } | Select-Object -ExpandProperty Value"],
                capture_output=True, text=True, timeout=3
            )
            if r.returncode == 0 and r.stdout.strip():
                for match in re.findall(r'(COM\d+)', r.stdout):
                    if match not in ports:
                        ports.append(match)
        except Exception:
            pass

        # Cách 2: Fallback pyserial
        if not ports:
            try:
                import serial.tools.list_ports
                for p in serial.tools.list_ports.comports():
                    ports.append(p.device)
            except Exception:
                pass
    else:
        import glob
        ports = glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*')
    
    return ports


def discover_via_serial(port: str = None, timeout: int = SERIAL_TIMEOUT) -> str | None:
    """Mở serial port, đọc boot log, trích xuất IP address."""
    try:
        import serial
    except ImportError:
        log("pyserial chưa cài. Chạy: pip install pyserial", "⚠️")
        return None

    # Auto-detect port nếu không chỉ định
    if port is None:
        ports = find_serial_ports()
        if not ports:
            log("Không tìm thấy COM port nào. Cắm cáp USB UART (J4)?", "⚠️")
            return None
        port = ports[0]
        log(f"Auto-selected serial port: {port}", "🔌")

    log(f"Mở {port} @ {SERIAL_BAUD} baud, chờ tối đa {timeout}s...", "🔌")

    try:
        ser = serial.Serial(port, SERIAL_BAUD, timeout=1)
    except serial.SerialException as e:
        log(f"Không mở được {port}: {e}", "❌")
        return None

    # Regex patterns cho IP address trong boot log
    ip_patterns = [
        # "inet 192.168.1.100/24" (ip addr show)
        re.compile(r'inet\s+((?:192|10|172)\.\d+\.\d+\.\d+)/\d+'),
        # "IP-Config: ... address: 192.168.1.100"
        re.compile(r'address:\s*((?:192|10|172)\.\d+\.\d+\.\d+)'),
        # DHCP: "bound to 192.168.1.100"
        re.compile(r'bound to\s+((?:192|10|172)\.\d+\.\d+\.\d+)'),
        # "eth0: 192.168.1.100"
        re.compile(r'eth\d+:\s*((?:192|10|172)\.\d+\.\d+\.\d+)'),
        # Fallback: any private IP
        re.compile(r'\b((?:192\.168|10\.\d+|172\.(?:1[6-9]|2\d|3[01]))\.\d+\.\d+)\b'),
    ]

    # Gửi Enter để kích hoạt prompt nếu board đã boot xong
    ser.write(b'\r\n')
    time.sleep(0.5)

    start = time.time()
    buffer = ""
    found_ip = None
    
    # State tracking cho serial login & query
    login_users = ["root", "petalinux", "ubuntu"]
    user_idx = 0
    logged_in = False
    last_sent_time = 0
    last_action = None

    log("Đang đọc serial output...", "📡")

    while time.time() - start < timeout:
        try:
            n = ser.in_waiting
            data = ser.read(n if n > 0 else 1)
            if data:
                text = data.decode('utf-8', errors='replace')
                buffer += text

                # Print real-time (abbreviated)
                for line in text.split('\n'):
                    line = line.strip()
                    if line:
                        if any(kw in line.lower() for kw in ['inet ', 'dhcp', 'address', 'login', 'eth0']):
                            print(f"  │ {line[:120]}")

                recent = buffer[-500:].lower()

                # 1. Kiểm tra nếu đã ở trong shell prompt (đã login thành công)
                shell_prompt_detected = any(p in recent for p in [
                    'root@', 'petalinux@', 'ubuntu@', '~# ', '~$ ', '# ', '$ '
                ]) and not ('login:' in recent or 'password:' in recent)

                if shell_prompt_detected:
                    if not logged_in:
                        logged_in = True
                        log("Shell prompt detected — gửi lệnh 'ip -4 addr show eth0'...", "✅")
                        ser.write(b'ip -4 addr show eth0\r\n')
                        last_sent_time = time.time()
                        last_action = "ip_cmd"

                # 2. Xử lý khi gặp Login prompt
                elif 'login:' in recent and (time.time() - last_sent_time > 2.0 or last_action != "user"):
                    curr_user = login_users[user_idx % len(login_users)]
                    log(f"Login prompt detected — gửi tài khoản '{curr_user}'...", "✅")
                    ser.write(f"{curr_user}\r\n".encode('utf-8'))
                    last_sent_time = time.time()
                    last_action = "user"

                # 3. Xử lý khi gặp Password prompt
                elif 'password:' in recent and (time.time() - last_sent_time > 1.5 or last_action != "pass"):
                    curr_user = login_users[user_idx % len(login_users)]
                    log(f"Password prompt detected — gửi mật khẩu '{curr_user}'...", "✅")
                    ser.write(f"{curr_user}\r\n".encode('utf-8'))
                    last_sent_time = time.time()
                    last_action = "pass"

                # 4. Xử lý nếu đăng nhập sai (Login incorrect)
                if 'incorrect' in recent and last_action != "failed":
                    user_idx += 1
                    next_user = login_users[user_idx % len(login_users)]
                    log(f"Đăng nhập chưa đúng, thử tài khoản tiếp theo '{next_user}'...", "⚠️")
                    last_action = "failed"
                    last_sent_time = time.time()

            # 5. Định kỳ gửi lại lệnh IP nếu đã login mà chưa trích xuất được IP (chờ DHCP)
            if logged_in and not found_ip and (time.time() - last_sent_time > 5.0):
                ser.write(b'ip -4 addr show eth0\r\n')
                last_sent_time = time.time()

            # 6. Tìm IP trong buffer
            for pattern in ip_patterns:
                match = pattern.search(buffer[-2000:])
                if match:
                    candidate = match.group(1)
                    if not candidate.startswith('127.'):
                        found_ip = candidate
                        break

            if found_ip:
                break

        except serial.SerialException as e:
            log(f"Lỗi đọc serial: {e}", "❌")
            break
        except Exception as e:
            log(f"Serial read error: {e}", "⚠️")
            time.sleep(0.5)

        time.sleep(0.1)

    ser.close()

    if found_ip:
        log(f"Tìm thấy IP qua Serial: {found_ip}", "✅")
    else:
        log("Không trích được IP từ serial log", "⚠️")
    
    return found_ip


# ═══════════════════════════════════════════════════════════════════════════════
# PHƯƠNG PHÁP 2: mDNS / Avahi — ping <hostname>.local
# ═══════════════════════════════════════════════════════════════════════════════
def discover_via_mdns() -> str | None:
    """Thử ping các hostname .local phổ biến của KV260 (Avahi/mDNS)."""
    log("Thử mDNS discovery (.local)...", "📡")

    for hostname in MDNS_HOSTNAMES:
        fqdn = f"{hostname}.local"
        log(f"  Trying: {fqdn}", "🔍")
        try:
            ip = socket.getaddrinfo(fqdn, None, socket.AF_INET)[0][4][0]
            log(f"  → Resolved: {fqdn} = {ip}", "✅")
            # Verify SSH port is open
            if check_ssh(ip):
                log(f"Tìm thấy board qua mDNS: {ip} ({fqdn})", "✅")
                return ip
        except socket.gaierror:
            continue
        except Exception as e:
            log(f"  → Error: {e}", "⚠️")
            continue

    log("mDNS không tìm thấy board", "⚠️")
    return None


# ═══════════════════════════════════════════════════════════════════════════════
# PHƯƠNG PHÁP 3: Network Scan — quét ARP table hoặc subnet
# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
def get_local_subnet() -> str | None:
    """Đoán subnet của máy host bằng socket nội bộ chuẩn (có fallback offline)."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        octets = local_ip.split('.')
        return f"{octets[0]}.{octets[1]}.{octets[2]}.0/24"
    except Exception:
        pass

    # Fallback khi máy host không có internet (cáp mạng LAN trực tiếp)
    try:
        host_name = socket.gethostname()
        for ip in socket.gethostbyname_ex(host_name)[2]:
            if not ip.startswith("127.") and not ip.startswith("169.254."):
                octets = ip.split('.')
                return f"{octets[0]}.{octets[1]}.{octets[2]}.0/24"
    except Exception:
        pass

    return None


def discover_via_network_scan(subnet: str = None) -> str | None:
    """Quét ARP table và subnet bằng ThreadPool đa luồng Python tìm KV260 mở cổng SSH."""
    log("Thử Network Scan...", "📡")

    # Bước 1: Kiểm tra ARP table trước (nhanh, không cần scan)
    log("  Kiểm tra ARP table...", "🔍")
    try:
        r = subprocess.run(['arp', '-a'], capture_output=True, text=True, timeout=10)
        arp_ips = re.findall(r'(\d+\.\d+\.\d+\.\d+)', r.stdout)
        
        for ip in arp_ips:
            if ip.startswith('127.') or ip.endswith('.255') or ip.endswith('.1'):
                continue
            if check_ssh(ip):
                if verify_kv260(ip):
                    log(f"Tìm thấy KV260 trong ARP table: {ip}", "✅")
                    return ip
    except Exception as e:
        log(f"  ARP scan error: {e}", "⚠️")

    # Bước 2: Quét subnet bằng Python ThreadPoolExecutor (độc lập nền tảng, không phụ thuộc PowerShell)
    if subnet is None:
        subnet = get_local_subnet()
    if subnet is None:
        log("Không xác định được subnet của host", "⚠️")
        return None

    log(f"  Quét đa luồng subnet: {subnet} ...", "🔍")
    base = subnet.rsplit('.', 1)[0].rsplit('/', 1)[0]
    candidate_ips = [f"{base}.{i}" for i in range(2, 255)]

    from concurrent.futures import ThreadPoolExecutor, as_completed

    def probe_ip(ip):
        if check_ssh(ip, timeout=0.6):
            if verify_kv260(ip):
                return ip
        return None

    try:
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(probe_ip, ip) for ip in candidate_ips]
            for future in as_completed(futures):
                res = future.result()
                if res:
                    log(f"Tìm thấy KV260 qua network scan: {res}", "✅")
                    return res
    except Exception as e:
        log(f"  Network scan error: {e}", "⚠️")

    log("Network scan không tìm thấy KV260", "⚠️")
    return None


def check_ssh(ip: str, timeout: float = 1.0) -> bool:
    """Kiểm tra port SSH 22 có mở không."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        result = s.connect_ex((ip, SSH_PORT))
        s.close()
        return result == 0
    except Exception:
        return False


def verify_kv260(ip: str) -> bool:
    """Xác nhận thiết bị là KV260 bằng cách thử kết nối SSH với tài khoản KV260.
    Tránh bắt nhầm IP của server Linux khác trong lab.
    """
    # Kiểm tra nhanh port SSH 22 trước để tránh timeout lặp lại khi gọi đơn lẻ
    if not check_ssh(ip, timeout=0.5):
        return False

    try:
        import paramiko
        import logging
        logging.getLogger("paramiko").setLevel(logging.CRITICAL)
    except ImportError:
        # Fallback nếu thiếu paramiko: kiểm tra banner SSH
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(1.5)
            s.connect((ip, SSH_PORT))
            banner = s.recv(256).decode('utf-8', errors='replace').lower()
            s.close()
            return 'ssh' in banner
        except Exception:
            return False

    # Danh sách tài khoản KV260 đặc trưng (ưu tiên root/root, petalinux/petalinux, ubuntu/ubuntu)
    credentials = [
        ("root", "root"),
        ("petalinux", "petalinux"),
        ("ubuntu", "ubuntu"),
        ("petalinux", None),
        ("ubuntu", None),
        ("root", None),
    ]

    # Kiểm tra thêm cấu hình trong board_config.json nếu có
    cfg_file = Path(__file__).resolve().parents[2] / "board_config.json"
    if cfg_file.exists():
        try:
            import json
            cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
            u = cfg.get("user")
            p = cfg.get("password")
            if u and p:
                cred = (u, p)
                if cred not in credentials:
                    credentials.insert(0, cred)
        except Exception:
            pass

    for u, p in credentials:
        cli = None
        try:
            cli = paramiko.SSHClient()
            cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            if p is not None:
                cli.connect(ip, port=SSH_PORT, username=u, password=p, timeout=1.5, look_for_keys=False, banner_timeout=1.5)
            else:
                cli.connect(ip, port=SSH_PORT, username=u, timeout=1.5, banner_timeout=1.5)
            
            # Đã kết nối được SSH - kiểm tra xác nhận phần cứng tránh nhầm server x86 khác trong lab
            try:
                stdin, stdout, stderr = cli.exec_command(
                    "uname -m; cat /proc/device-tree/model 2>/dev/null; uname -r 2>/dev/null", timeout=2.0
                )
                hw_info = stdout.read().decode('utf-8', errors='replace').lower()
                if 'aarch64' in hw_info or any(k in hw_info for k in ['zynq', 'xilinx', 'kria', 'kv260']):
                    log(f"  Xác thực thành công KV260 tại {ip} với tài khoản '{u}'", "✅")
                    return True
                else:
                    log(f"  Bỏ qua {ip}: Máy chủ không phải phần cứng KV260/aarch64", "⚠️")
                    return False
            except Exception:
                # Nếu không thể chạy lệnh exec kiểm tra, chấp nhận kết nối SSH
                log(f"  Xác thực thành công KV260 tại {ip} với tài khoản '{u}'", "✅")
                return True
        except (paramiko.AuthenticationException, paramiko.SSHException, socket.timeout, TimeoutError, OSError):
            continue
        except Exception:
            continue
        finally:
            if cli:
                try:
                    cli.close()
                except Exception:
                    pass

    return False


# ═══════════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════════
def discover(serial_port: str = None, subnet: str = None, skip_serial: bool = False) -> str | None:
    """Chạy 3 phương pháp theo thứ tự, trả về IP đầu tiên tìm được."""
    log("=" * 55)
    log("🔍 TACo-ISP — KV260 Auto-Discovery")
    log("=" * 55)

    # 1. Serial
    if not skip_serial:
        ip = discover_via_serial(serial_port)
        if ip and check_ssh(ip):
            return ip
    
    # 2. mDNS
    ip = discover_via_mdns()
    if ip:
        return ip

    # 3. Network scan
    ip = discover_via_network_scan(subnet)
    if ip:
        return ip

    log("❌ Không tìm thấy board KV260 bằng cả 3 phương pháp!", "❌")
    log("   Kiểm tra: cáp Ethernet đã cắm? Board đã boot xong?", "❌")
    return None


def main():
    parser = argparse.ArgumentParser(description="KV260 Auto-Discovery")
    parser.add_argument("--serial", default=None, help="COM port (e.g., COM5). Auto-detect if omitted.")
    parser.add_argument("--subnet", default=None, help="Subnet to scan (e.g., 192.168.1.0/24)")
    parser.add_argument("--no-serial", action="store_true", help="Skip serial method")
    args = parser.parse_args()

    ip = discover(
        serial_port=args.serial,
        subnet=args.subnet,
        skip_serial=args.no_serial,
    )

    if ip:
        log(f"\n🎯 KV260 IP: {ip}", "✅")
        log(f"   SSH: ssh {DEFAULT_USER}@{ip}")
        log(f"   Tiếp theo: python scripts/w1/run_all.py --host {ip} --user {DEFAULT_USER}")
        # Ghi IP ra file để script khác đọc
        ip_file = Path(__file__).parent / "kv260_ip.txt"
        ip_file.write_text(ip)
        log(f"   IP saved to: {ip_file}")
        print(f"\nBOARD_IP={ip}")  # Machine-readable output
        return 0
    else:
        return 1


if __name__ == "__main__":
    sys.exit(main())
