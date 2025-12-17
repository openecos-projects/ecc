# This script expects 3 arguments: <input_gds_path> <top_module_name> <output_drc_report_path>
# And 2 environment variables: <TECH_LEF> <CELL_LEFS>

proc escape_json {str} {
    set replacements [list "\\" "\\\\" "\"" "\\\"" "\n" "\\n" "\r" "\\r" "\t" "\\t"]
    return [string map $replacements $str]
}

set top_name [lindex $argv [expr {$argc - 3}]]
set gds_file [lindex $argv [expr {$argc - 2}]]
set drc_rpt  [lindex $argv [expr {$argc - 1}]]

set pdk_tech_lef $::env(TECH_LEF)
set pdk_cell_lefs $::env(CELL_LEFS)

if {![file exists $gds_file]} {
    puts stderr "\[ERROR\]: GDS file not found: $gds_file"
    exit 1
} else {
    gds read $gds_file
    puts "\[INFO\]: gds read $gds_file"
}

set oscale [cif scale out]
set cell_name $top_name
magic::suspendall
puts stdout "\[INFO\]: Loading $cell_name\n"
flush stdout
load $cell_name
select top cell
expand
drc euclidean on
drc style drc(fast) 
drc check
set drc_result [drc listall why]

set total_errors 0
set error_dict [dict create]

# Group violations by error type
foreach {errtype coordlist} $drc_result {
    set violations [list]
    
    foreach coord $coordlist {
        set bllx [expr {$oscale * [lindex $coord 0]}]
        set blly [expr {$oscale * [lindex $coord 1]}]
        set burx [expr {$oscale * [lindex $coord 2]}]
        set bury [expr {$oscale * [lindex $coord 3]}]
        
        set bbox [format "\[%.3f, %.3f, %.3f, %.3f\]" $bllx $blly $burx $bury]
        lappend violations $bbox
        incr total_errors
    }
    
    if {[llength $violations] > 0} {
        dict set error_dict $errtype $violations
    }
}

# Write JSON output
set fout [open $drc_rpt w]
puts $fout "\{"
puts $fout "  \"top_module\": \"[escape_json $top_name]\","
puts $fout "  \"total_errors\": $total_errors,"
puts $fout "  \"errors\": \["

set first_type 1
dict for {errtype violations} $error_dict {
    if {!$first_type} {
        puts $fout ","
    }
    set first_type 0
    
    puts $fout "    \{"
    puts $fout "      \"type\": \"[escape_json $errtype]\","
    puts $fout "      \"violations\": \["
    
    set first_viol 1
    foreach bbox $violations {
        if {!$first_viol} {
            puts $fout ","
        }
        set first_viol 0
        puts -nonewline $fout "        $bbox"
    }
    
    if {[llength $violations] > 0} {
        puts $fout ""
    }
    puts $fout "      \]"
    puts -nonewline $fout "    \}"
}

if {[dict size $error_dict] > 0} {
    puts $fout ""
}
puts $fout "  \]"
puts $fout "\}"
close $fout

puts "\[INFO\]: DRC Checking DONE ($drc_rpt)"

if {$total_errors > 0} {
    puts "\[ERROR\]: $total_errors DRC violations found"
} else {
    puts "\[INFO\]: No DRC violations found"
}
exit 0