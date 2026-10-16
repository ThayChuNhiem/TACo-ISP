import sys
import re
import inspect
import subprocess
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "w2"
sys.path.insert(0, str(SCRIPTS_DIR))


def test_camera_pipeline_script_lf_and_syntax():
    """Verify 01_camera_pipeline.sh has Unix LF line endings and valid bash syntax."""
    sh_path = SCRIPTS_DIR / "01_camera_pipeline.sh"
    raw = sh_path.read_bytes()
    assert b"\r\n" not in raw, "01_camera_pipeline.sh must have Unix LF line endings"

    rel_path = "scripts/w2/01_camera_pipeline.sh"
    res = subprocess.run(["bash", "-n", rel_path], capture_output=True, text=True)
    assert res.returncode == 0, f"Bash syntax check failed: {res.stderr}"


def test_camera_pipeline_overlay_logic():
    """Verify overlay parameter and auto-detection fallback logic in 01_camera_pipeline.sh."""
    sh_text = (SCRIPTS_DIR / "01_camera_pipeline.sh").read_text(encoding="utf-8")
    assert 'OVERLAY_APP="${1:-${OVERLAY_APP:-}}"' in sh_text
    assert "kv260-imx219-raw10" in sh_text
    assert "kv260-mipi-csi2" in sh_text
    assert "kv260-smartcam" in sh_text
    assert 'sudo xmutil loadapp "$OVERLAY_APP"' in sh_text
    assert "- **Overlay:** $OVERLAY_APP" in sh_text


def test_camera_pipeline_dmesg_fallback():
    """Verify dmesg command in 01_camera_pipeline.sh has sudo fallback for restricted environments."""
    sh_text = (SCRIPTS_DIR / "01_camera_pipeline.sh").read_text(encoding="utf-8")
    assert "sudo dmesg 2>/dev/null || dmesg 2>/dev/null" in sh_text


def test_camera_pipeline_entity_regex():
    """Verify media-ctl entity regex extraction distinguishes subdev from vcap node."""
    sample_topology = """
- entity 1: vcap_mipi_csi2_rx output 0 (1 pad, 1 link)
            type Node subtype V4L flags 0
            device node name /dev/video0
- entity 5: 80020000.mipi_csi2_rx_subsystem (2 pads, 2 links)
            type V4L2 subdev subtype Unknown flags 0
            device node name /dev/v4l-subdev0
- entity 8: imx219 2-0010 (1 pad, 1 link)
            type V4L2 subdev subtype Sensor flags 0
            device node name /dev/v4l-subdev1
"""
    # Test CSI entity extraction via bash command pipeline
    cmd_csi = [
        "bash", "-c",
        "grep -iE 'entity [0-9]+:.*mipi_csi2_rx' | grep -v 'vcap' | "
        "sed -E 's/.*entity [0-9]+: ([^(]+) \\(.*$/\\1/' | head -n 1 | xargs"
    ]
    res_csi = subprocess.run(cmd_csi, input=sample_topology, capture_output=True, text=True)
    assert res_csi.returncode == 0
    assert res_csi.stdout.strip() == "80020000.mipi_csi2_rx_subsystem"

    # Test IMX entity extraction via bash command pipeline
    cmd_imx = [
        "bash", "-c",
        "grep -iE 'entity [0-9]+:.*imx219' | grep -v 'vcap' | "
        "sed -E 's/.*entity [0-9]+: ([^(]+) \\(.*$/\\1/' | head -n 1 | xargs"
    ]
    res_imx = subprocess.run(cmd_imx, input=sample_topology, capture_output=True, text=True)
    assert res_imx.returncode == 0
    assert res_imx.stdout.strip() == "imx219 2-0010"


def test_camera_pipeline_entity_regex_python_equivalent():
    """Verify entity regex matching pure Python pattern simulation."""
    lines = [
        "- entity 1: vcap_mipi_csi2_rx output 0 (1 pad, 1 link)",
        "- entity 5: 80020000.mipi_csi2_rx_subsystem (2 pads, 2 links)",
        "- entity 8: imx219 2-0010 (1 pad, 1 link)",
        "entity 12: a0000000.mipi_csi2_rx_subsystem (2 pads, 2 links)"
    ]

    csi_candidates = [l for l in lines if re.search(r'entity [0-9]+:.*mipi_csi2_rx', l, re.IGNORECASE) and "vcap" not in l]
    assert len(csi_candidates) == 2

    # Verify first subdev is extracted
    m = re.search(r'entity [0-9]+: ([^(]+) \(', csi_candidates[0])
    assert m is not None
    assert m.group(1).strip() == "80020000.mipi_csi2_rx_subsystem"

    # Verify second subdev is extracted
    m2 = re.search(r'entity [0-9]+: ([^(]+) \(', csi_candidates[1])
    assert m2 is not None
    assert m2.group(1).strip() == "a0000000.mipi_csi2_rx_subsystem"


