#!/bin/bash
# ============================================================================
# TACo-ISP — W01 Vitis AI Demo Script (ĐV-4: Run Vitis AI Library samples)
# Chạy demo C++ & Python trên KV260 để xác nhận VART hoạt động
# ============================================================================
set -euo pipefail

LOG_DIR="$HOME/taco-isp/results/raw/W01_setup"
DEMO_LOG="$LOG_DIR/vitis_ai_demo.log"

echo "============================================"
echo "  TACo-ISP W01: Vitis AI Library Demo"
echo "  $(date -Iseconds)"
echo "============================================" | tee "$DEMO_LOG"

# --- 1. Kiểm tra VART Runtime ---
echo ""
echo ">>> [1/6] Checking VART Runtime..." | tee -a "$DEMO_LOG"

# Check C++ libraries
echo "--- C++ Libraries ---" | tee -a "$DEMO_LOG"
set +o pipefail
for lib in libvart-runner.so libxir.so libxrt_coreutil.so; do
    if ldconfig -p 2>/dev/null | grep -q "$lib" || find /usr/lib -name "$lib" 2>/dev/null | head -1 | grep -q .; then
        echo "  [✓] $lib found" | tee -a "$DEMO_LOG"
    else
        echo "  [✗] $lib NOT FOUND" | tee -a "$DEMO_LOG"
    fi
done
set -o pipefail

# Check Python
echo "--- Python ---" | tee -a "$DEMO_LOG"
python3 -c "
import sys
print(f'  Python: {sys.version}')
try:
    import vart
    print(f'  [✓] vart imported')
except ImportError as e:
    print(f'  [✗] vart: {e}')
try:
    import xir
    print(f'  [✓] xir imported')
except ImportError as e:
    print(f'  [✗] xir: {e}')
" 2>&1 | tee -a "$DEMO_LOG"

# --- 2. Tìm model xmodel có sẵn ---
echo ""
echo ">>> [2/6] Searching for xmodel files..." | tee -a "$DEMO_LOG"

XMODEL=""
MODEL_DIRS="/usr/share/vitis_ai_library/models /opt/xilinx/share/vitis_ai_library/models $HOME/.vitis_ai/models"
set +o pipefail
for dir in $MODEL_DIRS; do
    if [ -d "$dir" ]; then
        echo "  Scanning $dir..." | tee -a "$DEMO_LOG"
        find "$dir" -name "*.xmodel" 2>/dev/null | head -10 | tee -a "$DEMO_LOG" || true
        # Prefer yolox_nano or resnet50
        for m in $(find "$dir" -name "*.xmodel" 2>/dev/null); do
            if echo "$m" | grep -qi "yolox\|resnet\|classification"; then
                XMODEL="$m"
                break
            fi
        done
    fi
done

if [ -z "$XMODEL" ]; then
    echo "  [!] No xmodel found, will try xdputil benchmark with any available model" | tee -a "$DEMO_LOG"
    XMODEL=$(find /usr/share /opt -name "*.xmodel" 2>/dev/null | head -1 || echo "")
fi
set -o pipefail

echo "  Selected model: ${XMODEL:-NONE}" | tee -a "$DEMO_LOG"

# --- 3. Benchmark DPU (nếu có model) ---
echo ""
echo ">>> [3/6] DPU Benchmark..." | tee -a "$DEMO_LOG"

if [ -n "$XMODEL" ] && command -v xdputil &>/dev/null; then
    echo "  Running: xdputil benchmark $XMODEL -t 4 (4 threads, 10s)" | tee -a "$DEMO_LOG"
    timeout 30 xdputil benchmark "$XMODEL" -t 4 2>&1 | tee -a "$DEMO_LOG"
    echo "  [✓] Benchmark done" | tee -a "$DEMO_LOG"
else
    echo "  [!] Skipped (no xmodel or xdputil)" | tee -a "$DEMO_LOG"
fi

# --- 4. Chạy C++ demo (nếu có) ---
echo ""
echo ">>> [4/6] C++ Demo..." | tee -a "$DEMO_LOG"

DEMO_CPP_DIRS="/usr/share/vitis_ai_library/samples /opt/xilinx/examples"
CPP_DEMO_RAN=false
set +o pipefail
for dir in $DEMO_CPP_DIRS; do
    if [ -d "$dir" ]; then
        echo "  Found samples dir: $dir" | tee -a "$DEMO_LOG"
        ls "$dir" 2>/dev/null | head -10 | tee -a "$DEMO_LOG" || true

        # Try classification demo
        if [ -d "$dir/classification" ]; then
            echo "  Trying classification demo..." | tee -a "$DEMO_LOG"
            cd "$dir/classification"
            if [ -f "build.sh" ]; then
                bash build.sh 2>&1 | tail -5 | tee -a "$DEMO_LOG" || true
            fi
            # Find a test image
            TEST_IMG=$(find /usr/share -name "*.jpg" -o -name "*.png" 2>/dev/null | head -1 || echo "")
            if [ -n "$TEST_IMG" ]; then
                ./test_classification resnet50 "$TEST_IMG" 2>&1 | tee -a "$DEMO_LOG" || true
                CPP_DEMO_RAN=true
            fi
        fi
        break
    fi
