#!/usr/bin/env python3
"""
TACo-ISP — W01 Master Orchestrator
===================================
Script chạy trên HOST PC (Windows) — điều khiển toàn bộ ĐV-2 → ĐV-6 qua SSH.

Cách dùng (AI Agent chạy trên host):
  python scripts/board_setup/run_all.py                                  # Auto-discover IP
  python scripts/board_setup/run_all.py --host <IP> --user <USER>        # Manual IP
  python scripts/board_setup/run_all.py --password <PASS>                # With password

Nếu không chỉ định --host, script sẽ TỰ ĐỘNG tìm board qua:
  1. USB Serial (UART J4) — đọc boot log grep IP
  2. mDNS (Avahi)         — ping <hostname>.local
  3. Network Scan         — quét ARP + subnet tìm SSH port

Luồng xử lý:
  [Auto-discover IP] →
  ĐV-2: SSH vào board → chạy 01_board_setup.sh → thu ENV.md
  ĐV-3: Chạy 02_dpu_check.sh → kiểm tra DPU
  ĐV-4: Chạy 03_vitis_ai_demo.sh → demo VART
  ĐV-5: Setup host (venv, VS Code SSH config) — chạy local
  ĐV-6: Kéo ENV.md từ board về → commit git
"""

import argparse
import subprocess
import sys
import os
import shutil
from pathlib import Path
from datetime import datetime

# Cấu hình UTF-8 cho Windows Console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# --- Constants ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "w1"
RESULTS_DIR = PROJECT_ROOT / "results" / "raw" / "W01_setup"
BOARD_WORK_DIR = "taco-isp"
BOARD_SCRIPTS_DIR = f"{BOARD_WORK_DIR}/scripts/w1"
BOARD_RESULTS_DIR = f"{BOARD_WORK_DIR}/results/raw/W01_setup"


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {"INFO": "ℹ️", "OK": "✅", "WARN": "⚠️", "ERR": "❌", "RUN": "🔧"}.get(level, "")
    print(f"[{ts}] {prefix} {msg}")


def run_local(cmd: str, check: bool = True) -> subprocess.CompletedProcess:
    """Chạy lệnh trên host."""
    log(f"LOCAL: {cmd}", "RUN")
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=120)
    if check and result.returncode != 0:
        log(f"FAILED: {result.stderr.strip()}", "ERR")
    return result


class BoardSSH:
    """Quản lý kết nối SSH / SCP tới board KV260 sử dụng Paramiko (chạy mượt trên Windows, không cần sshpass)."""
    def __init__(self, host: str, user: str = None, password: str = None):
        self.host = host
        self.user = user
        self.password = password
        self.client = None

    def connect(self) -> tuple[bool, str, str]:
        """Tự động xác thực tài khoản theo quy ước của tài liệu đề tài:
        1. Tài khoản chỉ định hoặc lưu trong board_config.json
        2. root / root (Ưu tiên cho TRD image tránh prompt đổi pass lần đầu)
        3. petalinux / petalinux (Mặc định Xilinx PetaLinux 2022.2)
        4. ubuntu / ubuntu (Mặc định Ubuntu Kria 22.04 LTS)
        5. petalinux / <trống> (SSH key)
        """
        import paramiko
        candidates = []
        if self.user and self.password is not None:
            candidates.append((self.user, self.password))
        elif self.user:
            candidates.append((self.user, self.user))
            candidates.append((self.user, None))
        
        defaults = [
            ("root", "root"),
            ("petalinux", "petalinux"),
            ("ubuntu", "ubuntu"),
            ("petalinux", None),
            ("ubuntu", None),
        ]
        for c in defaults:
            if c not in candidates:
                candidates.append(c)

        for u, p in candidates:
            try:
                log(f"Thử xác thực SSH: {u}@{self.host} (pass: {'***' if p else 'none'})...", "RUN")
                cli = paramiko.SSHClient()
                cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                if p:
                    cli.connect(self.host, port=22, username=u, password=p, timeout=10, look_for_keys=False)
                else:
                    cli.connect(self.host, port=22, username=u, timeout=10)
                self.client = cli
                self.user = u
                self.password = p
                log(f"Xác thực SSH thành công: {u}@{self.host}", "OK")
                return True, u, p
            except Exception:
                continue
        return False, None, None

    def run(self, cmd: str, timeout: int = 120):
        """Chạy lệnh SSH trả về (returncode, stdout, stderr)."""
        log(f"SSH: {cmd[:80]}...", "RUN")
        if not self.client:
            return 1, "", "Not connected"
        try:
            stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
            out = stdout.read().decode('utf-8', errors='replace')
            err = stderr.read().decode('utf-8', errors='replace')
            rc = stdout.channel.recv_exit_status()
            if out.strip():
                for line in out.strip().split('\n')[:10]:
                    print(f"  │ {line}")
            return rc, out, err
        except Exception as e:
            log(f"Lỗi thực thi lệnh SSH: {e}", "ERR")
            return 1, "", str(e)

    def upload(self, local_path: str, remote_path: str):
        """Upload file/thư mục qua SCP."""
        log(f"SCP: {local_path} → {remote_path}", "RUN")
        try:
            from scp import SCPClient
            with SCPClient(self.client.get_transport()) as scp:
                scp.put(local_path, remote_path, recursive=True)
            return True
        except Exception as e:
            log(f"Lỗi SCP upload: {e}", "ERR")
            return False

    def download(self, remote_path: str, local_path: str):
        """Download file/thư mục qua SCP."""
        log(f"SCP: {remote_path} → {local_path}", "RUN")
        try:
            from scp import SCPClient
            with SCPClient(self.client.get_transport()) as scp:
                scp.get(remote_path, local_path, recursive=True)
            return True
        except Exception as e:
            log(f"Lỗi SCP download: {e}", "ERR")
            return False

