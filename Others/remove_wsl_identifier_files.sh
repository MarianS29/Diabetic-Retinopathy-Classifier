#!/bin/bash
# This script removes all .Identifier files from the WSL filesystem. These files are used by WSL to identify certain directories and can be safely removed if you want to clean up your filesystem.
echo "Removing .Identifier files..."

rm -rf */*/*/*/*.Identifier
rm -rf */*/*/*.Identifier
rm -rf */*/*.Identifier
rm -rf */*.Identifier
echo "Done. All .Identifier files have been removed."
echo "Luci te omor"