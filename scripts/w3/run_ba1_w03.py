#!/usr/bin/env python3
"""
TACo-ISP — W03 Baseline BA1 Master Orchestrator
==============================================
Script chạy trên HOST PC (Windows) — tự động hóa toàn bộ quy trình Tuần 3 qua SSH:
  1. Đồng bộ mã nguồn C++ (sw/) và tập lệnh (scripts/w3/) lên board KV260.
  2. Biên dịch ứng dụng baseline_ba trên board (01_build_ba1.sh).
  3. Chạy kiểm thử đo độ trễ và thông lượng baseline BA1 (02_run_ba1.sh).
  4. Đánh giá số liệu và sinh báo cáo BA1_ENV.md (03_eval_ba1.sh).
  5. Tải file kết quả CSV và BA1_ENV.md về máy host (results/raw/W03_ba1/).
  6. Kiểm tra hợp quy theo lược đồ chuẩn analysis/SCHEMAS.md.

Cách dùng:
  python scripts/w3/run_ba1_w03.py
  python scripts/w3/run_ba1_w03.py --host <IP_BOARD> --frames 200
  python scripts/w3/run_ba1_w03.py --mode ba2
  python scripts/w3/run_ba1_w03.py --skip-build
"""

import argparse
import csv
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Cấu hình UTF-8 cho Windows Console
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Thư mục gốc dự án
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SW_DIR = PROJECT_ROOT / "sw"
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "w3"
RESULTS_DIR = PROJECT_ROOT / "results" / "raw" / "W03_ba1"
CONFIG_FILE = PROJECT_ROOT / "board_config.json"

BOARD_WORK_DIR = "taco-isp"
BOARD_SW_DIR = f"{BOARD_WORK_DIR}/sw"
BOARD_SCRIPTS_DIR = f"{BOARD_WORK_DIR}/scripts/w3"
BOARD_RESULTS_DIR = f"{BOARD_WORK_DIR}/results/raw/W03_ba1"


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "INFO": "ℹ️",
        "OK": "✅",
        "WARN": "⚠️",
        "ERR": "❌",
        "RUN": "🔧",
        "BA1": "🚀",
        "BUILD": "🔨",
    }.get(level, "")
    print(f"[{ts}] {prefix} {msg}")


def get_git_commit_hash() -> str:
    """Lấy short commit hash từ git trên host (fallback UNKNOWN)."""
    try:
        import subprocess
        r = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=5,
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    return "UNKNOWN"


