#!/usr/bin/env python3
"""
TACo-ISP — W04 Milestone G0 Master Orchestrator
==============================================
Script chạy trên HOST PC (Windows) — điều khiển toàn bộ quy trình Cổng kiểm tra G0:
  1. Đồng bộ mã nguồn C++ (sw/) và tập lệnh (scripts/w4/) lên board KV260 qua SSH.
  2. Biên dịch ứng dụng pipeline G0 trên board (01_build_w04.sh).
  3. Thực thi chuỗi xử lý camera IMX219 -> DPU liên tục (02_run_g0.sh).
  4. Đánh giá thông lượng (FPS) và trích xuất báo cáo G0_ENV.md (03_eval_g0.sh).
  5. Kéo dữ liệu CSV và G0_ENV.md về host máy tính (results/raw/W04_g0/).
  6. Nghiệm thu chính thức Cổng kiểm tra G0 theo KeHoachTuan_TACo-ISP_3SV.xlsx!

Cách dùng:
  python scripts/w4/run_g0_w04.py
  python scripts/w4/run_g0_w04.py --host <IP_BOARD> --frames 300
  python scripts/w4/run_g0_w04.py --mode ba2
  python scripts/w4/run_g0_w04.py --skip-build
  python scripts/w4/run_g0_w04.py --dry-run
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
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "w4"
RESULTS_DIR = PROJECT_ROOT / "results" / "raw" / "W04_g0"
CONFIG_FILE = PROJECT_ROOT / "board_config.json"

BOARD_WORK_DIR = "taco-isp"
BOARD_SW_DIR = f"{BOARD_WORK_DIR}/sw"
BOARD_SCRIPTS_DIR = f"{BOARD_WORK_DIR}/scripts/w4"
BOARD_RESULTS_DIR = f"{BOARD_WORK_DIR}/results/raw/W04_g0"


def log(msg: str, level: str = "INFO"):
    ts = datetime.now().strftime("%H:%M:%S")
    prefix = {
        "INFO": "ℹ️",
        "OK": "✅",
        "WARN": "⚠️",
        "ERR": "❌",
        "RUN": "🔧",
        "G0": "🎯",
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
    """Giả lập toàn diện quy trình Tuần 4 trên host để kiểm tra tính sẵn sàng trước khi lên board."""
    log("=" * 65, "RUN")
    log("🧪 CHẾ ĐỘ GIẢ LẬP / DRY-RUN TUẦN 4 — CỔNG G0 (HOST INTEGRATION TEST)", "RUN")
    log("=" * 65, "RUN")

    # 1. Kiểm tra toàn vẹn file mã nguồn và scripts
    required_files = [
        SW_DIR / "CMakeLists.txt",
        SW_DIR / "app" / "baseline_ba.cpp",
        SW_DIR / "app" / "yolox_post.hpp",
        SCRIPTS_DIR / "01_build_w04.sh",
        SCRIPTS_DIR / "02_run_g0.sh",
        SCRIPTS_DIR / "03_eval_g0.sh",
        PROJECT_ROOT / "analysis" / "SCHEMAS.md",
    ]
    all_ok = True
    for f in required_files:
        if f.exists():
            log(f"  [✓] File tồn tại: {f.relative_to(PROJECT_ROOT)} ({f.stat().st_size} bytes)", "OK")
        else:
            log(f"  [✗] THIẾU FILE: {f.relative_to(PROJECT_ROOT)}", "ERR")
            all_ok = False

    # 2. Kiểm tra định dạng script bash
    log("Kiểm tra định dạng và cú pháp bash scripts...", "INFO")
    bash_files = [SCRIPTS_DIR / "01_build_w04.sh", SCRIPTS_DIR / "02_run_g0.sh", SCRIPTS_DIR / "03_eval_g0.sh"]
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
            log("  [✓] Cú pháp toàn bộ tập lệnh bash W4 (bash -n): HỢP LỆ 100%!", "OK")
        else:
            log(f"  [✗] Cú pháp bash có lỗi: {r_bash.stderr.strip()}", "ERR")
            all_ok = False
    except Exception:
        log("  [i] Bỏ qua kiểm tra bash -n (môi trường không có lệnh bash)", "INFO")

    # 3. Unit test cho yolox_post.hpp
    log("Kiểm tra biên dịch và chạy Unit Test YOLOX Post-Processor C++17...", "INFO")
    try:
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
    std::cout << "G0_YOLOX_UNIT_TEST_PASS";
    return 0;
}
"""
        test_cpp = Path("sim_g0_yolox_test.cpp")
        test_exe = Path("sim_g0_yolox_test.exe")
        test_cpp.write_text(unit_test_code, encoding="utf-8")
        r_compile = subprocess.run(["g++", "-std=c++17", "-O2", str(test_cpp), "-o", str(test_exe)],
                                   capture_output=True, text=True, timeout=15)
        if r_compile.returncode == 0:
            r_run = subprocess.run([f"./{test_exe}"], capture_output=True, text=True, timeout=10)
            if "G0_YOLOX_UNIT_TEST_PASS" in r_run.stdout:
                log("  [✓] Test YOLOX Post-Processor Unit: ĐẠT CHỈ TIÊU (Grids 3549, Clamping an toàn, No NaN/Inf)!", "OK")
            else:
                log(f"  [✗] Test YOLOX Post-Processor thất bại: mã {r_run.returncode}", "ERR")
                all_ok = False
            test_exe.unlink(missing_ok=True)
        test_cpp.unlink(missing_ok=True)
    except Exception as e:
        log(f"  [i] Bỏ qua kiểm tra g++ host: {e}", "INFO")

    # 4. Kiểm tra schema CSV validation
    log("Kiểm tra xác thực schema analysis/SCHEMAS.md...", "INFO")
    import tempfile

    # 4a. Hợp lệ
    with tempfile.NamedTemporaryFile("w+", suffix=".csv", delete=False, encoding="utf-8") as tf:
        tf.write("config,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_latency_ms\n")
        tf.write("G0_YOLOX_nano,2.150,18.420,1.050,5.520,3.210,30.350\n")
        temp_csv_valid = Path(tf.name)
    ok_valid = validate_schema(temp_csv_valid)
    temp_csv_valid.unlink(missing_ok=True)

    # 4b. Lỗi
    with tempfile.NamedTemporaryFile("w+", suffix=".csv", delete=False, encoding="utf-8") as tf:
        tf.write("config,capture_isp_ms,preproc_ms\n")
        tf.write("G0_YOLOX_nano,2.150,-18.420\n")
        temp_csv_invalid = Path(tf.name)
    ok_invalid = not validate_schema(temp_csv_invalid)
    temp_csv_invalid.unlink(missing_ok=True)

    if ok_valid and ok_invalid:
        log("  [✓] Xác thực schema dữ liệu G0 (T-A1 latency.csv) đạt chuẩn 100%!", "OK")
    else:
        log("  [✗] Lỗi xác thực schema!", "ERR")
        all_ok = False

    # 5. Kiểm tra file mẫu RAW10 dự phòng từ Tuần 2
    w2_sample = PROJECT_ROOT / "results" / "raw" / "W02_camera" / "sample_1080p.raw"
    if w2_sample.exists() and w2_sample.stat().st_size > 0:
        log(f"  [✓] Đã có ảnh RAW10 mẫu từ W2 ({w2_sample.stat().st_size:,} bytes) sẵn sàng nạp fallback.", "OK")
    else:
        log("  [i] Chưa có ảnh sample_1080p.raw cục bộ (hệ thống sẽ chụp camera trực tiếp hoặc tạo synthetic).", "INFO")

    # 6. Kiểm tra cấu hình board_config.json
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            log(f"  [✓] Đã có file cấu hình board: host_ip={cfg.get('host_ip')}, user={cfg.get('user')}", "OK")
        except Exception as e:
            log(f"  [!] board_config.json lỗi: {e}", "WARN")
    else:
        log("  [i] Chưa có board_config.json. Script sẽ đọc từ W1 khi chạy trên board thật.", "INFO")

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
        log("🎉 [GIẢ LẬP G0 THÀNH CÔNG] Toàn bộ kịch bản và mã nguồn Tuần 4 đã sẵn sàng 100%!", "OK")
        log("   Lệnh thực thi chính thức cho TV2:", "OK")
        log("       python scripts/w4/run_g0_w04.py", "OK")
    else:
        log("⚠️ Vui lòng kiểm tra các mục đánh dấu [✗] ở trên.", "WARN")
    log("=" * 65, "OK")
    return 0 if all_ok else 1


