open_project -reset hls_isp_proj
set_top isp_core
add_files isp_core.cpp
add_files -tb isp_core_tb.cpp
open_solution -reset "sol1" -flow_target vivado
set_part {xck26-sfvc784-2LV-c}
create_clock -period 3.33 -name default
csim_design
csynth_design
export_design -format ip_catalog -output ./ip_repo/isp_core.zip
exit