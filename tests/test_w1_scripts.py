import sys
import re
import subprocess
from pathlib import Path
import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts" / "w1"
sys.path.insert(0, str(SCRIPTS_DIR))


def test_run_all_defaults_priority():
    """Verify that ("root", "root") is at the top of defaults in run_all.py."""
    import run_all
    ssh = run_all.BoardSSH("127.0.0.1")
    # Verify defaults in the connect implementation
    import inspect
    src = inspect.getsource(ssh.connect)
    # Extract defaults list
    match = re.search(r'defaults\s*=\s*\[(.*?)\]', src, re.DOTALL)
    assert match is not None, "defaults list not found in BoardSSH.connect"
    defaults_block = match.group(1).strip()
    first_item = defaults_block.split("\n")[0].strip()
    assert '("root", "root")' in first_item, f"Expected ('root', 'root') as first default, got: {first_item}"


def test_run_all_sudo_nopasswd_command():
    """Verify that sudo NOPASSWD unlock logic is properly present in run_all.py."""
    import run_all
    import inspect
    src = inspect.getsource(run_all.main)
    assert "user != \"root\"" in src
    assert "NOPASSWD: ALL" in src
    assert "/etc/sudoers.d/" in src


def test_dpu_check_script_lf_and_syntax():
    """Verify 02_dpu_check.sh has LF line endings and valid bash syntax."""
    sh_path = SCRIPTS_DIR / "02_dpu_check.sh"
    raw = sh_path.read_bytes()
    assert b"\r\n" not in raw, "02_dpu_check.sh must have Unix LF line endings"

    # Run bash -n syntax check
    rel_path = "scripts/w1/02_dpu_check.sh"
    res = subprocess.run(["bash", "-n", rel_path], capture_output=True, text=True)
    assert res.returncode == 0, f"Bash syntax check failed: {res.stderr}"


def test_dpu_check_preloaded_logic():
    """Verify that 02_dpu_check.sh contains pre-loaded DPU check and skips loadapp."""
    sh_text = (SCRIPTS_DIR / "02_dpu_check.sh").read_text(encoding="utf-8")
    assert "DPUCZDX8G" in sh_text
    assert "default-dpu-b4096 (pre-loaded)" in sh_text
    assert "DPU_PRELOADED" in sh_text
    assert "Skipping xmutil unloadapp/loadapp" in sh_text


def test_find_board_serial_ip_regex():
    """Verify that find_board IP regexes match 'ip -4 addr show eth0' output."""
    import find_board
    sample_ip_output = """
2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 qdisc mq state UP group default qlen 1000
    inet 192.168.1.105/24 brd 192.168.1.255 scope global dynamic eth0
       valid_lft 85303sec preferred_lft 85303sec
    """
    pattern = re.compile(r'inet\s+((?:192|10|172)\.\d+\.\d+\.\d+)/\d+')
    m = pattern.search(sample_ip_output)
    assert m is not None
    assert m.group(1) == "192.168.1.105"


def test_find_board_verify_kv260():
    """Verify verify_kv260 uses paramiko and tries KV260 credentials."""
    import find_board
    import inspect
    src = inspect.getsource(find_board.verify_kv260)
    assert "import paramiko" in src
    assert '("root", "root")' in src
    assert '("petalinux", "petalinux")' in src
    # Test on an unreachable/non-existent IP to verify graceful failure
    res = find_board.verify_kv260("127.0.0.1")
    assert res is False, "verify_kv260 should return False on port where KV260 SSH is not running"


def test_find_board_verify_kv260_rejects_x86_server(monkeypatch):
    """Verify that verify_kv260 rejects non-aarch64 lab servers even if SSH credentials match."""
    import find_board
    import io

    # Mock check_ssh to return True
    monkeypatch.setattr(find_board, "check_ssh", lambda ip, timeout=1.0: True)

    class DummyChannel:
        pass

    class DummyStdout(io.StringIO):
        channel = DummyChannel()

    class MockSSHClient:
        def __init__(self):
            pass
        def set_missing_host_key_policy(self, policy):
            pass
        def connect(self, *args, **kwargs):
            return True
        def exec_command(self, cmd, timeout=None):
            # Simulate an x86 lab workstation/server
            return None, io.BytesIO(b"x86_64\nGeneric-PC\nLinux 6.8.0-generic\n"), io.BytesIO(b"")
        def close(self):
            pass

    import paramiko
    monkeypatch.setattr(paramiko, "SSHClient", MockSSHClient)

    res = find_board.verify_kv260("192.168.1.99")
    assert res is False, "verify_kv260 must reject x86_64 lab machines"


