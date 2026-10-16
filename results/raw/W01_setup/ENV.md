# ENV.md — W01 Board Setup
> Tự động sinh bởi `01_board_setup.sh`

## Thông tin Hệ thống
```
Ngày giờ:      2026-10-16T01:53:51-07:00
Hostname:      xilinx-kv260-starterkit-20222
Kernel:        5.15.36-xilinx-v2022.2
Architecture:  aarch64
OS:
ID=petalinux
NAME="PetaLinux"
VERSION="2022.2_release_S10071807 (honister)"
VERSION_ID=2022.2_release_s10071807
PRETTY_NAME="PetaLinux 2022.2_release_S10071807 (honister)"

--- CPU ---
4
 cores
processor	: 0
BogoMIPS	: 199.99
Features	: fp asimd aes pmull sha1 sha2 crc32 cpuid
CPU implementer	: 0x41
CPU architecture: 8
CPU variant	: 0x0
CPU part	: 0xd03
CPU revision	: 4

processor	: 1
BogoMIPS	: 199.99
Features	: fp asimd aes pmull sha1 sha2 crc32 cpuid
CPU implementer	: 0x41
CPU architecture: 8
CPU variant	: 0x0
CPU part	: 0xd03
CPU revision	: 4

processor	: 2
BogoMIPS	: 199.99

--- Memory ---
               total        used        free      shared  buff/cache   available
Mem:           3.8Gi       181Mi       3.3Gi        18Mi       325Mi       3.5Gi
Swap:             0B          0B          0B

--- Disk ---
Filesystem      Size  Used Avail Use% Mounted on
devtmpfs        1.2G  4.0K  1.2G   1% /dev
/dev/mmcblk1p2   58G  6.7G   49G  13% /
tmpfs           2.0G     0  2.0G   0% /dev/shm
tmpfs           786M   18M  769M   3% /run
tmpfs           4.0M     0  4.0M   0% /sys/fs/cgroup
tmpfs           2.0G  8.0K  2.0G   1% /tmp
tmpfs           2.0G  244K  2.0G   1% /var/volatile
/dev/mmcblk1p1   76M   49M   28M  64% /boot
tmpfs           393M     0  393M   0% /run/user/0
```

## Network
```
        inet 192.168.0.134  netmask 255.255.255.0  broadcast 192.168.0.255
        ether 00:0a:35:2b:9e:f2  txqueuelen 1000  (Ethernet)
        inet 127.0.0.1  netmask 255.0.0.0
```

## Phần mềm đã cài
```
python3: Python 3.9.9
gcc: gcc (GCC) 11.2.0
g++: g++ (GCC) 11.2.0
cmake: cmake version 3.21.1
make: GNU Make 4.3
git: git version 2.33.0
v4l2-ctl: v4l2-ctl: unrecognized option '--version'
INSTALLED
media-ctl: INSTALLED (/usr/bin/media-ctl)

--- Python3 packages (VART/XIR) ---
vart: OK (module loaded)
xir: OK (module loaded)
```

## DPU & Accelerator
### xmutil listapps
```
                     Accelerator          Accel_type                            Base           Base_type      #slots(PL+AIE)         Active_slot

           kv260-benchmark-b4096            XRT_FLAT           kv260-benchmark-b4096            XRT_FLAT               (0+0)                  0,
                k26-starter-kits            XRT_FLAT                k26-starter-kits            XRT_FLAT               (0+0)                  -1
```

### DPU Overlay Loaded
```
App: default-dpu-b4096 (pre-loaded)
```

### xdputil query
```
{
    "DPU IP Spec":{
        "DPU Core Count":1,
        "IP version":"v4.1.0",
        "generation timestamp":"2022-11-30 19-15-00",
        "git commit id":"ce8dd1",
        "git commit time":2022113019,
        "regmap":"1to1 version"
    },
    "VAI Version":{
        "libvaip-core.so":"Xilinx vaip Version: 1.0.0-a176db67b19f94b0a31f9d24ef80322efe4494ad  2022-12-27-01:24:22 ",
        "libvart-runner.so":"Xilinx vart-runner Version: 3.0.0-2efa5fe1e56c2b2c8a7e71e9fc1636242dd50a9f  2022-12-27-00:47:05 ",
        "libvitis_ai_library-dpu_task.so":"Xilinx vitis_ai_library dpu_task Version: 3.0.0-1cccff04dc341c4a6287226828f90aed56005f4f  2022-12-20 10:29:01 [UTC] ",
        "libxir.so":"Xilinx xir Version: xir-9204ac72103092a7b253a0c23ec7471481656940 2022-12-27-00:46:16",
        "target_factory":"target-factory.3.0.0 860ed0499ab009084e2df3004eeb9ae710c26351"
    },
    "kernels":[
        {
            "DPU Arch":"DPUCZDX8G_ISA1_B4096",
            "DPU Frequency (MHz)":300,
            "IP Type":"DPU",
            "Load Parallel":2,
            "Load augmentation":"enable",
            "Load minus mean":"disable",
            "Save Parallel":2,
            "XRT Frequency (MHz)":300,
            "cu_addr":"0xa0010000",
            "cu_handle":"0xaaaafac3aab0",
            "cu_idx":0,
            "cu_mask":1,
            "cu_name":"DPUCZDX8G:DPUCZDX8G_1",
            "device_id":0,
            "fingerprint":"0x101000056010407",
            "name":"DPU Core 0"
        }
    ]
}
```