done
set -o pipefail

if [ "$CPP_DEMO_RAN" = false ]; then
    echo "  [!] No C++ demo found/runnable. Will test via Python instead." | tee -a "$DEMO_LOG"
fi

# --- 5. Chạy Python demo ---
echo ""
echo ">>> [5/6] Python VART Demo..." | tee -a "$DEMO_LOG"

if [ -n "$XMODEL" ]; then
    python3 - "$XMODEL" <<'PYEOF' 2>&1 | tee -a "$DEMO_LOG"
import sys
import time

try:
    import xir
    import vart

    xmodel_path = sys.argv[1]
    print(f"Loading model: {xmodel_path}")

    # Deserialize xmodel
    graph = xir.Graph.deserialize(xmodel_path)
    print(f"  Graph name: {graph.get_name()}")

    # Get subgraphs
    subgraphs = graph.get_root_subgraph().toposort_child_subgraph()
    dpu_subgraphs = [s for s in subgraphs if s.has_attr("device") and s.get_attr("device").upper() == "DPU"]
    print(f"  Total subgraphs: {len(subgraphs)}")
    print(f"  DPU subgraphs:   {len(dpu_subgraphs)}")

    if dpu_subgraphs:
        sg = dpu_subgraphs[0]
        print(f"  DPU subgraph[0]: {sg.get_name()}")

        # Create runner
        runner = vart.Runner.create_runner(sg, "run")
        input_tensors = runner.get_input_tensors()
        output_tensors = runner.get_output_tensors()

        print(f"  Input tensors:")
        for t in input_tensors:
            fixpos = t.get_attr('fix_point') if t.has_attr('fix_point') else 'N/A'
            print(f"    {t.name}: {t.dims} (fixpos={fixpos})")
        print(f"  Output tensors:")
        for t in output_tensors:
            fixpos = t.get_attr('fix_point') if t.has_attr('fix_point') else 'N/A'
            print(f"    {t.name}: {t.dims} (fixpos={fixpos})")

        print(f"\n  [✓] VART Runner created successfully!")

        # Quick inference test with random data
        import numpy as np
        input_shape = tuple(input_tensors[0].dims)
        dummy_input = np.random.randint(-128, 127, input_shape, dtype=np.int8)
        input_data = [dummy_input]
        output_data = [np.empty(tuple(t.dims), dtype=np.int8) for t in output_tensors]

        t0 = time.time()
        job_id = runner.execute_async(input_data, output_data)
        runner.wait(job_id)
        dt = (time.time() - t0) * 1000
        print(f"  [✓] Dummy inference: {dt:.1f} ms")

        # Run 100 iterations for FPS
        t0 = time.time()
        N = 100
        for _ in range(N):
            job_id = runner.execute_async(input_data, output_data)
            runner.wait(job_id)
        dt = time.time() - t0
        fps = N / dt
        print(f"  [✓] {N} iterations: {dt:.2f}s → {fps:.1f} FPS (single-thread)")

        del runner
    else:
        print("  [!] No DPU subgraph found — model may not be compiled for this DPU")

except Exception as e:
    print(f"  [ERROR] {e}")
    import traceback
    traceback.print_exc()
PYEOF
else
    echo "  [!] No xmodel available for Python demo" | tee -a "$DEMO_LOG"
fi

# --- 6. Tóm tắt ---
echo ""
echo ">>> [6/6] Summary" | tee -a "$DEMO_LOG"
echo "============================================" | tee -a "$DEMO_LOG"
echo "  VART Libraries:  $(ldconfig -p 2>/dev/null | grep -c vart || echo '?') found" | tee -a "$DEMO_LOG"
echo "  XModel:          ${XMODEL:-NONE}" | tee -a "$DEMO_LOG"
echo "  C++ Demo:        $([ "$CPP_DEMO_RAN" = true ] && echo 'OK' || echo 'SKIPPED')" | tee -a "$DEMO_LOG"
echo "  Demo log:        $DEMO_LOG" | tee -a "$DEMO_LOG"
echo "============================================" | tee -a "$DEMO_LOG"

# Append to ENV.md
ENV_FILE="$LOG_DIR/ENV.md"
echo "" >> "$ENV_FILE"
echo "## Vitis AI Demo Results" >> "$ENV_FILE"
echo '```' >> "$ENV_FILE"
tail -20 "$DEMO_LOG" >> "$ENV_FILE"
echo '```' >> "$ENV_FILE"

echo "[✓] ĐV-4 complete!"