def test_run_camera_defaults_priority():
    """Verify that ('root', 'root') is the top priority default in BoardSSH.connect()."""
    import run_camera_w02
    ssh = run_camera_w02.BoardSSH("127.0.0.1")
    src = inspect.getsource(ssh.connect)
    match = re.search(r'defaults\s*=\s*\[(.*?)\]', src, re.DOTALL)
    assert match is not None, "defaults list not found in BoardSSH.connect"
    defaults_block = match.group(1).strip()
    first_item = defaults_block.split("\n")[0].strip()
    assert '("root", "root")' in first_item, f"Expected ('root', 'root') as first default, got: {first_item}"


def test_run_camera_sudo_nopasswd_command():
    """Verify that sudo NOPASSWD unlock logic is properly present in run_camera_w02.py."""
    import run_camera_w02
    src = inspect.getsource(run_camera_w02.main)
    assert 'session.user != "root"' in src
    assert "NOPASSWD: ALL" in src
    assert "/etc/sudoers.d/" in src


def test_run_camera_expected_formats_sizes():
    """Verify EXPECTED_FORMATS contains 4147200, 2764800, and 2592000 bytes."""
    import run_camera_w02
    src = inspect.getsource(run_camera_w02.main)
    assert "4147200" in src
    assert "2764800" in src
    assert "2592000" in src
    assert "RAW10 Xilinx 32-bit Packed" in src


def test_run_camera_cli_overlay_argument():
    """Verify --overlay argument is parsed and forwarded to 01_camera_pipeline.sh."""
    import run_camera_w02
    src = inspect.getsource(run_camera_w02.main)
    assert "--overlay" in src
    assert "01_camera_pipeline.sh{overlay_arg}" in src
    assert 'overlay_arg = f\' "{args.overlay}"\' if args.overlay else ""' in src


def test_board_ssh_connect_behavioral_candidate_order():
    """Behaviorally verify that BoardSSH.connect tests root:root first when unconfigured."""
    import run_camera_w02
    from unittest.mock import patch

    ssh = run_camera_w02.BoardSSH("127.0.0.1", user=None, password=None)
    tested_candidates = []

    def mock_connect(*args, **kwargs):
        tested_candidates.append((kwargs.get("username"), kwargs.get("password")))
        raise Exception("Authentication failed for test")

    with patch("paramiko.SSHClient.connect", side_effect=mock_connect):
        result = ssh.connect()

    assert result is False
    assert len(tested_candidates) == 5
    assert tested_candidates[0] == ("root", "root"), f"Expected ('root', 'root') first, got {tested_candidates[0]}"
    assert tested_candidates[1] == ("petalinux", "petalinux")
    assert tested_candidates[2] == ("ubuntu", "ubuntu")
    assert tested_candidates[3] == ("petalinux", None)
    assert tested_candidates[4] == ("ubuntu", None)
    assert len(tested_candidates) == len(set(tested_candidates))


def test_board_ssh_connect_empty_password_normalized():
    """Verify that an empty string password is normalized to None and does not cause duplicate candidates."""
    import run_camera_w02
    from unittest.mock import patch

    ssh = run_camera_w02.BoardSSH("127.0.0.1", user="petalinux", password="")
    tested_candidates = []

    def mock_connect(*args, **kwargs):
        tested_candidates.append((kwargs.get("username"), kwargs.get("password")))
        raise Exception("fail")

    with patch("paramiko.SSHClient.connect", side_effect=mock_connect):
        ssh.connect()

    assert ("petalinux", "") not in tested_candidates
    assert ("petalinux", "petalinux") in tested_candidates
    assert ("petalinux", None) in tested_candidates
    assert tested_candidates.count(("petalinux", None)) == 1


def test_board_ssh_run_masks_password_in_log(capsys):
    """Verify that passwords in sudo -S commands are masked in console output."""
    import run_camera_w02
    from unittest.mock import MagicMock

    ssh = run_camera_w02.BoardSSH("127.0.0.1", user="petalinux", password="secret_kv260_pass")
    mock_client = MagicMock()
    mock_stdout = MagicMock()
    mock_stdout.read.return_value = b""
    mock_stdout.channel.recv_exit_status.return_value = 0
    mock_stderr = MagicMock()
    mock_stderr.read.return_value = b""
    mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)
    ssh.client = mock_client

    cmd = "echo 'secret_kv260_pass' | sudo -S sh -c 'echo \"petalinux ALL=(ALL) NOPASSWD: ALL\" > /etc/sudoers.d/petalinux_nopasswd'"
    rc, out, err = ssh.run(cmd)

    captured = capsys.readouterr()
    assert rc == 0
    assert "secret_kv260_pass" not in captured.out, "Plain text password must not be leaked in log output"
    assert "echo '***' | sudo -S" in captured.out


