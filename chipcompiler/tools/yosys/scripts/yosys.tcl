#===========================================================
#   set parameter
#===========================================================
set DESIGN                  "$::env(TOP_NAME)"
set PDK_DIR                 "$::env(PDK_DIR)"
set SYNTH_STAT_TXT          "$::env(SYNTH_STAT_TXT)"
set SYNTH_CHECK_TXT         "$::env(SYNTH_CHECK_TXT)"
set SDC_FILE                "$::env(SDC_FILE)"
set NETLIST_FILE            "$::env(NETLIST_FILE)"
set VERILOG_FILES           "$::env(RTL_FILE)"
set VERILOG_INCLUDE_DIRS    "$::env(VERILOG_INCLUDE_DIRS)"
set CLOCK_PERIOD_PS         [expr 1000000.0 / $::env(CLK_FREQ_MHZ)]

set LIBERTY_FILE            "$PDK_DIR/lib/merged.lib"
set BLACKBOX_V_FILE         "$PDK_DIR/verilog/blackbox.v" 
set CLKGATE_MAP_FILE        "$PDK_DIR/verilog/cells_clkgate.v" 
set LATCH_MAP_FILE          "$PDK_DIR/verilog/cells_latch.v" 
set BLACKBOX_MAP_TCL        "$PDK_DIR/blackbox_map.tcl" 

set TIEHI_CELL_AND_PORT     "sky130_fd_sc_hs__conb_1 HI" 
set TIELO_CELL_AND_PORT     "sky130_fd_sc_hs__conb_1 LO" 
set MIN_BUF_CELL_AND_PORTS  "sky130_fd_sc_hs__buf_1 A X" 


#===========================================================
#   main running
#===========================================================
yosys -import

# Don't change these unless you know what you are doing
set stat_ext    "_stat.rep"
set gl_ext      "_gl.v"
set abc_script  "+read_constr,$SDC_FILE;strash;ifraig;retime,-D,{D},-M,6;strash;dch,-f;map,-p,-M,1,{D},-f;topo;dnsize;buffer,-p;upsize;"

# Setup verilog include directories
set vIdirsArgs ""
if {[info exist VERILOG_INCLUDE_DIRS]} {
    foreach dir $VERILOG_INCLUDE_DIRS {
        lappend vIdirsArgs "-I$dir"
    }
    set vIdirsArgs [join $vIdirsArgs]
}

# read verilog files
foreach file $VERILOG_FILES {
    read_verilog -sv {*}$vIdirsArgs $file
}

# Read blackbox stubs of standard/io/ip/memory cells. This allows for standard/io/ip/memory cell (or
# structural netlist support in the input verilog
read_verilog $BLACKBOX_V_FILE

# Apply toplevel parameters (if exist
if {[info exist VERILOG_TOP_PARAMS]} {
    dict for {key value} $VERILOG_TOP_PARAMS {
        chparam -set $key $value $DESIGN
    }
}

# Read platform specific mapfile for OPENROAD_CLKGATE cells
if {[info exist CLKGATE_MAP_FILE]} {
    read_verilog $CLKGATE_MAP_FILE
}

# Use hierarchy to automatically generate blackboxes for known memory macro.
# Pins are enumerated for proper mapping
if {[info exist BLACKBOX_MAP_TCL]} {
    source $BLACKBOX_MAP_TCL
}

# generic synthesis
synth  -top $DESIGN

# Optimize the design
opt -purge  

# technology mapping of latches
if {[info exist LATCH_MAP_FILE]} {
  techmap -map $LATCH_MAP_FILE
}

# technology mapping of flip-flops
dfflibmap -liberty $LIBERTY_FILE
opt -undriven

# Technology mapping for cells
abc -D $CLOCK_PERIOD_PS \
    -constr "$SDC_FILE" \
    -liberty $LIBERTY_FILE \
    -showtmp \
    -script $abc_script 

# technology mapping of constant hi- and/or lo-drivers
hilomap -singleton \
        -hicell {*}$TIEHI_CELL_AND_PORT \
        -locell {*}$TIELO_CELL_AND_PORT

# replace undef values with defined constants
setundef -zero

# Splitting nets resolves unwanted compound assign statements in netlist (assign {..} = {..}
splitnets

# insert buffer cells for pass through wires
insbuf -buf {*}$MIN_BUF_CELL_AND_PORTS

# remove unused cells and wires
opt_clean -purge

# reports
tee -o $SYNTH_CHECK_TXT check
tee -o $SYNTH_STAT_TXT stat -liberty $LIBERTY_FILE

# write synthesized design
write_verilog -noattr -noexpr -nohex -nodec $NETLIST_FILE
