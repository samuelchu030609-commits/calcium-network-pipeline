#!/usr/bin/env bash
# Installs the Calcium Network Pipeline on a Mac. See HOW_TO_INSTALL.md for the full guide.
# How to run it: open Terminal, type  bash  and a space, drag this file into the
# Terminal window, and press Return. No administrator password is needed.
exec bash "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/install/install_mac.sh" "$@"
