# Signoff release board

> **导览首页** — start here. This page is the human guide to signoff metrics; CSV/FileCheck under `test/lit/csv_gates` stays a util.

**Live snapshot:** readiness `WARN` · legacy `` · 68 catalog metrics

| PASS | WARN | MISS | ERROR |
| ---: | ---: | ---: | ---: |
| 49 | 8 | 1 | 0 |

## Contents

1. [How to read this board](#how-to-read-this-board)
2. [Catalog map](#catalog-map)
3. [Readiness board](#readiness-board)
4. [Categories](#categories)
   - [Quality gates (`quality_gate`)](#category-quality_gate)
   - [Performance / iSTA (`performance`)](#category-performance)
   - [Evidence artifacts (`artifact`)](#category-artifact)
   - [Reports (`report`)](#category-report)
   - [Flow completion (`flow`)](#category-flow)
   - [Configuration snapshots (`configuration`)](#category-configuration)
   - [Provenance (`provenance`)](#category-provenance)
5. [Per-metric index](#per-metric-index)

<details>
<summary>Jump to a metric (full list)</summary>

- [`quality.drc.clean`](#qualitydrcclean) — Final DRC clean
- [`quality.lvs.clean`](#qualitylvsclean) — Final LVS clean
- [`quality.rcx.corner_coverage`](#qualityrcxcorner_coverage) — RCX corner coverage
- [`quality.rcx.spef_parse_health`](#qualityrcxspef_parse_health) — RCX SPEF integrity
- [`quality.sta.setup_closed`](#qualitystasetup_closed) — STA setup closure
- [`quality.sta.hold_closed`](#qualitystahold_closed) — STA hold closure
- [`quality.mpc.minimum_area`](#qualitympcminimum_area) — Minimum core area
- [`quality.mpc.maximum_area`](#qualitympcmaximum_area) — Maximum core area
- [`artifact.harden.gds`](#artifacthardengds) — Harden GDS
- [`artifact.harden.lef`](#artifacthardenlef) — Harden LEF
- [`artifact.harden.lib`](#artifacthardenlib) — Harden LIB
- [`artifact.lvs.def`](#artifactlvsdef) — LVS DEF
- [`artifact.lvs.verilog`](#artifactlvsverilog) — LVS Verilog
- [`artifact.lvs.gds`](#artifactlvsgds) — LVS GDS
- [`artifact.lvs.report`](#artifactlvsreport) — LVS report
- [`artifact.lvs.json`](#artifactlvsjson) — LVS JSON
- [`artifact.rcx.spef_outputs`](#artifactrcxspef_outputs) — RCX SPEF outputs
- [`report.sta.timing_reports`](#reportstatiming_reports) — STA timing reports
- [`artifact.sta.corner_summaries`](#artifactstacorner_summaries) — STA structured corner summaries
- [`artifact.sta.timing_paths`](#artifactstatiming_paths) — STA structured timing paths
- [`artifact.synthesis.netlist`](#artifactsynthesisnetlist) — Mapped synthesis netlist
- [`artifact.sdc.constraints`](#artifactsdcconstraints) — SDC constraints file
- [`artifact.postroutelec.result`](#artifactpostroutelecresult) — Post-route LEC result
- [`artifact.lec.result`](#artifactlecresult) — Synthesis LEC result
- [`flow.route.completed`](#flowroutecompleted) — route flow completed
- [`flow.drc.completed`](#flowdrccompleted) — drc flow completed
- [`flow.lvs.completed`](#flowlvscompleted) — lvs flow completed
- [`flow.filler.completed`](#flowfillercompleted) — filler flow completed
- [`flow.postroutelec.completed`](#flowpostrouteleccompleted) — postRouteLec flow completed
- [`flow.rcx.completed`](#flowrcxcompleted) — RCX flow completed
- [`flow.sta.completed`](#flowstacompleted) — sta flow completed
- [`flow.harden.completed`](#flowhardencompleted) — Harden flow completed
- [`flow.synthesis.completed`](#flowsynthesiscompleted) — Synthesis flow completed
- [`flow.place.completed`](#flowplacecompleted) — place flow completed
- [`flow.cts.completed`](#flowctscompleted) — CTS flow completed
- [`flow.legalization.completed`](#flowlegalizationcompleted) — legalization flow completed
- [`flow.poweranalysis.completed`](#flowpoweranalysiscompleted) — powerAnalysis flow completed
- [`quality.cts.skew_target`](#qualityctsskew_target) — CTS skew target met
- [`quality.route.dr_clean`](#qualityroutedr_clean) — Route DR clean
- [`provenance.initial.rtl`](#provenanceinitialrtl) — Initial RTL
- [`provenance.initial.sdc`](#provenanceinitialsdc) — Initial SDC
- [`configuration.db`](#configurationdb) — Configuration db
- [`configuration.rcx`](#configurationrcx) — Configuration RCX
- [`configuration.sta`](#configurationsta) — Configuration sta
- [`performance.sta.setup_wns`](#performancestasetup_wns) — STA setup WNS
- [`performance.sta.setup_tns`](#performancestasetup_tns) — STA setup TNS
- [`performance.sta.hold_wns`](#performancestahold_wns) — STA hold WNS
- [`performance.sta.hold_tns`](#performancestahold_tns) — STA hold TNS
- [`performance.sta.frequency`](#performancestafrequency) — STA frequency
- [`performance.power.dynamic`](#performancepowerdynamic) — Dynamic power
- [`performance.power.leakage`](#performancepowerleakage) — Leakage power
- [`performance.sdc.clock_count`](#performancesdcclock_count) — SDC clock count
- [`performance.cts.skew`](#performancectsskew) — CTS worst skew
- [`performance.cts.insertion_latency`](#performancectsinsertion_latency) — CTS max insertion latency
- [`performance.cts.buffer_count`](#performancectsbuffer_count) — CTS buffer count
- [`performance.cts.clock_wirelength`](#performancectsclock_wirelength) — CTS clock wirelength
- [`performance.cts.tree_max_level`](#performancectstree_max_level) — CTS clock tree max level
- [`performance.place.hpwl`](#performanceplacehpwl) — Place HPWL
- [`performance.place.congestion_overflow`](#performanceplacecongestion_overflow) — Place EGR overflow total
- [`performance.route.wirelength`](#performanceroutewirelength) — Route wirelength
- [`performance.route.via_count`](#performanceroutevia_count) — Route via count
- [`performance.synthesis.cell_area`](#performancesynthesiscell_area) — Synthesis cell area
- [`performance.synthesis.cell_count`](#performancesynthesiscell_count) — Synthesis cell count
- [`performance.host.latency`](#performancehostlatency) — 组件耗时
- [`performance.host.throughput`](#performancehostthroughput) — 速度
- [`performance.host.peak_memory`](#performancehostpeak_memory) — 内存峰值
- [`performance.host.avg_memory`](#performancehostavg_memory) — 内存平均
- [`performance.host.compile_peak_memory`](#performancehostcompile_peak_memory) — 编译内存峰值

</details>

## How to read this board

Signoff readiness is `PASS | WARN | MISS | ERROR`. Quality-gate failures are **ERROR**; missing evidence is **MISS**; optional gaps are **WARN**.

```mermaid
flowchart LR
  A["1. Read map"] --> B["2. Check readiness board"]
  B --> C["3. Open a category"]
  C --> D["4. Drill into one metric"]
  D --> E["5. Fix evidence / re-inspect"]
```

| Step | What you do |
| --- | --- |
| Map | See which domains exist (quality / artifact / flow / …) |
| Readiness board | See where cards sit right now |
| Category | Open one domain diagram |
| Per metric | Drill one id → step → state |

## Catalog map

One hub per domain — click a category section below for detail.

```mermaid
flowchart TB
  hub["Signoff catalog"]
  map_quality_gate["Quality gates<br/>10 metrics"]
  hub --> map_quality_gate
  map_performance["Performance / iSTA<br/>24 metrics"]
  hub --> map_performance
  map_artifact["Evidence artifacts<br/>14 metrics"]
  hub --> map_artifact
  map_report["Reports<br/>2 metrics"]
  hub --> map_report
  map_flow["Flow completion<br/>13 metrics"]
  hub --> map_flow
  map_configuration["Configuration snapshots<br/>3 metrics"]
  hub --> map_configuration
  map_provenance["Provenance<br/>2 metrics"]
  hub --> map_provenance
```

| Domain | Metrics | Role |
| --- | ---: | --- |
| [Quality gates](#category-quality_gate) | 10 | Machine predicates (DRC/LVS/STA/RCX/area). Failures → ERROR readiness. |
| [Performance / iSTA](#category-performance) | 24 | Numeric timing (WNS/TNS/freq) and power slots for multi-version compare. |
| [Evidence artifacts](#category-artifact) | 14 | Required files from Harden / LVS / RCX / STA / synthesis (and optional LEC). |
| [Reports](#category-report) | 2 | Human-readable reports tied to steps (e.g. STA timing reports). |
| [Flow completion](#category-flow) | 13 | Ledger steps that must have completed for a full package. |
| [Configuration snapshots](#category-configuration) | 3 | Workspace config JSON (db / rcx / sta) frozen for the run. |
| [Provenance](#category-provenance) | 2 | Initial RTL / SDC inputs that anchor the workspace. |

## Readiness board

Cards placed by live assessment (PASS=49, WARN=8, MISS=1, ERROR=0).

```mermaid
flowchart LR
  subgraph col_PASS["PASS (49)"]
    PASS_quality_drc_clean["quality.drc.clean<br/>Final DRC clean"]
    PASS_quality_lvs_clean["quality.lvs.clean<br/>Final LVS clean"]
    PASS_quality_rcx_corner_coverage["quality.rcx.corner_coverage<br/>RCX corner coverage"]
    PASS_quality_rcx_spef_parse_health["quality.rcx.spef_parse_health<br/>RCX SPEF integrity"]
    PASS_quality_sta_setup_closed["quality.sta.setup_closed<br/>STA setup closure"]
    PASS_quality_sta_hold_closed["quality.sta.hold_closed<br/>STA hold closure"]
    PASS_artifact_harden_gds["artifact.harden.gds<br/>Harden GDS"]
    PASS_artifact_harden_lef["artifact.harden.lef<br/>Harden LEF"]
    PASS_artifact_harden_lib["artifact.harden.lib<br/>Harden LIB"]
    PASS_artifact_lvs_verilog["artifact.lvs.verilog<br/>LVS Verilog"]
    PASS_artifact_rcx_spef_outputs["artifact.rcx.spef_outputs<br/>RCX SPEF outputs"]
    PASS_artifact_synthesis_netlist["artifact.synthesis.netlist<br/>Mapped synthesis netlist"]
    more_PASS["… +37 more — see TOC"]
  end
  subgraph col_WARN["WARN (8)"]
    WARN_artifact_sdc_constraints["artifact.sdc.constraints<br/>SDC constraints file"]
    WARN_flow_synthesis_completed["flow.synthesis.completed<br/>Synthesis flow completed"]
    WARN_flow_place_completed["flow.place.completed<br/>place flow completed"]
    WARN_flow_cts_completed["flow.cts.completed<br/>CTS flow completed"]
    WARN_flow_legalization_completed["flow.legalization.completed<br/>legalization flow completed"]
    WARN_flow_poweranalysis_completed["flow.poweranalysis.completed<br/>powerAnalysis flow completed"]
    WARN_quality_cts_skew_target["quality.cts.skew_target<br/>CTS skew target met"]
    WARN_quality_route_dr_clean["quality.route.dr_clean<br/>Route DR clean"]
  end
  subgraph col_MISS["MISS (1)"]
    MISS_performance_host_compile_peak_memory["performance.host.compile_peak_memory<br/>编译内存峰值"]
  end
  subgraph col_ERROR["ERROR"]
    empty_ERROR["(none)"]
  end
```

## Categories

### Category: `quality_gate`

<a id="category-quality_gate"></a>

**Quality gates.** Machine predicates (DRC/LVS/STA/RCX/area). Failures → ERROR readiness.

| id | title | step | optional |
| --- | --- | --- | --- |
| [`quality.drc.clean`](#qualitydrcclean) | Final DRC clean | `drc` |  |
| [`quality.lvs.clean`](#qualitylvsclean) | Final LVS clean | `lvs` |  |
| [`quality.rcx.corner_coverage`](#qualityrcxcorner_coverage) | RCX corner coverage | `RCX` |  |
| [`quality.rcx.spef_parse_health`](#qualityrcxspef_parse_health) | RCX SPEF integrity | `RCX` |  |
| [`quality.sta.setup_closed`](#qualitystasetup_closed) | STA setup closure | `sta` |  |
| [`quality.sta.hold_closed`](#qualitystahold_closed) | STA hold closure | `sta` |  |
| [`quality.mpc.minimum_area`](#qualitympcminimum_area) | Minimum core area | `Harden` |  |
| [`quality.mpc.maximum_area`](#qualitympcmaximum_area) | Maximum core area | `Harden` |  |
| [`quality.cts.skew_target`](#qualityctsskew_target) | CTS skew target met | `CTS` | yes |
| [`quality.route.dr_clean`](#qualityroutedr_clean) | Route DR clean | `route` | yes |

```mermaid
flowchart TB
  subgraph cat_quality_gate["Quality gates"]
    quality_drc_clean["quality.drc.clean<br/>Final DRC clean"]
    quality_lvs_clean["quality.lvs.clean<br/>Final LVS clean"]
    quality_rcx_corner_coverage["quality.rcx.corner_coverage<br/>RCX corner coverage"]
    quality_rcx_spef_parse_health["quality.rcx.spef_parse_health<br/>RCX SPEF integrity"]
    quality_sta_setup_closed["quality.sta.setup_closed<br/>STA setup closure"]
    quality_sta_hold_closed["quality.sta.hold_closed<br/>STA hold closure"]
    quality_mpc_minimum_area["quality.mpc.minimum_area<br/>Minimum core area"]
    quality_mpc_maximum_area["quality.mpc.maximum_area<br/>Maximum core area"]
    quality_cts_skew_target["quality.cts.skew_target<br/>CTS skew target met (optional)"]
    quality_route_dr_clean["quality.route.dr_clean<br/>Route DR clean (optional)"]
  end
  quality_drc_clean -.-> quality_lvs_clean
  quality_lvs_clean -.-> quality_rcx_corner_coverage
  quality_rcx_corner_coverage -.-> quality_sta_setup_closed
  quality_sta_setup_closed -.-> quality_mpc_minimum_area
  quality_mpc_minimum_area -.-> quality_cts_skew_target
  quality_cts_skew_target -.-> quality_route_dr_clean
```

[↑ Contents](#contents) · [↑ Map](#catalog-map) · [↑ Readiness](#readiness-board)

### Category: `performance`

<a id="category-performance"></a>

**Performance / iSTA.** Numeric timing (WNS/TNS/freq) and power slots for multi-version compare.

| id | title | step | optional |
| --- | --- | --- | --- |
| [`performance.sta.setup_wns`](#performancestasetup_wns) | STA setup WNS | `sta` | yes |
| [`performance.sta.setup_tns`](#performancestasetup_tns) | STA setup TNS | `sta` | yes |
| [`performance.sta.hold_wns`](#performancestahold_wns) | STA hold WNS | `sta` | yes |
| [`performance.sta.hold_tns`](#performancestahold_tns) | STA hold TNS | `sta` | yes |
| [`performance.sta.frequency`](#performancestafrequency) | STA frequency | `sta` | yes |
| [`performance.power.dynamic`](#performancepowerdynamic) | Dynamic power | `sta` | yes |
| [`performance.power.leakage`](#performancepowerleakage) | Leakage power | `sta` | yes |
| [`performance.sdc.clock_count`](#performancesdcclock_count) | SDC clock count | `workspace` | yes |
| [`performance.cts.skew`](#performancectsskew) | CTS worst skew | `CTS` | yes |
| [`performance.cts.insertion_latency`](#performancectsinsertion_latency) | CTS max insertion latency | `CTS` | yes |
| [`performance.cts.buffer_count`](#performancectsbuffer_count) | CTS buffer count | `CTS` | yes |
| [`performance.cts.clock_wirelength`](#performancectsclock_wirelength) | CTS clock wirelength | `CTS` | yes |
| [`performance.cts.tree_max_level`](#performancectstree_max_level) | CTS clock tree max level | `CTS` | yes |
| [`performance.place.hpwl`](#performanceplacehpwl) | Place HPWL | `place` | yes |
| [`performance.place.congestion_overflow`](#performanceplacecongestion_overflow) | Place EGR overflow total | `place` | yes |
| [`performance.route.wirelength`](#performanceroutewirelength) | Route wirelength | `route` | yes |
| [`performance.route.via_count`](#performanceroutevia_count) | Route via count | `route` | yes |
| [`performance.synthesis.cell_area`](#performancesynthesiscell_area) | Synthesis cell area | `Synthesis` | yes |
| [`performance.synthesis.cell_count`](#performancesynthesiscell_count) | Synthesis cell count | `Synthesis` | yes |
| [`performance.host.latency`](#performancehostlatency) | 组件耗时 | `host` | yes |
| [`performance.host.throughput`](#performancehostthroughput) | 速度 | `host` | yes |
| [`performance.host.peak_memory`](#performancehostpeak_memory) | 内存峰值 | `host` | yes |
| [`performance.host.avg_memory`](#performancehostavg_memory) | 内存平均 | `host` | yes |
| [`performance.host.compile_peak_memory`](#performancehostcompile_peak_memory) | 编译内存峰值 | `host` | yes |

```mermaid
flowchart TB
  subgraph cat_performance["Performance / iSTA"]
    performance_sta_setup_wns["performance.sta.setup_wns<br/>STA setup WNS (optional)"]
    performance_sta_setup_tns["performance.sta.setup_tns<br/>STA setup TNS (optional)"]
    performance_sta_hold_wns["performance.sta.hold_wns<br/>STA hold WNS (optional)"]
    performance_sta_hold_tns["performance.sta.hold_tns<br/>STA hold TNS (optional)"]
    performance_sta_frequency["performance.sta.frequency<br/>STA frequency (optional)"]
    performance_power_dynamic["performance.power.dynamic<br/>Dynamic power (optional)"]
    performance_power_leakage["performance.power.leakage<br/>Leakage power (optional)"]
    performance_sdc_clock_count["performance.sdc.clock_count<br/>SDC clock count (optional)"]
    performance_cts_skew["performance.cts.skew<br/>CTS worst skew (optional)"]
    performance_cts_insertion_latency["performance.cts.insertion_latency<br/>CTS max insertion latency (optional)"]
    performance_cts_buffer_count["performance.cts.buffer_count<br/>CTS buffer count (optional)"]
    performance_cts_clock_wirelength["performance.cts.clock_wirelength<br/>CTS clock wirelength (optional)"]
    performance_cts_tree_max_level["performance.cts.tree_max_level<br/>CTS clock tree max level (optional)"]
    performance_place_hpwl["performance.place.hpwl<br/>Place HPWL (optional)"]
    performance_place_congestion_overflow["performance.place.congestion_overflow<br/>Place EGR overflow total (optional)"]
    performance_route_wirelength["performance.route.wirelength<br/>Route wirelength (optional)"]
    performance_route_via_count["performance.route.via_count<br/>Route via count (optional)"]
    performance_synthesis_cell_area["performance.synthesis.cell_area<br/>Synthesis cell area (optional)"]
    performance_synthesis_cell_count["performance.synthesis.cell_count<br/>Synthesis cell count (optional)"]
    performance_host_latency["performance.host.latency<br/>组件耗时 (optional)"]
    performance_host_throughput["performance.host.throughput<br/>速度 (optional)"]
    performance_host_peak_memory["performance.host.peak_memory<br/>内存峰值 (optional)"]
    performance_host_avg_memory["performance.host.avg_memory<br/>内存平均 (optional)"]
    performance_host_compile_peak_memory["performance.host.compile_peak_memory<br/>编译内存峰值 (optional)"]
  end
  performance_sta_setup_wns -.-> performance_sdc_clock_count
  performance_sdc_clock_count -.-> performance_cts_skew
  performance_cts_skew -.-> performance_place_hpwl
  performance_place_hpwl -.-> performance_route_wirelength
  performance_route_wirelength -.-> performance_synthesis_cell_area
  performance_synthesis_cell_area -.-> performance_host_latency
```

[↑ Contents](#contents) · [↑ Map](#catalog-map) · [↑ Readiness](#readiness-board)

### Category: `artifact`

<a id="category-artifact"></a>

**Evidence artifacts.** Required files from Harden / LVS / RCX / STA / synthesis (and optional LEC).

| id | title | step | optional |
| --- | --- | --- | --- |
| [`artifact.harden.gds`](#artifacthardengds) | Harden GDS | `Harden` |  |
| [`artifact.harden.lef`](#artifacthardenlef) | Harden LEF | `Harden` |  |
| [`artifact.harden.lib`](#artifacthardenlib) | Harden LIB | `Harden` |  |
| [`artifact.lvs.def`](#artifactlvsdef) | LVS DEF | `lvs` |  |
| [`artifact.lvs.verilog`](#artifactlvsverilog) | LVS Verilog | `lvs` |  |
| [`artifact.lvs.gds`](#artifactlvsgds) | LVS GDS | `lvs` |  |
| [`artifact.lvs.json`](#artifactlvsjson) | LVS JSON | `lvs` |  |
| [`artifact.rcx.spef_outputs`](#artifactrcxspef_outputs) | RCX SPEF outputs | `RCX` |  |
| [`artifact.sta.corner_summaries`](#artifactstacorner_summaries) | STA structured corner summaries | `sta` |  |
| [`artifact.sta.timing_paths`](#artifactstatiming_paths) | STA structured timing paths | `sta` |  |
| [`artifact.synthesis.netlist`](#artifactsynthesisnetlist) | Mapped synthesis netlist | `Synthesis` |  |
| [`artifact.sdc.constraints`](#artifactsdcconstraints) | SDC constraints file | `workspace` | yes |
| [`artifact.postroutelec.result`](#artifactpostroutelecresult) | Post-route LEC result | `postRouteLec` | yes |
| [`artifact.lec.result`](#artifactlecresult) | Synthesis LEC result | `lec` | yes |

```mermaid
flowchart TB
  subgraph cat_artifact["Evidence artifacts"]
    artifact_harden_gds["artifact.harden.gds<br/>Harden GDS"]
    artifact_harden_lef["artifact.harden.lef<br/>Harden LEF"]
    artifact_harden_lib["artifact.harden.lib<br/>Harden LIB"]
    artifact_lvs_def["artifact.lvs.def<br/>LVS DEF"]
    artifact_lvs_verilog["artifact.lvs.verilog<br/>LVS Verilog"]
    artifact_lvs_gds["artifact.lvs.gds<br/>LVS GDS"]
    artifact_lvs_json["artifact.lvs.json<br/>LVS JSON"]
    artifact_rcx_spef_outputs["artifact.rcx.spef_outputs<br/>RCX SPEF outputs"]
    artifact_sta_corner_summaries["artifact.sta.corner_summaries<br/>STA structured corner summaries"]
    artifact_sta_timing_paths["artifact.sta.timing_paths<br/>STA structured timing paths"]
    artifact_synthesis_netlist["artifact.synthesis.netlist<br/>Mapped synthesis netlist"]
    artifact_sdc_constraints["artifact.sdc.constraints<br/>SDC constraints file (optional)"]
    artifact_postroutelec_result["artifact.postroutelec.result<br/>Post-route LEC result (optional)"]
    artifact_lec_result["artifact.lec.result<br/>Synthesis LEC result (optional)"]
  end
  artifact_harden_gds -.-> artifact_lvs_def
  artifact_lvs_def -.-> artifact_rcx_spef_outputs
  artifact_rcx_spef_outputs -.-> artifact_sta_corner_summaries
  artifact_sta_corner_summaries -.-> artifact_synthesis_netlist
  artifact_synthesis_netlist -.-> artifact_sdc_constraints
  artifact_sdc_constraints -.-> artifact_postroutelec_result
  artifact_postroutelec_result -.-> artifact_lec_result
```

[↑ Contents](#contents) · [↑ Map](#catalog-map) · [↑ Readiness](#readiness-board)

### Category: `report`

<a id="category-report"></a>

**Reports.** Human-readable reports tied to steps (e.g. STA timing reports).

| id | title | step | optional |
| --- | --- | --- | --- |
| [`artifact.lvs.report`](#artifactlvsreport) | LVS report | `lvs` |  |
| [`report.sta.timing_reports`](#reportstatiming_reports) | STA timing reports | `sta` |  |

```mermaid
flowchart TB
  subgraph cat_report["Reports"]
    artifact_lvs_report["artifact.lvs.report<br/>LVS report"]
    report_sta_timing_reports["report.sta.timing_reports<br/>STA timing reports"]
  end
  artifact_lvs_report -.-> report_sta_timing_reports
```

[↑ Contents](#contents) · [↑ Map](#catalog-map) · [↑ Readiness](#readiness-board)

### Category: `flow`

<a id="category-flow"></a>

**Flow completion.** Ledger steps that must have completed for a full package.

| id | title | step | optional |
| --- | --- | --- | --- |
| [`flow.route.completed`](#flowroutecompleted) | route flow completed | `route` |  |
| [`flow.drc.completed`](#flowdrccompleted) | drc flow completed | `drc` |  |
| [`flow.lvs.completed`](#flowlvscompleted) | lvs flow completed | `lvs` |  |
| [`flow.filler.completed`](#flowfillercompleted) | filler flow completed | `filler` |  |
| [`flow.postroutelec.completed`](#flowpostrouteleccompleted) | postRouteLec flow completed | `postRouteLec` | yes |
| [`flow.rcx.completed`](#flowrcxcompleted) | RCX flow completed | `RCX` |  |
| [`flow.sta.completed`](#flowstacompleted) | sta flow completed | `sta` |  |
| [`flow.harden.completed`](#flowhardencompleted) | Harden flow completed | `Harden` |  |
| [`flow.synthesis.completed`](#flowsynthesiscompleted) | Synthesis flow completed | `Synthesis` | yes |
| [`flow.place.completed`](#flowplacecompleted) | place flow completed | `place` | yes |
| [`flow.cts.completed`](#flowctscompleted) | CTS flow completed | `CTS` | yes |
| [`flow.legalization.completed`](#flowlegalizationcompleted) | legalization flow completed | `legalization` | yes |
| [`flow.poweranalysis.completed`](#flowpoweranalysiscompleted) | powerAnalysis flow completed | `powerAnalysis` | yes |

```mermaid
flowchart TB
  subgraph cat_flow["Flow completion"]
    flow_route_completed["flow.route.completed<br/>route flow completed"]
    flow_drc_completed["flow.drc.completed<br/>drc flow completed"]
    flow_lvs_completed["flow.lvs.completed<br/>lvs flow completed"]
    flow_filler_completed["flow.filler.completed<br/>filler flow completed"]
    flow_postroutelec_completed["flow.postroutelec.completed<br/>postRouteLec flow completed (optional)"]
    flow_rcx_completed["flow.rcx.completed<br/>RCX flow completed"]
    flow_sta_completed["flow.sta.completed<br/>sta flow completed"]
    flow_harden_completed["flow.harden.completed<br/>Harden flow completed"]
    flow_synthesis_completed["flow.synthesis.completed<br/>Synthesis flow completed (optional)"]
    flow_place_completed["flow.place.completed<br/>place flow completed (optional)"]
    flow_cts_completed["flow.cts.completed<br/>CTS flow completed (optional)"]
    flow_legalization_completed["flow.legalization.completed<br/>legalization flow completed (optional)"]
    flow_poweranalysis_completed["flow.poweranalysis.completed<br/>powerAnalysis flow completed (optional)"]
  end
  flow_route_completed -.-> flow_drc_completed
  flow_drc_completed -.-> flow_lvs_completed
  flow_lvs_completed -.-> flow_filler_completed
  flow_filler_completed -.-> flow_postroutelec_completed
  flow_postroutelec_completed -.-> flow_rcx_completed
  flow_rcx_completed -.-> flow_sta_completed
  flow_sta_completed -.-> flow_harden_completed
  flow_harden_completed -.-> flow_synthesis_completed
  flow_synthesis_completed -.-> flow_place_completed
  flow_place_completed -.-> flow_cts_completed
  flow_cts_completed -.-> flow_legalization_completed
  flow_legalization_completed -.-> flow_poweranalysis_completed
```

[↑ Contents](#contents) · [↑ Map](#catalog-map) · [↑ Readiness](#readiness-board)

### Category: `configuration`

<a id="category-configuration"></a>

**Configuration snapshots.** Workspace config JSON (db / rcx / sta) frozen for the run.

| id | title | step | optional |
| --- | --- | --- | --- |
| [`configuration.db`](#configurationdb) | Configuration db | `workspace` |  |
| [`configuration.rcx`](#configurationrcx) | Configuration RCX | `workspace` |  |
| [`configuration.sta`](#configurationsta) | Configuration sta | `workspace` |  |

```mermaid
flowchart TB
  subgraph cat_configuration["Configuration snapshots"]
    configuration_db["configuration.db<br/>Configuration db"]
    configuration_rcx["configuration.rcx<br/>Configuration RCX"]
    configuration_sta["configuration.sta<br/>Configuration sta"]
  end
```

[↑ Contents](#contents) · [↑ Map](#catalog-map) · [↑ Readiness](#readiness-board)

### Category: `provenance`

<a id="category-provenance"></a>

**Provenance.** Initial RTL / SDC inputs that anchor the workspace.

| id | title | step | optional |
| --- | --- | --- | --- |
| [`provenance.initial.rtl`](#provenanceinitialrtl) | Initial RTL | `workspace` |  |
| [`provenance.initial.sdc`](#provenanceinitialsdc) | Initial SDC | `workspace` |  |

```mermaid
flowchart TB
  subgraph cat_provenance["Provenance"]
    provenance_initial_rtl["provenance.initial.rtl<br/>Initial RTL"]
    provenance_initial_sdc["provenance.initial.sdc<br/>Initial SDC"]
  end
```

[↑ Contents](#contents) · [↑ Map](#catalog-map) · [↑ Readiness](#readiness-board)

## Per-metric index

Each metric: step → id → board state.

### `quality.drc.clean`

- **Final DRC clean** · category `quality_gate` · step `drc` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_quality_drc_clean["step: drc"] --> metric_quality_drc_clean["quality.drc.clean"]
  metric_quality_drc_clean --> state_quality_drc_clean["PASS"]
  cat_quality_drc_clean["quality_gate"] -.-> metric_quality_drc_clean
```

[↑ category `quality_gate`](#category-quality_gate) · [↑ Contents](#contents)

### `quality.lvs.clean`

- **Final LVS clean** · category `quality_gate` · step `lvs` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_quality_lvs_clean["step: lvs"] --> metric_quality_lvs_clean["quality.lvs.clean"]
  metric_quality_lvs_clean --> state_quality_lvs_clean["PASS"]
  cat_quality_lvs_clean["quality_gate"] -.-> metric_quality_lvs_clean
```

[↑ category `quality_gate`](#category-quality_gate) · [↑ Contents](#contents)

### `quality.rcx.corner_coverage`

- **RCX corner coverage** · category `quality_gate` · step `RCX` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_quality_rcx_corner_coverage["step: RCX"] --> metric_quality_rcx_corner_coverage["quality.rcx.corner_coverage"]
  metric_quality_rcx_corner_coverage --> state_quality_rcx_corner_coverage["PASS"]
  cat_quality_rcx_corner_coverage["quality_gate"] -.-> metric_quality_rcx_corner_coverage
```

[↑ category `quality_gate`](#category-quality_gate) · [↑ Contents](#contents)

### `quality.rcx.spef_parse_health`

- **RCX SPEF integrity** · category `quality_gate` · step `RCX` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_quality_rcx_spef_parse_health["step: RCX"] --> metric_quality_rcx_spef_parse_health["quality.rcx.spef_parse_health"]
  metric_quality_rcx_spef_parse_health --> state_quality_rcx_spef_parse_health["PASS"]
  cat_quality_rcx_spef_parse_health["quality_gate"] -.-> metric_quality_rcx_spef_parse_health
```

[↑ category `quality_gate`](#category-quality_gate) · [↑ Contents](#contents)

### `quality.sta.setup_closed`

- **STA setup closure** · category `quality_gate` · step `sta` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_quality_sta_setup_closed["step: sta"] --> metric_quality_sta_setup_closed["quality.sta.setup_closed"]
  metric_quality_sta_setup_closed --> state_quality_sta_setup_closed["PASS"]
  cat_quality_sta_setup_closed["quality_gate"] -.-> metric_quality_sta_setup_closed
```

[↑ category `quality_gate`](#category-quality_gate) · [↑ Contents](#contents)

### `quality.sta.hold_closed`

- **STA hold closure** · category `quality_gate` · step `sta` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_quality_sta_hold_closed["step: sta"] --> metric_quality_sta_hold_closed["quality.sta.hold_closed"]
  metric_quality_sta_hold_closed --> state_quality_sta_hold_closed["PASS"]
  cat_quality_sta_hold_closed["quality_gate"] -.-> metric_quality_sta_hold_closed
```

[↑ category `quality_gate`](#category-quality_gate) · [↑ Contents](#contents)

### `quality.mpc.minimum_area`

- **Minimum core area** · category `quality_gate` · step `Harden` · optional `False` · state **ATTENTION**

```mermaid
flowchart LR
  step_quality_mpc_minimum_area["step: Harden"] --> metric_quality_mpc_minimum_area["quality.mpc.minimum_area"]
  metric_quality_mpc_minimum_area --> state_quality_mpc_minimum_area["ATTENTION"]
  cat_quality_mpc_minimum_area["quality_gate"] -.-> metric_quality_mpc_minimum_area
```

[↑ category `quality_gate`](#category-quality_gate) · [↑ Contents](#contents)

### `quality.mpc.maximum_area`

- **Maximum core area** · category `quality_gate` · step `Harden` · optional `False` · state **ATTENTION**

```mermaid
flowchart LR
  step_quality_mpc_maximum_area["step: Harden"] --> metric_quality_mpc_maximum_area["quality.mpc.maximum_area"]
  metric_quality_mpc_maximum_area --> state_quality_mpc_maximum_area["ATTENTION"]
  cat_quality_mpc_maximum_area["quality_gate"] -.-> metric_quality_mpc_maximum_area
```

[↑ category `quality_gate`](#category-quality_gate) · [↑ Contents](#contents)

### `artifact.harden.gds`

- **Harden GDS** · category `artifact` · step `Harden` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_artifact_harden_gds["step: Harden"] --> metric_artifact_harden_gds["artifact.harden.gds"]
  metric_artifact_harden_gds --> state_artifact_harden_gds["PASS"]
  cat_artifact_harden_gds["artifact"] -.-> metric_artifact_harden_gds
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.harden.lef`

- **Harden LEF** · category `artifact` · step `Harden` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_artifact_harden_lef["step: Harden"] --> metric_artifact_harden_lef["artifact.harden.lef"]
  metric_artifact_harden_lef --> state_artifact_harden_lef["PASS"]
  cat_artifact_harden_lef["artifact"] -.-> metric_artifact_harden_lef
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.harden.lib`

- **Harden LIB** · category `artifact` · step `Harden` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_artifact_harden_lib["step: Harden"] --> metric_artifact_harden_lib["artifact.harden.lib"]
  metric_artifact_harden_lib --> state_artifact_harden_lib["PASS"]
  cat_artifact_harden_lib["artifact"] -.-> metric_artifact_harden_lib
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.lvs.def`

- **LVS DEF** · category `artifact` · step `lvs` · optional `False` · state **ATTENTION**

```mermaid
flowchart LR
  step_artifact_lvs_def["step: lvs"] --> metric_artifact_lvs_def["artifact.lvs.def"]
  metric_artifact_lvs_def --> state_artifact_lvs_def["ATTENTION"]
  cat_artifact_lvs_def["artifact"] -.-> metric_artifact_lvs_def
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.lvs.verilog`

- **LVS Verilog** · category `artifact` · step `lvs` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_artifact_lvs_verilog["step: lvs"] --> metric_artifact_lvs_verilog["artifact.lvs.verilog"]
  metric_artifact_lvs_verilog --> state_artifact_lvs_verilog["PASS"]
  cat_artifact_lvs_verilog["artifact"] -.-> metric_artifact_lvs_verilog
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.lvs.gds`

- **LVS GDS** · category `artifact` · step `lvs` · optional `False` · state **ATTENTION**

```mermaid
flowchart LR
  step_artifact_lvs_gds["step: lvs"] --> metric_artifact_lvs_gds["artifact.lvs.gds"]
  metric_artifact_lvs_gds --> state_artifact_lvs_gds["ATTENTION"]
  cat_artifact_lvs_gds["artifact"] -.-> metric_artifact_lvs_gds
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.lvs.report`

- **LVS report** · category `report` · step `lvs` · optional `False` · state **ATTENTION**

```mermaid
flowchart LR
  step_artifact_lvs_report["step: lvs"] --> metric_artifact_lvs_report["artifact.lvs.report"]
  metric_artifact_lvs_report --> state_artifact_lvs_report["ATTENTION"]
  cat_artifact_lvs_report["report"] -.-> metric_artifact_lvs_report
```

[↑ category `report`](#category-report) · [↑ Contents](#contents)

### `artifact.lvs.json`

- **LVS JSON** · category `artifact` · step `lvs` · optional `False` · state **ATTENTION**

```mermaid
flowchart LR
  step_artifact_lvs_json["step: lvs"] --> metric_artifact_lvs_json["artifact.lvs.json"]
  metric_artifact_lvs_json --> state_artifact_lvs_json["ATTENTION"]
  cat_artifact_lvs_json["artifact"] -.-> metric_artifact_lvs_json
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.rcx.spef_outputs`

- **RCX SPEF outputs** · category `artifact` · step `RCX` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_artifact_rcx_spef_outputs["step: RCX"] --> metric_artifact_rcx_spef_outputs["artifact.rcx.spef_outputs"]
  metric_artifact_rcx_spef_outputs --> state_artifact_rcx_spef_outputs["PASS"]
  cat_artifact_rcx_spef_outputs["artifact"] -.-> metric_artifact_rcx_spef_outputs
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `report.sta.timing_reports`

- **STA timing reports** · category `report` · step `sta` · optional `False` · state **ATTENTION**

```mermaid
flowchart LR
  step_report_sta_timing_reports["step: sta"] --> metric_report_sta_timing_reports["report.sta.timing_reports"]
  metric_report_sta_timing_reports --> state_report_sta_timing_reports["ATTENTION"]
  cat_report_sta_timing_reports["report"] -.-> metric_report_sta_timing_reports
```

[↑ category `report`](#category-report) · [↑ Contents](#contents)

### `artifact.sta.corner_summaries`

- **STA structured corner summaries** · category `artifact` · step `sta` · optional `False` · state **ATTENTION**

```mermaid
flowchart LR
  step_artifact_sta_corner_summaries["step: sta"] --> metric_artifact_sta_corner_summaries["artifact.sta.corner_summaries"]
  metric_artifact_sta_corner_summaries --> state_artifact_sta_corner_summaries["ATTENTION"]
  cat_artifact_sta_corner_summaries["artifact"] -.-> metric_artifact_sta_corner_summaries
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.sta.timing_paths`

- **STA structured timing paths** · category `artifact` · step `sta` · optional `False` · state **ATTENTION**

```mermaid
flowchart LR
  step_artifact_sta_timing_paths["step: sta"] --> metric_artifact_sta_timing_paths["artifact.sta.timing_paths"]
  metric_artifact_sta_timing_paths --> state_artifact_sta_timing_paths["ATTENTION"]
  cat_artifact_sta_timing_paths["artifact"] -.-> metric_artifact_sta_timing_paths
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.synthesis.netlist`

- **Mapped synthesis netlist** · category `artifact` · step `Synthesis` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_artifact_synthesis_netlist["step: Synthesis"] --> metric_artifact_synthesis_netlist["artifact.synthesis.netlist"]
  metric_artifact_synthesis_netlist --> state_artifact_synthesis_netlist["PASS"]
  cat_artifact_synthesis_netlist["artifact"] -.-> metric_artifact_synthesis_netlist
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.sdc.constraints`

- **SDC constraints file** · category `artifact` · step `workspace` · optional `True` · state **WARN**

```mermaid
flowchart LR
  step_artifact_sdc_constraints["step: workspace"] --> metric_artifact_sdc_constraints["artifact.sdc.constraints"]
  metric_artifact_sdc_constraints --> state_artifact_sdc_constraints["WARN"]
  cat_artifact_sdc_constraints["artifact"] -.-> metric_artifact_sdc_constraints
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.postroutelec.result`

- **Post-route LEC result** · category `artifact` · step `postRouteLec` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_artifact_postroutelec_result["step: postRouteLec"] --> metric_artifact_postroutelec_result["artifact.postroutelec.result"]
  metric_artifact_postroutelec_result --> state_artifact_postroutelec_result["PASS"]
  cat_artifact_postroutelec_result["artifact"] -.-> metric_artifact_postroutelec_result
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `artifact.lec.result`

- **Synthesis LEC result** · category `artifact` · step `lec` · optional `True` · state **ATTENTION**

```mermaid
flowchart LR
  step_artifact_lec_result["step: lec"] --> metric_artifact_lec_result["artifact.lec.result"]
  metric_artifact_lec_result --> state_artifact_lec_result["ATTENTION"]
  cat_artifact_lec_result["artifact"] -.-> metric_artifact_lec_result
```

[↑ category `artifact`](#category-artifact) · [↑ Contents](#contents)

### `flow.route.completed`

- **route flow completed** · category `flow` · step `route` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_flow_route_completed["step: route"] --> metric_flow_route_completed["flow.route.completed"]
  metric_flow_route_completed --> state_flow_route_completed["PASS"]
  cat_flow_route_completed["flow"] -.-> metric_flow_route_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.drc.completed`

- **drc flow completed** · category `flow` · step `drc` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_flow_drc_completed["step: drc"] --> metric_flow_drc_completed["flow.drc.completed"]
  metric_flow_drc_completed --> state_flow_drc_completed["PASS"]
  cat_flow_drc_completed["flow"] -.-> metric_flow_drc_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.lvs.completed`

- **lvs flow completed** · category `flow` · step `lvs` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_flow_lvs_completed["step: lvs"] --> metric_flow_lvs_completed["flow.lvs.completed"]
  metric_flow_lvs_completed --> state_flow_lvs_completed["PASS"]
  cat_flow_lvs_completed["flow"] -.-> metric_flow_lvs_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.filler.completed`

- **filler flow completed** · category `flow` · step `filler` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_flow_filler_completed["step: filler"] --> metric_flow_filler_completed["flow.filler.completed"]
  metric_flow_filler_completed --> state_flow_filler_completed["PASS"]
  cat_flow_filler_completed["flow"] -.-> metric_flow_filler_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.postroutelec.completed`

- **postRouteLec flow completed** · category `flow` · step `postRouteLec` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_flow_postroutelec_completed["step: postRouteLec"] --> metric_flow_postroutelec_completed["flow.postroutelec.completed"]
  metric_flow_postroutelec_completed --> state_flow_postroutelec_completed["PASS"]
  cat_flow_postroutelec_completed["flow"] -.-> metric_flow_postroutelec_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.rcx.completed`

- **RCX flow completed** · category `flow` · step `RCX` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_flow_rcx_completed["step: RCX"] --> metric_flow_rcx_completed["flow.rcx.completed"]
  metric_flow_rcx_completed --> state_flow_rcx_completed["PASS"]
  cat_flow_rcx_completed["flow"] -.-> metric_flow_rcx_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.sta.completed`

- **sta flow completed** · category `flow` · step `sta` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_flow_sta_completed["step: sta"] --> metric_flow_sta_completed["flow.sta.completed"]
  metric_flow_sta_completed --> state_flow_sta_completed["PASS"]
  cat_flow_sta_completed["flow"] -.-> metric_flow_sta_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.harden.completed`

- **Harden flow completed** · category `flow` · step `Harden` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_flow_harden_completed["step: Harden"] --> metric_flow_harden_completed["flow.harden.completed"]
  metric_flow_harden_completed --> state_flow_harden_completed["PASS"]
  cat_flow_harden_completed["flow"] -.-> metric_flow_harden_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.synthesis.completed`

- **Synthesis flow completed** · category `flow` · step `Synthesis` · optional `True` · state **WARN**

```mermaid
flowchart LR
  step_flow_synthesis_completed["step: Synthesis"] --> metric_flow_synthesis_completed["flow.synthesis.completed"]
  metric_flow_synthesis_completed --> state_flow_synthesis_completed["WARN"]
  cat_flow_synthesis_completed["flow"] -.-> metric_flow_synthesis_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.place.completed`

- **place flow completed** · category `flow` · step `place` · optional `True` · state **WARN**

```mermaid
flowchart LR
  step_flow_place_completed["step: place"] --> metric_flow_place_completed["flow.place.completed"]
  metric_flow_place_completed --> state_flow_place_completed["WARN"]
  cat_flow_place_completed["flow"] -.-> metric_flow_place_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.cts.completed`

- **CTS flow completed** · category `flow` · step `CTS` · optional `True` · state **WARN**

```mermaid
flowchart LR
  step_flow_cts_completed["step: CTS"] --> metric_flow_cts_completed["flow.cts.completed"]
  metric_flow_cts_completed --> state_flow_cts_completed["WARN"]
  cat_flow_cts_completed["flow"] -.-> metric_flow_cts_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.legalization.completed`

- **legalization flow completed** · category `flow` · step `legalization` · optional `True` · state **WARN**

```mermaid
flowchart LR
  step_flow_legalization_completed["step: legalization"] --> metric_flow_legalization_completed["flow.legalization.completed"]
  metric_flow_legalization_completed --> state_flow_legalization_completed["WARN"]
  cat_flow_legalization_completed["flow"] -.-> metric_flow_legalization_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `flow.poweranalysis.completed`

- **powerAnalysis flow completed** · category `flow` · step `powerAnalysis` · optional `True` · state **WARN**

```mermaid
flowchart LR
  step_flow_poweranalysis_completed["step: powerAnalysis"] --> metric_flow_poweranalysis_completed["flow.poweranalysis.completed"]
  metric_flow_poweranalysis_completed --> state_flow_poweranalysis_completed["WARN"]
  cat_flow_poweranalysis_completed["flow"] -.-> metric_flow_poweranalysis_completed
```

[↑ category `flow`](#category-flow) · [↑ Contents](#contents)

### `quality.cts.skew_target`

- **CTS skew target met** · category `quality_gate` · step `CTS` · optional `True` · state **WARN**

```mermaid
flowchart LR
  step_quality_cts_skew_target["step: CTS"] --> metric_quality_cts_skew_target["quality.cts.skew_target"]
  metric_quality_cts_skew_target --> state_quality_cts_skew_target["WARN"]
  cat_quality_cts_skew_target["quality_gate"] -.-> metric_quality_cts_skew_target
```

[↑ category `quality_gate`](#category-quality_gate) · [↑ Contents](#contents)

### `quality.route.dr_clean`

- **Route DR clean** · category `quality_gate` · step `route` · optional `True` · state **WARN**

```mermaid
flowchart LR
  step_quality_route_dr_clean["step: route"] --> metric_quality_route_dr_clean["quality.route.dr_clean"]
  metric_quality_route_dr_clean --> state_quality_route_dr_clean["WARN"]
  cat_quality_route_dr_clean["quality_gate"] -.-> metric_quality_route_dr_clean
```

[↑ category `quality_gate`](#category-quality_gate) · [↑ Contents](#contents)

### `provenance.initial.rtl`

- **Initial RTL** · category `provenance` · step `workspace` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_provenance_initial_rtl["step: workspace"] --> metric_provenance_initial_rtl["provenance.initial.rtl"]
  metric_provenance_initial_rtl --> state_provenance_initial_rtl["PASS"]
  cat_provenance_initial_rtl["provenance"] -.-> metric_provenance_initial_rtl
```

[↑ category `provenance`](#category-provenance) · [↑ Contents](#contents)

### `provenance.initial.sdc`

- **Initial SDC** · category `provenance` · step `workspace` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_provenance_initial_sdc["step: workspace"] --> metric_provenance_initial_sdc["provenance.initial.sdc"]
  metric_provenance_initial_sdc --> state_provenance_initial_sdc["PASS"]
  cat_provenance_initial_sdc["provenance"] -.-> metric_provenance_initial_sdc
```

[↑ category `provenance`](#category-provenance) · [↑ Contents](#contents)

### `configuration.db`

- **Configuration db** · category `configuration` · step `workspace` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_configuration_db["step: workspace"] --> metric_configuration_db["configuration.db"]
  metric_configuration_db --> state_configuration_db["PASS"]
  cat_configuration_db["configuration"] -.-> metric_configuration_db
```

[↑ category `configuration`](#category-configuration) · [↑ Contents](#contents)

### `configuration.rcx`

- **Configuration RCX** · category `configuration` · step `workspace` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_configuration_rcx["step: workspace"] --> metric_configuration_rcx["configuration.rcx"]
  metric_configuration_rcx --> state_configuration_rcx["PASS"]
  cat_configuration_rcx["configuration"] -.-> metric_configuration_rcx
```

[↑ category `configuration`](#category-configuration) · [↑ Contents](#contents)

### `configuration.sta`

- **Configuration sta** · category `configuration` · step `workspace` · optional `False` · state **PASS**

```mermaid
flowchart LR
  step_configuration_sta["step: workspace"] --> metric_configuration_sta["configuration.sta"]
  metric_configuration_sta --> state_configuration_sta["PASS"]
  cat_configuration_sta["configuration"] -.-> metric_configuration_sta
```

[↑ category `configuration`](#category-configuration) · [↑ Contents](#contents)

### `performance.sta.setup_wns`

- **STA setup WNS** · category `performance` · step `sta` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_sta_setup_wns["step: sta"] --> metric_performance_sta_setup_wns["performance.sta.setup_wns"]
  metric_performance_sta_setup_wns --> state_performance_sta_setup_wns["PASS"]
  cat_performance_sta_setup_wns["performance"] -.-> metric_performance_sta_setup_wns
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.sta.setup_tns`

- **STA setup TNS** · category `performance` · step `sta` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_sta_setup_tns["step: sta"] --> metric_performance_sta_setup_tns["performance.sta.setup_tns"]
  metric_performance_sta_setup_tns --> state_performance_sta_setup_tns["PASS"]
  cat_performance_sta_setup_tns["performance"] -.-> metric_performance_sta_setup_tns
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.sta.hold_wns`

- **STA hold WNS** · category `performance` · step `sta` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_sta_hold_wns["step: sta"] --> metric_performance_sta_hold_wns["performance.sta.hold_wns"]
  metric_performance_sta_hold_wns --> state_performance_sta_hold_wns["PASS"]
  cat_performance_sta_hold_wns["performance"] -.-> metric_performance_sta_hold_wns
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.sta.hold_tns`

- **STA hold TNS** · category `performance` · step `sta` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_sta_hold_tns["step: sta"] --> metric_performance_sta_hold_tns["performance.sta.hold_tns"]
  metric_performance_sta_hold_tns --> state_performance_sta_hold_tns["PASS"]
  cat_performance_sta_hold_tns["performance"] -.-> metric_performance_sta_hold_tns
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.sta.frequency`

- **STA frequency** · category `performance` · step `sta` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_sta_frequency["step: sta"] --> metric_performance_sta_frequency["performance.sta.frequency"]
  metric_performance_sta_frequency --> state_performance_sta_frequency["PASS"]
  cat_performance_sta_frequency["performance"] -.-> metric_performance_sta_frequency
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.power.dynamic`

- **Dynamic power** · category `performance` · step `sta` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_power_dynamic["step: sta"] --> metric_performance_power_dynamic["performance.power.dynamic"]
  metric_performance_power_dynamic --> state_performance_power_dynamic["PASS"]
  cat_performance_power_dynamic["performance"] -.-> metric_performance_power_dynamic
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.power.leakage`

- **Leakage power** · category `performance` · step `sta` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_power_leakage["step: sta"] --> metric_performance_power_leakage["performance.power.leakage"]
  metric_performance_power_leakage --> state_performance_power_leakage["PASS"]
  cat_performance_power_leakage["performance"] -.-> metric_performance_power_leakage
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.sdc.clock_count`

- **SDC clock count** · category `performance` · step `workspace` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_sdc_clock_count["step: workspace"] --> metric_performance_sdc_clock_count["performance.sdc.clock_count"]
  metric_performance_sdc_clock_count --> state_performance_sdc_clock_count["PASS"]
  cat_performance_sdc_clock_count["performance"] -.-> metric_performance_sdc_clock_count
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.cts.skew`

- **CTS worst skew** · category `performance` · step `CTS` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_cts_skew["step: CTS"] --> metric_performance_cts_skew["performance.cts.skew"]
  metric_performance_cts_skew --> state_performance_cts_skew["PASS"]
  cat_performance_cts_skew["performance"] -.-> metric_performance_cts_skew
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.cts.insertion_latency`

- **CTS max insertion latency** · category `performance` · step `CTS` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_cts_insertion_latency["step: CTS"] --> metric_performance_cts_insertion_latency["performance.cts.insertion_latency"]
  metric_performance_cts_insertion_latency --> state_performance_cts_insertion_latency["PASS"]
  cat_performance_cts_insertion_latency["performance"] -.-> metric_performance_cts_insertion_latency
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.cts.buffer_count`

- **CTS buffer count** · category `performance` · step `CTS` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_cts_buffer_count["step: CTS"] --> metric_performance_cts_buffer_count["performance.cts.buffer_count"]
  metric_performance_cts_buffer_count --> state_performance_cts_buffer_count["PASS"]
  cat_performance_cts_buffer_count["performance"] -.-> metric_performance_cts_buffer_count
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.cts.clock_wirelength`

- **CTS clock wirelength** · category `performance` · step `CTS` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_cts_clock_wirelength["step: CTS"] --> metric_performance_cts_clock_wirelength["performance.cts.clock_wirelength"]
  metric_performance_cts_clock_wirelength --> state_performance_cts_clock_wirelength["PASS"]
  cat_performance_cts_clock_wirelength["performance"] -.-> metric_performance_cts_clock_wirelength
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.cts.tree_max_level`

- **CTS clock tree max level** · category `performance` · step `CTS` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_cts_tree_max_level["step: CTS"] --> metric_performance_cts_tree_max_level["performance.cts.tree_max_level"]
  metric_performance_cts_tree_max_level --> state_performance_cts_tree_max_level["PASS"]
  cat_performance_cts_tree_max_level["performance"] -.-> metric_performance_cts_tree_max_level
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.place.hpwl`

- **Place HPWL** · category `performance` · step `place` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_place_hpwl["step: place"] --> metric_performance_place_hpwl["performance.place.hpwl"]
  metric_performance_place_hpwl --> state_performance_place_hpwl["PASS"]
  cat_performance_place_hpwl["performance"] -.-> metric_performance_place_hpwl
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.place.congestion_overflow`

- **Place EGR overflow total** · category `performance` · step `place` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_place_congestion_overflow["step: place"] --> metric_performance_place_congestion_overflow["performance.place.congestion_overflow"]
  metric_performance_place_congestion_overflow --> state_performance_place_congestion_overflow["PASS"]
  cat_performance_place_congestion_overflow["performance"] -.-> metric_performance_place_congestion_overflow
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.route.wirelength`

- **Route wirelength** · category `performance` · step `route` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_route_wirelength["step: route"] --> metric_performance_route_wirelength["performance.route.wirelength"]
  metric_performance_route_wirelength --> state_performance_route_wirelength["PASS"]
  cat_performance_route_wirelength["performance"] -.-> metric_performance_route_wirelength
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.route.via_count`

- **Route via count** · category `performance` · step `route` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_route_via_count["step: route"] --> metric_performance_route_via_count["performance.route.via_count"]
  metric_performance_route_via_count --> state_performance_route_via_count["PASS"]
  cat_performance_route_via_count["performance"] -.-> metric_performance_route_via_count
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.synthesis.cell_area`

- **Synthesis cell area** · category `performance` · step `Synthesis` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_synthesis_cell_area["step: Synthesis"] --> metric_performance_synthesis_cell_area["performance.synthesis.cell_area"]
  metric_performance_synthesis_cell_area --> state_performance_synthesis_cell_area["PASS"]
  cat_performance_synthesis_cell_area["performance"] -.-> metric_performance_synthesis_cell_area
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.synthesis.cell_count`

- **Synthesis cell count** · category `performance` · step `Synthesis` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_synthesis_cell_count["step: Synthesis"] --> metric_performance_synthesis_cell_count["performance.synthesis.cell_count"]
  metric_performance_synthesis_cell_count --> state_performance_synthesis_cell_count["PASS"]
  cat_performance_synthesis_cell_count["performance"] -.-> metric_performance_synthesis_cell_count
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.host.latency`

- **组件耗时** · category `performance` · step `host` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_host_latency["step: host"] --> metric_performance_host_latency["performance.host.latency"]
  metric_performance_host_latency --> state_performance_host_latency["PASS"]
  cat_performance_host_latency["performance"] -.-> metric_performance_host_latency
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.host.throughput`

- **速度** · category `performance` · step `host` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_host_throughput["step: host"] --> metric_performance_host_throughput["performance.host.throughput"]
  metric_performance_host_throughput --> state_performance_host_throughput["PASS"]
  cat_performance_host_throughput["performance"] -.-> metric_performance_host_throughput
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.host.peak_memory`

- **内存峰值** · category `performance` · step `host` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_host_peak_memory["step: host"] --> metric_performance_host_peak_memory["performance.host.peak_memory"]
  metric_performance_host_peak_memory --> state_performance_host_peak_memory["PASS"]
  cat_performance_host_peak_memory["performance"] -.-> metric_performance_host_peak_memory
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.host.avg_memory`

- **内存平均** · category `performance` · step `host` · optional `True` · state **PASS**

```mermaid
flowchart LR
  step_performance_host_avg_memory["step: host"] --> metric_performance_host_avg_memory["performance.host.avg_memory"]
  metric_performance_host_avg_memory --> state_performance_host_avg_memory["PASS"]
  cat_performance_host_avg_memory["performance"] -.-> metric_performance_host_avg_memory
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

### `performance.host.compile_peak_memory`

- **编译内存峰值** · category `performance` · step `host` · optional `True` · state **MISS**

```mermaid
flowchart LR
  step_performance_host_compile_peak_memory["step: host"] --> metric_performance_host_compile_peak_memory["performance.host.compile_peak_memory"]
  metric_performance_host_compile_peak_memory --> state_performance_host_compile_peak_memory["MISS"]
  cat_performance_host_compile_peak_memory["performance"] -.-> metric_performance_host_compile_peak_memory
```

[↑ category `performance`](#category-performance) · [↑ Contents](#contents)

---

_Generated by `.github/scripts/generate-signoff-kanban.py` from `chipcompiler.engine.signoff.catalog`._

## Version

| Field | Value |
| --- | --- |
| Git commit | [`5ef13d11ec40`](https://github.com/plitenh/ecc/commit/5ef13d11ec40f352c97c7f401d6dcbe4526139d1) |
| Git commit (full) | `5ef13d11ec40f352c97c7f401d6dcbe4526139d1` |
| Snapshot SHA-256 | `3dda23f35c290f651d33c89f8fb0366166ca2de5ce855d3cc2f7ab2e48368b7a` |

Compare snapshots with `plitenh/ecc-ci`:

- pairwise: `scripts/diff_signoff_snapshots.py` (versions · item delta · state delta)
- multi-point batch diagram: `scripts/diagram_signoff_compare.py` (mermaid + ASCII matrix across N versions)
