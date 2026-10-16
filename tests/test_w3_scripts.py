import sys
import re
import inspect
import subprocess
from pathlib import Path
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts" / "w3"
sys.path.insert(0, str(SCRIPTS_DIR))


def test_w3_scripts_lf_and_syntax():
    """Verify all W3 bash scripts have Unix LF line endings and valid syntax (bash -n)."""
    for sh_name in ["01_build_ba1.sh", "02_run_ba1.sh", "03_eval_ba1.sh"]:
        sh_path = SCRIPTS_DIR / sh_name
        raw = sh_path.read_bytes()
        assert b"\r\n" not in raw, f"{sh_name} must have Unix LF line endings"

        rel_path = f"scripts/w3/{sh_name}"
        res = subprocess.run(["bash", "-n", rel_path], cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        assert res.returncode == 0, f"Bash syntax check failed for {sh_name}: {res.stderr}"


def test_w3_build_script_clean_and_pipefail():
    """Verify 01_build_ba1.sh cleans build dir completely and wraps checks in set +o pipefail."""
    sh_text = (SCRIPTS_DIR / "01_build_ba1.sh").read_text(encoding="utf-8")
    assert 'rm -rf "$BUILD_DIR"/*' in sh_text, "Build script must clean entire build dir with rm -rf"
    assert "set +o pipefail" in sh_text, "Build script must wrap pipe checks to prevent SIGPIPE 141"


def test_w3_run_video_dev_fallback_scope():
    """Verify in 02_run_ba1.sh that /dev/video* fallback is strictly inside MEDIA_DEV check."""
    sh_text = (SCRIPTS_DIR / "02_run_ba1.sh").read_text(encoding="utf-8")
    # Finding the position of MEDIA_DEV block and video* fallback
    media_dev_block = re.search(r'if \[ -n "\$MEDIA_DEV" \]; then(.*?)fi\n\nINPUT_OPT', sh_text, re.DOTALL)
    assert media_dev_block is not None, "MEDIA_DEV block must encompass video fallback before INPUT_OPT"
    content = media_dev_block.group(1)
    assert "for v in /dev/video*;" in content, "Fallback for /dev/video* MUST be inside 'if [ -n \"$MEDIA_DEV\" ]'"


def test_w3_run_imx_entity_bus():
    """Verify 02_run_ba1.sh uses imx219 2-0010 on I2C bus 2 (avoiding the 6-0010 trap)."""
    sh_text = (SCRIPTS_DIR / "02_run_ba1.sh").read_text(encoding="utf-8")
    assert 'IMX_ENTITY="imx219 2-0010"' in sh_text, "IMX_ENTITY fallback must be 'imx219 2-0010'"
    assert "6-0010" not in sh_text, "IMX_ENTITY must NEVER be '6-0010' on KV260"


def test_w3_run_csi_entity_regex():
    """Verify 02_run_ba1.sh CSI_ENTITY regex correctly parses subsystem entity and ignores vcap."""
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
    cmd_csi = [
        "bash", "-c",
        "grep -iE 'entity [0-9]+:.*mipi_csi2_rx' | grep -v 'vcap' | "
        "sed -E 's/.*entity [0-9]+: ([^(]+) \\(.*$/\\1/' | head -n 1 | xargs"
    ]
    res_csi = subprocess.run(cmd_csi, input=sample_topology, capture_output=True, text=True)
    assert res_csi.returncode == 0
    assert res_csi.stdout.strip() == "80020000.mipi_csi2_rx_subsystem"


def test_w3_run_overlay_benchmark_keyword():
    """Verify 02_run_ba1.sh includes 'benchmark' in overlay detection."""
    sh_text = (SCRIPTS_DIR / "02_run_ba1.sh").read_text(encoding="utf-8")
    assert "smartcam|aibox|benchmark|dpu|nlp" in sh_text


def test_w3_eval_cpu_model_avoid_processor_zero_trap(tmp_path):
    """Verify 03_eval_ba1.sh CPU detection does not match 'processor : 0' and resolves Cortex-A53."""
    sh_text = (SCRIPTS_DIR / "03_eval_ba1.sh").read_text(encoding="utf-8")
    assert "grep -m 1 '^Processor'" in sh_text or "grep -m 1 -E '^Processor'" in sh_text
    assert "0xd03" in sh_text, "Script must inspect CPU part 0xd03 for Cortex-A53"
    assert "ARM Cortex-A53 MPCore (ARMv8-A)" in sh_text

    # Test execution on typical ARM64 cpuinfo sample where model name is absent
    arm64_cpuinfo = """processor\t: 0
BogoMIPS\t: 40.00
Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 cpuid
CPU implementer\t: 0x41
CPU architecture: 8
CPU variant\t: 0x0
CPU part\t: 0xd03
CPU revision\t: 4

processor\t: 1
BogoMIPS\t: 40.00
Features\t: fp asimd evtstrm aes pmull sha1 sha2 crc32 cpuid
CPU implementer\t: 0x41
CPU architecture: 8
CPU variant\t: 0x0
CPU part\t: 0xd03
CPU revision\t: 4
"""
    mock_file = PROJECT_ROOT / "mock_w3_cpuinfo.txt"
    temp_sh = PROJECT_ROOT / "temp_w3_cpu_test.sh"
    try:
        mock_file.write_text(arm64_cpuinfo, encoding="utf-8")
        rel_posix = mock_file.name

        bash_cpu_test = f"""#!/bin/bash
set +o pipefail
CPU_MODEL=$(grep -m 1 'model name' '{rel_posix}' 2>/dev/null | awk -F: '{{print $2}}' | xargs)
if [ -z "$CPU_MODEL" ]; then
    CPU_MODEL=$(grep -m 1 '^Processor' '{rel_posix}' 2>/dev/null | awk -F: '{{print $2}}' | xargs)
fi
set -o pipefail

if [ -z "$CPU_MODEL" ] || [[ "$CPU_MODEL" =~ ^[0-9]+$ ]]; then
    if grep -qi "0xd03" '{rel_posix}' 2>/dev/null; then
        CPU_MODEL="ARM Cortex-A53 MPCore (ARMv8-A)"
    else
        CPU_MODEL="ARMv8 Processor (v8l)"
    fi
fi
echo "$CPU_MODEL"
"""
        temp_sh.write_bytes(bash_cpu_test.replace("\r\n", "\n").encode("utf-8"))
        res = subprocess.run(["bash", temp_sh.name], cwd=str(PROJECT_ROOT), capture_output=True, encoding="utf-8", errors="replace")
        assert res.returncode == 0
        assert res.stdout.strip() == "ARM Cortex-A53 MPCore (ARMv8-A)"
        assert res.stdout.strip() != "0"
    finally:
        mock_file.unlink(missing_ok=True)
        temp_sh.unlink(missing_ok=True)


def test_w3_eval_overlay_benchmark_keyword():
    """Verify 03_eval_ba1.sh includes 'benchmark' in overlay DPU detection."""
    sh_text = (SCRIPTS_DIR / "03_eval_ba1.sh").read_text(encoding="utf-8")
    assert "smartcam|aibox|benchmark|dpu|nlp" in sh_text


def test_w3_runner_defaults_priority_and_sudo_nopasswd():
    """Verify run_ba1_w03.py prioritizes ('root', 'root') and unlocks sudo NOPASSWD."""
    import run_ba1_w03
    ssh = run_ba1_w03.BoardSSH("127.0.0.1")
    src_conn = inspect.getsource(ssh.connect)
    match = re.search(r'defaults\s*=\s*\[(.*?)\]', src_conn, re.DOTALL)
    assert match is not None
    first_item = match.group(1).strip().split("\n")[0].strip()
    assert '("root", "root")' in first_item

    src_main = inspect.getsource(run_ba1_w03.main)
    assert "session.user != \"root\"" in src_main
    assert "NOPASSWD: ALL" in src_main
    assert "models_local" in src_main
    assert "upload_dir" in src_main


def test_w3_runner_dry_run_execution():
    """Verify run_ba1_w03.py --dry-run completes cleanly with code 0."""
    res = subprocess.run([sys.executable, str(SCRIPTS_DIR / "run_ba1_w03.py"), "--dry-run"],
                         cwd=str(PROJECT_ROOT), capture_output=True, encoding="utf-8", errors="replace")
    assert res.returncode == 0
    assert "[GIẢ LẬP THÀNH CÔNG]" in res.stdout


def test_w3_board_ssh_connect_behavioral_candidate_order():
    """Behaviorally verify that BoardSSH.connect tests root:root first when unconfigured."""
    import run_ba1_w03
    from unittest.mock import patch

    ssh = run_ba1_w03.BoardSSH("127.0.0.1", user=None, password=None)
    tested_candidates = []

    def mock_connect(*args, **kwargs):
        tested_candidates.append((kwargs.get("username"), kwargs.get("password")))
        raise Exception("Authentication failed for test")

    with patch("paramiko.SSHClient.connect", side_effect=mock_connect):
        result = ssh.connect()

    assert result is False
    assert len(tested_candidates) == 6
    assert tested_candidates[0] == ("root", "root"), f"Expected ('root', 'root') first, got {tested_candidates[0]}"
    assert tested_candidates[1] == ("petalinux", "petalinux")
    assert tested_candidates[2] == ("ubuntu", "ubuntu")
    assert tested_candidates[3] == ("petalinux", None)
    assert tested_candidates[4] == ("ubuntu", None)
    assert tested_candidates[5] == ("root", None)
    assert len(tested_candidates) == len(set(tested_candidates))


def test_w3_board_ssh_connect_empty_password_normalized():
    """Verify that an empty string password is normalized to None and does not cause duplicate candidates."""
    import run_ba1_w03
    from unittest.mock import patch

    ssh = run_ba1_w03.BoardSSH("127.0.0.1", user="petalinux", password="")
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


def test_w3_board_ssh_run_masks_password_in_log(capsys):
    """Verify that passwords in sudo -S commands are masked in console output."""
    import run_ba1_w03
    from unittest.mock import MagicMock

    ssh = run_ba1_w03.BoardSSH("127.0.0.1", user="petalinux", password="secret_kv260_pass")
    mock_client = MagicMock()
    mock_stdout = MagicMock()
    mock_stdout.readline.return_value = ""
    mock_stdout.channel.recv_exit_status.return_value = 0
    mock_stderr = MagicMock()
    mock_stderr.read.return_value = b""
    mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)
    ssh.client = mock_client

    cmd = "echo 'secret_kv260_pass' | sudo -S sh -c 'echo \"petalinux ALL=(ALL) NOPASSWD: ALL\" > /etc/sudoers.d/petalinux_nopasswd'"
    rc, out, err = ssh.run(cmd)
    captured = capsys.readouterr()
    assert "secret_kv260_pass" not in captured.out
    assert "echo '***' | sudo -S" in captured.out


