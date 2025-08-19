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
from pathlib import Path

import gi
gi.require_version('Gtk', '4.0')
gi.require_version('Adw', '1')
from gi.repository import Gtk, Adw, GLib, Gio


# Translation setup
TEXTDOMAIN = 'grub-btrfs-timeshift'
LOCALEDIR = '/usr/share/locale'

try:
    locale.setlocale(locale.LC_ALL, '')
    gettext.bindtextdomain(TEXTDOMAIN, LOCALEDIR)
    gettext.textdomain(TEXTDOMAIN)
    _ = gettext.gettext
except:
    # Fallback if translation fails
    _ = lambda x: x


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


class BtrfsManager:
    """Handles BTRFS subvolume operations"""
    
    @staticmethod
    def list_subvolumes():
        """List all BTRFS subvolumes"""
        try:
            result = subprocess.run(['btrfs', 'subvolume', 'list', '/'], 
                                 capture_output=True, text=True, check=True)
            return result.stdout
        except subprocess.CalledProcessError:
            return ""
    
    @staticmethod
    def check_root_subvolume_exists():
        """Check if original @ subvolume still exists"""
        subvolumes = BtrfsManager.list_subvolumes()
        return 'path @\n' in subvolumes or 'path @' in subvolumes.split('\n')[-1]


class GrubManager:
    """Handles GRUB configuration regeneration"""
    
    @staticmethod
    def regenerate_config():
        """Regenerate GRUB configuration"""
        try:
            result = subprocess.run(['grub-mkconfig', '-o', '/boot/grub/grub.cfg'], 
                                 capture_output=True, text=True, check=True)
            return True, result.stdout
        except subprocess.CalledProcessError as e:
            return False, e.stderr
    
    @staticmethod
    def verify_config():
        """Verify GRUB configuration has subvolume entries"""
        try:
            with open('/boot/grub/grub.cfg', 'r') as f:
                content = f.read()
            return 'rootflags=subvol=' in content
        except Exception:
            return False


class TimeshiftManager:
    """Handles Timeshift restore operations"""
    
    def __init__(self, progress_callback=None):
        self.progress_callback = progress_callback
    
    def restore_snapshot(self, snapshot_name):
        """Restore a specific snapshot using Timeshift"""
        try:
            if self.progress_callback:
                self.progress_callback(_("Starting Timeshift restoration..."))
            
            # Kill any running timeshift processes
            subprocess.run(['killall', 'timeshift-gtk'], capture_output=True)
            
            # Execute timeshift restore
            cmd = ['timeshift', '--restore', '--snapshot', snapshot_name, '--scripted', '--yes']
            process = subprocess.Popen(cmd, stdin=subprocess.PIPE, 
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, 
                                     text=True)
            
            # Send empty responses to any prompts
            stdout, stderr = process.communicate(input='\n' * 10)
            
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
        self.window.set_default_size(500, 630)
        self.window.set_resizable(False)
        
        # Main container - exactly like WelcomeDialog
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)

        # Header with close button - exactly like WelcomeDialog  
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL)
        header_box.set_size_request(-1, 50)
        header_box.set_margin_start(20)
        header_box.set_margin_end(15)
        header_box.set_margin_top(5)
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
        close_button.connect('clicked', self._on_close_clicked)
        header_box.append(close_button)
        
        main_box.append(header_box)

        # ScrolledWindow for content - exactly like WelcomeDialog
        scrolled_window = Gtk.ScrolledWindow()
        scrolled_window.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        scrolled_window.set_vexpand(True)

        # Content container
        content_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=16)
        content_box.set_margin_top(8)
        content_box.set_margin_bottom(16)
        content_box.set_margin_start(20)
        content_box.set_margin_end(20)

        # Icon centered
        icon = Gtk.Image.new_from_icon_name("timeshift")
        icon.set_pixel_size(72)
        icon.set_halign(Gtk.Align.CENTER)
        icon.set_margin_bottom(8)
        content_box.append(icon)
        
        # Title
        title_label = Gtk.Label()
        title_label.set_markup(f"<span size='large' weight='bold'>Snapshot {self.snapshot_info['name']}</span>")
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
        self.progress_bar.pulse()
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
            # Store pre-restore state
            update_progress(_("Checking system state..."))
            pre_restore_has_root = BtrfsManager.check_root_subvolume_exists()
            
            # Execute restoration
            success, output = timeshift.restore_snapshot(self.snapshot_info['name'])
            
            if success:
                update_progress(_("Restoration completed. Checking system consistency..."))
                
                # Check post-restore state
                post_restore_has_root = BtrfsManager.check_root_subvolume_exists()
                
                # Always regenerate GRUB for consistency
                update_progress(_("Regenerating GRUB configuration..."))
                grub_success, grub_output = GrubManager.regenerate_config()
                
                if grub_success and GrubManager.verify_config():
                    GLib.idle_add(self._restoration_completed)
                else:
                    GLib.idle_add(self._restoration_failed, 
                                _("GRUB configuration regeneration failed"))
            else:
                GLib.idle_add(self._restoration_failed, 
                            _("Timeshift restoration failed: {}").format(output))
                
        except Exception as e:
            GLib.idle_add(self._restoration_failed, str(e))
    
    def _update_status(self, message):
        """Update status label from main thread"""
        self.status_label.set_text(message)
        self.progress_bar.pulse()
        return False
    
    def _restoration_completed(self):
        """Handle successful restoration completion"""
        self.is_restoring = False
        self.is_restored = True
        
        self.progress_bar.set_visible(False)
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
        
        self.progress_bar.set_visible(False)
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
        if self.window:
            dialog.present(self.window)
        else:
            # If no window exists, just quit
            self.quit()


def main():
    """Main entry point"""
    # Create and run application
    app = SnapshotRestoreApp()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())