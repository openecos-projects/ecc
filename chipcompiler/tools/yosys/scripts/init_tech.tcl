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

# The names of the Liberty cells loaded into the current design, taken from
# yosys's own module listing. A Liberty cell name may contain "/", which is
# also what separates a cell from its pin in a selection record, so the set of
# cell names has to come from an authoritative listing rather than from
# guessing where a record splits.
proc liberty_module_names {} {
	global tmp_dir
	set out_file "${tmp_dir}/liberty_modules.txt"
	yosys tee -q -o $out_file ls
	set fh [open $out_file "r"]
	set text [read $fh]
	close $fh
	file delete $out_file
	set names {}
	set listing 0
	foreach line [split $text "\n"] {
		if {!$listing} {
			set listing [string match "*modules:" [string trim $line]]
			continue
		}
		# The listing is indented; anything flush left ends it.
		if {[string trim $line] eq ""} {
			continue
		}
		if {![string match " *" $line] && ![string match \t* $line]} {
			break
		}
		lappend names [string trim $line]
	}
	return $names
}

# The masters whose pins the mapping resolves. Every caller of
# liberty_cell_pins passes one of these, so the index can select each master's
# pins under its own exact name instead of parsing a combined listing: "/" is
# legal in both a cell name and a pin name, so where a selection record splits
# cannot be recovered from the record itself.
proc liberty_configured_masters {} {
	set masters {}
	foreach variable {
		tie_high_cell tie_low_cell latch_cell_n latch_cell_p
		latch_cell_nn0 latch_cell_nn1 latch_cell_pn0 latch_cell_pn1
		inverter_cell tbuf_cell
	} {
		upvar #0 $variable value
		if {[info exists value] && $value ne "" && [lsearch -exact $masters $value] < 0} {
			lappend masters $value
		}
	}
	return $masters
}

# Each configured master's pin names, keyed "<cell>/<direction>", read in an
# isolated scratch design so the blackbox modules used by dfflibmap/abc above
# are left untouched. Built once per run: a full PDK's Liberty set is hundreds
# of megabytes, and re-reading it per lookup dominated synthesis.
proc liberty_pin_index {} {
	global lib_list tmp_dir liberty_pins liberty_cells liberty_indexed
	if {[info exists liberty_cells]} {
		return
	}
	file mkdir $tmp_dir
	set liberty_pins [dict create]
	set liberty_cells [dict create]
	set liberty_indexed [dict create]
	yosys design -push
	foreach file $lib_list {
		yosys read_liberty -ignore_miss_func -ignore_miss_dir -ignore_buses "$file"
	}
	foreach name [liberty_module_names] {
		dict set liberty_cells $name 1
	}
	set out_file "${tmp_dir}/liberty_pins.txt"
	foreach cell [liberty_configured_masters] {
		if {![dict exists $liberty_cells $cell]} {
			continue
		}
		dict set liberty_indexed $cell 1
		foreach direction {i o} {
			# -module takes the name as its own argument, so a cell name
			# containing "/" addresses correctly; selection syntax cannot.
			yosys tee -q -o $out_file select -module $cell -list "${direction}:*"
			set fh [open $out_file "r"]
			set text [string trim [read $fh]]
			close $fh
			set prefix "${cell}/"
			foreach line [split $text "\n"] {
				set record [string trim $line]
				# The cell is known, so the pin is whatever follows its name.
				if {[string first $prefix $record] != 0} {
					continue
				}
				dict lappend liberty_pins "${cell}/${direction}" \
					[string range $record [string length $prefix] end]
			}
		}
	}
	file delete $out_file
	yosys design -pop
}

# A configured master's pin names on a given direction; empty if it declares
# none there. A cell absent from the libraries is reported as absent, so a
# master misnamed in the PDK does not surface as a missing pin on a cell that
# does not exist.
proc liberty_cell_pins {cell direction} {
	global liberty_pins liberty_cells liberty_indexed
	liberty_pin_index
	if {![dict exists $liberty_cells $cell]} {
		return -code error "cell $cell is not in the loaded Liberty libraries"
	}
	if {![dict exists $liberty_indexed $cell]} {
		return -code error "cell $cell was not indexed: add its PDK field to\
			liberty_configured_masters"
	}
	set key "${cell}/${direction}"
	if {[dict exists $liberty_pins $key]} {
		return [dict get $liberty_pins $key]
	}
	return {}
}

# A cell's only output pin. Used wherever one output is the whole contract:
# tie, inverter and tri-state masters. A multi-output Liberty entry is a hard
# error rather than a guess -- picking by name would silently wire a design to
# an inverted output of an otherwise plausible master.
proc liberty_single_output_pin {cell} {
	set pins [liberty_cell_pins $cell "o"]
	if {[llength $pins] != 1} {
		return -code error "cell $cell: expected exactly one output pin, got: $pins"
	}
	return [lindex $pins 0]
}

# A latch master's non-inverted data output, which $_DLATCH_*_ requires.
# Direction and output count cannot establish polarity -- a master exposing
# only the complement looks identical -- so this relies on the Q naming
# convention latch libraries follow, and refuses anything else rather than
# wiring a complement straight through and inverting the design. The
# convention holds for latches only, hence a separate proc from
# liberty_single_output_pin.
proc liberty_latch_output_pin {cell} {
	set pins [liberty_cell_pins $cell "o"]
	if {[lsearch -exact $pins "Q"] >= 0} {
		return "Q"
	}
	return -code error "latch cell $cell: no non-inverting output pin Q; outputs are: $pins"
}

# A Liberty name as a Verilog identifier, for the generated techmap. Liberty
# permits characters a bare identifier may not contain, so every name taken
# from a library is escaped: a backslash, the name, and the whitespace that
# terminates the escape.
proc verilog_id {name} {
	return "\\${name} "
}

# A cell's single input pin; only valid for single-input cells (inverters).
proc liberty_input_pin {cell} {
	set pins [liberty_cell_pins $cell "i"]
	if {[llength $pins] != 1} {
		return -code error "cell $cell: expected exactly one input pin, got: $pins"
	}
	return [lindex $pins 0]
}

# A cell's input pins minus the roles the PDK names (data/reset/set). Every
# named role must really exist in the Liberty, so a master whose pins were
# renamed fails loudly instead of producing a techmap wired to a missing pin.
proc liberty_unnamed_input_pins {cell named} {
	set inputs [liberty_cell_pins $cell "i"]
	foreach pin $named {
		if {[lsearch -exact $inputs $pin] < 0} {
			return -code error "cell $cell: Liberty has no input pin $pin; inputs are: $inputs"
		}
	}
	set rest {}
	foreach pin $inputs {
		if {[lsearch -exact $named $pin] < 0} {
			lappend rest $pin
		}
	}
	return $rest
}

# The one input left over once the named roles are accounted for: a latch's
# enable, or a tri-state buffer's output enable. Ambiguity is an error.
proc liberty_enable_pin {cell named} {
	set rest [liberty_unnamed_input_pins $cell $named]
	if {[llength $rest] != 1} {
		return -code error "cell $cell: expected one enable input besides $named, got: $rest"
	}
	return [lindex $rest 0]
}

# for hilomap
set tech_cell_tiehi ""
set tech_cell_tielo ""
if {$tie_high_cell ne "" && $tie_low_cell ne ""} {
	set tech_cell_tiehi "$tie_high_cell [liberty_single_output_pin $tie_high_cell]"
	set tech_cell_tielo "$tie_low_cell [liberty_single_output_pin $tie_low_cell]"
}
