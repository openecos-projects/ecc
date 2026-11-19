# Optional logical snapshots. JSON export sorts the active design, so isolate it
# on the Yosys design stack and restore even when writing fails.
set replay_sequence 0
set replay_start_us [clock clicks -microseconds]
proc replay_logical {phase} {
  global replay_sequence replay_start_us
  if {![info exists ::env(ECC_REPLAY_CAPTURE_DIR)] || $::env(ECC_REPLAY_CAPTURE_DIR) eq ""} { return }
  if {[catch {
    set directory [file join $::env(ECC_REPLAY_CAPTURE_DIR) logical]
    file mkdir $directory
    set stem [file join $directory [format %06d $replay_sequence]]
    yosys design -push-copy
    try {
      yosys write_json "${stem}.json"
    } finally {
      yosys design -pop
    }
    set elapsed [expr {([clock clicks -microseconds] - $replay_start_us) * 1000}]
    if {[info exists ::env(ECC_REPLAY_OFFSET_NS)]} { incr elapsed $::env(ECC_REPLAY_OFFSET_NS) }
    set stream [open "${stem}.event" w]
    puts $stream [format {{"phase":"%s","elapsed_ns":%d}} $phase $elapsed]
    close $stream
    incr replay_sequence
  } message]} {
    puts stderr "Replay capture failed: $message"
    catch {
      set stream [open [file join $::env(ECC_REPLAY_CAPTURE_DIR) error.json] w]
      puts $stream {{"error":"logical capture failed"}}
      close $stream
    }
  }
}
