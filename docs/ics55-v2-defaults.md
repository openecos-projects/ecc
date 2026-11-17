# ICS55 v2 stage configuration

This review targets the ICS55 v2 **9T** package and the ECC yell/ics55_v2 branch.
The v1 comparison input is the installed v1.10.103 **7T** package. Policy belongs
to ECC; LEF/Liberty/GDS and their process description remain PDK inputs.
The procedure below does not change system installations.

## Geometry changes

| Property | v1 (7T) | v2 (9T) | Consequence |
| --- | --- | --- | --- |
| Standard-cell site | core7 | SC9T_site | Select the adaptation's site, not the first tech-LEF site. |
| Site width / row height | 0.2 / 1.4 um | 0.2 / 1.8 um | Row construction and legalization use loaded LEF geometry. |
| Filler PG rail thickness | 0.16 um | 0.30 um | Reserve the full 0.30 um rail before signal routing. |
| Cell families | H7CH / H7CR / H7CL | 9THVT / 9TSVT / 9TLVT | Select v2 cells, libraries, catalog and VT suffixes throughout. |
| MET1–MET5 pitch / offset | 0.2 / 0.1 um | 0.2 / 0.1 um | Do not scale routing tracks by 9/7. |

The v1 H7CR LEF declares 1.4 um heights and filler VSS rectangles from -0.08 to
+0.08 um. The v2 SVT LEF declares 1.8 um heights and VSS rectangles from -0.15 to
+0.15 um (VDD: 1.65 to 1.95 um). MET1–MET5 technology LEF sections are identical
in the compared packages. V2 also contains legacy CoreSite/core7 definitions:
their presence does not authorize 7T rows for 9T cells. Select SC9T_site.

## Per-stage review

| Stage | Reviewed setting / action |
| --- | --- |
| Synthesis | Selected libraries and tie/driver cells use v2 9T names. Retain SS 1.08 V / 125 C synthesis; this is independent of STA report selection. Do not scale load or timing targets by row height. |
| preFloorplan | Select SC9T_site; the native row builder reads 0.2 x 1.8 um from LEF. Keep utilization target 0.4 in die_util mode and 2 um margins. This is not a guarantee of 40% core utilization after margins. |
| macroPlacement | Retain halo and utilization settings; coordinates use loaded LEF/DEF units. |
| postFloorplan | Change MET1 pdn_generator.rail width_micron from 0.16 to **0.30**. Retain VDD/VSS and VNW/VPW connections. Tap/endcap names are v2 TAPX1_9TSVT. |
| Tap / boundary cells | Retain 58 um tap spacing and 30 um boundary rule pending separate process-rule qualification; neither follows from 9/7 scaling. Existing FILLCAP boundary cells precede routing, so the router sees their shapes. Exclude them from post-route whitespace filling. |
| PDN stripes / IO | Retain MET4/MET5 stripes (1 um width, 16 um pitch) and MET3/MET4 auto IO. These are flow defaults, not current-capacity or latch-up signoff. |
| preplace / place / legalization | Keep one-site padding (200 DBU = 0.2 um) where selected; load site, row height and VT definitions from v2 resources. No 1.4 um row-height override is appropriate. |
| diff_sizing / Timing optimization | Use _9THVT, _9TSVT, _9TLVT groups, v2 buffers and the declared hold view. Keep DreamPlace coarse GR on MET2–MET5 independently of detailed routing. Track count alone does not justify scaling extraction/RC models. |
| CTS | Use v2 LVT buffers and libraries. Retain fanout, slew, skew and routing-layer settings; row height does not establish new electrical limits. |
| route | Default signal range **MET1–MET5**, as requested. MET2-only lower-layer pin access remains a separate router limitation; this change does not claim to fix it. |
| filler | Pass the explicit roles through native MJ.-filler: FILL32/16/8/4/2/1_9TSVT. Empty CLI selection resolves PDK filler roles. Refuse native insertion if the resolved list is empty, preventing all-CORE auto-selection. |
| DRC / LVS / antenna / postRouteLec | Preserve checks and policies. Do not waive spacing, connectivity or equivalence failures. Execution success is distinct from a clean physical result. |
| RCX / STA | Keep TYP_25/TYPICAL and MIN_m40 with Cworst/RCworst/Cbest/RCbest reports. SS libraries may remain available without adding SS reports. |
| Power / EMIR | Explicit synthetic ICS55 EMIR is for flow testing only, with provenance and non-signoff labels. A declared EM process resource has priority. |
| Harden / delivery | Register GDS files and the layer map in the ECC-managed description. Registration alone does not verify merged foundry cell geometry or tapeout qualification. |