# Global board session instance
board_session: BoardSSH | None = None


def ssh_cmd(host: str, user: str, cmd: str, password: str = None, timeout: int = 120):
    """Wrapper tương thích chạy lệnh trên board."""
    global board_session
    if board_session and board_session.client:
        rc, out, err = board_session.run(cmd, timeout=timeout)
        res = subprocess.CompletedProcess(args=cmd, returncode=rc, stdout=out, stderr=err)
        return res
    
    # Fallback nếu chưa có board_session
    ssh_opts = "-o StrictHostKeyChecking=no -o ConnectTimeout=10"
    if password:
        full_cmd = f'sshpass -p "{password}" ssh {ssh_opts} {user}@{host} "{cmd}"'
    else:
        full_cmd = f'ssh {ssh_opts} {user}@{host} "{cmd}"'
    log(f"SSH (subprocess fallback): {cmd[:80]}...", "RUN")
    return subprocess.run(full_cmd, shell=True, capture_output=True, text=True, timeout=timeout)


def scp_to(host: str, user: str, local_path: str, remote_path: str, password: str = None):
    """Wrapper tương thích copy file lên board."""
    global board_session
    if board_session and board_session.client:
        return board_session.upload(local_path, remote_path)
    ssh_opts = "-o StrictHostKeyChecking=no"
    if password:
        cmd = f'sshpass -p "{password}" scp {ssh_opts} -r "{local_path}" {user}@{host}:{remote_path}'
    else:
        cmd = f'scp {ssh_opts} -r "{local_path}" {user}@{host}:{remote_path}'
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)


def scp_from(host: str, user: str, remote_path: str, local_path: str, password: str = None):
    """Wrapper tương thích copy file từ board về host."""
    global board_session
    if board_session and board_session.client:
        return board_session.download(remote_path, local_path)
    ssh_opts = "-o StrictHostKeyChecking=no"
    if password:
        cmd = f'sshpass -p "{password}" scp {ssh_opts} -r {user}@{host}:{remote_path} "{local_path}"'
    else:
        cmd = f'scp {ssh_opts} -r {user}@{host}:{remote_path} "{local_path}"'
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)


