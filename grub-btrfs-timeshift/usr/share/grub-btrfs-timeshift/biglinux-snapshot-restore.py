#!/usr/bin/env python3
"""
BigLinux Snapshot Restore Tool
Authors: Tales A. Mendonça (communitybig.org)
Date: 2025
Description: GTK4 + libadwaita interface for Timeshift snapshot restoration
License: GPL V3
"""

import sys
import os
import re
import subprocess
import threading
import gettext
import locale
from datetime import datetime

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gdk


# Translation setup
TEXTDOMAIN = 'grub-btrfs-timeshift'
LOCALEDIR = '/usr/share/locale'

# What /etc/timeshift/restore-hooks.d/50-reinstall-grub prints when it fails.
GRUB_HOOK_FAILURE = 'grub-btrfs-timeshift: boot loader not reinstalled:'

try:
    locale.setlocale(locale.LC_ALL, '')
except locale.Error:
    # A locale the system does not have: the dialog stays in English.
    pass
gettext.bindtextdomain(TEXTDOMAIN, LOCALEDIR)
gettext.textdomain(TEXTDOMAIN)
_ = gettext.gettext


class SnapshotDetector:
    """Handles detection and parsing of current snapshot information"""
    
    @staticmethod
    def is_in_snapshot():
        """Check if system is booted from a timeshift snapshot"""
        try:
            with open('/proc/cmdline', 'r') as f:
                cmdline = f.read().strip()
            return 'timeshift-btrfs/snapshots' in cmdline
        except Exception:
            return False
    
    @staticmethod
    def get_snapshot_info():
        """Extract snapshot information from boot parameters"""
        try:
            with open('/proc/cmdline', 'r') as f:
                cmdline = f.read().strip()
            
            # Extract subvolume path
            subvol_match = re.search(r'subvol=([^\s]+)', cmdline)
            subvol_path = subvol_match.group(1) if subvol_match else ''
            
            # Extract snapshot date from path
            snapshot_match = re.search(r'timeshift-btrfs/snapshots/([^/@\s]+)', cmdline)
            if snapshot_match:
                snapshot_name = snapshot_match.group(1)
                # Parse date and time from snapshot name (format: 2025-08-11_23-00-00)
                date_part = snapshot_name.split('_')[0]
                time_part = snapshot_name.split('_')[1] if '_' in snapshot_name else '00-00-00'
                
                # Format date and time for display
                try:
                    date_obj = datetime.strptime(date_part, '%Y-%m-%d')
                    formatted_date = date_obj.strftime('%d/%m/%Y')
                    formatted_time = time_part.replace('-', ':')
                    
                    return {
                        'name': snapshot_name,
                        'path': subvol_path,
                        'date': formatted_date,
                        'time': formatted_time,
                        'raw_date': date_part,
                        'raw_time': time_part
                    }
                except ValueError:
                    pass
            
            return None
        except Exception:
            return None


class TimeshiftManager:
    """Handles Timeshift restore operations"""
    
    def __init__(self, progress_callback=None):
        self.progress_callback = progress_callback
    
    def restore_snapshot(self, snapshot_name):
        """Restore a specific snapshot using Timeshift"""
        try:
            if self.progress_callback:
                self.progress_callback(_("Restoring the snapshot and reinstalling the boot loader..."))
            
            # Kill any running timeshift processes
            subprocess.run(['killall', 'timeshift-gtk'], capture_output=True)
            
            # Execute timeshift restore with pkexec for privileges
            cmd = ['pkexec', 'timeshift', '--restore', '--snapshot', snapshot_name, '--scripted', '--yes']
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, 
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                    text=True, env={"DISPLAY": os.environ.get("DISPLAY", ""), 
                                                "XAUTHORITY": os.environ.get("XAUTHORITY", "")})
            
            # Send empty responses to any prompts
            stdout, stderr = process.communicate(input='\n' * 10)
            
            # The restore hook that reinstalls GRUB reports through Timeshift's
            # output, because Timeshift ignores the exit status of its hooks.
            for line in (stdout + stderr).splitlines():
                if line.startswith(GRUB_HOOK_FAILURE):
                    reason = line[len(GRUB_HOOK_FAILURE):].strip()
                    return False, _(
                        "The system was restored, but its boot loader could not be "
                        "reinstalled: {}. Restarting now may stop at the \"grub rescue\" "
                        "prompt. Try the restore again, or repair the boot loader with "
                        "BigLinux GRUB Restore from a live USB."
                    ).format(reason)

            if process.returncode == 0:
                if self.progress_callback:
                    self.progress_callback(_("Timeshift restoration completed"))
                return True, stdout
            else:
                return False, stderr
                
        except Exception as e:
            return False, str(e)


