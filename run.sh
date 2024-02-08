#!/usr/bin/env bash
# -*- coding: utf-8 -*-

# Allow running from anywhere by getting the script location
SCRIPT_DIR=$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )
cd "${SCRIPT_DIR}" || exit 1

if ! [ -d "venv" ]; then
    echo "Creating a dedicated environment"
    python3 -m venv --system-site-packages venv
    . venv/bin/activate
    echo "Adding dependencies:"
    pip install -r requirement.txt
else
    . venv/bin/activate
fi

echo "-------------------------------------------------"

python3 tesla_sniffer.py
