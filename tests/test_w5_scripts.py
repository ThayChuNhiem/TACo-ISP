import sys
import re
import subprocess
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "w5"
sys.path.insert(0, str(SCRIPTS_DIR))


def test_w5_scripts_lf_and_syntax():
    """Verify all W5 bash scripts have Unix LF line endings and valid syntax (bash -n)."""
    for sh_name in ["01_setup_uio_timer.sh", "02_test_hw_clock.sh"]:
        sh_path = SCRIPTS_DIR / sh_name
        assert sh_path.exists(), f"{sh_name} must exist"
        raw = sh_path.read_bytes()
        assert b"\r\n" not in raw, f"{sh_name} must have Unix LF line endings"

        rel_path = f"scripts/w5/{sh_name}"
        res = subprocess.run(["bash", "-n", rel_path], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        assert res.returncode == 0, f"Bash syntax check failed for {sh_name}: {res.stderr}"


def test_w5_dtsi_overlay_structure():
    """Verify Device Tree overlay hw/overlay/taco.dtsi has valid overlay syntax and properties."""
    dtsi_path = PROJECT_ROOT / "hw" / "overlay" / "taco.dtsi"
    assert dtsi_path.exists(), "hw/overlay/taco.dtsi must exist"
    content = dtsi_path.read_text(encoding="utf-8")

    assert "/dts-v1/;" in content, "Must declare /dts-v1/;"
    assert "/plugin/;" in content, "Must declare /plugin/; for overlay"
    assert 'compatible = "generic-uio"' in content, "Must use compatible = generic-uio"
    assert "timer@80030000" in content, "AXI Timer node base must be 0x80030000"
    assert "gpio@80040000" in content, "AXI GPIO node base must be 0x80040000"
    assert "xlnx,one-timer-only = <0>" in content, "AXI Timer must enable 2 cascaded timers (one-timer-only = 0)"
    assert "clock-frequency" in content, "AXI Timer must specify clock-frequency"


def test_w5_uio_header_structure():
    """Verify sw/common/uio.hpp defines UioDevice, HwClock, Gpio, and memory barriers."""
    header_path = PROJECT_ROOT / "sw" / "common" / "uio.hpp"
    assert header_path.exists(), "sw/common/uio.hpp must exist"
    content = header_path.read_text(encoding="utf-8")

    assert "class UioDevice" in content
    assert "class HwClock" in content
    assert "class Gpio" in content
    assert "memory_barrier" in content
    assert "dmb sy" in content, "Must implement ARM Cortex-A53 dmb sy memory barrier"
    assert "REG_TCSR0" in content
    assert "REG_TCR1" in content
    assert "TCSR_CASC" in content
    assert "now_ticks" in content


def test_w5_uio_cplusplus_compilation_and_execution(tmp_path):
    """Compile and run C++ tests verifying UioDevice mock, HwClock 64-bit anti-rollover, and Gpio."""
    test_cpp = PROJECT_ROOT / "tests" / "test_uio.cpp"
    assert test_cpp.exists(), "test_uio.cpp must exist"

    bin_path = tmp_path / "test_uio.exe"
    cmd_build = [
        "g++", "-std=c++17", "-Wall", "-Wextra",
        "-I", str(PROJECT_ROOT / "sw" / "common"),
        str(test_cpp), "-o", str(bin_path)
    ]
    res_build = subprocess.run(cmd_build, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    assert res_build.returncode == 0, f"C++ build failed: {res_build.stderr}"

    res_run = subprocess.run([str(bin_path)], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    assert res_run.returncode == 0, f"C++ execution failed: {res_run.stderr}"
    assert "All C++ UIO / HwClock / Gpio assertions passed!" in res_run.stdout


def test_w5_baseline_ba_stage_timestamps():
    """Verify baseline_ba.cpp records all 5 stage timestamps and supports --raw-csv."""
    ba_src = PROJECT_ROOT / "sw" / "app" / "baseline_ba.cpp"
    assert ba_src.exists()
    content = ba_src.read_text(encoding="utf-8")

    # Check CLI options
    assert "--raw-csv" in content
    assert "--timer-freq" in content
    assert "--uio-timer" in content
    assert "--uio-gpio" in content
    assert "--led-pin" in content

    # Check timestamp variables
    assert "t_sof" in content
    assert "t_pre_done" in content
    assert "t_dpu_start" in content
    assert "t_dpu_end" in content
    assert "t_nms_done" in content

    # Check raw CSV header conforms to SCHEMAS.md
    assert "frame_id,t_sof_ns,t_pre_done_ns,t_dpu_start_ns,t_dpu_end_ns,t_nms_done_ns" in content


def test_w5_taco_app_compilation_and_help(tmp_path):
    """Compile taco_app.cpp and verify CLI arguments."""
    taco_src = PROJECT_ROOT / "sw" / "app" / "taco_app.cpp"
    assert taco_src.exists()

    bin_path = tmp_path / "taco_app_test.exe"
    cmd_build = [
        "g++", "-std=c++17", "-Wall", "-Wextra",
        "-I", str(PROJECT_ROOT / "sw" / "common"),
        str(taco_src), "-o", str(bin_path)
    ]
    res_build = subprocess.run(cmd_build, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    assert res_build.returncode == 0, f"taco_app build failed: {res_build.stderr}"

    res_help = subprocess.run([str(bin_path), "--help"], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    assert res_help.returncode == 0
    assert "--raw-csv" in res_help.stdout
    assert "--timer-freq" in res_help.stdout
    assert "--nbuf" in res_help.stdout
    assert "--copy-mode" in res_help.stdout

    # Test executing taco_app with --raw-csv and --csv
    raw_csv = tmp_path / "test_taco_raw.csv"
    sum_csv = tmp_path / "test_taco_sum.csv"
    res_run = subprocess.run(
        [str(bin_path), "--frames", "5", "--warmup", "2", "--raw-csv", str(raw_csv), "--csv", str(sum_csv), "--dummy"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True
    )
    assert res_run.returncode == 0, f"taco_app execution failed: {res_run.stderr}"
    assert raw_csv.exists(), "taco_app must generate raw CSV when --raw-csv is provided"
    assert sum_csv.exists(), "taco_app must generate summary CSV when --csv is provided"

    raw_lines = raw_csv.read_text(encoding="utf-8").strip().splitlines()
    assert len(raw_lines) == 6 # header + 5 frames
    assert "frame_id,t_sof_ns,t_pre_done_ns,t_dpu_start_ns,t_dpu_end_ns,t_nms_done_ns" in raw_lines[0]
    # Verify non-zero timestamps (proving fallback steady_clock works and is not 0)
    parts = raw_lines[1].split(",")
    t_sof_ns = int(parts[1])
    assert t_sof_ns > 0, "Timestamps in raw CSV must be non-zero"

    sum_lines = sum_csv.read_text(encoding="utf-8").strip().splitlines()
    assert len(sum_lines) == 2
    assert "config,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_latency_ms" in sum_lines[0]


def test_w5_orchestrator_execution():
    """Verify scripts/w5/run_w05.py orchestrator runs successfully."""
    orch_path = SCRIPTS_DIR / "run_w05.py"
    assert orch_path.exists()

    res = subprocess.run(
        [sys.executable, str(orch_path), "--dry-run"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace"
    )
    assert res.returncode == 0, f"run_w05.py failed: {res.stderr}\nStdout: {res.stdout}"
    assert "TUẦN 5 ĐÃ SẴN SÀNG 100%!" in res.stdout

    # Verify generated sample raw timestamps CSV
    raw_csv = PROJECT_ROOT / "results" / "raw" / "W05_measurement" / "raw_timestamps.csv"
    assert raw_csv.exists()
    header = raw_csv.read_text(encoding="utf-8").splitlines()[0]
    expected_header = "frame_id,t_sof_ns,t_pre_done_ns,t_dpu_start_ns,t_dpu_end_ns,t_nms_done_ns,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_ms,num_dets"
    assert header == expected_header
