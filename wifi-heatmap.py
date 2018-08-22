#!/usr/bin/env python3

"""
    Simple tool to collect samples of wifi signal strength in an area
    such as a house, and then make simple heatmap plots.

    Copyright 2017 Benjamin Webb

    This program is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    This program is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import sys
from PyQt5 import QtCore
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QApplication, QWidget, QLabel, QScrollArea,
                             QMainWindow, QAction, QFileDialog, QDialog,
                             QGroupBox, QFormLayout, QComboBox,
                             QDialogButtonBox, QVBoxLayout, QCheckBox)
from PyQt5.QtGui import QIcon, QPixmap
import tempfile
import os
import platform
import subprocess
import re
import csv
import collections
import operator
import numpy as np
from scipy.interpolate import Rbf
import matplotlib.pyplot as plt
import pylab

if platform.system() == 'Windows':
    from pywiwi.WindowsWifi import getWirelessInterfaces
    from pywiwi.WindowsWifi import getWirelessNetworkBssList
elif platform.system() == 'Linux':
    from pyric import pyw
    from wifi import Cell

# Information on a single wireless AP
Signal = collections.namedtuple('Signal', ['ssid', 'bssid', 'rssi'])

class PointSignals(dict):
    """All signals for a given Cartesian point"""

    def add_signal(self, s):
        self[s.bssid] = s

    def get_text(self):
        """Get text suitable for a tooltip"""
        return "\n".join("%s %s %d" % (self[b].ssid, self[b].bssid,
                                       self[b].rssi)
                         for b in sorted(self.keys()))

    def get_all_rssi(self, bssids):
        """Get a list of RSSI values for the given BSSIDs.
           None is returned for any missing BSSID."""
        def get_rssi(sd, b):
            if b in sd:
                return sd[b].rssi
        return [get_rssi(self, b) for b in bssids]


class Signals(object):
    """All wireless AP signal information, sorted by bssid and position"""
    def __init__(self):
        self._signals = {}

    def add_point_signals(self, point, point_signals):
        self._signals[point] = point_signals

    def positions(self):
        return self._signals.items()

    def get_all_bssids(self):
        seen = {}
        for sd in self._signals.values():
            for signal in sd.values():
                seen[signal.bssid] = signal.ssid
        return sorted(seen.items(), key=operator.itemgetter(0))

    def write_csv(self, csvfile):
        w = csv.writer(csvfile)
        bssids = self.get_all_bssids()
        w.writerow(['X', 'Y'] + ["%s;%s" % b for b in bssids])
        bssids = [b[0] for b in bssids]
        for pos, ps in self.positions():
            p = list(pos) + ps.get_all_rssi(bssids)
            w.writerow(p)

    def read_csv(self, csvfile, add_point_signals):
        r = csv.DictReader(csvfile)
        for row in r:
            pos = (int(row.pop('X')), int(row.pop('Y')))
            p = PointSignals()
            for k, v in row.items():
                bssid, ssid = k.split(';', 1)
                if v != '':
                    s = Signal(ssid=ssid, bssid=bssid, rssi=int(v))
                    p.add_signal(s)
            self.add_point_signals(pos, p)
            add_point_signals(pos, p)


class WifiQuery(object):
    def get_signals(self):
        try:
            func = getattr(self, '_%s_get_signals' % platform.system().lower())
        except AttributeError:
            raise Exception('get_signals not implemented for %s' % platform.system())
        return func()

    def _windows_get_signals(self):
        p = PointSignals()
        for iface in getWirelessInterfaces():
            for cell in getWirelessNetworkBssList(iface):
                s = Signal(ssid=cell.ssid.decode("utf-8"), bssid=cell.bssid, rssi=cell.rssi)
                p.add_signal(s)
        return p


    def _darwin_get_signals(self):
        out = subprocess.check_output(['/System/Library/PrivateFrameworks/Apple80211.framework/Versions/Current/Resources/airport', '-s'], universal_newlines=True)
        p = PointSignals()
        for ssid, bssid, rssi in re.findall(
                              '(\S+)\s+(..:..:..:..:..:..)\s+([\d-]+)', out):
            s = Signal(ssid=ssid, bssid=bssid, rssi=int(rssi))
            p.add_signal(s)
        return p

    def _linux_get_signals(self):
        p = PointSignals()
        for iface in pyw.winterfaces():
            for cell in Cell.all(iface):
                s = Signal(ssid=cell.ssid, bssid=cell.address, rssi=cell.signal)
                p.add_signal(s)
        return p


class FloorPlan(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        pixmap = QPixmap()
        self.setPixmap(pixmap)
        self.q = WifiQuery()
        self._signals = Signals()

        self.setCursor(Qt.CrossCursor)

    def mousePressEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            pos = event.pos()
            pos = (pos.x(), pos.y())
            ps = self.q.get_signals()
            self._signals.add_point_signals(pos, ps)
            self.add_point_signals(pos, ps)

    def add_point_signals(self, pos, ps):
        label = QLabel('X', self)
        label.setToolTip(ps.get_text())
        label.move(*pos)
        label.show()


class ChooseHeatmapDialog(QDialog):
    def __init__(self, signals):
        super().__init__()
        self.signals = signals
        l = QVBoxLayout()

        self.ssid_combo = QComboBox()
        for bssid, ssid in sorted(self.signals.get_all_bssids(),
                                  key=operator.itemgetter(1)):
            self.ssid_combo.addItem("%s (%s)" % (ssid, bssid), bssid)

        ssid_layout = QFormLayout()
        ssid_layout.addRow(QLabel("SSID:"), self.ssid_combo)
        l.addLayout(ssid_layout)

        gb = QGroupBox("Plot parameters")
        gb_layout = QVBoxLayout()
        self.contour = QCheckBox("Contoured")
        gb_layout.addWidget(self.contour)
        gb.setLayout(gb_layout)
        l.addWidget(gb)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        l.addWidget(bb)
        self.setLayout(l)
        self.setWindowTitle("Show Heatmap")

 
class App(QMainWindow):
 
    def __init__(self):
        super().__init__()
        self.title = 'WiFi Heatmap'
        self.setWindowTitle(self.title)

        self.setup_menu()

        # Create widget
        self.plan = FloorPlan()

        self.scrollArea = QScrollArea()
        self.scrollArea.setWidget(self.plan)
        self.setCentralWidget(self.scrollArea)
        self.show()

    def load_image(self, file_name):
        p = self.plan.pixmap()
        p.load(file_name)
        self.image_file_name = file_name
        self.plan.setFixedSize(p.width(), p.height())
        self.setMaximumSize(QtCore.QSize(max(self.plan.width(), 400),
                                         max(self.plan.height(), 400)))

    def open_floor_plan_dialog(self):
        options = QFileDialog.Options()
        fileName, _ = QFileDialog.getOpenFileName(self, "Select image file",
                       "","All Files (*);;Image Files (*.jpg)", options=options)
        if fileName:
            self.load_image(fileName)

    def save_survey(self):
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getSaveFileName(self, "Select CSV file",
                       "","All Files (*);;CSV Files (*.csv)", options=options)
        if file_name:
            with open(file_name, 'w', newline='') as csvfile:
                self.plan._signals.write_csv(csvfile)
            print('file saved as ' + file_name)

    def load_survey(self):
        options = QFileDialog.Options()
        file_name, _ = QFileDialog.getOpenFileName(self, "Select CSV file",
                       "","All Files (*);;CSV Files (*.csv)", options=options)
        if file_name:
            with open(file_name) as csvfile:
                self.plan._signals.read_csv(csvfile,
                                            self.plan.add_point_signals)

    def show_heatmap(self):
        d = ChooseHeatmapDialog(self.plan._signals)
        if not d.exec_():
            return
        bssid = d.ssid_combo.currentData()
        contour = d.contour.isChecked()

        signals = []
        for pos, ps in self.plan._signals.positions():
            if bssid in ps:
                signals.append((pos, ps[bssid]))
        x = np.array([s[0][0] for s in signals])
        y = np.array([s[0][1] for s in signals])
        z = np.array([s[1].rssi for s in signals])

        # Make evenly-spaced grid of xy values
        num_grid_x = num_grid_y = 100
        grid_x, grid_y = np.meshgrid(np.linspace(0, self.plan.width(),
                                                 num_grid_x),
                                     np.linspace(0, self.plan.height(),
                                                 num_grid_y))
        grid_x = grid_x.flatten()
        grid_y = grid_y.flatten()

        # Interpolate on the grid
        r = Rbf(x, y, z, function='linear')
        grid_z = r(grid_x, grid_y).reshape((num_grid_y, num_grid_x))

        if contour:
            self.plot_contour(grid_x, grid_y, grid_z)
        else:
            self.plot_heatmap(grid_x, grid_y, grid_z)

    def plot_heatmap(self, x, y, z):
        num_y, num_x = z.shape
        plt.figure()

        plt.axis('off')
        image = pylab.imread(self.image_file_name)
        plt.imshow(image, interpolation='bicubic', zorder=-100)

        im = plt.imshow(z, extent=(0, self.plan.width(), self.plan.height(), 0),
                        cmap='RdYlGn', vmin=-85, vmax=-25, alpha=0.7)
        plt.show()

    def plot_contour(self, x, y, z):
        num_y, num_x = z.shape
        plt.figure()
        plt.axis('off')
        image = pylab.imread(self.image_file_name)
        plt.imshow(image, interpolation='bicubic', zorder=-100)

        cs = plt.contourf(x.reshape((num_y, num_x)),
                          y.reshape((num_y, num_x)), z,
                          np.append(np.arange(-85, -25, 10), [0]),
                          cmap='RdYlGn', alpha=0.7)
        plt.clabel(cs, inline=1, fontsize=10)
        plt.show()

    def setup_menu(self):
        mainMenu = self.menuBar()
        menu = mainMenu.addMenu('File')
        b = QAction('Open Floor Plan...', self)
        b.triggered.connect(self.open_floor_plan_dialog)
        menu.addAction(b)

        b = QAction('Save Survey...', self)
        b.triggered.connect(self.save_survey)
        menu.addAction(b)

        b = QAction('Load Survey...', self)
        b.triggered.connect(self.load_survey)
        menu.addAction(b)

        menu = mainMenu.addMenu('View')
        b = QAction('Show Heatmap', self)
        b.triggered.connect(self.show_heatmap)
        menu.addAction(b)
 
if __name__ == '__main__':
    app = QApplication(sys.argv)
    ex = App()
    sys.exit(app.exec_())