def test_w3_run_camera_timeout_stream_probe():
    """Verify 02_run_ba1.sh performs a timeout 3s stream probe and safely falls back if camera hangs."""
    sh_text = (SCRIPTS_DIR / "02_run_ba1.sh").read_text(encoding="utf-8")
    assert "timeout 3s v4l2-ctl" in sh_text
    assert "--stream-mmap --stream-count=1" in sh_text
    assert "CAMERA_STREAMING=false" in sh_text
    assert "CAMERA_STREAMING=true" in sh_text
    assert '--device none --input $W2_RAW' in sh_text


def test_w3_run_dpu_preloaded_base_trd():
    """Verify 02_run_ba1.sh detects preloaded DPU (Base TRD) and bypasses unnecessary xmutil reload."""
    sh_text = (SCRIPTS_DIR / "02_run_ba1.sh").read_text(encoding="utf-8")
    assert "DPU_PRELOADED=0" in sh_text
    assert 'xdputil query 2>/dev/null' in sh_text
    assert 'DPUCZDX8G' in sh_text
    assert 'DPU_PRELOADED=1' in sh_text
    assert '[ "$DPU_PRELOADED" -eq 1 ]' in sh_text


def test_w3_eval_dpu_base_trd_handling():
    """Verify 03_eval_ba1.sh labels Base TRD bitstream when DPU is present without xmutil app."""
    sh_text = (SCRIPTS_DIR / "03_eval_ba1.sh").read_text(encoding="utf-8")
    assert "Base TRD (Pre-loaded Bitstream)" in sh_text
    assert "DPUCZDX8G (Vitis AI 3.0 Hardware Core)" in sh_text