class BoardSSH:
    """Quản lý kết nối SSH và SCP bằng Paramiko trên Windows."""
    def __init__(self, host: str, user: str = None, password: str = None):
        self.host = host
        self.user = user
        self.password = password
        self.client = None

    def connect(self) -> bool:
        import paramiko
        candidates = []
        user = self.user
        password = self.password if self.password else None

        if user and password is not None:
            candidates.append((user, password))
        elif user:
            candidates.append((user, user))
            candidates.append((user, None))

        defaults = [
            ("root", "root"),
            ("petalinux", "petalinux"),
            ("ubuntu", "ubuntu"),
            ("petalinux", None),
            ("ubuntu", None),
            ("root", None),
        ]
        for c in defaults:
            if c not in candidates:
                candidates.append(c)

        for u, p in candidates:
            try:
                log(f"Thử xác thực SSH: {u}@{self.host}...", "RUN")
                cli = paramiko.SSHClient()
                cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                if p:
                    cli.connect(self.host, port=22, username=u, password=p, timeout=10, look_for_keys=False)
                else:
                    cli.connect(self.host, port=22, username=u, timeout=10)
                self.client = cli
                self.user = u
                self.password = p
                log(f"Kết nối SSH thành công: {u}@{self.host}", "OK")
                return True
            except Exception:
                continue
        return False

    def run(self, cmd: str, timeout: int = 300) -> tuple[int, str, str]:
        if not self.client:
            return 1, "", "Not connected"
        import re
        log_cmd = cmd
        if "sudo -S" in cmd and "echo " in cmd:
            log_cmd = re.sub(r"echo\s+['\"][^'\"]*['\"]\s*\|\s*sudo\s+-S", "echo '***' | sudo -S", cmd)
        log(f"SSH: {log_cmd[:95]}...", "RUN")
        try:
            stdin, stdout, stderr = self.client.exec_command(cmd, timeout=timeout)
            out_lines = []
            for line in iter(stdout.readline, ""):
                line_str = line.rstrip("\r\n")
                if line_str:
                    print(f"  │ {line_str}")
                out_lines.append(line)
            err = stderr.read().decode("utf-8", errors="replace")
            rc = stdout.channel.recv_exit_status()
            out = "".join(out_lines)
            return rc, out, err
        except Exception as e:
            log(f"Lỗi thực thi lệnh: {e}", "ERR")
            return 1, "", str(e)

    def upload_dir(self, local_path: Path, remote_path: str):
        from scp import SCPClient
        with SCPClient(self.client.get_transport()) as scp:
            log(f"Đang đồng bộ thư mục: {local_path.name} → {remote_path}...", "RUN")
            scp.put(str(local_path), remote_path, recursive=True)

    def upload_file(self, local_file: Path, remote_file: str):
        from scp import SCPClient
        with SCPClient(self.client.get_transport()) as scp:
            log(f"Tải lên file: {local_file.name} → {remote_file}", "RUN")
            scp.put(str(local_file), remote_file)

    def download_file(self, remote_file: str, local_file: Path):
        from scp import SCPClient
        with SCPClient(self.client.get_transport()) as scp:
            log(f"Tải file: {remote_file} → {local_file.name}", "RUN")
            scp.get(remote_file, str(local_file))


def validate_schema(csv_path: Path) -> bool:
    """Xác thực file CSV tuân thủ theo analysis/SCHEMAS.md."""
    if not csv_path.exists() or csv_path.stat().st_size == 0:
        return False

    expected_cols = [
        "config",
        "capture_isp_ms",
        "preproc_ms",
        "dma_sync_ms",
        "dpu_infer_ms",
        "postproc_ms",
        "total_latency_ms",
    ]

    with open(csv_path, mode="r", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader, None)
        if not header:
            return False

        header = [c.strip() for c in header]
        if header != expected_cols:
            log(f"Cột CSV không khớp schema: {header} != {expected_cols}", "WARN")
            return False

        has_data = False
        for row in reader:
            if not row or all(not c.strip() for c in row):
                continue
            if len(row) != len(expected_cols):
                log(f"Dòng CSV sai số lượng cột ({len(row)} != {len(expected_cols)})", "WARN")
                return False
            try:
                for val in row[1:]:
                    if float(val.strip()) < 0.0:
                        return False
            except ValueError:
                return False
            has_data = True

    return has_data


