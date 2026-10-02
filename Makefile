# Makefile for TACo-ISP KV260 Co-design Project
PYTHON ?= python3

.PHONY: help test test-fast tb vectors regs demo tables figs clean

help:
	@echo "TACo-ISP Build & Test Shortcuts"
	@echo "  make test        : Run all 35 pytest unit and bit-exact tests"
	@echo "  make test-fast   : Run quick tests (skipping 1080p full frame)"
	@echo "  make tb          : Compile C++ host testbench"
	@echo "  make vectors     : Generate test vectors for Vitis HLS simulation"
	@echo "  make regs        : Generate default registers (default.txt, tone_basis.txt)"
	@echo "  make demo        : Generate synthetic demo results for pipeline check"
	@echo "  make tables      : Generate LaTeX & Markdown summary tables (T-A1 to T-B5)"
	@echo "  make figs        : Generate publication vector PDF figures"
	@echo "  make clean       : Clean temporary build files and caches"

test:
	pytest -v

test-fast:
	pytest -v -m "not slow"

tb:
	g++ -O3 -Wall -std=c++17 -DTACO_HOST -Ihw/hls/common -Ihw/hls/isp -Ihw/hls/s2t hw/hls/tb/tb_host.cpp -o hw/hls/tb/tb_host

vectors:
	$(PYTHON) tools/make_tb_vectors.py

regs:
	$(PYTHON) tools/make_default_regs.py

demo:
	$(PYTHON) tools/make_demo_results.py

tables:
	$(PYTHON) analysis/make_tables.py --in results/summary --out tables/out

figs:
	$(PYTHON) analysis/plots.py --summary results/summary --out figs

clean:
	rm -rf build/ __pycache__ .pytest_cache *.log *.jou