## Apply defaults through ECC CLI

First import a complete matching description/adaptation through ECC's existing
PDK configure import interface. From this repository:

~~~sh
export ECC_PDK_INVENTORY=/isolated/test/state/pdk-inventory.json
python3 scripts/pdk/configure_ics55_v2.py \
  --ecc /path/to/local/ecc \
  --root /path/to/icsprout55-pdk-v2 \
  --synthetic-emir
~~~

The helper uses public ECC configure show/set commands with revision checks.
It requires the existing ICS55 SC9T_site adaptation, updates MET1 routing,
the 0.30 um rail and native filler configuration, and registers available GDS
resources with hashes. The optional flag explicitly selects synthetic EMIR.
The adaptation's parameters.dreamplace.gpugr_bottom_routing_layer is MET2;
parameters.bottom_layer remains MET1 for final routing. This separation prevents
the detail-router default from changing the coarse GR timing model's layer range.
It never writes the PDK root or installs tools. Keep the inventory isolated
while testing alongside the server's v1 installation.

New projects bind these defaults. Existing project/workspace locks do not
automatically migrate. Retest an existing RTL design in a new project:

~~~sh
/path/to/local/ecc pdk clone-with-pdk --source /projects/aes_v2 \
  --target /projects/aes_v2_defaults --root /path/to/icsprout55-pdk-v2
/path/to/local/ecc run --project /projects/aes_v2_defaults --workspace ws_0001
~~~

Do not edit generated workspace JSON. Public parameters route.bottom_layer,
filler.-filler and emir.synthetic_model support explicit workspace experiments
through ECC param set. A rail-width change requires floorplanning and all
dependent physical stages to be rerun.

## Regression evidence

On the retained AES route checkpoint, fixing the native filler allowlist removed
all reported shorts: signal nets and both power nets had zero opens/shorts.
Independent DRC decreased from 29,992 to 109 MET1 spacing violations. Remaining
markers involve VDD/VSS, consistent with the old 0.16 um rail reservation and
newly inserted 0.30 um filler rails. The filler-only rerun does not prove that
changing the rail width closes all DRC; a new full flow verifies that separately.

The initial full AES rerun exposed an additional configuration interaction:
propagating MET1 into sizing GR produced an unrouted dcnt_0_ net and was correctly
rejected by the GR RC-tree validator. Explicitly retaining MET2 for DreamPlace GR
passed differential sizing; no unrouted-net guard was disabled.

The fresh GCD project created using the updated managed defaults has 1800 DBU
row spacing, a 300 DBU MET1 follow-pin rail, and 585 post-route insertions, all
from the six selected passive FILL masters. Its independent post-filler DRC
reports zero violations, and LVS reports zero opens/shorts for signal, VDD and
VSS nets. This is a configuration regression result, not foundry signoff.
The native summary reports about 39.5% die utilization and 45.4% core utilization:
the die_util target applies before the core margins. Neither target nor margins
need automatic 9/7 scaling.
All 21 enabled GCD stages complete successfully, including EMIR and Harden,
which produces GDS, LEF, Liberty and PNG. TYP setup/hold WNS is 2.188/0.206 ns;
the four MIN reports also have positive setup/hold slack. EMIR provenance
correctly identifies the synthetic model as not_for_signoff.

The AES rerun with 0.30 um rails has zero signal/PG opens or shorts and one
remaining independent MET1 spacing violation. The router already reports that
violation before filler insertion: the input access via on BUFX10_9TLVT at
(134.500, 170.233) um has 0.088 um clearance to the cell's internal OBS, versus
the technology LEF's 0.090 um requirement. This is a remaining native pin-access
repair issue, not evidence that the rail should be narrowed or filler roles
expanded. Preserve the DRC gate; AES is not physically clean.

The matching local native runtime passes 4484 unit tests (3 skipped, 2 integration
tests deselected, 4 expected failures) and 272 Agent tests. Ruff and the
basedpyright gate pass. The local PyInstaller CLI builds successfully; it is
tested through an isolated launcher and is not installed to the system.

Raw regression artifacts are under benchmark/test/ics55_v2_defaults_20261118/.
Consult that campaign's final report for full-flow results and limitations.