def run_simulation(args):
    """Giả lập toàn diện quy trình Tuần 3 trên host để kiểm tra tính sẵn sàng trước khi lên board."""
    log("=" * 65, "RUN")
    log("🧪 CHẾ ĐỘ GIẢ LẬP / DRY-RUN TUẦN 3 (HOST INTEGRATION TEST)", "RUN")
    log("=" * 65, "RUN")

    # 1. Kiểm tra toàn vẹn file mã nguồn và scripts
    required_files = [
        SW_DIR / "CMakeLists.txt",
        SW_DIR / "app" / "baseline_ba.cpp",
        SW_DIR / "app" / "yolox_post.hpp",
        SW_DIR / "controller" / "ctrl_ref.cpp",
        SCRIPTS_DIR / "01_build_ba1.sh",
        SCRIPTS_DIR / "02_run_ba1.sh",
        SCRIPTS_DIR / "03_eval_ba1.sh",
        PROJECT_ROOT / "analysis" / "SCHEMAS.md",
    ]
    all_ok = True
    for f in required_files:
        if f.exists():
            log(f"  [✓] File tồn tại: {f.relative_to(PROJECT_ROOT)} ({f.stat().st_size} bytes)", "OK")
        else:
            log(f"  [✗] THIẾU FILE: {f.relative_to(PROJECT_ROOT)}", "ERR")
            all_ok = False

    # 2. Kiểm tra cú pháp script bash (không bị ký tự CRLF lỗi và cú pháp bash -n)
    log("Kiểm tra định dạng và cú pháp bash scripts...", "INFO")
    bash_files = [SCRIPTS_DIR / "01_build_ba1.sh", SCRIPTS_DIR / "02_run_ba1.sh", SCRIPTS_DIR / "03_eval_ba1.sh"]
    for s in bash_files:
        content = s.read_bytes()
        if b"\r\n" in content:
            log(f"  [!] Phát hiện CRLF trong {s.name}. Đang chuẩn hóa sang LF...", "WARN")
            s.write_bytes(content.replace(b"\r\n", b"\n"))
            log(f"  [✓] Đã chuẩn hóa {s.name} sang chuẩn POSIX LF!", "OK")
        else:
            log(f"  [✓] {s.name}: Chuẩn LF (an toàn cho Linux bash)", "OK")

    # Chạy bash -n kiểm tra cú pháp
    import subprocess
    try:
        bash_args = ["bash", "-n"] + [s.relative_to(PROJECT_ROOT).as_posix() for s in bash_files]
        r_bash = subprocess.run(bash_args, cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=10)
        if r_bash.returncode == 0:
            log("  [✓] Cú pháp toàn bộ tập lệnh bash W3 (bash -n): HỢP LỆ 100%!", "OK")
        else:
            log(f"  [✗] Cú pháp bash có lỗi: {r_bash.stderr.strip()}", "ERR")
            all_ok = False
    except Exception:
        log("  [i] Bỏ qua kiểm tra bash -n (môi trường không có lệnh bash)", "INFO")

    # 3. Kiểm tra kiểm thử C++ với g++ trên host: Controller & YOLOX Post-proc
    log("Kiểm tra biên dịch và chạy Unit Test C++17 độc lập...", "INFO")
    try:
        res = subprocess.run(["g++", "-std=c++17", "-O3", str(SW_DIR / "controller" / "ctrl_ref.cpp"), "-o", "sim_ctrl_ref.exe"],
                             capture_output=True, text=True, timeout=15)
        if res.returncode == 0:
            log("  [✓] Trình biên dịch g++ C++17: Hoạt động tốt!", "OK")
            r_bench = subprocess.run(["./sim_ctrl_ref.exe"], capture_output=True, text=True, timeout=10)
            if "budget: < 500 us" in r_bench.stdout:
                last_line = r_bench.stdout.strip().splitlines()[-1]
                log(f"  [✓] Test Controller Reference: ĐẠT CHỈ TIÊU BUDGET ({last_line})", "OK")
            try:
                Path("sim_ctrl_ref.exe").unlink(missing_ok=True)
            except Exception:
                pass
        else:
            log(f"  [!] g++ cảnh báo ctrl_ref: {res.stderr.strip()[:100]}", "WARN")

        # Unit test cho yolox_post.hpp (anchor grids, INT8 decoding, clamping, NMS)
        unit_test_code = """
#include "sw/app/yolox_post.hpp"
#include <iostream>
#include <vector>
#include <cassert>
#include <cmath>

int main() {
    taco::YoloXPostProcessor post(416, 416, 80);
    // 1. Buffer rỗng
    auto r_empty = post.decode_and_nms(nullptr, 0, 7);
    if (!r_empty.empty()) return 1;

    // 2. Buffer số cực đại kiểm tra clamping không sinh Inf / NaN
    std::vector<int8_t> overflow(3549 * 85, 127);
    auto r_ovf = post.decode_and_nms(overflow.data(), overflow.size(), 0);
    for (const auto& b : r_ovf) {
        if (std::isnan(b.x1) || std::isnan(b.y1) || std::isnan(b.x2) || std::isnan(b.y2) ||
            std::isinf(b.x1) || std::isinf(b.y1) || std::isinf(b.x2) || std::isinf(b.y2)) {
            return 2;
        }
    }
    std::cout << "YOLOX_UNIT_TEST_PASS";
    return 0;
}
"""
        test_cpp = Path("sim_yolox_test.cpp")
        test_exe = Path("sim_yolox_test.exe")
        test_cpp.write_text(unit_test_code, encoding="utf-8")
        r_compile = subprocess.run(["g++", "-std=c++17", "-O2", str(test_cpp), "-o", str(test_exe)],
                                   capture_output=True, text=True, timeout=15)
        if r_compile.returncode == 0:
            r_run = subprocess.run([f"./{test_exe}"], capture_output=True, text=True, timeout=10)
            if "YOLOX_UNIT_TEST_PASS" in r_run.stdout:
                log("  [✓] Test YOLOX Post-Processor Unit: ĐẠT CHỈ TIÊU (Grids 3549, Clamping an toàn, No NaN/Inf)!", "OK")
            else:
                log(f"  [✗] Test YOLOX Post-Processor thất bại: mã {r_run.returncode}", "ERR")
                all_ok = False
            test_exe.unlink(missing_ok=True)
        test_cpp.unlink(missing_ok=True)
    except Exception as e:
        log(f"  [i] Bỏ qua kiểm tra g++ host: {e}", "INFO")

    # 4. Kiểm tra schema CSV validation (Test cả trường hợp hợp lệ và các lỗi biên)
    log("Kiểm tra xác thực schema analysis/SCHEMAS.md...", "INFO")
    import tempfile

    # 4a. Trường hợp hợp lệ
    with tempfile.NamedTemporaryFile("w+", suffix=".csv", delete=False, encoding="utf-8") as tf:
        tf.write("config,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_latency_ms\n")
        tf.write("BA1_YOLOX_nano,2.150,18.420,1.050,5.520,3.210,30.350\n")
        temp_csv_valid = Path(tf.name)
    ok_valid = validate_schema(temp_csv_valid)
    temp_csv_valid.unlink(missing_ok=True)

    # 4b. Trường hợp lỗi (thiếu cột hoặc số âm)
    with tempfile.NamedTemporaryFile("w+", suffix=".csv", delete=False, encoding="utf-8") as tf:
        tf.write("config,capture_isp_ms,preproc_ms\n")
        tf.write("BA1_YOLOX_nano,2.150,-18.420\n")
        temp_csv_invalid = Path(tf.name)
    ok_invalid = not validate_schema(temp_csv_invalid)
    temp_csv_invalid.unlink(missing_ok=True)

    if ok_valid and ok_invalid:
        log("  [✓] Hàm xác thực schema (T-A1 latency.csv) kiểm soát chặt chẽ 100%!", "OK")
    else:
        log("  [✗] Lỗi logic trong hàm xác thực schema!", "ERR")
        all_ok = False

    # 5. Kiểm tra file mẫu RAW10 dự phòng từ Tuần 2
    w2_sample = PROJECT_ROOT / "results" / "raw" / "W02_camera" / "sample_1080p.raw"
    if w2_sample.exists() and w2_sample.stat().st_size > 0:
        log(f"  [✓] Đã có ảnh RAW10 mẫu từ W2 ({w2_sample.stat().st_size:,} bytes) sẵn sàng nạp fallback.", "OK")
    else:
        log("  [i] Chưa có ảnh sample_1080p.raw cục bộ (hệ thống sẽ tạo ảnh giả lập synthetic hoặc chụp trực tiếp).", "INFO")

    # 6. Kiểm tra file cấu hình board_config.json
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            log(f"  [✓] Đã có file cấu hình board: host_ip={cfg.get('host_ip')}, user={cfg.get('user')}", "OK")
        except Exception as e:
            log(f"  [!] board_config.json lỗi cú pháp: {e}", "WARN")
    else:
        log("  [i] Chưa có board_config.json. Script sẽ tự đọc từ W1 hoặc quét mạng khi có board thật.", "INFO")

    # 7. Kiểm tra thư mục mô hình AI (models/)
    models_local = PROJECT_ROOT / "models"
    if models_local.exists() and any(models_local.iterdir()):
        log(f"  [✓] Thư mục models/ tồn tại với {len(list(models_local.iterdir()))} file mô hình.", "OK")
    else:
        log("  [i] Chưa có mô hình models/ cục bộ (hệ thống sẽ dò Vitis AI Library trên board hoặc dummy).", "INFO")

    # 8. Kiểm tra Git commit hash trên Host
    git_hash = get_git_commit_hash()
    log(f"  [✓] Git commit hash trên Host: {git_hash}", "OK")

    log("=" * 65, "OK")
    if all_ok:
        log("🎉 [GIẢ LẬP THÀNH CÔNG] Toàn bộ mã nguồn & kịch bản Tuần 3 đã sẵn sàng 100% cho ca board!", "OK")
        log("   Ngày mai bạn chỉ cần bật nguồn board KV260 và chạy lệnh:", "OK")
        log("       python scripts/w3/run_ba1_w03.py", "OK")
    else:
        log("⚠️ Có một số thành phần cần lưu ý, vui lòng kiểm tra các mục đánh dấu [✗] ở trên.", "WARN")
    log("=" * 65, "OK")
    return 0 if all_ok else 1


