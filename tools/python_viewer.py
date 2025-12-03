#!/usr/bin/env python3
"""
Professional DICOM Viewer - Medical Imaging Excellence
Optimized for diagnostic quality visualization with advanced image processing
Specially enhanced for X-ray, CT, MRI, and other medical imaging modalities
"""

import sys
import os
import argparse
import numpy as np
import pydicom
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
                             QWidget, QPushButton, QLabel, QSlider, QFileDialog,
                             QScrollArea, QFrame, QGridLayout, QComboBox, QTextEdit,
                             QMessageBox, QInputDialog, QListWidget, QListWidgetItem,
                             QSplitter, QGroupBox, QCheckBox, QSpinBox, QDoubleSpinBox,
                             QTabWidget, QProgressBar, QStatusBar)
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QThread, pyqtSlot
from PyQt5.QtGui import QPixmap, QImage, QPainter, QPen, QColor, QFont, QIcon
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from matplotlib.colors import LinearSegmentedColormap
import matplotlib.pyplot as plt
from io import BytesIO
import requests
from PIL import Image as PILImage, ImageEnhance, ImageFilter
from scipy import ndimage
from scipy.ndimage import gaussian_filter, sobel
import cv2
from skimage import exposure, filters, morphology
from skimage.restoration import denoise_nl_means
import logging