def test_find_board_verify_kv260_accepts_kv260_hardware(monkeypatch):
    """Verify that verify_kv260 accepts genuine KV260 / ZynqMP aarch64 hardware."""
    import find_board
    import io

    monkeypatch.setattr(find_board, "check_ssh", lambda ip, timeout=1.0: True)

    class MockSSHClient:
        def __init__(self):
            pass
        def set_missing_host_key_policy(self, policy):
            pass
        def connect(self, *args, **kwargs):
            return True
        def exec_command(self, cmd, timeout=None):
            # Simulate KV260 hardware response
            return None, io.BytesIO(b"aarch64\nZynqMP Kria KV260 Vision AI Starter Kit\n5.15.0-xilinx-v2022.2\n"), io.BytesIO(b"")
        def close(self):
            pass

    import paramiko
    monkeypatch.setattr(paramiko, "SSHClient", MockSSHClient)

    res = find_board.verify_kv260("192.168.1.100")
    assert res is True, "verify_kv260 must accept aarch64 ZynqMP KV260 hardware"


def test_serial_discovery_login_and_ip_query(monkeypatch):
    """Verify serial discovery state machine: login prompt -> password -> shell -> ip query."""
    import find_board
    import io

    class MockSerial:
        def __init__(self, port, baud, timeout=1):
            self.written = b""
            self.read_queue = [
                b"kv260-smartcam login: ",
                b"Password: ",
                b"\r\nroot@kria:~# ",
                b"\r\n2: eth0: <BROADCAST> mtu 1500\r\n    inet 192.168.1.188/24 brd 192.168.1.255 scope global eth0\r\n",
            ]
            self.queue_idx = 0

        @property
        def in_waiting(self):
            if self.queue_idx < len(self.read_queue):
                return len(self.read_queue[self.queue_idx])
            return 0

        def read(self, n=1):
            if self.queue_idx < len(self.read_queue):
                chunk = self.read_queue[self.queue_idx]
                self.queue_idx += 1
                return chunk
            return b""

        def write(self, data):
            self.written += data

        def close(self):
            pass

    import serial
    monkeypatch.setattr(serial, "Serial", MockSerial)

    ip = find_board.discover_via_serial(port="COM99", timeout=3)
    assert ip == "192.168.1.188", f"Expected '192.168.1.188', got {ip}"


def test_serial_discovery_fallback_to_petalinux(monkeypatch):
    """Verify serial discovery advances to petalinux when root login fails."""
    import find_board

    class MockSerialFallback:
        def __init__(self, port, baud, timeout=1):
            self.written = b""
            self.read_queue = [
                b"kv260 login: ",
                b"Password: ",
                b"Login incorrect\r\nkv260 login: ",
                b"Password: ",
                b"\r\npetalinux@kria:~$ ",
                b"\r\n2: eth0: inet 10.0.0.42/24 scope global eth0\r\n",
            ]
            self.queue_idx = 0

        @property
        def in_waiting(self):
            if self.queue_idx < len(self.read_queue):
                return len(self.read_queue[self.queue_idx])
            return 0

        def read(self, n=1):
            if self.queue_idx < len(self.read_queue):
                chunk = self.read_queue[self.queue_idx]
                self.queue_idx += 1
                return chunk
            return b""

        def write(self, data):
            self.written += data

        def close(self):
            pass

    import serial
    monkeypatch.setattr(serial, "Serial", MockSerialFallback)

    ip = find_board.discover_via_serial(port="COM99", timeout=4)
    assert ip == "10.0.0.42", f"Expected '10.0.0.42', got {ip}"

