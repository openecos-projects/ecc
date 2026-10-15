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
set_routing_layers -signal MET2-MET5 -clock MET2-MET5
set_global_routing_layer_adjustment * 0.5
# Use STA clock sources and register clock pins to identify the pre-CTS clock
# networks. Add eligible dbNets directly, avoiding wildcard interpretation of
# synthesized names containing brackets.
set clock_nets [dict create]
set clock_pins [all_registers -clock_pins]
foreach clock [all_clocks] {
    set clock_pins [concat $clock_pins [get_property $clock sources]]
}
foreach pin $clock_pins {
    set iterm [sta::sta_to_db_pin $pin]
    if {$iterm ne "NULL"} {
        set db_net [$iterm getNet]
    } else {
        set bterm [sta::sta_to_db_port [sta::sta_pin_to_port $pin]]
        if {$bterm eq "NULL"} {continue}
        set db_net [$bterm getNet]
    }
    if {$db_net ne "NULL"} {dict set clock_nets [$db_net getName] 1}
}
set skipped_clock_net_count 0
set skipped_fanout_net_count 0
set routed_signal_net_count 0
set skipped_file [open "skipped_nets.tsv" w]
puts $skipped_file "reason\tnet\tterm_count"
foreach db_net [[ord::get_db_block] getNets] {
    set name [$db_net getName]
    set terms [$db_net getTermCount]
    if {[$db_net getSigType] in {POWER GROUND}} {continue}
    if {[dict exists $clock_nets $name] || [$db_net getSigType] eq "CLOCK"} {
        puts $skipped_file "clock\t$name\t$terms"
        incr skipped_clock_net_count
    } elseif {$terms > 100} {
        puts $skipped_file "fanout\t$name\t$terms"
        incr skipped_fanout_net_count
    } else {
        grt::add_net_to_route $db_net
        incr routed_signal_net_count
    }
}
close $skipped_file
puts "GR_AUDIT_METRIC skipped_clock_net_count=$skipped_clock_net_count"
puts "GR_AUDIT_METRIC skipped_fanout_net_count=$skipped_fanout_net_count"
puts "GR_AUDIT_METRIC routed_signal_net_count=$routed_signal_net_count"
global_route -congestion_iterations 50 -skip_large_fanout_nets 100 -allow_congestion
estimate_parasitics -global_routing
if {$before ne [design_state]} {error "External GR evaluation changed the design"}
puts "OPENROAD_GR_AUDIT_BEGIN"
report_units
report_clock_properties
report_design_area
report_wns -digits 6
report_tns -digits 6
report_check_types -max_slew -max_capacitance -max_fanout -digits 6
puts "GR_AUDIT_METRIC slew_violation_count=[sta::max_slew_violation_count]"
puts "GR_AUDIT_METRIC cap_violation_count=[sta::max_capacitance_violation_count]"
puts "GR_AUDIT_METRIC worst_slew_slack_ns=[sta::max_slew_check_slack]"
puts "GR_AUDIT_METRIC worst_cap_slack_pf=[sta::max_capacitance_check_slack]"
puts "GR_AUDIT_METRIC instance_count=[llength [[ord::get_db_block] getInsts]]"
puts "GR_AUDIT_METRIC net_count=[llength [[ord::get_db_block] getNets]]"
report_checks -path_delay max -format full_clock_expanded -digits 6 -group_path_count 3
puts "OPENROAD_GR_AUDIT_END design_unchanged=1 clock=ideal rc=global_routing"
