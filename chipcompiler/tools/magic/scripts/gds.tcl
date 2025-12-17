# Copyright 2020 Efabless Corporation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This script expects 5 arguments: <top_name> <die_area> <input_def_path> <def_dir> <output_gds_path>
# And 3 environment variables: <MAGIC_SCRIPTS_DIR> <TECH_LEF> <CELL_GDS>

set top_name [lindex $argv [expr {$argc - 5}]]
set die_area [lindex $argv [expr {$argc - 4}]]
set def_file [lindex $argv [expr {$argc - 3}]]
set def_dir  [lindex $argv [expr {$argc - 2}]]
set gds_file [lindex $argv [expr {$argc - 1}]]

source $::env(MAGIC_SCRIPTS_DIR)/read.tcl
drc off

read_pdk_gds
gds noduplicates true

# read_macro_gds

# load (NEWCELL)

read_tech_lef
def read $def_file

load $top_name
select top cell

box [lindex $die_area 0]um [lindex $die_area 1]um [lindex $die_area 2]um [lindex $die_area 3]um
property FIXED_BBOX [box values]

select top cell

cellname filepath $top_name $def_dir

save

load $top_name

select top cell

# disable writing Caltech Intermediate Format (CIF) hierarchy and subcell array information
cif *hier write disable
cif *array write disable

gds nodatestamp yes

gds write $gds_file
puts "\[INFO\] GDS Write Complete"

exit 0