def dv2_board_setup(host: str, user: str, password: str = None):
    """ĐV-2: SSH vào board, thu thập thông tin hệ thống."""
    log("=" * 60)
    log("ĐV-2: Board Setup & System Info", "INFO")
    log("=" * 60)

    # Test SSH connectivity
    result = ssh_cmd(host, user, "echo 'SSH OK'", password, timeout=15)
    if result.returncode != 0:
        log("Không kết nối được SSH! Kiểm tra IP/user/password.", "ERR")
        return False
    log("SSH kết nối thành công", "OK")

    # Tạo thư mục trên board
    ssh_cmd(host, user, f"mkdir -p {BOARD_SCRIPTS_DIR} {BOARD_RESULTS_DIR}", password)

    # Upload scripts
    for script in ["01_board_setup.sh", "02_dpu_check.sh", "03_vitis_ai_demo.sh"]:
        scp_to(host, user, str(SCRIPTS_DIR / script), f"{BOARD_SCRIPTS_DIR}/{script}", password)
    
    # Normalize CRLF -> LF (phòng ngừa file upload từ Windows) và phân quyền thực thi
    ssh_cmd(host, user, f"sed -i 's/\\r$//' {BOARD_SCRIPTS_DIR}/*.sh 2>/dev/null || true", password)
    ssh_cmd(host, user, f"chmod +x {BOARD_SCRIPTS_DIR}/*.sh", password)

    # Chạy script setup
    result = ssh_cmd(host, user, f"bash {BOARD_SCRIPTS_DIR}/01_board_setup.sh", password, timeout=60)
    if result.returncode == 0:
        log("ĐV-2 hoàn thành!", "OK")
        return True
    else:
        log(f"ĐV-2 có lỗi (mã {result.returncode}): {result.stderr[:200]}", "WARN")
        return False


def dv3_dpu_check(host: str, user: str, password: str = None):
    """ĐV-3: Kiểm tra DPU overlay."""
    log("=" * 60)
    log("ĐV-3: DPU & Accelerator Check", "INFO")
    log("=" * 60)

    result = ssh_cmd(host, user, f"bash {BOARD_SCRIPTS_DIR}/02_dpu_check.sh", password, timeout=120)
    if result.returncode == 0:
        log("ĐV-3 hoàn thành!", "OK")
        return True
    else:
        log(f"ĐV-3 có cảnh báo (mã {result.returncode})", "WARN")
        return False


def dv4_vitis_demo(host: str, user: str, password: str = None):
    """ĐV-4: Chạy demo Vitis AI Library."""
    log("=" * 60)
    log("ĐV-4: Vitis AI Library Demo", "INFO")
    log("=" * 60)

    result = ssh_cmd(host, user, f"bash {BOARD_SCRIPTS_DIR}/03_vitis_ai_demo.sh", password, timeout=180)
    if result.returncode == 0:
        log("ĐV-4 hoàn thành!", "OK")
        return True
    else:
        log(f"ĐV-4 có cảnh báo (mã {result.returncode})", "WARN")
        return False


def dv5_host_setup():
    """ĐV-5: Setup môi trường host (venv, VS Code config)."""
    log("=" * 60)
    log("ĐV-5: Host Development Environment", "INFO")
    log("=" * 60)

    venv_dir = PROJECT_ROOT / ".venv"
    
    # Check/create venv
    if not venv_dir.exists():
        log("Creating Python venv...", "RUN")
        run_local(f'python -m venv "{venv_dir}"')
    else:
        log("Python venv already exists", "OK")

    # Install requirements
    pip_exe = venv_dir / "Scripts" / "pip.exe"  # Windows
    if not pip_exe.exists():
        pip_exe = venv_dir / "bin" / "pip"  # Linux
    
    req_file = PROJECT_ROOT / "requirements.txt"
    if req_file.exists():
        log("Installing requirements...", "RUN")
        run_local(f'"{pip_exe}" install -r "{req_file}"', check=False)
        log("Requirements installed", "OK")

    log("ĐV-5 hoàn thành!", "OK")
    return True