# Configure logging for professional debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class DicomCanvas(FigureCanvas):
    """Professional DICOM Canvas with Medical-Grade Rendering"""
    mouse_pressed = pyqtSignal(int, int)
    mouse_moved = pyqtSignal(int, int)
    mouse_released = pyqtSignal(int, int)
    pixel_value_changed = pyqtSignal(float, float, float)  # x, y, value

    def __init__(self, parent=None):
        # High-DPI rendering support
        self.fig = Figure(figsize=(10, 10), facecolor='black', dpi=100)
        super().__init__(self.fig)
        self.setParent(parent)
        
        # Professional medical imaging display setup
        self.ax = self.fig.add_subplot(111)
        self.ax.set_facecolor('black')
        self.ax.axis('off')
        
        # Optimize for medical imaging - no margins, perfect fit
        self.fig.subplots_adjust(left=0, right=1, top=1, bottom=0, wspace=0, hspace=0)
        
        # Enhanced interaction tracking
        self.mouse_pressed_flag = False
        self.last_mouse_pos = None
        self.current_pixel_pos = None
        
        # Professional rendering settings
        self.fig.patch.set_facecolor('black')
        self.setStyleSheet("background-color: black; border: none;")
        
        # Enable high-quality rendering
        self.setRenderHint(QPainter.Antialiasing, True)
        self.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self.setRenderHint(QPainter.HighQualityAntialiasing, True)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.mouse_pressed_flag = True
            self.last_mouse_pos = (event.x(), event.y())
            self.current_pixel_pos = (event.x(), event.y())
            self.mouse_pressed.emit(event.x(), event.y())
            self._emit_pixel_value(event.x(), event.y())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Always track mouse position for pixel value display
        self.current_pixel_pos = (event.x(), event.y())
        self._emit_pixel_value(event.x(), event.y())
        
        if self.mouse_pressed_flag:
            self.mouse_moved.emit(event.x(), event.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.mouse_pressed_flag = False
            self.mouse_released.emit(event.x(), event.y())
        super().mouseReleaseEvent(event)
    
    def _emit_pixel_value(self, x, y):
        """Emit pixel value at mouse position for HU display"""
        try:
            if hasattr(self.parent(), 'current_image_data') and self.parent().current_image_data is not None:
                # Convert widget coordinates to data coordinates
                inv = self.ax.transData.inverted()
                data_x, data_y = inv.transform((x, y))
                
                # Get pixel value if within bounds
                image_data = self.parent().current_image_data
                if (0 <= int(data_y) < image_data.shape[0] and 
                    0 <= int(data_x) < image_data.shape[1]):
                    pixel_value = float(image_data[int(data_y), int(data_x)])
                    self.pixel_value_changed.emit(data_x, data_y, pixel_value)
        except Exception as e:
            logger.debug(f"Pixel value emission error: {e}")

    def wheelEvent(self, event):
        """Enhanced wheel event with smooth zooming and slice navigation"""
        delta = event.angleDelta().y()
        
        if event.modifiers() & Qt.ControlModifier:
            # Smooth zoom with variable speed
            zoom_factor = 1.15 if delta > 0 else 0.87
            self.parent().handle_zoom(zoom_factor, event.x(), event.y())
        elif event.modifiers() & Qt.ShiftModifier:
            # Window/Level adjustment with mouse wheel
            if delta > 0:
                self.parent().adjust_window_level(10, 0)  # Increase window width
            else:
                self.parent().adjust_window_level(-10, 0)  # Decrease window width
        else:
            # Slice navigation
            direction = 1 if delta > 0 else -1
            self.parent().handle_slice_change(direction)
        
        super().wheelEvent(event)


class DicomViewer(QMainWindow):
    """Professional DICOM Viewer - Medical Imaging Excellence"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Professional DICOM Viewer - Medical Imaging Excellence")
        self.setGeometry(50, 50, 1600, 1000)
        
        # Professional dark theme optimized for medical imaging
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1a1a1a;
                color: #ffffff;
            }
            QWidget {
                background-color: #1a1a1a;
                color: #ffffff;
                font-family: 'Segoe UI', 'Arial', sans-serif;
                font-size: 11px;
            }
        """)

        # Core DICOM data
        self.dicom_files = []
        self.current_image_index = 0
        self.current_image_data = None
        self.current_dicom = None
        self.original_pixel_data = None  # Store original for processing
        
        # Enhanced display parameters
        self.window_width = 400
        self.window_level = 40
        self.zoom_factor = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.inverted = False
        self.crosshair = False
        self.pixel_value_display = True
        self.ruler_enabled = False
        
        # Advanced image processing flags
        self.noise_reduction = False
        self.edge_enhancement = False
        self.contrast_enhancement = True
        self.histogram_equalization = False

        # Tool management
        self.active_tool = 'windowing'
        self.measurements = []
        self.annotations = []
        self.current_measurement = None
        self.drag_start = None

        # Professional medical imaging presets - Enhanced for X-ray optimization
        self.window_presets = {
            # CT Presets
            'lung': {'ww': 1600, 'wl': -600, 'description': 'Lung Window - Optimal for pulmonary imaging'},
            'bone': {'ww': 2000, 'wl': 300, 'description': 'Bone Window - Skeletal structures'},
            'soft': {'ww': 400, 'wl': 40, 'description': 'Soft Tissue - General abdomen/pelvis'},
            'brain': {'ww': 80, 'wl': 40, 'description': 'Brain Window - Neurological imaging'},
            'liver': {'ww': 160, 'wl': 60, 'description': 'Liver Window - Hepatic imaging'},
            'mediastinum': {'ww': 350, 'wl': 50, 'description': 'Mediastinum - Chest soft tissue'},
            
            # X-ray Optimized Presets
            'xray_chest': {'ww': 2500, 'wl': 500, 'description': 'Chest X-ray - Lungs and mediastinum'},
            'xray_bone': {'ww': 3000, 'wl': 1500, 'description': 'X-ray Bone - Skeletal detail'},
            'xray_soft': {'ww': 1000, 'wl': 300, 'description': 'X-ray Soft Tissue'},
            'xray_pediatric': {'ww': 1500, 'wl': 200, 'description': 'Pediatric X-ray'},
            'xray_extremity': {'ww': 2500, 'wl': 800, 'description': 'Extremity X-ray'},
            'xray_spine': {'ww': 2000, 'wl': 600, 'description': 'Spine X-ray'},
            'xray_abdomen': {'ww': 1200, 'wl': 400, 'description': 'Abdominal X-ray'},
            
            # Specialized presets
            'angio': {'ww': 600, 'wl': 150, 'description': 'Angiography - Vascular imaging'},
            'pe_study': {'ww': 700, 'wl': 100, 'description': 'Pulmonary Embolism Study'},
            'trauma': {'ww': 400, 'wl': 40, 'description': 'Trauma Assessment'},
            'stroke': {'ww': 40, 'wl': 40, 'description': 'Stroke Imaging - Brain'},
        }

        # View management
        self.view_xlim = None
        self.view_ylim = None
        
        # Advanced caching system
        self._cached_image_data = None
        self._cached_image_params = (None, None, None, None, None, None)  # Enhanced cache params
        self._processing_cache = {}  # Cache for processed images
        
        # Current pixel information
        self.current_pixel_value = 0.0
        self.current_hu_value = 0.0
        self.current_mouse_pos = (0, 0)

        # Backend mode (web API parity)
        self.backend_mode = False
        self.base_url = os.environ.get('DICOM_VIEWER_BASE_URL', 'http://127.0.0.1:8000/viewer')
        if self.base_url.endswith('/'):
            self.base_url = self.base_url[:-1]
        self.backend_study = None
        self.backend_series = None
        self.backend_images = []
        self.series_options = []
        
        # Status bar for professional feedback
        self.status_bar = None
        self.pixel_info_label = None
        
        # Initialize the professional UI
        self.init_ui()

    def init_ui(self):
        """Initialize professional medical imaging UI"""
        # Create main widget with professional layout
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # Create status bar for professional feedback
        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        
        # Pixel information display
        self.pixel_info_label = QLabel("Ready")
        self.pixel_info_label.setStyleSheet("""
            QLabel {
                background-color: #2d2d2d;
                color: #ffffff;
                padding: 4px 8px;
                border-radius: 3px;
                font-family: 'Courier New', monospace;
                font-size: 10px;
            }
        """)
        self.status_bar.addPermanentWidget(self.pixel_info_label)
        
        # Main layout using splitters for professional resizing
        main_layout = QHBoxLayout(main_widget)
        main_layout.setContentsMargins(2, 2, 2, 2)
        main_layout.setSpacing(2)
        
        # Create main splitter
        main_splitter = QSplitter(Qt.Horizontal)
        main_splitter.setStyleSheet("""
            QSplitter::handle {
                background-color: #404040;
                width: 3px;
            }
            QSplitter::handle:hover {
                background-color: #0078d4;
            }
        """)
        
        # Create toolbar with enhanced organization
        self.create_professional_toolbar(main_splitter)
        
        # Create center area with viewport
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        center_layout.setContentsMargins(0, 0, 0, 0)
        center_layout.setSpacing(1)
        
        self.create_enhanced_top_bar(center_layout)
        self.create_professional_viewport(center_layout)
        
        main_splitter.addWidget(center_widget)
        
        # Create enhanced right panel
        self.create_professional_right_panel(main_splitter)
        
        # Set splitter proportions for optimal viewing
        main_splitter.setSizes([90, 800, 280])  # toolbar, center, right panel
        
        main_layout.addWidget(main_splitter)
    
    def create_professional_right_panel(self, main_splitter):
        """Create enhanced right panel with tabbed interface"""
        right_panel = QWidget()
        right_panel.setFixedWidth(300)
        right_panel.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                border-left: 2px solid #404040;
            }
        """)
        
        panel_layout = QVBoxLayout(right_panel)
        panel_layout.setContentsMargins(5, 5, 5, 5)
        panel_layout.setSpacing(2)
        
        # Create tabbed interface for better organization
        tab_widget = QTabWidget()
        tab_widget.setStyleSheet("""
            QTabWidget::pane {
                border: 1px solid #555555;
                background-color: #2d2d2d;
            }
            QTabBar::tab {
                background-color: #404040;
                color: white;
                padding: 8px 12px;
                margin-right: 2px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
            }
            QTabBar::tab:selected {
                background-color: #0078d4;
            }
            QTabBar::tab:hover {
                background-color: #4a4a4a;
            }
        """)
        
        # Create tabs
        self.create_display_controls_tab(tab_widget)
        self.create_measurements_tab(tab_widget)
        self.create_image_info_tab(tab_widget)
        self.create_presets_tab(tab_widget)
        
        panel_layout.addWidget(tab_widget)
        main_splitter.addWidget(right_panel)
    
    def create_display_controls_tab(self, tab_widget):
        """Create display controls tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(15)
        
        # Window/Level section
        self.create_enhanced_window_level_section(layout)
        
        # Navigation section  
        self.create_enhanced_navigation_section(layout)
        
        # Transform section
        self.create_enhanced_transform_section(layout)
        
        layout.addStretch()
        tab_widget.addTab(tab, "Display")
    
    def create_measurements_tab(self, tab_widget):
        """Create measurements tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.create_enhanced_measurements_section(layout)
        
        tab_widget.addTab(tab, "Measure")
    
    def create_image_info_tab(self, tab_widget):
        """Create image information tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.create_enhanced_image_info_section(layout)
        
        tab_widget.addTab(tab, "Info")
    
    def create_presets_tab(self, tab_widget):
        """Create window/level presets tab"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.create_enhanced_presets_section(layout)
        
        tab_widget.addTab(tab, "Presets")
    
    def create_enhanced_window_level_section(self, layout):
        """Create enhanced window/level controls with professional styling"""
        wl_frame = QGroupBox("Window/Level Controls")
        wl_frame.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
                background-color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-size: 12px;
            }
        """)
        wl_layout = QVBoxLayout(wl_frame)
        wl_layout.setSpacing(12)
        
        # Window Width with professional styling
        ww_container = QWidget()
        ww_container.setStyleSheet("background-color: transparent;")
        ww_layout_inner = QVBoxLayout(ww_container)
        ww_layout_inner.setContentsMargins(0, 0, 0, 0)
        
        ww_header = QHBoxLayout()
        ww_label = QLabel("Window Width")
        ww_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #cccccc;
                font-weight: bold;
            }
        """)
        
        self.ww_value_label = QLabel(str(self.window_width))
        self.ww_value_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #00ff00;
                font-weight: bold;
                background-color: #1a1a1a;
                padding: 2px 6px;
                border-radius: 3px;
                border: 1px solid #555555;
                min-width: 60px;
            }
        """)
        self.ww_value_label.setAlignment(Qt.AlignCenter)
        
        ww_header.addWidget(ww_label)
        ww_header.addStretch()
        ww_header.addWidget(self.ww_value_label)
        ww_layout_inner.addLayout(ww_header)
        
        self.ww_slider = QSlider(Qt.Horizontal)
        self.ww_slider.setRange(1, 4000)
        self.ww_slider.setValue(self.window_width)
        self.ww_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #555555;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2d2d2d, stop:1 #1a1a1a);
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #0078d4, stop:1 #005a9e);
                border: 2px solid #0078d4;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #106ebe, stop:1 #0078d4);
                border: 2px solid #106ebe;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #0078d4, stop:1 #005a9e);
                border: 1px solid #0078d4;
                height: 8px;
                border-radius: 4px;
            }
        """)
        self.ww_slider.valueChanged.connect(self.handle_window_width_change)
        ww_layout_inner.addWidget(self.ww_slider)
        wl_layout.addWidget(ww_container)
        
        # Window Level with professional styling
        wl_container = QWidget()
        wl_container.setStyleSheet("background-color: transparent;")
        wl_layout_inner = QVBoxLayout(wl_container)
        wl_layout_inner.setContentsMargins(0, 0, 0, 0)
        
        wl_header = QHBoxLayout()
        wl_label = QLabel("Window Level")
        wl_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #cccccc;
                font-weight: bold;
            }
        """)
        
        self.wl_value_label = QLabel(str(self.window_level))
        self.wl_value_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #ffff00;
                font-weight: bold;
                background-color: #1a1a1a;
                padding: 2px 6px;
                border-radius: 3px;
                border: 1px solid #555555;
                min-width: 60px;
            }
        """)
        self.wl_value_label.setAlignment(Qt.AlignCenter)
        
        wl_header.addWidget(wl_label)
        wl_header.addStretch()
        wl_header.addWidget(self.wl_value_label)
        wl_layout_inner.addLayout(wl_header)
        
        self.wl_slider = QSlider(Qt.Horizontal)
        self.wl_slider.setRange(-1000, 1000)
        self.wl_slider.setValue(self.window_level)
        self.wl_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #555555;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2d2d2d, stop:1 #1a1a1a);
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffd700, stop:1 #ffb000);
                border: 2px solid #ffd700;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffed4e, stop:1 #ffd700);
                border: 2px solid #ffed4e;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ffd700, stop:1 #ffb000);
                border: 1px solid #ffd700;
                height: 8px;
                border-radius: 4px;
            }
        """)
        self.wl_slider.valueChanged.connect(self.handle_window_level_change)
        wl_layout_inner.addWidget(self.wl_slider)
        wl_layout.addWidget(wl_container)
        
        # Auto Window/Level button
        auto_wl_btn = QPushButton("🎯 Auto W/L")
        auto_wl_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #0078d4, stop:1 #005a9e);
                color: white;
                border: 2px solid #0078d4;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 11px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #106ebe, stop:1 #0078d4);
                border-color: #106ebe;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #005a9e, stop:1 #004578);
                border-color: #005a9e;
            }
        """)
        auto_wl_btn.clicked.connect(self.auto_window_level)
        wl_layout.addWidget(auto_wl_btn)
        
        layout.addWidget(wl_frame)
    
    def create_enhanced_navigation_section(self, layout):
        """Create enhanced navigation controls"""
        nav_frame = QGroupBox("Image Navigation")
        nav_frame.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
                background-color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-size: 12px;
            }
        """)
        nav_layout = QVBoxLayout(nav_frame)
        nav_layout.setSpacing(12)
        
        # Slice navigation
        slice_container = QWidget()
        slice_container.setStyleSheet("background-color: transparent;")
        slice_layout = QVBoxLayout(slice_container)
        slice_layout.setContentsMargins(0, 0, 0, 0)
        
        slice_header = QHBoxLayout()
        slice_label = QLabel("Slice Navigation")
        slice_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #cccccc;
                font-weight: bold;
            }
        """)
        
        self.slice_value_label = QLabel("1 / 1")
        self.slice_value_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #00ffff;
                font-weight: bold;
                background-color: #1a1a1a;
                padding: 2px 6px;
                border-radius: 3px;
                border: 1px solid #555555;
                min-width: 60px;
            }
        """)
        self.slice_value_label.setAlignment(Qt.AlignCenter)
        
        slice_header.addWidget(slice_label)
        slice_header.addStretch()
        slice_header.addWidget(self.slice_value_label)
        slice_layout.addLayout(slice_header)
        
        self.slice_slider = QSlider(Qt.Horizontal)
        self.slice_slider.setRange(0, 0)
        self.slice_slider.setValue(0)
        self.slice_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #555555;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2d2d2d, stop:1 #1a1a1a);
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #00ffff, stop:1 #00cccc);
                border: 2px solid #00ffff;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #33ffff, stop:1 #00ffff);
                border: 2px solid #33ffff;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00ffff, stop:1 #00cccc);
                border: 1px solid #00ffff;
                height: 8px;
                border-radius: 4px;
            }
        """)
        self.slice_slider.valueChanged.connect(self.handle_slice_change_slider)
        slice_layout.addWidget(self.slice_slider)
        nav_layout.addWidget(slice_container)
        
        # Navigation buttons
        nav_buttons = QHBoxLayout()
        
        first_btn = QPushButton("⏮️ First")
        first_btn.setStyleSheet(self._get_nav_button_style())
        first_btn.clicked.connect(lambda: self.go_to_slice(0))
        nav_buttons.addWidget(first_btn)
        
        prev_btn = QPushButton("⏪ Prev")
        prev_btn.setStyleSheet(self._get_nav_button_style())
        prev_btn.clicked.connect(lambda: self.handle_slice_change(-1))
        nav_buttons.addWidget(prev_btn)
        
        next_btn = QPushButton("Next ⏩")
        next_btn.setStyleSheet(self._get_nav_button_style())
        next_btn.clicked.connect(lambda: self.handle_slice_change(1))
        nav_buttons.addWidget(next_btn)
        
        last_btn = QPushButton("Last ⏭️")
        last_btn.setStyleSheet(self._get_nav_button_style())
        last_btn.clicked.connect(lambda: self.go_to_slice(len(self.dicom_files) - 1))
        nav_buttons.addWidget(last_btn)
        
        nav_layout.addLayout(nav_buttons)
        layout.addWidget(nav_frame)
    
    def create_enhanced_transform_section(self, layout):
        """Create enhanced transform controls"""
        transform_frame = QGroupBox("Display Transform")
        transform_frame.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
                background-color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-size: 12px;
            }
        """)
        transform_layout = QVBoxLayout(transform_frame)
        transform_layout.setSpacing(12)
        
        # Zoom control
        zoom_container = QWidget()
        zoom_container.setStyleSheet("background-color: transparent;")
        zoom_layout = QVBoxLayout(zoom_container)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        
        zoom_header = QHBoxLayout()
        zoom_label = QLabel("Zoom Level")
        zoom_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #cccccc;
                font-weight: bold;
            }
        """)
        
        self.zoom_value_label = QLabel("100%")
        self.zoom_value_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #ff8800;
                font-weight: bold;
                background-color: #1a1a1a;
                padding: 2px 6px;
                border-radius: 3px;
                border: 1px solid #555555;
                min-width: 60px;
            }
        """)
        self.zoom_value_label.setAlignment(Qt.AlignCenter)
        
        zoom_header.addWidget(zoom_label)
        zoom_header.addStretch()
        zoom_header.addWidget(self.zoom_value_label)
        zoom_layout.addLayout(zoom_header)
        
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(25, 500)
        self.zoom_slider.setValue(100)
        self.zoom_slider.setStyleSheet("""
            QSlider::groove:horizontal {
                border: 1px solid #555555;
                height: 8px;
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #2d2d2d, stop:1 #1a1a1a);
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ff8800, stop:1 #cc6600);
                border: 2px solid #ff8800;
                width: 18px;
                margin: -5px 0;
                border-radius: 9px;
            }
            QSlider::handle:horizontal:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #ffaa33, stop:1 #ff8800);
                border: 2px solid #ffaa33;
            }
            QSlider::sub-page:horizontal {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #ff8800, stop:1 #cc6600);
                border: 1px solid #ff8800;
                height: 8px;
                border-radius: 4px;
            }
        """)
        self.zoom_slider.valueChanged.connect(self.handle_zoom_slider)
        zoom_layout.addWidget(self.zoom_slider)
        transform_layout.addWidget(zoom_container)
        
        # Zoom buttons
        zoom_buttons = QHBoxLayout()
        
        zoom_fit_btn = QPushButton("🔍 Fit")
        zoom_fit_btn.setStyleSheet(self._get_transform_button_style())
        zoom_fit_btn.clicked.connect(self.zoom_to_fit)
        zoom_buttons.addWidget(zoom_fit_btn)
        
        zoom_100_btn = QPushButton("1:1")
        zoom_100_btn.setStyleSheet(self._get_transform_button_style())
        zoom_100_btn.clicked.connect(self.zoom_to_100)
        zoom_buttons.addWidget(zoom_100_btn)
        
        zoom_in_btn = QPushButton("🔍+")
        zoom_in_btn.setStyleSheet(self._get_transform_button_style())
        zoom_in_btn.clicked.connect(lambda: self.handle_zoom(1.25))
        zoom_buttons.addWidget(zoom_in_btn)
        
        zoom_out_btn = QPushButton("🔍-")
        zoom_out_btn.setStyleSheet(self._get_transform_button_style())
        zoom_out_btn.clicked.connect(lambda: self.handle_zoom(0.8))
        zoom_buttons.addWidget(zoom_out_btn)
        
        transform_layout.addLayout(zoom_buttons)
        
        # Display options
        display_options = QVBoxLayout()
        
        # Interpolation checkbox
        self.interpolation_cb = QCheckBox("🎨 Smooth Interpolation")
        self.interpolation_cb.setStyleSheet("""
            QCheckBox {
                color: #cccccc;
                font-size: 11px;
                font-weight: bold;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 2px solid #555555;
                border-radius: 3px;
                background-color: #1a1a1a;
            }
            QCheckBox::indicator:checked {
                background-color: #0078d4;
                border-color: #0078d4;
            }
            QCheckBox::indicator:hover {
                border-color: #0078d4;
            }
        """)
        self.interpolation_cb.setChecked(True)
        self.interpolation_cb.toggled.connect(self.toggle_interpolation)
        display_options.addWidget(self.interpolation_cb)
        
        # Grid overlay checkbox
        self.grid_cb = QCheckBox("📐 Show Grid")
        self.grid_cb.setStyleSheet("""
            QCheckBox {
                color: #cccccc;
                font-size: 11px;
                font-weight: bold;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border: 2px solid #555555;
                border-radius: 3px;
                background-color: #1a1a1a;
            }
            QCheckBox::indicator:checked {
                background-color: #00ff00;
                border-color: #00ff00;
            }
            QCheckBox::indicator:hover {
                border-color: #00ff00;
            }
        """)
        self.grid_cb.toggled.connect(self.toggle_grid)
        display_options.addWidget(self.grid_cb)
        
        transform_layout.addLayout(display_options)
        layout.addWidget(transform_frame)

    def create_professional_toolbar(self, main_splitter):
        """Create professional medical imaging toolbar with organized tool groups"""
        toolbar = QWidget()
        toolbar.setFixedWidth(85)
        toolbar.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                border-right: 2px solid #404040;
            }
        """)

        toolbar_layout = QVBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(5, 10, 5, 10)
        toolbar_layout.setSpacing(3)
        
        # Professional tool organization
        tool_groups = [
            {
                'name': 'Navigation',
                'tools': [
                    ('windowing', 'Window/Level', '🪟', 'Adjust window and level settings'),
                    ('zoom', 'Zoom', '🔍', 'Zoom in/out of image'),
                    ('pan', 'Pan', '✋', 'Pan around the image'),
                    ('reset', 'Reset View', '🏠', 'Reset zoom and pan to fit'),
                ]
            },
            {
                'name': 'Measurement',
                'tools': [
                    ('measure', 'Measure', '📏', 'Linear measurements'),
                    ('annotate', 'Annotate', '📝', 'Add text annotations'),
                    ('crosshair', 'Crosshair', '✚', 'Show crosshair overlay'),
                ]
            },
            {
                'name': 'Display',
                'tools': [
                    ('invert', 'Invert', '⚫', 'Invert image colors'),
                    ('enhance', 'Enhance', '✨', 'Image enhancement'),
                    ('filter', 'Filter', '🔧', 'Apply image filters'),
                ]
            },
            {
                'name': 'Advanced',
                'tools': [
                    ('cine', 'Cine', '▶️', 'Cine mode playback'),
                    ('3d', '3D/MPR', '🧊', '3D reconstruction'),
                    ('export', 'Export', '💾', 'Export image/study'),
                ]
            }
        ]

        self.tool_buttons = {}
        
        for group in tool_groups:
            # Group separator
            if toolbar_layout.count() > 0:
                separator = QFrame()
                separator.setFrameShape(QFrame.HLine)
                separator.setStyleSheet("color: #555555;")
                toolbar_layout.addWidget(separator)
            
            # Group label
            group_label = QLabel(group['name'])
            group_label.setStyleSheet("""
                QLabel {
                    color: #888888;
                    font-size: 9px;
                    font-weight: bold;
                    padding: 2px;
                    text-align: center;
                }
            """)
            group_label.setAlignment(Qt.AlignCenter)
            toolbar_layout.addWidget(group_label)
            
            # Group tools
            for tool_key, tool_label, tool_icon, tool_tip in group['tools']:
                btn = QPushButton(f"{tool_icon}\n{tool_label.split()[0]}")  # First word only
                btn.setFixedSize(75, 55)
                btn.setToolTip(f"{tool_label}\n{tool_tip}")
                btn.setStyleSheet("""
                    QPushButton {
                        background-color: #404040;
                        color: white;
                        border: 1px solid #555555;
                        border-radius: 6px;
                        font-size: 9px;
                        font-weight: bold;
                        text-align: center;
                    }
                    QPushButton:hover {
                        background-color: #4a4a4a;
                        border-color: #0078d4;
                    }
                    QPushButton:pressed {
                        background-color: #0078d4;
                        border-color: #005a9e;
                    }
                    QPushButton:checked {
                        background-color: #0078d4;
                        border-color: #005a9e;
                    }
                """)
                btn.setCheckable(True)  # Make buttons toggleable
                btn.clicked.connect(lambda checked, tool=tool_key: self.handle_tool_click(tool))
                toolbar_layout.addWidget(btn)
                self.tool_buttons[tool_key] = btn

        toolbar_layout.addStretch()
        main_splitter.addWidget(toolbar)

    def create_enhanced_top_bar(self, center_layout):
        """Create enhanced top bar with professional controls"""
        top_bar = QWidget()
        top_bar.setFixedHeight(55)
        top_bar.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                border-bottom: 2px solid #404040;
            }
        """)

        top_layout = QHBoxLayout(top_bar)
        top_layout.setContentsMargins(15, 5, 15, 5)
        top_layout.setSpacing(10)

        # File operations group
        file_group = QGroupBox("File Operations")
        file_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        file_layout = QHBoxLayout(file_group)
        file_layout.setContentsMargins(5, 5, 5, 5)
        
        load_btn = QPushButton("📁 Load Files")
        load_btn.setStyleSheet("""
            QPushButton {
                background-color: #0078d4;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #106ebe;
            }
        """)
        load_btn.clicked.connect(self.load_dicom_files)
        file_layout.addWidget(load_btn)

        folder_btn = QPushButton("📂 Load Folder")
        folder_btn.setStyleSheet("""
            QPushButton {
                background-color: #0b8457;
                color: white;
                border: none;
                padding: 8px 16px;
                border-radius: 4px;
                font-size: 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #086b46;
            }
        """)
        folder_btn.clicked.connect(self.load_dicom_folder)
        file_layout.addWidget(folder_btn)
        
        top_layout.addWidget(file_group)

        # Series selection
        series_group = QGroupBox("Series Selection")
        series_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        series_layout = QHBoxLayout(series_group)
        series_layout.setContentsMargins(5, 5, 5, 5)
        
        self.backend_combo = QComboBox()
        self.backend_combo.addItem("Select Series")
        self.backend_combo.setStyleSheet("""
            QComboBox {
                padding: 6px;
                border-radius: 4px;
                font-size: 12px;
                background-color: #404040;
                border: 1px solid #555555;
                min-width: 150px;
            }
            QComboBox::drop-down {
                subcontrol-origin: padding;
                subcontrol-position: top right;
                width: 20px;
                border-left: 1px solid #555555;
            }
        """)
        self.backend_combo.currentTextChanged.connect(self.handle_backend_study_select)
        series_layout.addWidget(self.backend_combo)
        
        top_layout.addWidget(series_group)

        # Patient information
        info_group = QGroupBox("Patient Information")
        info_group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 5px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        info_layout = QHBoxLayout(info_group)
        info_layout.setContentsMargins(5, 5, 5, 5)
        
        self.patient_info_label = QLabel("Ready to load DICOM files...")
        self.patient_info_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #cccccc;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
        """)
        info_layout.addWidget(self.patient_info_label)
        
        top_layout.addWidget(info_group, 1)  # Take remaining space

        center_layout.addWidget(top_bar)

    def create_professional_viewport(self, center_layout):
        """Create professional medical imaging viewport with enhanced overlays"""
        viewport_widget = QWidget()
        viewport_widget.setStyleSheet("""
            QWidget {
                background-color: #000000;
                border: 2px solid #404040;
                border-radius: 3px;
            }
        """)

        viewport_layout = QVBoxLayout(viewport_widget)
        viewport_layout.setContentsMargins(2, 2, 2, 2)

        # Create the enhanced DICOM canvas
        self.canvas = DicomCanvas(self)
        self.canvas.mouse_pressed.connect(self.on_mouse_press)
        self.canvas.mouse_moved.connect(self.on_mouse_move)
        self.canvas.mouse_released.connect(self.on_mouse_release)
        self.canvas.pixel_value_changed.connect(self.on_pixel_value_changed)

        viewport_layout.addWidget(self.canvas)
        
        # Create professional overlay system
        self.create_professional_overlays(viewport_widget)
        
        center_layout.addWidget(viewport_widget)
        
    def create_professional_overlays(self, viewport_widget):
        """Create professional medical imaging overlays"""
        # Top-left overlay - Window/Level and slice info
        self.wl_overlay = QLabel()
        self.wl_overlay.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 180);
                color: #00ff00;
                padding: 8px 12px;
                border-radius: 6px;
                font-family: 'Courier New', monospace;
                font-size: 11px;
                font-weight: bold;
                border: 1px solid #333333;
            }
        """)
        self.wl_overlay.setParent(viewport_widget)
        self.wl_overlay.move(15, 15)
        
        # Top-right overlay - Image information
        self.image_overlay = QLabel()
        self.image_overlay.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 180);
                color: #00ffff;
                padding: 8px 12px;
                border-radius: 6px;
                font-family: 'Courier New', monospace;
                font-size: 10px;
                border: 1px solid #333333;
            }
        """)
        self.image_overlay.setParent(viewport_widget)
        
        # Bottom-left overlay - Zoom and tool info
        self.zoom_overlay = QLabel()
        self.zoom_overlay.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 180);
                color: #ffff00;
                padding: 6px 10px;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                font-size: 10px;
                font-weight: bold;
                border: 1px solid #333333;
            }
        """)
        self.zoom_overlay.setParent(viewport_widget)
        
        # Bottom-right overlay - Pixel value and coordinates
        self.pixel_overlay = QLabel()
        self.pixel_overlay.setStyleSheet("""
            QLabel {
                background-color: rgba(0, 0, 0, 180);
                color: #ff8800;
                padding: 6px 10px;
                border-radius: 4px;
                font-family: 'Courier New', monospace;
                font-size: 10px;
                font-weight: bold;
                border: 1px solid #333333;
            }
        """)
        self.pixel_overlay.setParent(viewport_widget)
        
        # Position overlays with timer for proper sizing
        QTimer.singleShot(100, self.position_overlays)
    
    def position_overlays(self):
        """Position overlay labels professionally"""
        if not hasattr(self, 'wl_overlay'):
            return
            
        parent = self.wl_overlay.parent()
        if not parent:
            return
            
        parent_width = parent.width()
        parent_height = parent.height()
        
        # Position top-right overlay
        self.image_overlay.adjustSize()
        self.image_overlay.move(parent_width - self.image_overlay.width() - 15, 15)
        
        # Position bottom-left overlay
        self.zoom_overlay.adjustSize()
        self.zoom_overlay.move(15, parent_height - self.zoom_overlay.height() - 15)
        
        # Position bottom-right overlay
        self.pixel_overlay.adjustSize()
        self.pixel_overlay.move(
            parent_width - self.pixel_overlay.width() - 15,
            parent_height - self.pixel_overlay.height() - 15
        )

    def create_overlay_labels(self, viewport_widget):
        self.wl_label = QLabel("WW: 400\nWL: 40\nSlice: 1/1")
        self.wl_label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 0);
            color: white;
            padding: 10px;
            border-radius: 5px;
            font-size: 12px;
        """
        )
        self.wl_label.setParent(viewport_widget)
        self.wl_label.move(10, 10)

        self.zoom_label = QLabel("Zoom: 100%")
        self.zoom_label.setStyleSheet("""
            background-color: rgba(0, 0, 0, 0);
            color: white;
            padding: 5px 10px;
            border-radius: 3px;
            font-size: 12px;
        """
        )
        self.zoom_label.setParent(viewport_widget)
        QTimer.singleShot(100, self.position_zoom_label)

    def position_zoom_label(self):
        if hasattr(self, 'zoom_label'):
            parent = self.zoom_label.parent()
            if parent:
                self.zoom_label.move(10, parent.height() - 40)  # type: ignore

    def create_right_panel(self, main_layout):
        right_panel = QWidget()
        right_panel.setFixedWidth(250)
        right_panel.setStyleSheet("background-color: #333; border-left: 1px solid #555;")

        scroll_area = QScrollArea()
        scroll_area.setWidget(right_panel)
        scroll_area.setWidgetResizable(True)
        scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)  # type: ignore

        panel_layout = QVBoxLayout(right_panel)
        panel_layout.setContentsMargins(20, 20, 20, 20)
        panel_layout.setSpacing(20)

        self.create_window_level_section(panel_layout)
        self.create_navigation_section(panel_layout)
        self.create_transform_section(panel_layout)
        self.create_image_info_section(panel_layout)
        self.create_measurements_section(panel_layout)

        panel_layout.addStretch()
        main_layout.addWidget(scroll_area)

    def create_window_level_section(self, panel_layout):
        wl_frame = QFrame()
        wl_layout = QVBoxLayout(wl_frame)

        wl_title = QLabel("Window/Level")
        wl_title.setStyleSheet("font-size: 14px; font-weight: bold; color: white; margin-bottom: 10px;")
        wl_layout.addWidget(wl_title)

        ww_label = QLabel("Window Width")
        ww_label.setStyleSheet("font-size: 12px; color: #ccc;")
        wl_layout.addWidget(ww_label)

        self.ww_value_label = QLabel(str(self.window_width))
        self.ww_value_label.setStyleSheet("font-size: 12px; color: #ccc;")
        self.ww_value_label.setAlignment(Qt.AlignRight)  # type: ignore

        ww_header = QHBoxLayout()
        ww_header.addWidget(ww_label)
        ww_header.addWidget(self.ww_value_label)
        wl_layout.addLayout(ww_header)

        self.ww_slider = QSlider(Qt.Horizontal)  # type: ignore
        self.ww_slider.setRange(1, 4000)
        self.ww_slider.setValue(self.window_width)
        self.ww_slider.valueChanged.connect(self.handle_window_width_change)
        wl_layout.addWidget(self.ww_slider)

        wl_label = QLabel("Window Level")
        wl_label.setStyleSheet("font-size: 12px; color: #ccc;")
        wl_layout.addWidget(wl_label)

        self.wl_value_label = QLabel(str(self.window_level))
        self.wl_value_label.setStyleSheet("font-size: 12px; color: #ccc;")
        self.wl_value_label.setAlignment(Qt.AlignRight)  # type: ignore

        wl_header = QHBoxLayout()
        wl_header.addWidget(wl_label)
        wl_header.addWidget(self.wl_value_label)
        wl_layout.addLayout(wl_header)

        self.wl_slider = QSlider(Qt.Horizontal)  # type: ignore
        self.wl_slider.setRange(-1000, 1000)
        self.wl_slider.setValue(self.window_level)
        self.wl_slider.valueChanged.connect(self.handle_window_level_change)
        wl_layout.addWidget(self.wl_slider)

        preset_layout = QGridLayout()
        preset_layout.setSpacing(5)

        preset_buttons = ['lung', 'bone', 'soft', 'brain']
        for i, preset in enumerate(preset_buttons):
            btn = QPushButton(preset.capitalize())
            btn.setStyleSheet("""
                QPushButton { background-color: #444; color: white; border: none; padding: 8px 4px; border-radius: 3px; font-size: 11px; }
                QPushButton:hover { background-color: #555; }
            """
            )
            btn.clicked.connect(lambda checked, p=preset: self.handle_preset(p))
            preset_layout.addWidget(btn, i // 2, i % 2)

        wl_layout.addLayout(preset_layout)
        panel_layout.addWidget(wl_frame)

    def create_navigation_section(self, panel_layout):
        nav_frame = QFrame()
        nav_layout = QVBoxLayout(nav_frame)

        nav_title = QLabel("Image Navigation")
        nav_title.setStyleSheet("font-size: 14px; font-weight: bold; color: white; margin-bottom: 10px;")
        nav_layout.addWidget(nav_title)

        slice_label = QLabel("Slice")
        slice_label.setStyleSheet("font-size: 12px; color: #ccc;")
        nav_layout.addWidget(slice_label)

        self.slice_value_label = QLabel("1")
        self.slice_value_label.setStyleSheet("font-size: 12px; color: #ccc;")
        self.slice_value_label.setAlignment(Qt.AlignRight)  # type: ignore

        slice_header = QHBoxLayout()
        slice_header.addWidget(slice_label)
        slice_header.addWidget(self.slice_value_label)
        nav_layout.addLayout(slice_header)

        self.slice_slider = QSlider(Qt.Horizontal)  # type: ignore
        self.slice_slider.setRange(0, 0)
        self.slice_slider.setValue(0)
        self.slice_slider.valueChanged.connect(self.handle_slice_change_slider)
        nav_layout.addWidget(self.slice_slider)

        panel_layout.addWidget(nav_frame)

    def create_transform_section(self, panel_layout):
        transform_frame = QFrame()
        transform_layout = QVBoxLayout(transform_frame)

        transform_title = QLabel("Transform")
        transform_title.setStyleSheet("font-size: 14px; font-weight: bold; color: white; margin-bottom: 10px;")
        transform_layout.addWidget(transform_title)

        zoom_label = QLabel("Zoom")
        zoom_label.setStyleSheet("font-size: 12px; color: #ccc;")
        transform_layout.addWidget(zoom_label)

        self.zoom_value_label = QLabel("100%")
        self.zoom_value_label.setStyleSheet("font-size: 12px; color: #ccc;")
        self.zoom_value_label.setAlignment(Qt.AlignRight)  # type: ignore

        zoom_header = QHBoxLayout()
        zoom_header.addWidget(zoom_label)
        zoom_header.addWidget(self.zoom_value_label)
        transform_layout.addLayout(zoom_header)

        self.zoom_slider = QSlider(Qt.Horizontal)  # type: ignore
        self.zoom_slider.setRange(25, 500)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(self.handle_zoom_slider)
        transform_layout.addWidget(self.zoom_slider)

        panel_layout.addWidget(transform_frame)

    def create_image_info_section(self, panel_layout):
        info_frame = QFrame()
        info_layout = QVBoxLayout(info_frame)

        info_title = QLabel("Image Info")
        info_title.setStyleSheet("font-size: 14px; font-weight: bold; color: white; margin-bottom: 10px;")
        info_layout.addWidget(info_title)

        self.info_labels = {}
        info_items = ['dimensions', 'pixel_spacing', 'series', 'institution']

        for item in info_items:
            label = QLabel(f"{item.replace('_', ' ').title()}: -")
            label.setStyleSheet("font-size: 12px; color: #ccc; margin-bottom: 5px;")
            info_layout.addWidget(label)
            self.info_labels[item] = label

        panel_layout.addWidget(info_frame)

    def create_measurements_section(self, panel_layout):
        measurements_frame = QFrame()
        measurements_layout = QVBoxLayout(measurements_frame)

        measurements_title = QLabel("Measurements")
        measurements_title.setStyleSheet("font-size: 14px; font-weight: bold; color: white; margin-bottom: 10px;")
        measurements_layout.addWidget(measurements_title)

        clear_btn = QPushButton("Clear All")
        clear_btn.setStyleSheet("""
            QPushButton { background-color: #444; color: white; border: none; padding: 8px 4px; border-radius: 3px; font-size: 11px; }
            QPushButton:hover { background-color: #555; }
        """
        )
        clear_btn.clicked.connect(self.clear_measurements)
        measurements_layout.addWidget(clear_btn)

        self.measurements_list = QListWidget()
        self.measurements_list.setStyleSheet("""
            QListWidget { background-color: #444; color: white; border: 1px solid #555; font-size: 12px; }
        """
        )
        measurements_layout.addWidget(self.measurements_list)

        panel_layout.addWidget(measurements_frame)

    def handle_tool_click(self, tool):
        """Enhanced professional tool handling"""
        logger.info(f"Tool activated: {tool}")
        
        # Handle action tools (non-persistent)
        if tool == 'reset':
            self.reset_view()
            return
        elif tool == 'invert':
            self.inverted = not self.inverted
            self.update_display()
            return
        elif tool == 'crosshair':
            self.crosshair = not self.crosshair
            self.update_display()
            return
        elif tool == 'enhance':
            # Toggle contrast enhancement
            self.contrast_enhancement = not self.contrast_enhancement
            self._cached_image_data = None  # Force re-processing
            self.update_display()
            self.status_bar.showMessage(f"Contrast enhancement: {'ON' if self.contrast_enhancement else 'OFF'}", 2000)
            return
        elif tool == 'filter':
            # Cycle through filter options
            if not self.noise_reduction and not self.edge_enhancement:
                self.noise_reduction = True
                filter_msg = "Noise Reduction ON"
            elif self.noise_reduction and not self.edge_enhancement:
                self.noise_reduction = False
                self.edge_enhancement = True
                filter_msg = "Edge Enhancement ON"
            else:
                self.noise_reduction = False
                self.edge_enhancement = False
                filter_msg = "Filters OFF"
            
            self._cached_image_data = None  # Force re-processing
            self.update_display()
            self.status_bar.showMessage(filter_msg, 2000)
            return
        elif tool == 'cine':
            QMessageBox.information(self, "Cine Mode", "Cine mode playback - Feature in development")
            return
        elif tool == '3d':
            QMessageBox.information(self, "3D Reconstruction", "3D/MPR reconstruction - Feature in development")
            return
        elif tool == 'export':
            QMessageBox.information(self, "Export", "Export functionality - Feature in development")
            return
        
        # Handle persistent tools (change active tool)
        old_tool = self.active_tool
        self.active_tool = tool
        
        # Update button states
        for btn_key, btn in self.tool_buttons.items():
            if btn_key == tool:
                btn.setChecked(True)
            else:
                btn.setChecked(False)
        
        # Update status
        tool_descriptions = {
            'windowing': 'Window/Level adjustment - Drag to adjust contrast and brightness',
            'zoom': 'Zoom tool - Drag up/down to zoom in/out',
            'pan': 'Pan tool - Drag to move around the image',
            'measure': 'Measurement tool - Click and drag to measure distances',
            'annotate': 'Annotation tool - Click to add text annotations'
        }
        
        description = tool_descriptions.get(tool, f'{tool.title()} tool active')
        self.status_bar.showMessage(description, 3000)
        
        # Update zoom overlay to show current tool
        self.update_zoom_overlay()
    
    def create_enhanced_measurements_section(self, layout):
        """Create enhanced measurements section"""
        measurements_frame = QGroupBox("Measurements & Annotations")
        measurements_frame.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
                background-color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-size: 12px;
            }
        """)
        measurements_layout = QVBoxLayout(measurements_frame)
        measurements_layout.setSpacing(12)
        
        # Measurement controls
        measure_controls = QHBoxLayout()
        
        clear_btn = QPushButton("🗑️ Clear All")
        clear_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #dc3545, stop:1 #bd2130);
                color: white;
                border: 2px solid #dc3545;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #e4606d, stop:1 #dc3545);
                border-color: #e4606d;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #bd2130, stop:1 #a71e2a);
                border-color: #bd2130;
            }
        """)
        clear_btn.clicked.connect(self.clear_measurements)
        measure_controls.addWidget(clear_btn)
        
        export_btn = QPushButton("📊 Export")
        export_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #28a745, stop:1 #1e7e34);
                color: white;
                border: 2px solid #28a745;
                border-radius: 6px;
                padding: 6px 10px;
                font-size: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #48c767, stop:1 #28a745);
                border-color: #48c767;
            }
            QPushButton:pressed {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #1e7e34, stop:1 #155724);
                border-color: #1e7e34;
            }
        """)
        export_btn.clicked.connect(self.export_measurements)
        measure_controls.addWidget(export_btn)
        
        measurements_layout.addLayout(measure_controls)
        
        # Measurements list
        self.measurements_list = QListWidget()
        self.measurements_list.setStyleSheet("""
            QListWidget {
                background-color: #1a1a1a;
                border: 2px solid #555555;
                border-radius: 6px;
                color: #ffffff;
                font-size: 11px;
                padding: 5px;
                alternate-background-color: #2d2d2d;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #404040;
                border-radius: 3px;
                margin: 2px;
            }
            QListWidget::item:selected {
                background-color: #0078d4;
                color: white;
            }
            QListWidget::item:hover {
                background-color: #404040;
            }
        """)
        self.measurements_list.setMaximumHeight(150)
        measurements_layout.addWidget(self.measurements_list)
        
        # Measurement statistics
        self.measurement_stats_label = QLabel("No measurements")
        self.measurement_stats_label.setStyleSheet("""
            QLabel {
                color: #cccccc;
                font-size: 10px;
                padding: 5px;
                background-color: #1a1a1a;
                border: 1px solid #555555;
                border-radius: 3px;
            }
        """)
        measurements_layout.addWidget(self.measurement_stats_label)
        
        layout.addWidget(measurements_frame)
    
    def create_enhanced_image_info_section(self, layout):
        """Create enhanced image information section"""
        info_frame = QGroupBox("DICOM Information")
        info_frame.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
                background-color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-size: 12px;
            }
        """)
        info_layout = QVBoxLayout(info_frame)
        info_layout.setSpacing(8)
        
        self.info_labels = {}
        info_items = [
            ('patient_name', 'Patient Name'),
            ('study_date', 'Study Date'),
            ('modality', 'Modality'),
            ('dimensions', 'Image Size'),
            ('pixel_spacing', 'Pixel Spacing'),
            ('slice_thickness', 'Slice Thickness'),
            ('series_description', 'Series Description'),
            ('institution', 'Institution')
        ]
        
        for key, display_name in info_items:
            info_container = QWidget()
            info_container.setStyleSheet("background-color: transparent;")
            info_container_layout = QVBoxLayout(info_container)
            info_container_layout.setContentsMargins(0, 0, 0, 0)
            info_container_layout.setSpacing(2)
            
            # Label
            label_widget = QLabel(display_name + ":")
            label_widget.setStyleSheet("""
                QLabel {
                    color: #888888;
                    font-size: 10px;
                    font-weight: bold;
                }
            """)
            info_container_layout.addWidget(label_widget)
            
            # Value
            value_widget = QLabel("-")
            value_widget.setStyleSheet("""
                QLabel {
                    color: #ffffff;
                    font-size: 11px;
                    background-color: #1a1a1a;
                    padding: 4px 6px;
                    border: 1px solid #555555;
                    border-radius: 3px;
                    font-family: 'Courier New', monospace;
                }
            """)
            value_widget.setWordWrap(True)
            info_container_layout.addWidget(value_widget)
            
            self.info_labels[key] = value_widget
            info_layout.addWidget(info_container)
        
        layout.addWidget(info_frame)
    
    def create_enhanced_presets_section(self, layout):
        """Create enhanced window/level presets section"""
        presets_frame = QGroupBox("Window/Level Presets")
        presets_frame.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 2px solid #555555;
                border-radius: 8px;
                margin-top: 15px;
                padding-top: 15px;
                background-color: #333333;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 15px;
                padding: 0 8px 0 8px;
                color: #ffffff;
                font-size: 12px;
            }
        """)
        presets_layout = QVBoxLayout(presets_frame)
        presets_layout.setSpacing(15)
        
        # CT Presets
        ct_group = QWidget()
        ct_layout = QVBoxLayout(ct_group)
        ct_layout.setContentsMargins(0, 0, 0, 0)
        ct_layout.setSpacing(8)
        
        ct_label = QLabel("🏥 CT Imaging Presets")
        ct_label.setStyleSheet("""
            QLabel {
                color: #00ffff;
                font-size: 11px;
                font-weight: bold;
                padding: 4px;
                background-color: #1a1a1a;
                border-radius: 3px;
                border: 1px solid #00ffff;
            }
        """)
        ct_layout.addWidget(ct_label)
        
        ct_presets_grid = QGridLayout()
        ct_presets = [
            ('lung', 'Lung', '#00ffff'), ('bone', 'Bone', '#ffffff'),
            ('soft', 'Soft Tissue', '#ffaaaa'), ('brain', 'Brain', '#ffff00'),
            ('liver', 'Liver', '#ff8800'), ('mediastinum', 'Mediastinum', '#ff00ff')
        ]
        
        for i, (key, label, color) in enumerate(ct_presets):
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #404040, stop:1 #2d2d2d);
                    color: {color};
                    border: 2px solid {color};
                    border-radius: 6px;
                    padding: 8px 6px;
                    font-size: 10px;
                    font-weight: bold;
                    min-height: 20px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #555555, stop:1 #404040);
                    border-color: {color};
                }}
                QPushButton:pressed {{
                    background: {color};
                    color: #000000;
                }}
            """)
            btn.clicked.connect(lambda checked, k=key: self.handle_preset(k))
            ct_presets_grid.addWidget(btn, i // 2, i % 2)
        
        ct_layout.addLayout(ct_presets_grid)
        presets_layout.addWidget(ct_group)
        
        # X-ray Presets
        xray_group = QWidget()
        xray_layout = QVBoxLayout(xray_group)
        xray_layout.setContentsMargins(0, 0, 0, 0)
        xray_layout.setSpacing(8)
        
        xray_label = QLabel("🩻 X-ray Imaging Presets")
        xray_label.setStyleSheet("""
            QLabel {
                color: #00ff00;
                font-size: 11px;
                font-weight: bold;
                padding: 4px;
                background-color: #1a1a1a;
                border-radius: 3px;
                border: 1px solid #00ff00;
            }
        """)
        xray_layout.addWidget(xray_label)
        
        xray_presets_grid = QGridLayout()
        xray_presets = [
            ('xray_chest', 'Chest', '#00ff00'), ('xray_bone', 'Bone', '#ffffff'),
            ('xray_soft', 'Soft Tissue', '#ffaaaa'), ('xray_pediatric', 'Pediatric', '#ffff00'),
            ('xray_extremity', 'Extremity', '#ff8800'), ('xray_spine', 'Spine', '#ff00ff')
        ]
        
        for i, (key, label, color) in enumerate(xray_presets):
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #404040, stop:1 #2d2d2d);
                    color: {color};
                    border: 2px solid {color};
                    border-radius: 6px;
                    padding: 8px 6px;
                    font-size: 10px;
                    font-weight: bold;
                    min-height: 20px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #555555, stop:1 #404040);
                    border-color: {color};
                }}
                QPushButton:pressed {{
                    background: {color};
                    color: #000000;
                }}
            """)
            btn.clicked.connect(lambda checked, k=key: self.handle_preset(k))
            xray_presets_grid.addWidget(btn, i // 2, i % 2)
        
        xray_layout.addLayout(xray_presets_grid)
        presets_layout.addWidget(xray_group)
        
        # Specialized Presets
        special_group = QWidget()
        special_layout = QVBoxLayout(special_group)
        special_layout.setContentsMargins(0, 0, 0, 0)
        special_layout.setSpacing(8)
        
        special_label = QLabel("🎯 Specialized Presets")
        special_label.setStyleSheet("""
            QLabel {
                color: #ff8800;
                font-size: 11px;
                font-weight: bold;
                padding: 4px;
                background-color: #1a1a1a;
                border-radius: 3px;
                border: 1px solid #ff8800;
            }
        """)
        special_layout.addWidget(special_label)
        
        special_presets_grid = QGridLayout()
        special_presets = [
            ('angio', 'Angiography', '#ff0000'), ('pe_study', 'PE Study', '#ff4444'),
            ('trauma', 'Trauma', '#ff6666'), ('stroke', 'Stroke', '#ff8888')
        ]
        
        for i, (key, label, color) in enumerate(special_presets):
            btn = QPushButton(label)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #404040, stop:1 #2d2d2d);
                    color: {color};
                    border: 2px solid {color};
                    border-radius: 6px;
                    padding: 8px 6px;
                    font-size: 10px;
                    font-weight: bold;
                    min-height: 20px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #555555, stop:1 #404040);
                    border-color: {color};
                }}
                QPushButton:pressed {{
                    background: {color};
                    color: #000000;
                }}
            """)
            btn.clicked.connect(lambda checked, k=key: self.handle_preset(k))
            special_presets_grid.addWidget(btn, i // 2, i % 2)
        
        special_layout.addLayout(special_presets_grid)
        presets_layout.addWidget(special_group)
        
        layout.addWidget(presets_frame)
    
    def _get_nav_button_style(self):
        """Get navigation button style"""
        return """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #404040, stop:1 #2d2d2d);
                color: #00ffff;
                border: 2px solid #00ffff;
                border-radius: 6px;
                padding: 6px 8px;
                font-size: 10px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #555555, stop:1 #404040);
                border-color: #33ffff;
            }
            QPushButton:pressed {
                background: #00ffff;
                color: #000000;
            }
        """
    
    def _get_transform_button_style(self):
        """Get transform button style"""
        return """
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #404040, stop:1 #2d2d2d);
                color: #ff8800;
                border: 2px solid #ff8800;
                border-radius: 6px;
                padding: 6px 8px;
                font-size: 10px;
                font-weight: bold;
                min-height: 20px;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #555555, stop:1 #404040);
                border-color: #ffaa33;
            }
            QPushButton:pressed {
                background: #ff8800;
                color: #000000;
            }
        """
    
    # Enhanced functionality methods
    def auto_window_level(self):
        """Automatically calculate optimal window/level"""
        if not self.current_image_data:
            return
            
        try:
            # Calculate optimal window/level based on image histogram
            flat_data = self.current_image_data.flatten()
            
            # Remove extreme outliers
            p1, p99 = np.percentile(flat_data, [1, 99])
            filtered_data = flat_data[(flat_data >= p1) & (flat_data <= p99)]
            
            if len(filtered_data) > 0:
                # Calculate window width and level
                self.window_width = int(p99 - p1)
                self.window_level = int((p99 + p1) / 2)
                
                # Update sliders
                self.ww_slider.setValue(self.window_width)
                self.wl_slider.setValue(self.window_level)
                
                # Update display
                self.update_display()
                
                # Show status
                self.status_bar.showMessage(f"Auto W/L: WW={self.window_width}, WL={self.window_level}", 3000)
            
        except Exception as e:
            logger.error(f"Auto window/level failed: {e}")
            self.status_bar.showMessage("Auto W/L failed", 2000)
    
    def go_to_slice(self, slice_index):
        """Go to specific slice"""
        if 0 <= slice_index < len(self.dicom_files):
            self.current_image_index = slice_index
            self.slice_slider.setValue(slice_index)
            self.update_display()
    
    def zoom_to_fit(self):
        """Zoom to fit image in viewport"""
        self.zoom_factor = 1.0
        self.zoom_slider.setValue(100)
        self.view_xlim = None
        self.view_ylim = None
        self.update_display()
        self.status_bar.showMessage("Zoomed to fit", 2000)
    
    def zoom_to_100(self):
        """Zoom to 100% (1:1 pixel ratio)"""
        self.zoom_factor = 1.0
        self.zoom_slider.setValue(100)
        self.update_display()
        self.status_bar.showMessage("Zoom: 100% (1:1)", 2000)
    
    def toggle_interpolation(self, enabled):
        """Toggle smooth interpolation"""
        self.interpolation_enabled = enabled
        self.update_display()
        status = "enabled" if enabled else "disabled"
        self.status_bar.showMessage(f"Smooth interpolation {status}", 2000)
    
    def toggle_grid(self, enabled):
        """Toggle grid overlay"""
        self.grid_enabled = enabled
        self.update_display()
        status = "enabled" if enabled else "disabled"
        self.status_bar.showMessage(f"Grid overlay {status}", 2000)
    
    def export_measurements(self):
        """Export measurements to file"""
        if not self.measurements:
            QMessageBox.information(self, "No Measurements", "No measurements to export.")
            return
            
        try:
            filename, _ = QFileDialog.getSaveFileName(
                self, "Export Measurements", "measurements.txt", 
                "Text Files (*.txt);;CSV Files (*.csv);;All Files (*)"
            )
            
            if filename:
                with open(filename, 'w') as f:
                    f.write("DICOM Viewer Measurements Export\n")
                    f.write("=" * 40 + "\n\n")
                    
                    for i, measurement in enumerate(self.measurements, 1):
                        start = measurement['start']
                        end = measurement['end']
                        distance = np.sqrt((end[0] - start[0])**2 + (end[1] - start[1])**2)
                        
                        f.write(f"Measurement {i}:\n")
                        f.write(f"  Start: ({start[0]:.1f}, {start[1]:.1f})\n")
                        f.write(f"  End: ({end[0]:.1f}, {end[1]:.1f})\n")
                        f.write(f"  Distance: {distance:.1f} pixels\n")
                        
                        # Add real-world measurements if available
                        if (self.current_dicom and hasattr(self.current_dicom, 'PixelSpacing')):
                            try:
                                pixel_spacing = self.current_dicom.PixelSpacing
                                if len(pixel_spacing) >= 2:
                                    avg_spacing = (float(pixel_spacing[0]) + float(pixel_spacing[1])) / 2
                                    distance_mm = distance * avg_spacing
                                    f.write(f"  Distance: {distance_mm:.2f} mm\n")
                            except:
                                pass
                        
                        f.write("\n")
                
                self.status_bar.showMessage(f"Measurements exported to {filename}", 3000)
                
        except Exception as e:
            QMessageBox.warning(self, "Export Error", f"Failed to export measurements: {str(e)}")
    
    def update_measurement_stats(self):
        """Update measurement statistics display"""
        if not hasattr(self, 'measurement_stats_label'):
            return
            
        if not self.measurements:
            self.measurement_stats_label.setText("No measurements")
            return
        
        count = len(self.measurements)
        total_distance = 0
        
        for measurement in self.measurements:
            start = measurement['start']
            end = measurement['end']
            distance = np.sqrt((end[0] - start[0])**2 + (end[1] - start[1])**2)
            total_distance += distance
        
        avg_distance = total_distance / count if count > 0 else 0
        
        stats_text = f"Count: {count} | Avg: {avg_distance:.1f}px"
        
        # Add real-world units if available
        if (self.current_dicom and hasattr(self.current_dicom, 'PixelSpacing')):
            try:
                pixel_spacing = self.current_dicom.PixelSpacing
                if len(pixel_spacing) >= 2:
                    avg_spacing = (float(pixel_spacing[0]) + float(pixel_spacing[1])) / 2
                    avg_distance_mm = avg_distance * avg_spacing
                    stats_text += f" | {avg_distance_mm:.2f}mm"
            except:
                pass
        
        self.measurement_stats_label.setText(stats_text)
    
    def display_dicom(self, dicom_data):
        """Display a DICOM image (legacy compatibility method)"""
        self.current_dicom = dicom_data
        if hasattr(dicom_data, 'pixel_array'):
            self.current_image_data = dicom_data.pixel_array.copy()
            self.update_display()
    
    def zoom_to_fit(self):
        """Zoom to fit image in viewport"""
        self.zoom_factor = 1.0
        self.zoom_slider.setValue(100)
        self.view_xlim = None
        self.view_ylim = None
        self.update_display()
        if hasattr(self, 'status_bar'):
            self.status_bar.showMessage("Zoomed to fit", 2000)
    
    def zoom_to_100(self):
        """Zoom to 100% (1:1 pixel ratio)"""
        self.zoom_factor = 1.0
        self.zoom_slider.setValue(100)
        self.update_display()
        if hasattr(self, 'status_bar'):
            self.status_bar.showMessage("Zoom: 100% (1:1)", 2000)
    
    def toggle_interpolation(self, enabled):
        """Toggle smooth interpolation"""
        self.interpolation_enabled = enabled
        self.update_display()
        if hasattr(self, 'status_bar'):
            status = "enabled" if enabled else "disabled"
            self.status_bar.showMessage(f"Smooth interpolation {status}", 2000)
    
    def toggle_grid(self, enabled):
        """Toggle grid overlay"""
        self.grid_enabled = enabled
        self.update_display()
        if hasattr(self, 'status_bar'):
            status = "enabled" if enabled else "disabled"
            self.status_bar.showMessage(f"Grid overlay {status}", 2000)

    def handle_window_width_change(self, value):
        self.window_width = value
        self.ww_value_label.setText(str(value))
        self.update_display()

    def handle_window_level_change(self, value):
        self.window_level = value
        self.wl_value_label.setText(str(value))
        self.update_display()

    def handle_preset(self, preset):
        preset_values = self.window_presets[preset]
        self.window_width = preset_values['ww']
        self.window_level = preset_values['wl']
        self.ww_slider.setValue(self.window_width)
        self.wl_slider.setValue(self.window_level)
        self.update_display()

    def handle_slice_change_slider(self, value):
        self.current_image_index = value
        self.slice_value_label.setText(str(value + 1))
        self.update_display()

    def handle_slice_change(self, direction):
        new_index = self.current_image_index + direction
        if 0 <= new_index < len(self.dicom_files):
            self.current_image_index = new_index
            self.slice_slider.setValue(new_index)
            self.update_display()

    def handle_zoom_slider(self, value):
        self.zoom_factor = value / 100.0
        self.zoom_value_label.setText(f"{value}%")
        self.update_display()

    def handle_zoom(self, factor):
        xlim = self.canvas.ax.get_xlim()
        ylim = self.canvas.ax.get_ylim()
        xcenter = (xlim[0] + xlim[1]) / 2
        ycenter = (ylim[0] + ylim[1]) / 2
        xwidth = (xlim[1] - xlim[0]) / factor
        yheight = (ylim[0] - ylim[1]) / factor
        new_xlim = (xcenter - xwidth/2, xcenter + xwidth/2)
        new_ylim = (ycenter + yheight/2, ycenter - yheight/2)
        self.canvas.ax.set_xlim(new_xlim)
        self.canvas.ax.set_ylim(new_ylim)
        self.view_xlim = new_xlim
        self.view_ylim = new_ylim
        self.zoom_factor *= factor
        self.zoom_factor = max(0.1, min(5.0, self.zoom_factor))
        zoom_percent = int(self.zoom_factor * 100)
        self.zoom_slider.setValue(zoom_percent)
        self.update_display()

    def handle_backend_study_select(self, text):
        if not self.backend_mode:
            return
        if not text or text == "Select Series":
            return
        # map to id
        for label, sid in self.series_options:
            if label == text:
                try:
                    self._load_backend_series(sid)
                except Exception as e:
                    QMessageBox.warning(self, "Error", f"Failed to load series: {str(e)}")
                return

    # Backend integration methods
    def _fetch_json(self, path: str):
        url = f"{self.base_url}{path}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        return r.json()

    def _fetch_png_as_array(self, url: str):
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        img = PILImage.open(BytesIO(r.content)).convert('L')
        return np.array(img)

    def load_backend_study(self, study_id: int):
        try:
            self.backend_mode = True
            data = self._fetch_json(f"/study/{study_id}/")
            self.backend_study = data.get('study')
            series_list = data.get('series_list') or []
            # Fill combo with series
            self.series_options = []
            self.backend_combo.blockSignals(True)
            self.backend_combo.clear()
            self.backend_combo.addItem("Select Series")
            for s in series_list:
                label = f"Series {s.get('series_number')} - {s.get('modality')} ({s.get('image_count')} images)"
                self.series_options.append((label, s.get('id')))
                self.backend_combo.addItem(label)
            self.backend_combo.blockSignals(False)
            # Patient info
            if self.backend_study:
                self.patient_info_label.setText(f"Patient: {self.backend_study.get('patient_name','-')} | Study Date: {self.backend_study.get('study_date','-')} | Modality: {self.backend_study.get('modality','-')}")
            # Auto-load first series
            if self.series_options:
                self.backend_combo.setCurrentText(self.series_options[0][0])
                self._load_backend_series(self.series_options[0][1])
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to load study {study_id}: {str(e)}")

    def _load_backend_series(self, series_id: int):
        data = self._fetch_json(f"/series/{series_id}/images/")
        self.backend_series = data.get('series')
        self.backend_images = data.get('images') or []
        self.current_image_index = 0
        if hasattr(self, 'slice_slider'):
            self.slice_slider.setRange(0, max(0, len(self.backend_images) - 1))
            self.slice_slider.setValue(0)
        # Try initial WW/WL
        if self.backend_images:
            first = self.backend_images[0]
            ww = first.get('window_width')
            wl = first.get('window_center')
            if ww is not None and wl is not None:
                try:
                    self.window_width = float(ww)
                    self.window_level = float(wl)
                    self.ww_slider.setValue(int(self.window_width))
                    self.wl_slider.setValue(int(self.window_level))
                except Exception:
                    pass
        self.update_display()

    def widget_to_data_coords(self, x, y):
        inv = self.canvas.ax.transData.inverted()
        return inv.transform((x, y))

    def on_mouse_press(self, x, y):
        if self.current_image_data is None:
            return
        data_x, data_y = self.widget_to_data_coords(x, y)
        self.drag_start = (data_x, data_y)
        if self.active_tool == 'measure':
            self.current_measurement = {'start': (data_x, data_y), 'end': (data_x, data_y)}
        elif self.active_tool == 'annotate':
            text, ok = QInputDialog.getText(self, 'Annotation', 'Enter annotation text:')
            if ok and text:
                self.annotations.append({'pos': (data_x, data_y), 'text': text})
                self.update_display()

    def update_overlays(self):
        self.canvas.ax.lines.clear()
        self.canvas.ax.texts.clear()
        self.draw_measurements()
        self.draw_annotations()
        if self.crosshair:
            self.draw_crosshair()
        self.update_overlay_labels()
        self.canvas.draw_idle()

    def on_mouse_move(self, x, y):
        if not self.drag_start or self.current_image_data is None:
            return
        data_x, data_y = self.widget_to_data_coords(x, y)
        dx = data_x - self.drag_start[0]
        dy = data_y - self.drag_start[1]
        if self.active_tool == 'pan':
            xlim = self.canvas.ax.get_xlim()
            ylim = self.canvas.ax.get_ylim()
            new_xlim = (xlim[0] - dx, xlim[1] - dx)
            new_ylim = (ylim[0] - dy, ylim[1] - dy)
            self.canvas.ax.set_xlim(new_xlim)
            self.canvas.ax.set_ylim(new_ylim)
            self.view_xlim = new_xlim
            self.view_ylim = new_ylim
            self.drag_start = (data_x, data_y)
            self.canvas.draw_idle()
        elif self.active_tool == 'zoom':
            zoom_delta = 1 + dy * 0.01
            xlim = self.canvas.ax.get_xlim()
            ylim = self.canvas.ax.get_ylim()
            xcenter = (xlim[0] + xlim[1]) / 2
            ycenter = (ylim[0] + ylim[1]) / 2
            xwidth = (xlim[1] - xlim[0]) / zoom_delta
            yheight = (ylim[0] - ylim[1]) / zoom_delta
            new_xlim = (xcenter - xwidth/2, xcenter + xwidth/2)
            new_ylim = (ycenter + yheight/2, ycenter - yheight/2)
            self.canvas.ax.set_xlim(new_xlim)
            self.canvas.ax.set_ylim(new_ylim)
            self.view_xlim = new_xlim
            self.view_ylim = new_ylim
            self.zoom_factor *= zoom_delta
            self.zoom_factor = max(0.1, min(5.0, self.zoom_factor))
            zoom_percent = int(self.zoom_factor * 100)
            self.zoom_slider.setValue(zoom_percent)
            self.drag_start = (data_x, data_y)
            self.canvas.draw_idle()
        elif self.active_tool == 'windowing':
            self.window_width = max(1, self.window_width + dx * 2)
            self.window_level = max(-1000, min(1000, self.window_level + dy * 2))
            self.drag_start = (data_x, data_y)
            self.ww_slider.setValue(int(self.window_width))
            self.wl_slider.setValue(int(self.window_level))
            self.update_display()
        elif self.active_tool == 'measure' and self.current_measurement:
            self.current_measurement['end'] = (data_x, data_y)
            self.update_overlays()

    def on_mouse_release(self, x, y):
        if self.active_tool == 'measure' and self.current_measurement:
            data_x, data_y = self.widget_to_data_coords(x, y)
            self.current_measurement['end'] = (data_x, data_y)
            self.measurements.append(self.current_measurement)
            self.current_measurement = None
            self.update_measurements_list()
            self.update_overlays()
        self.drag_start = None

    def load_dicom_files(self):
        file_dialog = QFileDialog()
        file_paths, _ = file_dialog.getOpenFileNames(self, "Select DICOM Files", "", "DICOM Files (*.dcm *.dicom);;All Files (*)")
        if file_paths:
            self._load_dicom_paths(file_paths)

    def load_dicom_folder(self):
        directory = QFileDialog.getExistingDirectory(self, "Select DICOM Folder", "")
        if directory:
            paths = []
            for root, dirs, files in os.walk(directory):
                for name in files:
                    if name.lower().endswith('.dcm') or name.lower().endswith('.dicom'):
                        paths.append(os.path.join(root, name))
            if not paths:
                QMessageBox.information(self, "No DICOM files", "No .dcm or .dicom files found in the selected folder.")
                return
            self._load_dicom_paths(paths)

    def _load_dicom_paths(self, paths):
        self.dicom_files = []
        for file_path in paths:
            try:
                dicom_data = pydicom.dcmread(file_path)
                self.dicom_files.append(dicom_data)
            except Exception as e:
                QMessageBox.warning(self, "Error", f"Could not load {file_path}: {str(e)}")
        if self.dicom_files:
            self.dicom_files.sort(key=lambda x: getattr(x, 'InstanceNumber', 0))
            self.current_image_index = 0
            self.slice_slider.setRange(0, len(self.dicom_files) - 1)
            self.slice_slider.setValue(0)
            first_dicom = self.dicom_files[0]
            self.current_dicom = first_dicom
            self.display_dicom(first_dicom)
            modality = getattr(first_dicom, 'Modality', 'Unknown')
            patient_name = getattr(first_dicom, 'PatientName', 'Unknown')
            study_date = getattr(first_dicom, 'StudyDate', 'Unknown')
            self.patient_info_label.setText(f"Patient: {patient_name} | Study Date: {study_date} | Modality: {modality}")

    def update_patient_info(self):
        """Update patient information display with enhanced formatting"""
        if not self.dicom_files:
            return
            
        dicom_data = self.dicom_files[self.current_image_index]
        
        # Extract patient information
        patient_name = getattr(dicom_data, 'PatientName', 'Unknown')
        study_date = getattr(dicom_data, 'StudyDate', 'Unknown')
        modality = getattr(dicom_data, 'Modality', 'Unknown')
        
        # Update top bar patient info
        if hasattr(self, 'patient_info_label'):
            self.patient_info_label.setText(f"Patient: {patient_name} | Study Date: {study_date} | Modality: {modality}")
        
        # Update detailed info labels if they exist
        if hasattr(self, 'info_labels') and self.info_labels:
            # Patient information
            if 'patient_name' in self.info_labels:
                self.info_labels['patient_name'].setText(str(patient_name))
            
            if 'study_date' in self.info_labels:
                formatted_date = study_date
                if study_date != 'Unknown' and len(study_date) == 8:
                    try:
                        formatted_date = f"{study_date[:4]}-{study_date[4:6]}-{study_date[6:8]}"
                    except:
                        pass
                self.info_labels['study_date'].setText(formatted_date)
            
            if 'modality' in self.info_labels:
                self.info_labels['modality'].setText(str(modality))
            
            # Image dimensions
            rows = getattr(dicom_data, 'Rows', 'Unknown')
            cols = getattr(dicom_data, 'Columns', 'Unknown')
            if 'dimensions' in self.info_labels:
                self.info_labels['dimensions'].setText(f"{cols} × {rows}")
            
            # Pixel spacing
            pixel_spacing = getattr(dicom_data, 'PixelSpacing', ['Unknown', 'Unknown'])
            if 'pixel_spacing' in self.info_labels:
                if isinstance(pixel_spacing, list) and len(pixel_spacing) >= 2:
                    try:
                        spacing_text = f"{float(pixel_spacing[0]):.3f} × {float(pixel_spacing[1]):.3f} mm"
                    except:
                        spacing_text = f"{pixel_spacing[0]} × {pixel_spacing[1]} mm"
                else:
                    spacing_text = str(pixel_spacing)
                self.info_labels['pixel_spacing'].setText(spacing_text)
            
            # Slice thickness
            slice_thickness = getattr(dicom_data, 'SliceThickness', 'Unknown')
            if 'slice_thickness' in self.info_labels:
                if slice_thickness != 'Unknown':
                    try:
                        self.info_labels['slice_thickness'].setText(f"{float(slice_thickness):.2f} mm")
                    except:
                        self.info_labels['slice_thickness'].setText(str(slice_thickness))
                else:
                    self.info_labels['slice_thickness'].setText("Unknown")
            
            # Series description
            series_description = getattr(dicom_data, 'SeriesDescription', 'Unknown')
            if 'series_description' in self.info_labels:
                self.info_labels['series_description'].setText(str(series_description))
            
            # Institution
            institution = getattr(dicom_data, 'InstitutionName', 'Unknown')
            if 'institution' in self.info_labels:
                self.info_labels['institution'].setText(str(institution))
        
        # Update legacy info labels for backward compatibility
        elif hasattr(self, 'info_labels') and self.info_labels:
            rows = getattr(dicom_data, 'Rows', 'Unknown')
            cols = getattr(dicom_data, 'Columns', 'Unknown')
            pixel_spacing = getattr(dicom_data, 'PixelSpacing', ['Unknown', 'Unknown'])
            series_description = getattr(dicom_data, 'SeriesDescription', 'Unknown')
            institution = getattr(dicom_data, 'InstitutionName', 'Unknown')
            
            if 'dimensions' in self.info_labels:
                self.info_labels['dimensions'].setText(f"Dimensions: {cols}×{rows}")
            
            if 'pixel_spacing' in self.info_labels:
                if isinstance(pixel_spacing, list) and len(pixel_spacing) >= 2:
                    self.info_labels['pixel_spacing'].setText(f"Pixel Spacing: {pixel_spacing[0]}\\{pixel_spacing[1]}")
                else:
                    self.info_labels['pixel_spacing'].setText(f"Pixel Spacing: {pixel_spacing}")
            
            if 'series' in self.info_labels:
                self.info_labels['series'].setText(f"Series: {series_description}")
            
            if 'institution' in self.info_labels:
                self.info_labels['institution'].setText(f"Institution: {institution}")

    def update_display(self):
        if self.backend_mode:
            if not self.backend_images:
                return
            try:
                img_meta = self.backend_images[self.current_image_index]
                invert_flag = 'true' if self.inverted else 'false'
                url = f"{self.base_url}/image/{img_meta['id']}/?ww={int(self.window_width)}&wl={int(self.window_level)}&invert={invert_flag}"
                image_data = self._fetch_png_as_array(url)
                self.current_image_data = image_data
                self.canvas.ax.clear()
                self.canvas.ax.set_facecolor('black')
                self.canvas.ax.axis('off')
                h, w = image_data.shape
                self.canvas.ax.imshow(image_data, cmap='gray', origin='upper', extent=(0, w, h, 0))
                if self.view_xlim and self.view_ylim:
                    self.canvas.ax.set_xlim(self.view_xlim)
                    self.canvas.ax.set_ylim(self.view_ylim)
                else:
                    self.canvas.ax.set_xlim(0, w)
                    self.canvas.ax.set_ylim(h, 0)
                    self.view_xlim = (0, w)
                    self.view_ylim = (h, 0)
                self.draw_measurements()
                self.draw_annotations()
                if self.crosshair:
                    self.draw_crosshair()
                self.update_overlay_labels()
                self.canvas.draw()
                return
            except Exception as e:
                QMessageBox.warning(self, "Display Error", f"Failed to render backend image: {str(e)}")
                return
        if not self.dicom_files:
            return
        self.canvas.ax.clear()
        self.canvas.ax.set_facecolor('black')
        self.canvas.ax.axis('off')
        self.current_dicom = self.dicom_files[self.current_image_index]
        cache_params = (self.current_image_index, self.window_width, self.window_level, self.inverted)
        if self._cached_image_params == cache_params and self._cached_image_data is not None:
            image_data = self._cached_image_data
        else:
            if hasattr(self.current_dicom, 'pixel_array'):
                self.current_image_data = self.current_dicom.pixel_array.copy()
            else:
                return
            image_data = self.apply_medical_grade_windowing(self.current_image_data)
            if self.inverted:
                image_data = 255 - image_data
            self._cached_image_data = image_data
            self._cached_image_params = cache_params
        h, w = image_data.shape
        self.canvas.ax.imshow(image_data, cmap='gray', origin='upper', extent=(0, w, h, 0))
        if self.view_xlim and self.view_ylim:
            self.canvas.ax.set_xlim(self.view_xlim)
            self.canvas.ax.set_ylim(self.view_ylim)
        else:
            self.canvas.ax.set_xlim(0, w)
            self.canvas.ax.set_ylim(h, 0)
            self.view_xlim = (0, w)
            self.view_ylim = (h, 0)
        self.draw_measurements()
        self.draw_annotations()
        if self.crosshair:
            self.draw_crosshair()
        self.update_overlay_labels()
        self.canvas.draw()

    def apply_medical_grade_windowing(self, image_data):
        """Apply medical-grade windowing with advanced image processing"""
        # Convert to float for processing
        processed_data = image_data.astype(np.float32)
        
        # Store original for HU calculations
        original_data = processed_data.copy()
        
        # Apply advanced preprocessing for X-ray images
        if self.current_dicom and hasattr(self.current_dicom, 'Modality'):
            modality = str(getattr(self.current_dicom, 'Modality', '')).upper()
            
            if modality in ['CR', 'DX', 'DR']:  # Digital radiography
                processed_data = self._enhance_xray_image(processed_data)
            elif modality == 'CT':
                processed_data = self._enhance_ct_image(processed_data)
            elif modality in ['MR', 'MRI']:
                processed_data = self._enhance_mr_image(processed_data)
        
        # Apply noise reduction if enabled
        if self.noise_reduction:
            processed_data = self._apply_noise_reduction(processed_data)
        
        # Apply edge enhancement if enabled
        if self.edge_enhancement:
            processed_data = self._apply_edge_enhancement(processed_data)
        
        # Apply contrast enhancement
        if self.contrast_enhancement:
            processed_data = self._apply_contrast_enhancement(processed_data)
        
        # Apply histogram equalization if enabled
        if self.histogram_equalization:
            processed_data = self._apply_histogram_equalization(processed_data)
        
        # Apply window/level
        min_val = self.window_level - self.window_width / 2
        max_val = self.window_level + self.window_width / 2
        
        # Advanced windowing with smooth transitions
        windowed_data = np.clip(processed_data, min_val, max_val)
        
        if max_val > min_val:
            # Smooth windowing curve for better tissue differentiation
            windowed_data = (windowed_data - min_val) / (max_val - min_val)
            
            # Apply gamma correction for medical displays
            gamma = self._get_optimal_gamma()
            windowed_data = np.power(windowed_data, gamma)
            
            # Scale to display range
            windowed_data = windowed_data * 255
        else:
            windowed_data = np.zeros_like(windowed_data)
        
        return windowed_data.astype(np.uint8)
    
    def _enhance_xray_image(self, image_data):
        """Advanced X-ray image enhancement for diagnostic quality"""
        try:
            # X-ray specific enhancement pipeline
            enhanced = image_data.copy()
            
            # 1. Noise reduction with edge preservation
            enhanced = self._bilateral_filter(enhanced)
            
            # 2. Contrast enhancement using CLAHE
            enhanced = self._apply_clahe(enhanced)
            
            # 3. Unsharp masking for edge enhancement
            enhanced = self._unsharp_mask(enhanced, amount=0.3, sigma=1.0)
            
            # 4. Logarithmic enhancement for wide dynamic range
            enhanced = self._log_enhancement(enhanced)
            
            logger.info("Applied X-ray enhancement pipeline")
            return enhanced
            
        except Exception as e:
            logger.warning(f"X-ray enhancement failed: {e}")
            return image_data
    
    def _enhance_ct_image(self, image_data):
        """CT image enhancement for optimal diagnostic viewing"""
        try:
            enhanced = image_data.copy()
            
            # CT-specific processing
            # 1. Mild noise reduction
            enhanced = gaussian_filter(enhanced, sigma=0.5)
            
            # 2. Edge-preserving smoothing
            enhanced = self._edge_preserving_smooth(enhanced)
            
            return enhanced
            
        except Exception as e:
            logger.warning(f"CT enhancement failed: {e}")
            return image_data
    
    def _enhance_mr_image(self, image_data):
        """MR image enhancement"""
        try:
            enhanced = image_data.copy()
            
            # MR-specific processing
            # 1. Non-local means denoising
            if 'denoise_nl_means' in globals():
                enhanced = denoise_nl_means(enhanced, h=0.1, fast_mode=True)
            
            # 2. Bias field correction simulation
            enhanced = self._bias_field_correction(enhanced)
            
            return enhanced
            
        except Exception as e:
            logger.warning(f"MR enhancement failed: {e}")
            return image_data
    
    def _bilateral_filter(self, image_data):
        """Apply bilateral filter for noise reduction with edge preservation"""
        try:
            # Normalize for OpenCV
            normalized = ((image_data - image_data.min()) / 
                         (image_data.max() - image_data.min()) * 255).astype(np.uint8)
            
            # Apply bilateral filter
            filtered = cv2.bilateralFilter(normalized, 9, 75, 75)
            
            # Scale back to original range
            return (filtered.astype(np.float32) / 255.0 * 
                   (image_data.max() - image_data.min()) + image_data.min())
            
        except Exception as e:
            logger.warning(f"Bilateral filter failed: {e}")
            return gaussian_filter(image_data, sigma=0.5)
    
    def _apply_clahe(self, image_data):
        """Apply Contrast Limited Adaptive Histogram Equalization"""
        try:
            # Normalize to 0-255 range
            normalized = ((image_data - image_data.min()) / 
                         (image_data.max() - image_data.min()) * 255).astype(np.uint8)
            
            # Apply CLAHE
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
            enhanced = clahe.apply(normalized)
            
            # Scale back to original range
            return (enhanced.astype(np.float32) / 255.0 * 
                   (image_data.max() - image_data.min()) + image_data.min())
            
        except Exception as e:
            logger.warning(f"CLAHE failed: {e}")
            return image_data
    
    def _unsharp_mask(self, image_data, amount=0.5, sigma=1.0):
        """Apply unsharp masking for edge enhancement"""
        try:
            # Create blurred version
            blurred = gaussian_filter(image_data, sigma=sigma)
            
            # Create mask
            mask = image_data - blurred
            
            # Apply enhancement
            enhanced = image_data + amount * mask
            
            return enhanced
            
        except Exception as e:
            logger.warning(f"Unsharp mask failed: {e}")
            return image_data
    
    def _log_enhancement(self, image_data):
        """Apply logarithmic enhancement for wide dynamic range"""
        try:
            # Ensure positive values
            min_val = image_data.min()
            if min_val <= 0:
                image_data = image_data - min_val + 1
            
            # Apply log enhancement
            enhanced = np.log1p(image_data)
            
            # Normalize
            enhanced = (enhanced - enhanced.min()) / (enhanced.max() - enhanced.min())
            enhanced = enhanced * (image_data.max() - image_data.min()) + image_data.min()
            
            return enhanced
            
        except Exception as e:
            logger.warning(f"Log enhancement failed: {e}")
            return image_data
    
    def _apply_noise_reduction(self, image_data):
        """Apply advanced noise reduction"""
        return gaussian_filter(image_data, sigma=0.8)
    
    def _apply_edge_enhancement(self, image_data):
        """Apply edge enhancement"""
        # Sobel edge detection
        edges_x = sobel(image_data, axis=1)
        edges_y = sobel(image_data, axis=0)
        edges = np.sqrt(edges_x**2 + edges_y**2)
        
        # Enhance edges
        enhanced = image_data + 0.2 * edges
        return enhanced
    
    def _apply_contrast_enhancement(self, image_data):
        """Apply advanced contrast enhancement"""
        # Histogram stretching
        p2, p98 = np.percentile(image_data, (2, 98))
        if p98 > p2:
            enhanced = np.clip((image_data - p2) / (p98 - p2), 0, 1)
            enhanced = enhanced * (image_data.max() - image_data.min()) + image_data.min()
            return enhanced
        return image_data
    
    def _apply_histogram_equalization(self, image_data):
        """Apply histogram equalization"""
        try:
            # Use skimage exposure
            enhanced = exposure.equalize_hist(image_data)
            # Scale back to original range
            enhanced = enhanced * (image_data.max() - image_data.min()) + image_data.min()
            return enhanced
        except:
            return image_data
    
    def _get_optimal_gamma(self):
        """Get optimal gamma correction for current window settings"""
        if self.window_level < -200:  # Lung window
            return 0.8  # Brighten dark areas
        elif self.window_level > 200:  # Bone window  
            return 1.2  # Slightly darken bright areas
        else:  # Soft tissue
            return 1.0  # Standard gamma
    
    def _edge_preserving_smooth(self, image_data):
        """Edge-preserving smoothing filter"""
        return gaussian_filter(image_data, sigma=0.5)
    
    def _bias_field_correction(self, image_data):
        """Simple bias field correction simulation"""
        # Create smooth bias field estimate
        from scipy.ndimage import uniform_filter
        bias_field = uniform_filter(image_data.astype(np.float32), size=50)
        
        # Correct bias field
        corrected = image_data / (bias_field + 1e-6) * np.mean(bias_field)
        return corrected

    def draw_measurements(self):
        for measurement in self.measurements:
            start = measurement['start']
            end = measurement['end']
            x_data = [start[0], end[0]]
            y_data = [start[1], end[1]]
            self.canvas.ax.plot(x_data, y_data, 'r-', linewidth=2)
            distance = np.sqrt((x_data[1] - x_data[0])**2 + (y_data[1] - y_data[0])**2)
            distance_text = f"{distance:.1f} px"
            if self.current_dicom is not None and hasattr(self.current_dicom, 'PixelSpacing'):
                pixel_spacing = self.current_dicom.PixelSpacing
                if pixel_spacing is not None and len(pixel_spacing) >= 2:
                    try:
                        spacing_x = float(pixel_spacing[0])
                        spacing_y = float(pixel_spacing[1])
                        avg_spacing = (spacing_x + spacing_y) / 2
                        distance_mm = distance * avg_spacing
                        distance_cm = distance_mm / 10.0
                        distance_text = f"{distance_mm:.1f} mm / {distance_cm:.2f} cm"
                    except Exception:
                        pass
            mid_x = (x_data[0] + x_data[1]) / 2
            mid_y = (y_data[0] + y_data[1]) / 2
            self.canvas.ax.text(mid_x, mid_y, distance_text, color='red', fontsize=10, ha='center', va='center',
                                bbox=dict(boxstyle="round,pad=0.3", facecolor='black', alpha=0.7))
        if self.current_measurement:
            start = self.current_measurement['start']
            end = self.current_measurement['end']
            x_data = [start[0], end[0]]
            y_data = [start[1], end[1]]
            self.canvas.ax.plot(x_data, y_data, 'y--', linewidth=2, alpha=0.7)

    def draw_annotations(self):
        for annotation in self.annotations:
            pos = annotation['pos']
            text = annotation['text']
            self.canvas.ax.text(pos[0], pos[1], text, color='yellow', fontsize=12, ha='left', va='bottom',
                                bbox=dict(boxstyle="round,pad=0.5", facecolor='black', alpha=0.8))

    def draw_crosshair(self):
        if self.current_image_data is not None:
            height, width = self.current_image_data.shape
            center_x = width // 2
            center_y = height // 2
            self.canvas.ax.axvline(x=center_x, color='cyan', linewidth=1, alpha=0.7)
            self.canvas.ax.axhline(y=center_y, color='cyan', linewidth=1, alpha=0.7)

    def update_overlay_labels(self):
        """Update all professional overlay labels"""
        # Legacy support for old overlays
        if hasattr(self, 'wl_label') and self.wl_label:
            self.wl_label.setText(f"WW: {int(self.window_width)}\nWL: {int(self.window_level)}\nSlice: {self.current_image_index + 1}/{len(self.dicom_files)}")
        if hasattr(self, 'zoom_label') and self.zoom_label:
            self.zoom_label.setText(f"Zoom: {int(self.zoom_factor * 100)}%")
            
        # New professional overlays
        if not hasattr(self, 'wl_overlay'):
            return
            
        # Window/Level overlay
        modality = getattr(self.current_dicom, 'Modality', 'Unknown') if self.current_dicom else 'Unknown'
        slice_info = f"{self.current_image_index + 1}/{len(self.dicom_files)}" if self.dicom_files else "0/0"
        
        self.wl_overlay.setText(f"WW: {int(self.window_width):4d}\nWL: {int(self.window_level):4d}\nSlice: {slice_info}")
        self.wl_overlay.adjustSize()
        
        # Image information overlay
        if self.current_dicom:
            rows = getattr(self.current_dicom, 'Rows', 'N/A')
            cols = getattr(self.current_dicom, 'Columns', 'N/A')
            thickness = getattr(self.current_dicom, 'SliceThickness', 'N/A')
            spacing = getattr(self.current_dicom, 'PixelSpacing', ['N/A', 'N/A'])
            
            if isinstance(spacing, list) and len(spacing) >= 2:
                spacing_text = f"{spacing[0]:.2f}×{spacing[1]:.2f}"
            else:
                spacing_text = str(spacing)
                
            self.image_overlay.setText(
                f"Modality: {modality}\n"
                f"Matrix: {cols}×{rows}\n"
                f"Spacing: {spacing_text}mm\n"
                f"Thickness: {thickness}mm"
            )
            self.image_overlay.adjustSize()
        
        # Update zoom overlay
        self.update_zoom_overlay()

    def update_measurements_list(self):
        """Update the measurements list with enhanced display"""
        if not hasattr(self, 'measurements_list'):
            return
            
        self.measurements_list.clear()
        
        for i, measurement in enumerate(self.measurements):
            start = measurement['start']
            end = measurement['end']
            distance = np.sqrt((end[0] - start[0])**2 + (end[1] - start[1])**2)
            distance_text = f"{distance:.1f} px"
            
            # Add real-world measurements if available
            if self.current_dicom is not None and hasattr(self.current_dicom, 'PixelSpacing'):
                pixel_spacing = self.current_dicom.PixelSpacing
                if pixel_spacing is not None and len(pixel_spacing) >= 2:
                    try:
                        spacing_x = float(pixel_spacing[0])
                        spacing_y = float(pixel_spacing[1])
                        avg_spacing = (spacing_x + spacing_y) / 2
                        distance_mm = distance * avg_spacing
                        distance_cm = distance_mm / 10.0
                        distance_text = f"{distance_mm:.1f} mm ({distance_cm:.2f} cm)"
                    except Exception:
                        pass
            
            # Create enhanced list item
            item_text = f"📏 Measurement {i+1}: {distance_text}"
            item = QListWidgetItem(item_text)
            item.setToolTip(f"Start: ({start[0]:.1f}, {start[1]:.1f})\nEnd: ({end[0]:.1f}, {end[1]:.1f})\nDistance: {distance_text}")
            self.measurements_list.addItem(item)
        
        # Update statistics
        self.update_measurement_stats()

    def clear_measurements(self):
        """Clear all measurements and annotations"""
        self.measurements.clear()
        self.annotations.clear()
        self.current_measurement = None
        self.update_measurements_list()
        self.update_display()
        
        # Show status message
        if hasattr(self, 'status_bar'):
            self.status_bar.showMessage("All measurements and annotations cleared", 2000)

    def reset_view(self):
        self.zoom_factor = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.zoom_slider.setValue(100)
        if self.current_image_data is not None:
            h, w = self.current_image_data.shape
            self.view_xlim = (0, w)
            self.view_ylim = (h, 0)
        self.update_display()
    
    def on_pixel_value_changed(self, x, y, pixel_value):
        """Handle pixel value changes for professional HU display"""
        self.current_pixel_value = pixel_value
        self.current_mouse_pos = (x, y)
        
        # Calculate Hounsfield Units if CT data
        hu_value = pixel_value
        if self.current_dicom and hasattr(self.current_dicom, 'RescaleSlope'):
            try:
                slope = float(getattr(self.current_dicom, 'RescaleSlope', 1.0))
                intercept = float(getattr(self.current_dicom, 'RescaleIntercept', 0.0))
                hu_value = pixel_value * slope + intercept
                self.current_hu_value = hu_value
            except:
                pass
        
        # Update pixel overlay
        self.update_pixel_overlay()
        
        # Update status bar
        if self.pixel_info_label:
            modality = getattr(self.current_dicom, 'Modality', '') if self.current_dicom else ''
            if modality == 'CT':
                self.pixel_info_label.setText(
                    f"Pos: ({int(x)}, {int(y)}) | Pixel: {pixel_value:.0f} | HU: {hu_value:.1f}"
                )
            else:
                self.pixel_info_label.setText(
                    f"Pos: ({int(x)}, {int(y)}) | Value: {pixel_value:.0f}"
                )
    
    def adjust_window_level(self, ww_delta, wl_delta):
        """Adjust window/level with delta values"""
        self.window_width = max(1, self.window_width + ww_delta)
        self.window_level = max(-1000, min(1000, self.window_level + wl_delta))
        
        # Update sliders
        self.ww_slider.setValue(int(self.window_width))
        self.wl_slider.setValue(int(self.window_level))
        
        self.update_display()
    
    def update_pixel_overlay(self):
        """Update pixel value overlay"""
        if hasattr(self, 'pixel_overlay') and self.pixel_overlay:
            x, y = self.current_mouse_pos
            pixel_val = self.current_pixel_value
            hu_val = self.current_hu_value
            
            if self.current_dicom and getattr(self.current_dicom, 'Modality', '') == 'CT':
                self.pixel_overlay.setText(f"X: {int(x):4d} Y: {int(y):4d}\nPixel: {pixel_val:6.0f}\nHU: {hu_val:7.1f}")
            else:
                self.pixel_overlay.setText(f"X: {int(x):4d} Y: {int(y):4d}\nValue: {pixel_val:6.0f}")
            
            self.pixel_overlay.adjustSize()
    
    def update_zoom_overlay(self):
        """Update zoom and tool overlay"""
        if hasattr(self, 'zoom_overlay') and self.zoom_overlay:
            tool_text = f"Tool: {self.active_tool.title()}"
            zoom_text = f"Zoom: {int(self.zoom_factor * 100)}%"
            self.zoom_overlay.setText(f"{tool_text}\n{zoom_text}")
            self.zoom_overlay.adjustSize()

    def open_path(self, path):
        paths = []
        if os.path.isdir(path):
            for root, _, files in os.walk(path):
                for name in files:
                    if name.lower().endswith(('.dcm', '.dicom')):
                        paths.append(os.path.join(root, name))
        elif os.path.isfile(path):
            paths = [path]
        else:
            QMessageBox.warning(self, "Error", f"Path not found: {path}")
            return
        if not paths:
            QMessageBox.warning(self, "Error", f"No DICOM files found in: {path}")
            return
        self._load_dicom_paths(paths)
    
    def resizeEvent(self, event):
        """Handle window resize events professionally"""
        super().resizeEvent(event)
        # Reposition overlays after resize
        QTimer.singleShot(50, self.position_overlays)


def main():
    parser = argparse.ArgumentParser(description='Professional DICOM Viewer - Medical Imaging Excellence')
    parser.add_argument('--path', help='Path to a DICOM file or directory to open')
    parser.add_argument('--study-id', help='Study ID to load from backend', type=int)
    parser.add_argument('--debug', action='store_true', help='Enable debug logging')
    args = parser.parse_args()
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName("Professional DICOM Viewer")
    app.setApplicationVersion("2.0 Enhanced")

    # Create the enhanced viewer
    viewer = DicomViewer()
    viewer.show()

    # Load initial data if provided
    if args.path:
        viewer.open_path(args.path)
    if args.study_id:
        try:
            viewer.load_backend_study(args.study_id)
        except Exception as e:
            logger.error(f"Failed to load study {args.study_id}: {e}")

    # Show startup message
    logger.info("Professional DICOM Viewer started successfully")
    if hasattr(viewer, 'status_bar'):
        viewer.status_bar.showMessage("Professional DICOM Viewer - Ready for medical imaging excellence", 5000)

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()