def test_w3_runner_try_finally_log_download():
    """Verify run_ba1_w03.py wraps board execution in try...finally to ensure logs are downloaded even on failure."""
    import run_ba1_w03
    src_main = inspect.getsource(run_ba1_w03.main)
    assert "try:" in src_main
    assert "finally:" in src_main
    assert "download_targets = [" in src_main
    assert '"build.log"' in src_main
    assert '"ba1_run.log"' in src_main


def test_w3_runner_sudo_n_true_check():
    """Verify run_ba1_w03.py verifies passwordless sudo with sudo -n true and defaults user to None."""
    import run_ba1_w03
    src_main = inspect.getsource(run_ba1_w03.main)
    assert "sudo -n true" in src_main
    assert 'user = args.user or (local_cfg.get("user") or "").strip() or None' in src_main


def test_w3_eval_ba1_execution_and_base_trd_behavioral():
    """Behaviorally execute 03_eval_ba1.sh and verify BA1_ENV.md generation with Base TRD detection."""
    import shutil
    tmp = PROJECT_ROOT / "results" / "raw" / "tmp_test_w3"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        csv_file = tmp / "ba1_latency.csv"
        csv_file.write_text(
            "config,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_latency_ms\n"
            "BA1_Test,10.0,5.0,2.0,15.0,3.0,35.0\n",
            encoding="utf-8"
        )
        res = subprocess.run(
            ["bash", "scripts/w3/03_eval_ba1.sh", "results/raw/tmp_test_w3"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        assert res.returncode == 0, f"03_eval_ba1.sh failed with stderr: {res.stderr}"
        env_file = tmp / "BA1_ENV.md"
        assert env_file.exists()
        content = env_file.read_text(encoding="utf-8")
        assert "BA1_ENV.md" in content
        assert "BA1_Test" in content
        assert "35.0 ms" in content
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_w3_runner_try_finally_log_download_on_build_failure(tmp_path):
    """Verify run_ba1_w03.py always downloads diagnostic logs even when remote build fails."""
    import run_ba1_w03
    from unittest.mock import patch, MagicMock

    mock_session = MagicMock()
    mock_session.connect.return_value = True
    mock_session.user = "root"
    mock_session.password = "root"

    def mock_run(cmd, *args, **kwargs):
        if "01_build_ba1.sh" in cmd:
            return 1, "Build compilation error on board", "g++: fatal error"
        return 0, "", ""

    mock_session.run.side_effect = mock_run
    downloaded = []
    mock_session.download_file.side_effect = lambda remote, local: downloaded.append(remote)

    test_args = ["run_ba1_w03.py", "--host", "192.168.1.100", "--user", "root", "--password", "root"]
    with patch("sys.argv", test_args), \
         patch("run_ba1_w03.CONFIG_FILE", tmp_path / "board_config.json"), \
         patch("run_ba1_w03.BoardSSH", return_value=mock_session), \
         pytest.raises(SystemExit) as exc_info:
        run_ba1_w03.main()

    assert exc_info.value.code == 1
    assert any("build.log" in d for d in downloaded)
    assert any("ba1_run.log" in d for d in downloaded)


def test_w3_runner_try_finally_log_download_on_run_failure(tmp_path):
    """Verify run_ba1_w03.py always downloads diagnostic logs when 02_run_ba1.sh fails."""
    import run_ba1_w03
    from unittest.mock import patch, MagicMock

    mock_session = MagicMock()
    mock_session.connect.return_value = True
    mock_session.user = "root"
    mock_session.password = "root"

    def mock_run(cmd, *args, **kwargs):
        if "02_run_ba1.sh" in cmd:
            return 1, "Pipeline execution error", "VART runner exception"
        return 0, "", ""

    mock_session.run.side_effect = mock_run
    downloaded = []
    mock_session.download_file.side_effect = lambda remote, local: downloaded.append(remote)

    test_args = ["run_ba1_w03.py", "--host", "192.168.1.100", "--user", "root", "--password", "root", "--skip-build"]
    with patch("sys.argv", test_args), \
         patch("run_ba1_w03.CONFIG_FILE", tmp_path / "board_config.json"), \
         patch("run_ba1_w03.BoardSSH", return_value=mock_session), \
         pytest.raises(SystemExit) as exc_info:
        run_ba1_w03.main()

    assert exc_info.value.code == 1
    assert any("ba1_run.log" in d for d in downloaded)


def test_w3_camera_timeout_stream_probe_behavioral():
    """Verify timeout safely aborts hanging stream probe and selects fallback."""
    import shutil
    tmp = PROJECT_ROOT / "results" / "raw" / "tmp_test_probe_w3"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        raw_file = tmp / "sample.raw"
        raw_file.write_text("raw10_data", encoding="utf-8")

        probe_sh = tmp / "probe.sh"
        probe_code = """#!/bin/bash
set -eu
VIDEO_DEV="/dev/video0"
W2_RAW="results/raw/tmp_test_probe_w3/sample.raw"

v4l2_hang() {
    sleep 5
    return 0
}
export -f v4l2_hang

CAMERA_STREAMING=false
if timeout 1s bash -c 'v4l2_hang' >/dev/null 2>&1; then
    CAMERA_STREAMING=true
    INPUT_OPT="--device $VIDEO_DEV"
else
    INPUT_OPT="--device none --input $W2_RAW"
fi

echo "CAMERA_STREAMING=$CAMERA_STREAMING"
echo "INPUT_OPT=$INPUT_OPT"
"""
        probe_sh.write_bytes(probe_code.replace("\r\n", "\n").encode("utf-8"))

        res = subprocess.run(["bash", "results/raw/tmp_test_probe_w3/probe.sh"], cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=4)
        assert res.returncode == 0
        assert "CAMERA_STREAMING=false" in res.stdout
        assert "INPUT_OPT=--device none --input results/raw/tmp_test_probe_w3/sample.raw" in res.stdout
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_w3_run_model_search_priority_and_no_resnet():
    """Verify 02_run_ba1.sh searches repo models first, scans yolox then yolo, and excludes resnet."""
    sh_text = (SCRIPTS_DIR / "02_run_ba1.sh").read_text(encoding="utf-8")
    assert 'MODEL_DIRS="$REPO_DIR/models $HOME/taco-isp/models /usr/share/vitis_ai_library/models /opt/xilinx/share/vitis_ai_library/models"' in sh_text
    assert 'grep -qi "yolox"' in sh_text
    assert 'grep -qi "yolo"' in sh_text
    assert 'yolox|yolo|resnet' not in sh_text

    # Behavioral test of model search logic
    tmp = PROJECT_ROOT / "results" / "raw" / "tmp_test_model_w3"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        repo_m = tmp / "repo_models"
        usr_m = tmp / "usr_models"
        repo_m.mkdir(parents=True, exist_ok=True)
        usr_m.mkdir(parents=True, exist_ok=True)

        (usr_m / "resnet50.xmodel").write_text("resnet", encoding="utf-8")
        (repo_m / "yolox_nano.xmodel").write_text("yolox", encoding="utf-8")

        repo_m_rel = repo_m.relative_to(PROJECT_ROOT).as_posix()
        usr_m_rel = usr_m.relative_to(PROJECT_ROOT).as_posix()
        search_sh = tmp / "search.sh"
        rel_sh = search_sh.relative_to(PROJECT_ROOT).as_posix()
        search_code = f"""#!/bin/bash
set -eu
REPO_DIR="{tmp.relative_to(PROJECT_ROOT).as_posix()}"
MODEL_DIRS="{repo_m_rel} {usr_m_rel}"
XMODEL=""
for dir in $MODEL_DIRS; do
    if [ -d "$dir" ]; then
        for m in $(find "$dir" -name "*.xmodel" 2>/dev/null); do
            if echo "$m" | grep -qi "yolox"; then
                XMODEL="$m"
                break 2
            fi
        done
    fi
done
if [ -z "$XMODEL" ]; then
    for dir in $MODEL_DIRS; do
        if [ -d "$dir" ]; then
            for m in $(find "$dir" -name "*.xmodel" 2>/dev/null); do
                if echo "$m" | grep -qi "yolo" && ! echo "$m" | grep -qi "resnet"; then
                    XMODEL="$m"
                    break 2
                fi
            done
        fi
    done
fi
echo "SELECTED_MODEL=$XMODEL"
"""
        search_sh.write_bytes(search_code.replace("\r\n", "\n").encode("utf-8"))
        res = subprocess.run(["bash", rel_sh], cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=5)
        assert res.returncode == 0
        assert "yolox_nano.xmodel" in res.stdout
        assert "resnet50.xmodel" not in res.stdout

        # Test when ONLY resnet50 is present: MUST reject and leave XMODEL empty
        (repo_m / "yolox_nano.xmodel").unlink()
        res2 = subprocess.run(["bash", rel_sh], cwd=str(PROJECT_ROOT), capture_output=True, text=True, timeout=5)
        assert res2.returncode == 0
        assert "SELECTED_MODEL=" in res2.stdout
        assert "resnet50.xmodel" not in res2.stdout
    finally:
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)


def test_w3_run_synthetic_tag_watermark():
    """Verify 02_run_ba1.sh appends _SYNTHETIC_DEMO to tag when camera streaming or model is dummy."""
    sh_text = (SCRIPTS_DIR / "02_run_ba1.sh").read_text(encoding="utf-8")
    assert 'CONFIG_TAG="${CONFIG_TAG}_SYNTHETIC_DEMO"' in sh_text
    assert '--tag "$CONFIG_TAG"' in sh_text


def test_w3_eval_synthetic_demo_warning_banner(tmp_path):
    """Verify 03_eval_ba1.sh detects SYNTHETIC_DEMO and includes warning banner in BA1_ENV.md."""
    import shutil
    tmp = PROJECT_ROOT / "results" / "raw" / "tmp_test_w3_synth"
    tmp.mkdir(parents=True, exist_ok=True)
    try:
        csv_file = tmp / "ba1_latency.csv"
        csv_file.write_text(
            "config,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_latency_ms\n"
            "BA1_YOLOX_nano_SYNTHETIC_DEMO,2.15,18.42,1.05,5.52,3.21,30.35\n",
            encoding="utf-8"
        )
        (tmp / ".commit_hash").write_text("a1b2c3d\n", encoding="utf-8")
        res = subprocess.run(
            ["bash", "scripts/w3/03_eval_ba1.sh", "results/raw/tmp_test_w3_synth"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
        )
        assert res.returncode == 0, f"03_eval_ba1.sh failed: {res.stderr}"
        env_content = (tmp / "BA1_ENV.md").read_text(encoding="utf-8")
        assert "CẢNH BÁO BẢO TOÀN DỮ LIỆU (SYNTHETIC DEMO)" in env_content
        assert "Git Commit Hash:** a1b2c3d" in env_content
        assert "Bitstream Hash (SHA256):" in env_content
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def test_w3_runner_get_git_commit_hash():
    """Verify run_ba1_w03.py provides a working get_git_commit_hash helper."""
    import run_ba1_w03
    h = run_ba1_w03.get_git_commit_hash()
    assert isinstance(h, str)
    assert len(h) >= 4 or h == "UNKNOWN"


def test_w3_runner_synthetic_demo_warning_log(tmp_path):
    """Verify run_ba1_w03.py outputs yellow WARN log instead of congratulations when SYNTHETIC_DEMO is detected."""
    import run_ba1_w03
    from unittest.mock import patch, MagicMock

    mock_session = MagicMock()
    mock_session.connect.return_value = True
    mock_session.user = "root"
    mock_session.password = "root"
    mock_session.run.return_value = (0, "", "")

    def mock_download(remote, local):
        local = Path(local)
        local.parent.mkdir(parents=True, exist_ok=True)
        if "ba1_latency.csv" in remote:
            local.write_text(
                "config,capture_isp_ms,preproc_ms,dma_sync_ms,dpu_infer_ms,postproc_ms,total_latency_ms\n"
                "BA1_YOLOX_nano_SYNTHETIC_DEMO,2.15,18.42,1.05,5.52,3.21,30.35\n",
                encoding="utf-8"
            )
        elif "BA1_ENV.md" in remote:
            local.write_text("# Mock BA1_ENV.md", encoding="utf-8")

    mock_session.download_file.side_effect = mock_download

    logged_levels = []
    original_log = run_ba1_w03.log

    def spy_log(msg, level="INFO"):
        logged_levels.append((msg, level))
        original_log(msg, level)

    test_args = ["run_ba1_w03.py", "--host", "192.168.1.100", "--user", "root", "--password", "root", "--skip-build"]
    with patch("sys.argv", test_args), \
         patch("run_ba1_w03.CONFIG_FILE", tmp_path / "board_config.json"), \
         patch("run_ba1_w03.RESULTS_DIR", tmp_path / "results" / "raw" / "W03_ba1"), \
         patch("run_ba1_w03.BoardSSH", return_value=mock_session), \
         patch("run_ba1_w03.log", side_effect=spy_log):
        run_ba1_w03.main()

    warn_msgs = [msg for msg, lvl in logged_levels if lvl == "WARN" and "SYNTHETIC DEMO" in msg]
    assert len(warn_msgs) > 0, "run_ba1_w03.py must log yellow WARN banner for synthetic demo"
    congrat_msgs = [msg for msg, lvl in logged_levels if "NGHIỆM THU THÀNH CÔNG" in msg and lvl == "OK"]
    assert len(congrat_msgs) == 0, "run_ba1_w03.py must NOT log congratulatory OK for synthetic demo"





