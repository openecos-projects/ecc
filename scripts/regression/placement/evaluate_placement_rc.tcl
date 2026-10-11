# Read-only external evaluation of final DEF connectivity and placement.
source $::env(GR_AUDIT_INPUTS)
set_thread_count 4
read_lef $tech_lef
foreach path $cell_lefs {read_lef $path}
foreach path $liberties {read_liberty $path}
read_def $input_def
if {[llength [info commands remove_from_collection]] == 0} {
    proc remove_from_collection {collection remove} {
        set result {}
        foreach item $collection {
            if {[lsearch -exact $remove $item] < 0} {lappend result $item}
        }
        return $result
    }
}
read_sdc $input_sdc
set_cmd_units -time ns -capacitance pF -resistance ohm -distance um
unset_propagated_clock [all_clocks]
check_placement -verbose

proc design_state {} {
    set block [ord::get_db_block]
    set state {}
    foreach inst [$block getInsts] {
        lappend state [list [$inst getName] [[$inst getMaster] getName] \
            [$inst getLocation] [$inst getOrient]]
        foreach pin [$inst getITerms] {
            set net [$pin getNet]
            lappend state [list [$pin getName] \
                [expr {$net eq "NULL" ? "" : [$net getName]}]]
        }
    }
    foreach pin [$block getBTerms] {
        set net [$pin getNet]
        lappend state [list [$pin getName] \
            [expr {$net eq "NULL" ? "" : [$net getName]}]]
    }
    return $state
}
set before [design_state]
# Layer RC comes directly from the loaded LEF width, RPERSQ, area/edge C and via R.
set_wire_rc -signal -layer MET2
set_wire_rc -clock -layer MET2
report_layer_rc
estimate_parasitics -placement
if {$before ne [design_state]} {error "External placement RC evaluation changed the design"}
puts "OPENROAD_PLACEMENT_AUDIT_BEGIN"
report_units
report_clock_properties
report_design_area
report_wns -digits 6
report_tns -digits 6
report_check_types -max_slew -max_capacitance -max_fanout -digits 6
puts "PLACEMENT_AUDIT_METRIC slew_violation_count=[sta::max_slew_violation_count]"
puts "PLACEMENT_AUDIT_METRIC cap_violation_count=[sta::max_capacitance_violation_count]"
puts "PLACEMENT_AUDIT_METRIC worst_slew_slack_ns=[sta::max_slew_check_slack]"
puts "PLACEMENT_AUDIT_METRIC worst_cap_slack_pf=[sta::max_capacitance_check_slack]"
puts "PLACEMENT_AUDIT_METRIC instance_count=[llength [[ord::get_db_block] getInsts]]"
puts "PLACEMENT_AUDIT_METRIC net_count=[llength [[ord::get_db_block] getNets]]"
report_checks -path_delay max -format full_clock_expanded -digits 6 -group_path_count 3
puts "OPENROAD_PLACEMENT_AUDIT_END design_unchanged=1 clock=ideal rc=placement"