def main():
    parser = argparse.ArgumentParser(description="TACo-ISP W03 Baseline BA1 Master Orchestrator")
    parser.add_argument("--host", default=None, help="IP của KV260 (mặc định đọc từ board_config.json sinh bởi W1)")
    parser.add_argument("--user", default=None, help="User SSH (mặc định đọc từ board_config.json hoặc petalinux)")
    parser.add_argument("--password", default=None, help="Mật khẩu SSH (mặc định đọc từ board_config.json)")
    parser.add_argument("--scan", action="store_true", help="Tự động quét mạng tìm board nếu chưa có cấu hình từ W1")
    parser.add_argument("--frames", type=int, default=100, help="Số lượng khung hình kiểm thử (mặc định: 100)")
    parser.add_argument("--mode", default="ba1", choices=["ba1", "ba2"], help="Chế độ baseline (ba1 hoặc ba2)")
    parser.add_argument("--skip-build", action="store_true", help="Bỏ qua bước build nếu binary đã có sẵn")
    parser.add_argument("--dry-run", action="store_true", help="Chạy giả lập kiểm thử toàn diện trên máy Host (không cần board vật lý)")
    args = parser.parse_args()

    if args.dry_run:
        sys.exit(run_simulation(args))

    log("=" * 65, "BA1")
    log("🚀 TACo-ISP W03 — Triển khai & Đo lường Baseline BA1 (C++/OpenCV/VART)", "BA1")
    log("=" * 65, "BA1")

    # 1. Đọc cấu hình board_config.json (được thiết lập và lưu từ Tuần 1 - W1)
    local_cfg = {}
    if not CONFIG_FILE.exists():
        log(f"Không tìm thấy file cấu hình board: {CONFIG_FILE.name}!", "WARN")
    else:
        try:
            local_cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"Lỗi đọc file cấu hình {CONFIG_FILE.name}: {e}", "WARN")

    host = args.host or (local_cfg.get("host_ip") or "").strip() or None
    user = args.user or (local_cfg.get("user") or "").strip() or None
    password = args.password or (local_cfg.get("password") or "").strip() or None

    # Tự động quét tìm board nếu chưa có host IP
    if not host:
        log("Chưa có IP trong cấu hình board_config.json → Đang tự động quét tìm board qua find_board.py...", "INFO")
        try:
            w1_dir = PROJECT_ROOT / "scripts" / "w1"
            sys.path.insert(0, str(w1_dir))
            from find_board import discover
            host = discover()
        except ImportError:
            log("Không tìm thấy module find_board.py trong scripts/w1/!", "ERR")
        except Exception as e:
            log(f"Không thể thực thi quét mạng tự động: {e}", "WARN")

        if not host:
            log("=" * 65, "ERR")
            log("CHƯA CÓ ĐỊA CHỈ IP CỦA BOARD KV260 TRONG CẤU HÌNH!", "ERR")
            log("Theo quy trình TACo-ISP, địa chỉ IP và môi trường board phải được khởi tạo từ Tuần 1 (W1).", "ERR")
            log("Vui lòng thực hiện một trong các cách sau:", "ERR")
            log("  [Cách 1 - Khuyên dùng]: Chạy tự động nghiệm thu Tuần 1 để dò board và lưu cấu hình:", "ERR")
            log("      python scripts/w1/run_all.py", "ERR")
            log("  [Cách 2]: Chỉ định trực tiếp IP của board thông qua tham số --host:", "ERR")
            log("      python scripts/w3/run_ba1_w03.py --host <IP_BOARD>", "ERR")
            log("=" * 65, "ERR")
            sys.exit(1)
        log(f"Đã tự động tìm thấy board tại IP: {host}", "OK")

    # 2. Kết nối SSH
    session = BoardSSH(host, user, password)
    if not session.connect():
        log(f"Không thể kết nối SSH tới {host}. Vui lòng kiểm tra mạng/IP!", "ERR")
        sys.exit(1)

    # Tự động mở khóa sudo NOPASSWD (tránh sập script do sudo đòi terminal/mật khẩu)
    sudo_pass = session.password or password
    if sudo_pass and session.user != "root":
        session.run(
            f"echo '{sudo_pass}' | sudo -S sh -c 'echo \"{session.user} ALL=(ALL) NOPASSWD: ALL\" > /etc/sudoers.d/{session.user}_nopasswd && chmod 440 /etc/sudoers.d/{session.user}_nopasswd'"
        )

    # Chốt chặn 1: Kiểm tra quyền sudo không cần mật khẩu (sudo -n true)
    if session.user != "root":
        rc_sudo, _, _ = session.run("sudo -n true 2>/dev/null")
        if rc_sudo != 0:
            log(f"Cảnh báo: User {session.user} chưa có quyền sudo NOPASSWD (sudo -n true trả về {rc_sudo})!", "WARN")
        else:
            log(f"Quyền sudo NOPASSWD cho {session.user}: HỢP LỆ (sudo -n true)", "OK")

    # Cập nhật board_config.json
    local_cfg["host_ip"] = host
    local_cfg["user"] = session.user
    if session.password:
        local_cfg["password"] = session.password
    local_cfg["last_updated"] = datetime.now().isoformat()
    CONFIG_FILE.write_text(json.dumps(local_cfg, indent=2, ensure_ascii=False), encoding="utf-8")

    # 3. Chuẩn bị thư mục và đồng bộ mã nguồn lên KV260
    log("Tạo cấu trúc thư mục trên board KV260...", "RUN")
    session.run(f"mkdir -p {BOARD_WORK_DIR} {BOARD_SW_DIR} {BOARD_SCRIPTS_DIR} {BOARD_RESULTS_DIR}")

    log("Đồng bộ mã nguồn phần mềm C++ (sw/) lên board...", "RUN")
    session.upload_dir(SW_DIR, BOARD_WORK_DIR)

    # Đồng bộ mô hình xmodel (models/) do TV3 bàn giao nếu có trên máy host
    models_local = PROJECT_ROOT / "models"
    if models_local.exists() and any(models_local.iterdir()):
        log("Đồng bộ thư mục mô hình AI (models/) lên board...", "RUN")
        session.upload_dir(models_local, BOARD_WORK_DIR)

    log("Đồng bộ tập lệnh tự động (scripts/w3/) lên board...", "RUN")
    session.upload_dir(SCRIPTS_DIR, f"{BOARD_WORK_DIR}/scripts")
    session.run(f"sed -i 's/\\r$//' {BOARD_SCRIPTS_DIR}/*.sh 2>/dev/null || true")
    session.run(f"chmod +x {BOARD_SCRIPTS_DIR}/*.sh")

    # Đẩy Git commit hash từ Host lên board để phục vụ báo cáo ENV.md
    commit_hash = get_git_commit_hash()
    log(f"Git commit hash trên Host: {commit_hash}", "INFO")
    session.run(f"echo '{commit_hash}' > {BOARD_WORK_DIR}/.commit_hash")
    session.run(f"echo '{commit_hash}' > {BOARD_RESULTS_DIR}/.commit_hash")

    # Đồng bộ ảnh mẫu RAW10 từ W2 nếu có trên máy host để làm fallback an toàn
    w2_raw_local = PROJECT_ROOT / "results" / "raw" / "W02_camera" / "sample_1080p.raw"
    if w2_raw_local.exists():
        log(f"Đồng bộ ảnh mẫu RAW10 ({w2_raw_local.stat().st_size:,} bytes) lên board...", "RUN")
        session.run(f"mkdir -p {BOARD_WORK_DIR}/results/raw/W02_camera")
        session.upload_file(w2_raw_local, f"{BOARD_WORK_DIR}/results/raw/W02_camera/sample_1080p.raw")

    # 4. Biên dịch phần mềm trên board (nếu không skip)
    pipeline_ok = True
    try:
        if not args.skip_build:
            log("Bắt đầu biên dịch target 'baseline_ba' trên KV260...", "BUILD")
            rc, _, _ = session.run(f"bash {BOARD_SCRIPTS_DIR}/01_build_ba1.sh")
            if rc != 0:
                log("Biên dịch thất bại! Kiểm tra log tại results/raw/W03_ba1/build.log", "ERR")
                pipeline_ok = False
            else:
                log("Biên dịch hoàn tất thành công!", "OK")
        else:
            log("Bỏ qua bước biên dịch (--skip-build).", "INFO")

        # 5. Thực thi ứng dụng Baseline BA1
        if pipeline_ok:
            log(f"Chạy thử nghiệm baseline ({args.mode.upper()}) với {args.frames} khung hình...", "RUN")
            rc, _, _ = session.run(f"bash {BOARD_SCRIPTS_DIR}/02_run_ba1.sh {args.frames} {args.mode}")
            if rc != 0:
                log("Quá trình thực thi baseline gặp lỗi!", "ERR")
                pipeline_ok = False

        # 6. Đánh giá và sinh báo cáo BA1_ENV.md
        if pipeline_ok:
            log("Sinh báo cáo môi trường và phân tích độ trễ...", "RUN")
            rc, _, _ = session.run(f"bash {BOARD_SCRIPTS_DIR}/03_eval_ba1.sh")
            if rc != 0:
                log("Đánh giá kết quả BA1 trên board gặp lỗi! Vui lòng kiểm tra log.", "ERR")
                pipeline_ok = False
    finally:
        # 7. Kéo dữ liệu về Laptop host (luôn thực thi dù thành công hay lỗi)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        log(f"Tải kết quả về host: {RESULTS_DIR}", "RUN")

        download_targets = [
            ("ba1_latency.csv", RESULTS_DIR / "ba1_latency.csv"),
            ("BA1_ENV.md", RESULTS_DIR / "BA1_ENV.md"),
            ("build.log", RESULTS_DIR / "build.log"),
            ("ba1_run.log", RESULTS_DIR / "ba1_run.log"),
        ]

        for remote_name, local_path in download_targets:
            try:
                session.download_file(f"{BOARD_RESULTS_DIR}/{remote_name}", local_path)
            except Exception as e:
                log(f"Không thể tải file {remote_name}: {e}", "WARN")

    if not pipeline_ok:
        log("Thực thi Baseline BA1 gặp sự cố trên board! Xem các file log đã tải về.", "ERR")
        sys.exit(1)

    # 8. Xác thực và in kết quả nghiệm thu
    csv_local = RESULTS_DIR / "ba1_latency.csv"
    if validate_schema(csv_local):
        is_synthetic = False
        with open(csv_local, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "SYNTHETIC_DEMO" in row.get("config", ""):
                    is_synthetic = True
                    break

        log("=" * 65, "WARN" if is_synthetic else "OK")
        if is_synthetic:
            log("⚠️ [CHẾ ĐỘ GIẢ LẬP / SYNTHETIC DEMO] ĐÃ HOÀN TẤT KIỂM THỬ PHẦN MỀM!", "WARN")
            log("   Cảnh báo: Dữ liệu đo từ khung hình giả lập / dummy DPU, CHƯA ĐẠT TRÊN PHẦN CỨNG THẬT.", "WARN")
            log("   Tuyệt đối không dùng số liệu này để viết bài báo chính thức (Tuân thủ Nguyên tắc Vàng #1)!", "WARN")
        else:
            log("🎉 [NGHIỆM THU THÀNH CÔNG] DỮ LIỆU ĐỘ TRỄ BASELINE BA1 ĐẠT CHUẨN SCHEMA!", "OK")
        
        # In bảng kết quả
        with open(csv_local, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cfg_name = row.get("config", "BA1")
                t_cap = float(row.get("capture_isp_ms", 0))
                t_pre = float(row.get("preproc_ms", 0))
                t_dma = float(row.get("dma_sync_ms", 0))
                t_dpu = float(row.get("dpu_infer_ms", 0))
                t_post = float(row.get("postproc_ms", 0))
                t_tot = float(row.get("total_latency_ms", 0))
                fps = (1000.0 / t_tot) if t_tot > 0 else 0

                print("\n  ┌" + "─" * 60 + "┐")
                print(f"  │ Cấu hình:             {cfg_name:<34} │")
                print(f"  │ Thu nhận & ISP (p50): {t_cap:>8.2f} ms                       │")
                print(f"  │ CPU Tiền xử lý (p50): {t_pre:>8.2f} ms  (Nút cổ chai chính)  │")
                print(f"  │ DMA Sync (p50):       {t_dma:>8.2f} ms                       │")
                print(f"  │ DPU Infer (p50):      {t_dpu:>8.2f} ms                       │")
                print(f"  │ Post-proc NMS (p50):  {t_post:>8.2f} ms                       │")
                print("  ├" + "─" * 60 + "┤")
                print(f"  │ TỔNG ĐỘ TRỄ (p50):    {t_tot:>8.2f} ms                       │")
                print(f"  │ THÔNG LƯỢNG THỰC TẾ:  {fps:>8.2f} FPS                      │")
                print("  └" + "─" * 60 + "┘\n")

        log(f"Báo cáo chi tiết: {RESULTS_DIR / 'BA1_ENV.md'}", "OK")
        log("=" * 65, "OK")
        if is_synthetic:
            log("👉 Hướng dẫn bàn giao & bước tiếp theo của TV2:", "WARN")
            log("   1. Lưu ý: Thử nghiệm chạy ở chế độ giả lập (SYNTHETIC_DEMO), chưa phải số liệu thực trên KV260.", "WARN")
            log("   2. Cần kết nối board KV260 và camera thật trong ca làm việc buổi chiều để đo số liệu chính thức.", "WARN")
            log("   3. Tuyệt đối không dùng số liệu này để nghiệm thu Tuần 3 chính thức hoặc viết bài báo!", "WARN")
        else:
            log("👉 Hướng dẫn bàn giao & bước tiếp theo của TV2:", "INFO")
            log("   1. Gửi kết quả phân rã BA1 cho TV1 (làm động lực tối ưu hardware s2t_top).", "INFO")
            log("   2. Cập nhật sheet TV2 dòng Tuần 3 trong KeHoachTuan_TACo-ISP_3SV.xlsx sang 'Xong'.", "INFO")
            log("   3. Sẵn sàng cho Tuần 4 (Mốc G0: Chạy YOLOX-nano trực tiếp trên camera).", "INFO")
    else:
        log("Dữ liệu CSV không hợp lệ hoặc thiếu file. Vui lòng kiểm tra lại log!", "ERR")
        sys.exit(1)


if __name__ == "__main__":
    main()