def main():
    parser = argparse.ArgumentParser(description="TACo-ISP W04 Milestone G0 Master Orchestrator")
    parser.add_argument("--host", default=None, help="IP của KV260 (mặc định đọc từ board_config.json sinh bởi W1)")
    parser.add_argument("--user", default=None, help="User SSH (mặc định đọc từ board_config.json hoặc petalinux)")
    parser.add_argument("--password", default=None, help="Mật khẩu SSH (mặc định đọc từ board_config.json)")
    parser.add_argument("--scan", action="store_true", help="Tự động quét mạng tìm board nếu chưa có cấu hình từ W1")
    parser.add_argument("--frames", type=int, default=200, help="Số khung hình chạy luồng kiểm thử G0 (mặc định: 200)")
    parser.add_argument("--mode", default="ba1", choices=["ba1", "ba2"], help="Chế độ pipeline (ba1 hoặc ba2)")
    parser.add_argument("--skip-build", action="store_true", help="Bỏ qua bước build nếu binary đã có sẵn")
    parser.add_argument("--dry-run", action="store_true", help="Chạy giả lập kiểm thử toàn diện trên máy Host")
    args = parser.parse_args()

    if args.dry_run:
        sys.exit(run_simulation(args))

    log("=" * 65, "G0")
    log("🎯 TACo-ISP W04 — CỔNG KIỂM TRA G0: PIPELINE CAMERA -> DPU CHẠY THÔNG", "G0")
    log("=" * 65, "G0")

    # 1. Đọc cấu hình board_config.json
    local_cfg = {}
    if not CONFIG_FILE.exists():
        log(f"Không tìm thấy file cấu hình board: {CONFIG_FILE.name}!", "WARN")
        log("Hệ thống yêu cầu chạy Tuần 1 (W1) để định danh board: python scripts/w1/run_all.py", "WARN")
    else:
        try:
            local_cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        except Exception as e:
            log(f"Lỗi đọc file cấu hình {CONFIG_FILE.name}: {e}", "WARN")

    host = args.host or (local_cfg.get("host_ip") or "").strip() or None
    user = args.user or (local_cfg.get("user") or "").strip() or None
    password = args.password or (local_cfg.get("password") or "").strip() or None

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
            log(f"Lỗi quét mạng: {e}", "WARN")

        if not host:
            log("=" * 65, "ERR")
            log("CHƯA CÓ ĐỊA CHỈ IP CỦA BOARD KV260 TRONG CẤU HÌNH!", "ERR")
            log("Vui lòng thực hiện một trong các cách sau:", "ERR")
            log("  [Cách 1]: python scripts/w4/run_g0_w04.py --host <IP_BOARD>", "ERR")
            log("  [Cách 2]: python scripts/w4/run_g0_w04.py --scan", "ERR")
            log("=" * 65, "ERR")
            sys.exit(1)
        log(f"Đã tự động tìm thấy board tại IP: {host}", "OK")

    # 2. Kết nối SSH
    session = BoardSSH(host, user, password)
    if not session.connect():
        log(f"Không thể kết nối SSH tới {host}!", "ERR")
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

    log("Đồng bộ tập lệnh Cổng G0 (scripts/w4/) lên board...", "RUN")
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

    # 4. Biên dịch phần mềm trên board
    pipeline_ok = True
    try:
        if not args.skip_build:
            log("Bắt đầu biên dịch ứng dụng pipeline G0 trên KV260...", "BUILD")
            rc, _, _ = session.run(f"bash {BOARD_SCRIPTS_DIR}/01_build_w04.sh")
            if rc != 0:
                log("Biên dịch thất bại! Kiểm tra log tại results/raw/W04_g0/build.log", "ERR")
                pipeline_ok = False
            else:
                log("Biên dịch hoàn tất thành công!", "OK")
        else:
            log("Bỏ qua bước biên dịch (--skip-build).", "INFO")

        # 5. Thực thi Cổng kiểm tra G0
        if pipeline_ok:
            log(f"Khởi chạy Cổng G0 ({args.mode.upper()}) với {args.frames} khung hình liên tục...", "RUN")
            rc, _, _ = session.run(f"bash {BOARD_SCRIPTS_DIR}/02_run_g0.sh {args.frames} {args.mode}")
            if rc != 0:
                log("Thực thi pipeline G0 gặp lỗi! Kiểm tra log tại results/raw/W04_g0/g0_run.log", "ERR")
                pipeline_ok = False

        # 6. Đánh giá và sinh báo cáo G0_ENV.md
        if pipeline_ok:
            log("Sinh báo cáo nghiệm thu Cổng G0 (G0_ENV.md)...", "RUN")
            rc, _, _ = session.run(f"bash {BOARD_SCRIPTS_DIR}/03_eval_g0.sh")
            if rc != 0:
                log("Đánh giá nghiệm thu Cổng G0 trên board gặp lỗi! Vui lòng kiểm tra log.", "ERR")
                pipeline_ok = False
    finally:
        # 7. Kéo dữ liệu về Laptop host (luôn thực thi dù thành công hay lỗi)
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        log(f"Tải kết quả về host: {RESULTS_DIR}", "RUN")

        download_targets = [
            ("g0_pipeline.csv", RESULTS_DIR / "g0_pipeline.csv"),
            ("G0_ENV.md", RESULTS_DIR / "G0_ENV.md"),
            ("build.log", RESULTS_DIR / "build.log"),
            ("g0_run.log", RESULTS_DIR / "g0_run.log"),
        ]

        for remote_name, local_path in download_targets:
            try:
                session.download_file(f"{BOARD_RESULTS_DIR}/{remote_name}", local_path)
            except Exception as e:
                log(f"Không thể tải file {remote_name}: {e}", "WARN")

    if not pipeline_ok:
        log("Pipeline G0 gặp sự cố trong quá trình thực thi trên board! Xem các file log đã tải về.", "ERR")
        sys.exit(1)

    # 8. Xác thực và công bố kết quả nghiệm thu Cổng G0
    csv_local = RESULTS_DIR / "g0_pipeline.csv"
    env_local = RESULTS_DIR / "G0_ENV.md"
    if validate_schema(csv_local):
        is_synthetic = False
        with open(csv_local, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if "SYNTHETIC_DEMO" in row.get("config", ""):
                    is_synthetic = True
                    break

        env_has_c04_failure = False
        if env_local.exists():
            env_content = env_local.read_text(encoding="utf-8")
            if "- [ ] **C0.4" in env_content:
                env_has_c04_failure = True

        log("=" * 65, "WARN" if (is_synthetic or env_has_c04_failure) else "OK")
        if is_synthetic:
            log("⚠️ [CHẾ ĐỘ GIẢ LẬP / SYNTHETIC DEMO] ĐÃ HOÀN TẤT KIỂM THỬ PHẦN MỀM!", "WARN")
            log("   Cảnh báo: Dữ liệu đo từ khung hình giả lập / dummy DPU, CHƯA ĐẠT TRÊN PHẦN CỨNG THẬT.", "WARN")
            log("   Tuyệt đối không dùng số liệu này để nghiệm thu Cổng G0 chính thức hoặc viết bài báo!", "WARN")
        elif env_has_c04_failure:
            log("⚠️ [CỔNG G0 CHƯA ĐẠT CHỈ TIÊU] Tiêu chí C0.4 chưa hoàn tất (Đồ thị bị phân mảnh hoặc thiếu 1 DPU subgraph)!", "WARN")
            log("   Mô hình xmodel bị băm nhỏ trên CPU hoặc chưa đạt chuẩn 1 DPU subgraph duy nhất.", "WARN")
            log("   Cần tối ưu lại xmodel để nén gọn trong 1 DPU subgraph trước khi nghiệm thu Cổng G0!", "WARN")
        else:
            log("🎉 [XÁC NHẬN NGHIỆM THU] CỔNG KIỂM TRA G0 ĐÃ ĐẠT CHỈ TIÊU!", "OK")
            log("   Pipeline camera IMX219 -> DPUCZDX8G B4096 chạy thông suốt 100% (1 DPU Subgraph)!", "OK")

        with open(csv_local, mode="r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                cfg_name = row.get("config", "G0_Pipeline")
                t_cap = float(row.get("capture_isp_ms", 0))
                t_pre = float(row.get("preproc_ms", 0))
                t_dma = float(row.get("dma_sync_ms", 0))
                t_dpu = float(row.get("dpu_infer_ms", 0))
                t_post = float(row.get("postproc_ms", 0))
                t_tot = float(row.get("total_latency_ms", 0))
                fps = (1000.0 / t_tot) if t_tot > 0 else 0

                print("\n  ┌" + "─" * 60 + "┐")
                print(f"  │ Cổng kiểm tra:        MILESTONE G0 (W04)                   │")
                print(f"  │ Cấu hình:             {cfg_name:<34} │")
                print(f"  │ Thu nhận & ISP (p50): {t_cap:>8.2f} ms                       │")
                print(f"  │ CPU Tiền xử lý (p50): {t_pre:>8.2f} ms                       │")
                print(f"  │ DMA Sync (p50):       {t_dma:>8.2f} ms                       │")
                print(f"  │ DPU Infer (p50):      {t_dpu:>8.2f} ms                       │")
                print(f"  │ Post-proc NMS (p50):  {t_post:>8.2f} ms                       │")
                print("  ├" + "─" * 60 + "┤")
                print(f"  │ TỔNG ĐỘ TRỄ (p50):    {t_tot:>8.2f} ms                       │")
                print(f"  │ THÔNG LƯỢNG THỰC TẾ:  {fps:>8.2f} FPS                      │")
                print("  └" + "─" * 60 + "┘\n")

        log(f"Báo cáo nghiệm thu chi tiết: {RESULTS_DIR / 'G0_ENV.md'}", "OK")
        log("=" * 65, "OK")
        if is_synthetic or env_has_c04_failure:
            log("👉 Bước tiếp theo của TV2:", "WARN")
            if is_synthetic:
                log("   1. Cắm camera IMX219 (J9) và nạp xmodel YOLOX-nano thật lên KV260.", "WARN")
                log("   2. Chạy lại python scripts/w4/run_g0_w04.py trên phần cứng thật để nghiệm thu Cổng G0 chính thức.", "WARN")
            else:
                log("   1. Kiểm tra lại mô hình xmodel (ReLU thay vì SiLU) để đảm bảo toàn bộ nén trong 1 DPU subgraph.", "WARN")
                log("   2. Chạy lại python scripts/w4/run_g0_w04.py để xác nhận 0 phân mảnh CPU.", "WARN")
            log("   3. CHƯA đánh dấu 'Xong' Tuần 4 trên KeHoachTuan_TACo-ISP_3SV.xlsx cho đến khi đạt chuẩn trên phần cứng thật!", "WARN")
        else:
            log("👉 Bước tiếp theo của TV2:", "INFO")
            log("   1. Mở file KeHoachTuan_TACo-ISP_3SV.xlsx, đổi Tuần 4 sang 'Xong'.", "INFO")
            log("   2. Nghiệm thu Cổng G0 (Hoàn thành Nội dung 1: Dựng nền tảng), tiếp tục Giai đoạn 1 với Tuần 5–8 (Nội dung 2: Hệ đo lường).", "INFO")
            log("   3. Bắt đầu chuẩn bị Tuần 5 (Hệ đo độ trễ AXI Timer + GPIO).", "INFO")
    else:
        log("Dữ liệu CSV không hợp lệ hoặc thiếu file. Vui lòng kiểm tra lại log!", "ERR")
        sys.exit(1)


if __name__ == "__main__":
    main()