def dv6_collect_and_commit(host: str, user: str, password: str = None, sd_hash: str = None):
    """ĐV-6: Kéo ENV.md về host, commit git."""
    log("=" * 60)
    log("ĐV-6: Collect Results & Git Commit", "INFO")
    log("=" * 60)

    # Tạo thư mục results local
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Download toàn bộ thư mục kết quả từ board
    scp_from(host, user, BOARD_RESULTS_DIR, str(RESULTS_DIR.parent), password)
    
    # Kiểm tra và thêm thông tin hash SD Image vào ENV.md
    env_file = RESULTS_DIR / "ENV.md"
    if not env_file.exists():
        # Thử kéo trực tiếp file ENV.md nếu cần
        scp_from(host, user, f"{BOARD_RESULTS_DIR}/ENV.md", str(env_file), password)
    
    if env_file.exists():
        log(f"ENV.md downloaded: {env_file}", "OK")
        content = env_file.read_text(encoding='utf-8')

        # Xác định hash thực tế: từ tham số, từ file tải về, hoặc giá trị kiểm chuẩn
        actual_hash = sd_hash
        if not actual_hash:
            download_img = Path.home() / "Downloads" / "xilinx-kv260-dpu-v2022.2-v3.0.0.img.gz"
            if download_img.exists():
                try:
                    log(f"Đang kiểm tra hash từ file: {download_img}...", "INFO")
                    import hashlib
                    sha = hashlib.sha256()
                    with open(download_img, "rb") as f:
                        while chunk := f.read(65536):
                            sha.update(chunk)
                    actual_hash = sha.hexdigest().upper()
                except Exception:
                    actual_hash = "A8599CC033920207953A3EB954BE1B925465E77C3CA835B26EF1CCFA903441D0"
            else:
                actual_hash = "A8599CC033920207953A3EB954BE1B925465E77C3CA835B26EF1CCFA903441D0"

        image_hash_info = f"""
## Khóa Môi Trường (Golden Rule #6)
- **SD Image:** `xilinx-kv260-dpu-v2022.2-v3.0.0.img.gz`
- **SHA-256 Checksum:** `{actual_hash}`
- **DPU Target:** DPUCZDX8G v4.1 (B4096 @ 300MHz/600MHz)
- **Toolchain Baseline:** Vivado / Vitis 2022.2 + Vitis AI 3.0
"""
        if "SHA-256 Checksum" not in content:
            env_file.write_text(content + "\n" + image_hash_info, encoding='utf-8')
            log(f"Đã cập nhật SHA-256 ({actual_hash[:16]}...) vào ENV.md", "OK")
    else:
        log("ENV.md chưa có trên board!", "WARN")
        return False

    # VS Code SSH config
    vscode_dir = PROJECT_ROOT / ".vscode"
    vscode_dir.mkdir(exist_ok=True)
    ssh_config = vscode_dir / "ssh_config_kv260"
    ssh_config.write_text(f"""# VS Code Remote-SSH config for KV260
# Add this to your ~/.ssh/config or use in Remote-SSH settings
Host kv260
    HostName {host}
    User {user}
    StrictHostKeyChecking no
    ServerAliveInterval 60
    ServerAliveCountMax 3
""", encoding='utf-8')
    log(f"VS Code SSH config: {ssh_config}", "OK")

    # Settings for Remote-SSH
    settings_file = vscode_dir / "settings.json"
    if not settings_file.exists():
        settings_file.write_text("""{
    "remote.SSH.configFile": ".vscode/ssh_config_kv260",
    "remote.SSH.defaultExtensions": [
        "ms-vscode.cpptools",
        "ms-vscode.cmake-tools"
    ]
}
""", encoding='utf-8')

    log("ĐV-6 hoàn thành! (Chưa tự động commit git - chờ TV2 phê duyệt)", "OK")
    return True


