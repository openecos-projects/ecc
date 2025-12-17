# This script expects 2 arguments: <input_def_path> <output_lef_path>
# And 3 environment variables: <MAGIC_SCRIPTS_DIR> <TECH_LEF> <CELL_GDS>

if {$argc < 2} {
    puts stderr "TCL ERROR: Not enough arguments. Expected at least 2 arguments at the end of ARGV, got total $argc."
    puts stderr "TCL ARGV: $argv"
    exit 1
}

# Extract the last two arguments from the $argv list
set input_def_path  [lindex $argv [expr {$argc - 2}]]
set output_lef_path [lindex $argv [expr {$argc - 1}]]

drc off
source $::env(MAGIC_SCRIPTS_DIR)/read.tcl

read_tech_lef
read_pdk_gds
# read_macro_gds
# read_extra_gds
# load (REFRESHLAYOUT?)

def read $input_def_path

lef write $output_lef_path -hide
# -hide: set OBS
puts "\[INFO\]: lef write $output_lef_path"

exit 0