class SnapshotRestoreApp(Adw.Application):
    """Main GTK4 + libadwaita application"""
    
    def __init__(self):
        super().__init__(application_id='org.biglinux.SnapshotRestore')
        self.snapshot_info = None
        self.window = None
        self.restore_button = None
        self.status_label = None
        self.progress_bar = None
        self.is_restoring = False
        self.is_restored = False
        self.pulse_source = 0
        
    def do_activate(self):
        """Application activation handler"""
        # Check if in snapshot
        if not SnapshotDetector.is_in_snapshot():
            print(_("Snapshot not detected: This application only runs when booted from a Timeshift snapshot."))
            print(_("Did you really boot into the snapshot?"))
            self.quit()
            return
        
        # Get snapshot information
        self.snapshot_info = SnapshotDetector.get_snapshot_info()
        if not self.snapshot_info:
            self.show_error_dialog(_("Error"), 
                                 _("Could not parse snapshot information"))
            return
        
        # Create and show main window
        self.create_main_window()
    
    def create_main_window(self):
        """Create the main application window"""
        self.window = Adw.ApplicationWindow(application=self)
        self.window.set_title(f"Snapshot {self.snapshot_info['name']}")
        self.window.set_default_size(500, -1)
        self.window.set_resizable(False)
        
        # Center the window on the screen
        self.window.set_modal(True)
        
        # Main container - exactly like WelcomeDialog
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header with close button - exactly like WelcomeDialog  
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header_box.set_size_request(-1, 35)
        header_box.set_margin_start(20)
        header_box.set_margin_end(8)
        header_box.set_margin_top(4)
        header_box.add_css_class("header-area")
        
        # Spacer to push close button to the right
        header_spacer = Gtk.Box()
        header_spacer.set_hexpand(True)
        header_box.append(header_spacer)
        
        # Close button in top right corner
        close_button = Gtk.Button()
        close_button.set_icon_name("window-close-symbolic")
        close_button.set_tooltip_text(_("Close"))
        close_button.add_css_class("flat")
        close_button.add_css_class("circular")
        close_button.set_size_request(32, 32)
        # Ensure button is perfectly square for circular effect
        close_button.set_valign(Gtk.Align.CENTER)
        close_button.set_halign(Gtk.Align.CENTER)
        close_button.connect('clicked', self._on_close_clicked)
        header_box.append(close_button)
        
        main_box.append(header_box)

        # ScrolledWindow for content - exactly like WelcomeDialog
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_vexpand(True)
        # The window grows with a long status message, up to what a 768-pixel
        # screen shows; past that the content scrolls.
        scrolled_window.set_propagate_natural_height(True)
        scrolled_window.set_max_content_height(680)

        # Content container
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content_box.set_margin_top(4)
        content_box.set_margin_bottom(16)
        content_box.set_margin_start(20)
        content_box.set_margin_end(20)

        # Icon centered
        icon = Gtk.Image.new_from_icon_name("big-timeshift")
        icon.set_pixel_size(72)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_margin_bottom(8)
        content_box.append(icon)
        
        # Title
        title_label = Gtk.Label()
        name = GLib.markup_escape_text(self.snapshot_info['name'])
        title_label.set_markup(f"<span size='large' weight='bold'>Snapshot {name}</span>")
        title_label.set_halign(Gtk.Align.CENTER)
        title_label.set_margin_bottom(12)
        content_box.append(title_label)

        # Snapshot information group
        info_group = Adw.PreferencesGroup()
        info_group.set_margin_bottom(15)
        
        # File path row
        file_row = Adw.ActionRow()
        file_row.set_title(_("File"))
        file_row.set_subtitle(self.snapshot_info['path'])
        file_row.add_css_class("property")
        info_group.add(file_row)
        
        # Date row
        date_row = Adw.ActionRow()
        date_row.set_title(_("Date"))
        date_row.set_subtitle(self.snapshot_info['date'])
        date_row.add_css_class("property")
        info_group.add(date_row)
        
        # Time row
        time_row = Adw.ActionRow()
        time_row.set_title(_("Time"))
        time_row.set_subtitle(self.snapshot_info['time'])
        time_row.add_css_class("property")
        info_group.add(time_row)
        
        content_box.append(info_group)
        
        # Description
        description = Gtk.Label()
        description.set_text(_("The system was booted from a restore point (Snapshot).\n\n"
                            "To make this restore point the default boot option, "
                            "click the button below."))
        description.set_wrap(True)
        description.set_justify(Gtk.Justification.CENTER)
        description.add_css_class("body")
        description.set_margin_top(15)
        description.set_margin_bottom(20)
        content_box.append(description)
        
        # Progress bar (initially hidden)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_visible(False)
        content_box.append(self.progress_bar)
        
        # Status label
        self.status_label = Gtk.Label()
        self.status_label.set_wrap(True)
        self.status_label.set_max_width_chars(50)
        self.status_label.set_justify(Gtk.Justification.CENTER)
        self.status_label.set_visible(False)
        content_box.append(self.status_label)
        
        # Button container
        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        button_box.set_halign(Gtk.Align.CENTER)
        button_box.set_margin_top(16)

        # Restore button
        self.restore_button = Gtk.Button()
        self.restore_button.set_label(_("Restore system to this snapshot"))
        self.restore_button.add_css_class("suggested-action")
        self.restore_button.add_css_class("pill")
        self.restore_button.set_size_request(200, 40)
        self.restore_button.connect("clicked", self.on_restore_clicked)
        button_box.append(self.restore_button)
        
        content_box.append(button_box)

        # Add content to ScrolledWindow
        scrolled_window.set_child(content_box)
        main_box.append(scrolled_window)

        # Set the content
        self.window.set_content(main_box)
        self.window.present()

        # Center after presenting
        GLib.idle_add(self._center_window)

    def _center_window(self):
        """Center window after it's been presented"""
        try:
            # Use native window positioning
            native = self.window.get_native()
            if native:
                surface = native.get_surface()
                if surface:
                    display = Gdk.Display.get_default()
                    monitor = display.get_monitors().get_item(0)  # Primary monitor
                    if monitor:
                        geometry = monitor.get_geometry()
                        window_width, window_height = 500, 640
                        x = (geometry.width - window_width) // 2
                        y = (geometry.height - window_height) // 2
                        
                        # Try different positioning methods
                        if hasattr(surface, 'set_position'):
                            surface.set_position(x, y)
                        elif hasattr(surface, 'move_to_rect'):
                            rect = Gdk.Rectangle()
                            rect.x = x
                            rect.y = y
                            rect.width = window_width
                            rect.height = window_height
                            surface.move_to_rect(rect, Gdk.Gravity.NORTH_WEST, Gdk.Gravity.NORTH_WEST, Gdk.AnchorHints.NONE, 0, 0)
        except Exception:
            pass  # Fallback to default positioning
        return False

    def _on_close_clicked(self, button):
        """Handle close button click"""
        self.quit()
    
    def on_restore_clicked(self, button):
        """Handle restore button click"""
        if self.is_restored:
            self.reboot_system()
        else:
            self.restore_system()
    
    def restore_system(self):
        """Start the restoration process"""
        if self.is_restoring:
            return
        
        self.is_restoring = True
        self.restore_button.set_sensitive(False)
        self.restore_button.set_label(_("Restoring..."))
        
        self.progress_bar.set_visible(True)
        self.pulse_source = GLib.timeout_add(100, self._pulse_progress)
        self.status_label.set_visible(True)
        
        # Start restoration in background thread
        thread = threading.Thread(target=self._restore_thread)
        thread.daemon = True
        thread.start()
    
    def _restore_thread(self):
        """Background thread for restoration process"""
        def update_progress(message):
            GLib.idle_add(self._update_status, message)
        
        # Initialize managers
        timeshift = TimeshiftManager(progress_callback=update_progress)
        
        try:
            success, output = timeshift.restore_snapshot(self.snapshot_info['name'])
            
            if success:
                GLib.idle_add(self._restoration_completed)
            else:
                GLib.idle_add(self._restoration_failed, 
                            _("Timeshift restoration failed: {}").format(output))
                
        except Exception as e:
            GLib.idle_add(self._restoration_failed, str(e))
    
    def _update_status(self, message):
        """Update status label from main thread"""
        self.status_label.set_text(message)
        return False

    def _pulse_progress(self):
        """Keep the bar moving while Timeshift, which reports no progress, runs"""
        self.progress_bar.pulse()
        return GLib.SOURCE_CONTINUE

    def _stop_progress(self):
        if self.pulse_source:
            GLib.source_remove(self.pulse_source)
            self.pulse_source = 0
        self.progress_bar.set_visible(False)
    
    def _restoration_completed(self):
        """Handle successful restoration completion"""
        self.is_restoring = False
        self.is_restored = True
        
        self._stop_progress()
        self.status_label.set_text(_("Restoration completed successfully! Please reboot the system."))
        self.status_label.add_css_class("success")
        
        self.restore_button.set_sensitive(True)
        self.restore_button.set_label(_("Restart"))
        self.restore_button.remove_css_class("suggested-action")
        self.restore_button.add_css_class("destructive-action")
        
        return False
    
    def _restoration_failed(self, error_message):
        """Handle restoration failure"""
        self.is_restoring = False
        
        self._stop_progress()
        self.status_label.set_text(_("Error: {}").format(error_message))
        self.status_label.add_css_class("error")
        
        self.restore_button.set_sensitive(True)
        self.restore_button.set_label(_("Restore System"))
        
        return False
    
    def reboot_system(self):
        """Reboot the system"""
        try:
            subprocess.run(['reboot'], check=True)
        except Exception as e:
            self.show_error_dialog(_("Reboot Error"), 
                                 _("Could not restart system: {}").format(str(e)))
    
    def show_error_dialog(self, title, message):
        """Show error dialog using newer libadwaita API"""
        dialog = Adw.AlertDialog()
        dialog.set_heading(title)
        dialog.set_body(message)
        dialog.add_response("ok", _("OK"))
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.DEFAULT)
        dialog.connect("response", lambda d, r: self.quit())
        if not self.window:
            # Without a window nothing else keeps the application running.
            self.hold()
        dialog.present(self.window)


def main():
    """Main entry point"""
    # Create and run application
    app = SnapshotRestoreApp()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())