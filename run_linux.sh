#!/usr/bin/env bash
cd "$(dirname "$0")"
python3 -m pip install --user -r requirements.txt
python3 main.py
