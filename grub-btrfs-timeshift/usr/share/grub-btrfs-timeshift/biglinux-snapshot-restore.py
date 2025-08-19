#!/usr/bin/env python3
"""
BigLinux Snapshot Restore Tool
Authors: Tales A. Mendonça (communitybig.org)
Date: 2025
Description: GTK4 + libadwaita interface for Timeshift snapshot restoration
License: GPL V2 or greater
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
            self.show_error_dialog(_("Snapshot not detected"), 
                                 _("Did you really boot into the snapshot?"))
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
        self.window.set_title(_("BigLinux Snapshot Restore"))
        self.window.set_default_size(500, 400)
        self.window.set_resizable(False)
        
        # Header bar
        header_bar = Adw.HeaderBar()
        header_bar.set_title_widget(Gtk.Label(label=f"Snapshot {self.snapshot_info['name']}"))
        self.window.set_titlebar(header_bar)
        
        # Main content
        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        main_box.set_margin_top(30)
        main_box.set_margin_bottom(30)
        main_box.set_margin_start(30)
        main_box.set_margin_end(30)
        
        # Icon and title
        icon_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=15)
        icon_box.set_halign(Gtk.Align.CENTER)
        
        icon = Gtk.Image.new_from_icon_name("timeshift")
        icon.set_pixel_size(64)
        icon_box.append(icon)
        
        title_label = Gtk.Label(label="Timeshift")
        title_label.add_css_class("title-1")
        icon_box.append(title_label)
        
        main_box.append(icon_box)
        
        # Snapshot information group
        info_group = Adw.PreferencesGroup()
        info_group.set_title(_("Snapshot Information"))
        
        # File path row
        file_row = Adw.ActionRow()
        file_row.set_title(_("File"))
        file_row.set_subtitle(self.snapshot_info['path'])
        info_group.add(file_row)
        
        # Date row
        date_row = Adw.ActionRow()
        date_row.set_title(_("Date"))
        date_row.set_subtitle(self.snapshot_info['date'])
        info_group.add(date_row)
        
        # Time row
        time_row = Adw.ActionRow()
        time_row.set_title(_("Time"))
        time_row.set_subtitle(self.snapshot_info['time'])
        info_group.add(time_row)
        
        main_box.append(info_group)
        
        # Description
        description = Gtk.Label()
        description.set_text(_("The system was booted from a restore point, also called a Snapshot.\n\n"
                             "If you want to make this restore point the default boot option, "
                             "click the Restore button or use Timeshift for more options."))
        description.set_wrap(True)
        description.set_justify(Gtk.Justification.CENTER)
        description.set_margin_top(10)
        description.set_margin_bottom(10)
        main_box.append(description)
        
        # Progress bar (initially hidden)
        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_visible(False)
        main_box.append(self.progress_bar)
        
        # Status label
        self.status_label = Gtk.Label()
        self.status_label.set_visible(False)
        main_box.append(self.status_label)
        
        # Restore button
        self.restore_button = Gtk.Button()
        self.restore_button.set_label(_("Restore System"))
        self.restore_button.add_css_class("suggested-action")
        self.restore_button.add_css_class("pill")
        self.restore_button.set_halign(Gtk.Align.CENTER)
        self.restore_button.set_size_request(200, 40)
        self.restore_button.connect("clicked", self.on_restore_clicked)
        main_box.append(self.restore_button)
        
        self.window.set_content(main_box)
        self.window.present()
    
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
        """Show error dialog and exit"""
        dialog = Adw.MessageDialog.new(None, title, message)
        dialog.add_response("ok", _("OK"))
        dialog.set_response_appearance("ok", Adw.ResponseAppearance.DEFAULT)
        dialog.connect("response", lambda d, r: self.quit())
        dialog.present()


def main():
    """Main entry point"""
    # Check if running as root (required for system operations)
    if os.geteuid() != 0:
        print(_("This application requires administrator privileges."))
        print(_("Please run with: pkexec {}").format(sys.argv[0]))
        return 1
    
    # Create and run application
    app = SnapshotRestoreApp()
    return app.run(sys.argv)


if __name__ == '__main__':
    sys.exit(main())