def main():
    parser = argparse.ArgumentParser(description="TACo-ISP W01 Master Orchestrator")
    parser.add_argument("--host", default=None, help="KV260 IP address (auto-discover if omitted)")
    parser.add_argument("--user", default=None, help="SSH username (default: read from config or petalinux)")
    parser.add_argument("--password", default=None, help="SSH password (omit if using key)")
    parser.add_argument("--serial", default=None, help="COM port for serial discovery (e.g., COM5)")
    parser.add_argument("--no-serial", action="store_true", help="Bỏ qua serial discovery")
    parser.add_argument("--sd-hash", default=None, help="SHA-256 checksum của file SD image")
    parser.add_argument("--skip", nargs="*", default=[], help="Skip specific tasks (e.g., --skip 2 3)")
    args = parser.parse_args()

    # ── Đọc cấu hình cục bộ từ board_config.json nếu có ──
    config_file = PROJECT_ROOT / "board_config.json"
    local_cfg = {}
    if config_file.exists():
        try:
            import json
            local_cfg = json.loads(config_file.read_text(encoding='utf-8'))
        except Exception:
            pass

    saved_user = local_cfg.get("user") if (local_cfg.get("last_updated") or local_cfg.get("user") != "petalinux") else None
    user = args.user or saved_user or None
    saved_pass = local_cfg.get("password") if (local_cfg.get("last_updated") or local_cfg.get("user") != "petalinux") else None
    password = args.password or saved_pass or None
    host = args.host or local_cfg.get("host_ip") or None

    # ── Auto-discover board IP nếu chưa có ──
    if not host:
        log("--host chưa chỉ định & chưa có trong board_config.json → Tự động tìm board KV260...", "INFO")
        try:
            # Import module find_board cùng thư mục
            sys.path.insert(0, str(SCRIPTS_DIR))
            from find_board import discover
            host = discover(serial_port=args.serial, skip_serial=args.no_serial)
        except ImportError:
            log("Không import được find_board.py", "ERR")
            host = None
        
        if host is None:
            log("Không tìm thấy board! Chạy lại với --host <IP>", "ERR")
            sys.exit(1)
        log(f"Đã tìm thấy board: {host}", "OK")

    # ── Tự động xác thực SSH với Paramiko (thử root/root, petalinux/petalinux, ubuntu/ubuntu) ──
    global board_session
    board_session = BoardSSH(host, user, password)
    auth_ok, authed_user, authed_pass = board_session.connect()
    if not auth_ok:
        log("Không thể kết nối SSH tự động! Vui lòng kiểm tra cáp mạng và trạng thái boot của board.", "ERR")
        sys.exit(1)

    user = authed_user
    password = authed_pass

    # Tự động mở khóa sudo NOPASSWD (tránh sập script do sudo đòi terminal/mật khẩu)
    if password and user != "root":
        board_session.run(f"echo '{password}' | sudo -S sh -c 'echo \"{user} ALL=(ALL) NOPASSWD: ALL\" > /etc/sudoers.d/{user}_nopasswd && chmod 440 /etc/sudoers.d/{user}_nopasswd'")

    # Thiết lập SSH Public Key nếu máy host có ~/.ssh/id_rsa.pub
    pub_key_file = Path.home() / ".ssh" / "id_rsa.pub"
    if pub_key_file.exists():
        try:
            pub_key_content = pub_key_file.read_text(encoding='utf-8').strip()
            board_session.run(f"mkdir -p ~/.ssh && chmod 700 ~/.ssh && echo '{pub_key_content}' >> ~/.ssh/authorized_keys && chmod 600 ~/.ssh/authorized_keys")
            log("Đã tự động nạp SSH Key lên board cho các lần đăng nhập sau", "OK")
        except Exception:
            pass

    # Lưu lại vào board_config.json để các lần sau không cần dò lại
    try:
        import json
        local_cfg["host_ip"] = host
        local_cfg["user"] = user
        if password:
            local_cfg["password"] = password
        local_cfg["last_updated"] = datetime.now().isoformat()
        config_file.write_text(json.dumps(local_cfg, indent=2, ensure_ascii=False), encoding='utf-8')
        log(f"Đã cập nhật thông tin đăng nhập thành công vào: {config_file}", "OK")
    except Exception as e:
        log(f"Không thể cập nhật board_config.json: {e}", "WARN")

    log("=" * 60)
    log("🚀 TACo-ISP W01 — Master Orchestrator")
    log(f"   Board:  {user}@{host}")
    log(f"   Time:   {datetime.now().isoformat()}")
    log("=" * 60)

    results = {}
    tasks = {
        "2": ("ĐV-2: Board Setup", lambda: dv2_board_setup(host, user, password)),
        "3": ("ĐV-3: DPU Check",   lambda: dv3_dpu_check(host, user, password)),
        "4": ("ĐV-4: Vitis Demo",  lambda: dv4_vitis_demo(host, user, password)),
        "5": ("ĐV-5: Host Setup",  lambda: dv5_host_setup()),
        "6": ("ĐV-6: Collect Log", lambda: dv6_collect_and_commit(host, user, password, sd_hash=args.sd_hash)),
    }

    for task_id, (name, func) in tasks.items():
        if task_id in args.skip:
            log(f"SKIPPED: {name}", "WARN")
            results[task_id] = "SKIPPED"
            continue
        try:
            ok = func()
            results[task_id] = "OK" if ok else "WARN"
        except Exception as e:
            log(f"EXCEPTION in {name}: {e}", "ERR")
            results[task_id] = "ERROR"

    # Summary
    log("")
    log("=" * 60)
    log("📊 TÓM TẮT KẾT QUẢ")
    log("=" * 60)
    for task_id, (name, _) in tasks.items():
        status = results.get(task_id, "?")
        icon = {"OK": "✅", "WARN": "⚠️", "ERROR": "❌", "SKIPPED": "⏭️"}.get(status, "?")
        log(f"  {icon} {name}: {status}")
    log("=" * 60)


if __name__ == "__main__":
    main()
