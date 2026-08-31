proc require_file {label path} {
    if {$path eq ""} {
        error "$label is empty"
    }
    if {![file exists $path]} {
        error "missing $label: $path"
    }
    if {![file readable $path]} {
        error "$label is not readable: $path"
    }
}

proc read_support_models {} {
    global liberty_files model_files
    foreach liberty_file $liberty_files {
        require_file "liberty file" $liberty_file
        yosys read_liberty -ignore_miss_func -ignore_miss_data_latch $liberty_file
    }
    foreach model_file $model_files {
        require_file "LEC model file" $model_file
        yosys read_verilog -sv $model_file
    }
}

proc normalize_design {top_design} {
    yosys hierarchy -top $top_design
    yosys proc
    yosys memory
    yosys async2sync
    yosys flatten
    yosys splitnets -ports -format __v
    yosys opt_clean -purge
}

proc build_design {stash_name top_design netlist_file} {
    read_support_models
    yosys read_verilog -sv $netlist_file
    normalize_design $top_design
    yosys design -stash $stash_name
}

proc write_failure_artifacts {reason} {
    global status_file equiv_status_file failed_rtlil_file failed_verilog_file
    set handle [open $status_file "w"]
    puts $handle "Yosys LEC did not prove equivalence."
    puts $handle ""
    puts $handle "Reason:"
    puts $handle $reason
    close $handle

    catch {yosys tee -o $equiv_status_file equiv_status}
    catch {yosys write_rtlil $failed_rtlil_file}
    catch {yosys write_verilog -noattr $failed_verilog_file}
}

proc run_equivalence {} {
    global top_design blacklist_file use_undef equiv_status_file
    yosys design -copy-from gold -as gold $top_design
    yosys design -copy-from gate -as gate $top_design
    if {$blacklist_file ne ""} {
        require_file "LEC blacklist" $blacklist_file
        yosys equiv_make -blacklist $blacklist_file gold gate equiv
    } else {
        yosys equiv_make gold gate equiv
    }
    yosys hierarchy -top equiv
    yosys opt_clean -purge

    if {$use_undef} {
        yosys equiv_simple -undef
        yosys equiv_induct -undef
    } else {
        yosys equiv_simple
        yosys equiv_induct
    }
    yosys tee -o $equiv_status_file equiv_status

    set handle [open $equiv_status_file "r"]
    set status_text [read $handle]
    close $handle
    if {![regexp {Equivalence successfully proven!} $status_text]
        && ![regexp {Found a total of 0 unproven \$equiv cells\.} $status_text]} {
        error "equivalence proof has unproven cells; see $equiv_status_file"
    }
}

set script_dir [file dirname [file normalize [info script]]]
source [file normalize [file join $script_dir .. data lec_config.tcl]]
file mkdir $report_dir

require_file "golden netlist" $golden_file
require_file "gate netlist" $gate_file

set result [catch {
    build_design gold $top_design $golden_file
    yosys design -reset
    build_design gate $top_design $gate_file
    yosys design -reset
    run_equivalence
} message]

if {$result != 0} {
    write_failure_artifacts $message
    exit 1
}

set handle [open $status_file "w"]
puts $handle "Yosys LEC completed with proven equivalence."
puts $handle "Golden: $golden_file"
puts $handle "Gate: $gate_file"
close $handle
