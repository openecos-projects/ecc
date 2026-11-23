# Copyright (c) 2022 ETH Zurich and University of Bologna.
# Licensed under the Apache License, Version 2.0, see LICENSE for details.
# SPDX-License-Identifier: Apache-2.0
#
# Authors:
# - Philippe Sauter <phsauter@iis.ee.ethz.ch>

# All paths relative to yosys/

# pre-formated for easier use in yosys commands
# TODO: Distinguish between stdcell and other libraries?
set liberty_args_list [lmap lib $lib_list {list "-liberty" $lib}]
set liberty_args [concat {*}$liberty_args_list]
# only the standard cells
set tech_cells_args_list [lmap lib $lib_stdcell_list {list "-liberty" $lib}]
set tech_cells_args [concat {*}$tech_cells_args_list]

# read library files
foreach file $lib_list {
	yosys read_liberty -lib "$file"
}

# A cell's pin names on a given direction, read from the loaded Liberty in
# an isolated scratch design so the blackbox modules used by dfflibmap/abc
# above are left untouched.
proc liberty_cell_pins {cell direction} {
	global lib_list tmp_dir
	file mkdir $tmp_dir
	yosys design -push
	foreach file $lib_list {
		yosys read_liberty -ignore_miss_func -ignore_miss_dir -ignore_buses "$file"
	}
	set out_file "${tmp_dir}/liberty_pins.txt"
	yosys tee -q -o $out_file select -list "\\${cell}/${direction}:*"
	yosys design -pop
	set fh [open $out_file "r"]
	set text [string trim [read $fh]]
	close $fh
	file delete $out_file
	set pins {}
	if {$text ne ""} {
		foreach line [split $text "\n"] {
			if {[string first "/" $line] >= 0} {
				lappend pins [lindex [split $line "/"] 1]
			}
		}
	}
	return $pins
}

# A cell's single output pin. Latch libraries may declare a complementary
# QN alongside Q; Q is the conventional non-inverted data output.
proc liberty_output_pin {cell} {
	set pins [liberty_cell_pins $cell "o"]
	if {[llength $pins] == 1} {
		return [lindex $pins 0]
	}
	if {[lsearch -exact $pins "Q"] >= 0} {
		return "Q"
	}
	return -code error "cell $cell: expected exactly one output pin or a Q pin, got: $pins"
}

# A tie cell's output pin: unlike liberty_output_pin, no Q fallback — a tie
# cell is expected to have exactly one output, so a multi-output Liberty
# entry (e.g. accidentally pointing at a latch master) is a hard error.
proc liberty_tie_output_pin {cell} {
	set pins [liberty_cell_pins $cell "o"]
	if {[llength $pins] != 1} {
		return -code error "tie cell $cell: expected exactly one output pin, got: $pins"
	}
	return [lindex $pins 0]
}

# A cell's single input pin; only valid for single-input cells (inverters).
proc liberty_input_pin {cell} {
	set pins [liberty_cell_pins $cell "i"]
	if {[llength $pins] != 1} {
		return -code error "cell $cell: expected exactly one input pin, got: $pins"
	}
	return [lindex $pins 0]
}

# for hilomap
set tech_cell_tiehi ""
set tech_cell_tielo ""
if {$tie_high_cell ne "" && $tie_low_cell ne ""} {
	set tech_cell_tiehi "$tie_high_cell [liberty_tie_output_pin $tie_high_cell]"
	set tech_cell_tielo "$tie_low_cell [liberty_tie_output_pin $tie_low_cell]"
}