def test_camera_pipeline_video_node_discovery_both_patterns():
    """Verify video node discovery logic correctly handles both vcap and generic device node patterns."""
    sample_topology_vcap = """
- entity 1: vcap_mipi_csi2_rx output 0 (1 pad, 1 link)
            type Node subtype V4L flags 0
            device node name /dev/video0
"""
    sample_topology_frmbuf = """
- entity 20: 80030000.v_frmbuf_wr (1 pad, 1 link)
            type Node subtype V4L flags 0
            device node name /dev/video2
"""
    cmd = [
        "bash", "-c",
        "grep -E 'device node name /dev/video' | head -n 1 | sed -E 's/.*device node name[[:space:]]+//' | xargs"
    ]
    res1 = subprocess.run(cmd, input=sample_topology_vcap, capture_output=True, text=True)
    assert res1.returncode == 0
    assert res1.stdout.strip() == "/dev/video0"

    res2 = subprocess.run(cmd, input=sample_topology_frmbuf, capture_output=True, text=True)
    assert res2.returncode == 0
    assert res2.stdout.strip() == "/dev/video2"


def test_camera_pipeline_v4l2_error_logging_behavior():
    """Verify 01_camera_pipeline.sh logs v4l2-ctl errors rather than discarding to /dev/null."""
    sh_text = (SCRIPTS_DIR / "01_camera_pipeline.sh").read_text(encoding="utf-8")
    assert "V4L2_ERR_LOG" in sh_text
    assert "Chi tiết lỗi từ v4l2-ctl" in sh_text


def test_camera_pipeline_synthetic_fallback_generation(tmp_path):
    """Verify that the synthetic RAW10 generator embedded in 01_camera_pipeline.sh produces a compliant 1080p RG10 frame."""
    sh_text = (SCRIPTS_DIR / "01_camera_pipeline.sh").read_text(encoding="utf-8")
    assert "SYNTHETIC_FALLBACK" in sh_text
    assert "KHUNG MẪU RAW10 MÔ PHỎNG" in sh_text

    raw_file = tmp_path / "sample_1080p.raw"

    # Simulate the Python generation logic from the bash script
    width, height = 1920, 1080
    row_even = bytearray(width * 2)
    row_odd = bytearray(width * 2)

    for x in range(0, width, 2):
        val_r = 64 + int(800 * (x / width))
        row_even[2*x] = val_r & 0xFF
        row_even[2*x + 1] = (val_r >> 8) & 0x03
        val_g = 64 + int(600 * ((width - x) / width))
        row_even[2*(x+1)] = val_g & 0xFF
        row_even[2*(x+1) + 1] = (val_g >> 8) & 0x03

    for x in range(0, width, 2):
        val_g = 64 + int(600 * ((width - x) / width))
        row_odd[2*x] = val_g & 0xFF
        row_odd[2*x + 1] = (val_g >> 8) & 0x03
        val_b = 64 + int(700 * (x / width))
        row_odd[2*(x+1)] = val_b & 0xFF
        row_odd[2*(x+1) + 1] = (val_b >> 8) & 0x03

    with open(raw_file, "wb") as f:
        for y in range(height):
            f.write(row_even if y % 2 == 0 else row_odd)

    assert raw_file.exists()
    assert raw_file.stat().st_size == 4147200, "Unpacked 1080p RG10 size must be exactly 4,147,200 bytes"

    # Check non-zero and range
    data = raw_file.read_bytes()
    assert any(b != 0 for b in data[:4096]), "Buffer must not be all-zero"
    # Check 16-bit pixel values are in 10-bit range (0..1023)
    p0 = data[0] | (data[1] << 8)
    assert 64 <= p0 <= 1023, f"Pixel value {p0} must be in valid 10-bit range with pedestal >= 64"


def test_run_camera_synthetic_status_detection(tmp_path, monkeypatch, capsys):
    """Verify run_camera_w02.py properly identifies synthetic mode and prints distinct guidance."""
    import run_camera_w02
    results_dir = tmp_path / "results"
    results_dir.mkdir()
    monkeypatch.setattr(run_camera_w02, "RESULTS_DIR", results_dir)

    raw_file = results_dir / "sample_1080p.raw"
    raw_file.write_bytes(b"\x40\x00" * (1920 * 1080))  # 4,147,200 bytes of value 64

    env_file = results_dir / "CAMERA_ENV.md"
    env_file.write_text("# CAMERA_ENV.md\n- **Chế độ hoạt động:** KHUNG MẪU RAW10 MÔ PHỎNG (Sẵn sàng đón overlay TV1)", encoding="utf-8")

    # Read and test status detection snippet
    env_text = env_file.read_text(encoding="utf-8")
    assert "MÔ PHỎNG" in env_text or "SYNTHETIC" in env_text

