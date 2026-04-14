#!/bin/bash

# EDT regeneration:
# edit or create skeleton_input_file (chains working on falling and rising edge)

# !!!!!!!!!! add module load dft-mentor/2022.3 if not loaded !!!!!!!!!!!!!!!!!!!!
moduleunload dft-mentor
module load dft-mentor/2022.3

cleartool co -unres -nc skeleton_input_file
cleartool co -unres -nc dummy_design*
cleartool co -unres -nc edt_ip.dofile

echo -e "\nDon't forget to change number_of_chains variable here, in skeleton_input_file and in source/verilog/rtl/soc_student_edt.v !!!\n"

declare -i number_of_chains=70
echo -e "\nCreating skeleton_input_file for $number_of_chains chains...\n"
create_skeleton_design -i skeleton_input_file -o dummy_design

  
echo -e "\nExecuting edt_ip.dofile in 5 seconds...\n"
echo -e "5....."
sleep 1
echo -e "4...."
sleep 1
echo -e "3..."
sleep 1
echo -e "2.."
sleep 1
echo -e "1."
sleep 1
tessent -shell -dofile edt_ip.dofile -replace -logfile edt_ip.log


# generated EDT RTL: gen/created_edt.v 
# copy EDT RTL to source dir
echo -e "\nCheckout and copying generated RTL in my source folder for edt design later...\n"
cleartool co -unres -nc ../source/verilog/rtl/edt.v
echo -e "\nStill passed, continuing...\n"
cp gen/created_edt.v ../source/verilog/rtl/edt.v


# copy and process gen/created_edt.dofile
# !!!ATTENTION testpattern/edt/edt_atpg/edt_cfg.dofile will be overwritten
cleartool co -nc ../testpattern/edt/edt_"$number_of_chains"_chains/edt_atpg_"$number_of_chains"/edt_cfg.dofile
cp -f gen/created_edt.dofile ../testpattern/edt/edt_"$number_of_chains"_chains/edt_atpg_"$number_of_chains"/edt_cfg.dofile

echo -e "\nDeleting lines with add_clocks and the others...\n"

sed -i '/^add_scan_groups/d'  		../testpattern/edt/edt_"$number_of_chains"_chains/edt_atpg_"$number_of_chains"/edt_cfg.dofile
sed -i '/^add_scan_chains/d'		../testpattern/edt/edt_"$number_of_chains"_chains/edt_atpg_"$number_of_chains"/edt_cfg.dofile
sed -i '/^add_clocks/d'			../testpattern/edt/edt_"$number_of_chains"_chains/edt_atpg_"$number_of_chains"/edt_cfg.dofile
sed -i '/^add_pin_constraints/d'	../testpattern/edt/edt_"$number_of_chains"_chains/edt_atpg_"$number_of_chains"/edt_cfg.dofile

echo -e "\nScript finished!\n"

echo -e "Now make synthesis on the new edt with $number_of_chains chains"
  