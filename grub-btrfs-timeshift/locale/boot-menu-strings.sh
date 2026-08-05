#!/bin/bash
# Not executed, and not shipped: only the usr, etc and opt trees are packaged.
#
# The boot menu is built by generators under /etc/grub.d, which look up their
# text with `gettext "..."` at grub-mkconfig time. The translation pipeline
# extracts shell strings with `bash --dump-po-strings`, and that only sees
# bash's own $"..." form - so none of the menu text ever reached a catalog and
# every entry came out in English no matter the language of the machine.
#
# Listing the same strings here in the form the extractor understands is what
# puts them in the .pot, which is what keeps their translations from being
# marked obsolete on the next run.
#
# Keep in step with:
#   usr/share/libalpm/scripts/grub-btrfs-timeshift
#   etc/grub.d/42_uefi-firmware

# The entry that leaves a submenu, and the name of the snapshot list.
: $"Back to the main menu"
: $"Restore points (snapshots)"

# The firmware entry, and the line grub-mkconfig prints while adding it.
: $"UEFI firmware settings"
: $"Adding boot menu entry for the UEFI firmware settings ..."

# Timeshift records why it took each snapshot as a single letter; these are the
# words those letters become before they are looked up.
: $"On demand"
: $"At boot"
: $"Hourly"
: $"Daily"
: $"Weekly"
: $"Monthly"
