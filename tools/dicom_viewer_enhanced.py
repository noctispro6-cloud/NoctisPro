#!/usr/bin/env python3
"""
Professional DICOM Viewer - Medical Imaging Excellence
Enhanced version with systematic improvements for diagnostic quality
Optimized for X-ray, CT, MRI, and other medical imaging modalities
"""

import sys
import os
import argparse
import logging

# Configure logging for professional debugging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

try:
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
    
    try:
        from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
        from matplotlib.figure import Figure
        from matplotlib.colors import LinearSegmentedColormap
        import matplotlib.pyplot as plt
        MATPLOTLIB_AVAILABLE = True
    except ImportError:
        MATPLOTLIB_AVAILABLE = False
        logger.warning("Matplotlib not available - using basic image display")
    
    try:
        from PIL import Image as PILImage, ImageEnhance, ImageFilter
        PIL_AVAILABLE = True
    except ImportError:
        PIL_AVAILABLE = False
        logger.warning("PIL not available - using basic image processing")
    
    try:
        from scipy import ndimage
        from scipy.ndimage import gaussian_filter, sobel
        SCIPY_AVAILABLE = True
    except ImportError:
        SCIPY_AVAILABLE = False
        logger.warning("SciPy not available - using basic filtering")
    
    try:
        import cv2
        OPENCV_AVAILABLE = True
    except ImportError:
        OPENCV_AVAILABLE = False
        logger.warning("OpenCV not available - using basic image processing")
    
    try:
        from skimage import exposure, filters, morphology
        from skimage.restoration import denoise_nl_means
        SKIMAGE_AVAILABLE = True
    except ImportError:
        SKIMAGE_AVAILABLE = False
        logger.warning("scikit-image not available - using basic enhancement")
    
    from io import BytesIO
    import requests
    
except ImportError as e:
    logger.error(f"Critical import error: {e}")
    print(f"Error: Missing required packages. Please install: {e}")
    sys.exit(1)


class BasicCanvas(QWidget):
    """Basic canvas for DICOM display when matplotlib is not available"""
    mouse_pressed = pyqtSignal(int, int)
    mouse_moved = pyqtSignal(int, int)
    mouse_released = pyqtSignal(int, int)
    pixel_value_changed = pyqtSignal(float, float, float)
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet("background-color: black; border: none;")
        self.setMinimumSize(400, 400)
        self.image_data = None
        self.qimage = None
        self.scale_factor = 1.0
        self.offset_x = 0
        self.offset_y = 0
        self.mouse_pressed_flag = False
        
    def set_image_data(self, image_data):
        """Set image data and convert to QImage"""
        if image_data is None:
            return
            
        self.image_data = image_data
        
        # Convert to QImage
        if image_data.dtype != np.uint8:
            # Normalize to 0-255
            img_norm = ((image_data - image_data.min()) / 
                       (image_data.max() - image_data.min()) * 255).astype(np.uint8)
        else:
            img_norm = image_data
            
        height, width = img_norm.shape
        bytes_per_line = width
        
        self.qimage = QImage(img_norm.data, width, height, bytes_per_line, QImage.Format_Grayscale8)
        self.update()
    
    def paintEvent(self, event):
        if self.qimage is None:
            return
            
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        
        # Calculate display rectangle
        widget_rect = self.rect()
        image_rect = self.qimage.rect()
        
        # Scale to fit while maintaining aspect ratio
        scaled_size = image_rect.size().scaled(widget_rect.size(), Qt.KeepAspectRatio)
        
        # Center the image
        x = (widget_rect.width() - scaled_size.width()) // 2 + self.offset_x
        y = (widget_rect.height() - scaled_size.height()) // 2 + self.offset_y
        
        target_rect = QImage(x, y, 
                           int(scaled_size.width() * self.scale_factor), 
                           int(scaled_size.height() * self.scale_factor))
        
        painter.drawImage(target_rect, self.qimage)
    
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.mouse_pressed_flag = True
            self.mouse_pressed.emit(event.x(), event.y())
    
    def mouseMoveEvent(self, event):
        if self.mouse_pressed_flag:
            self.mouse_moved.emit(event.x(), event.y())
    
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.mouse_pressed_flag = False
            self.mouse_released.emit(event.x(), event.y())


if MATPLOTLIB_AVAILABLE:
    class DicomCanvas(FigureCanvas):
        """Professional DICOM Canvas with Medical-Grade Rendering"""
        mouse_pressed = pyqtSignal(int, int)
        mouse_moved = pyqtSignal(int, int)
        mouse_released = pyqtSignal(int, int)
        pixel_value_changed = pyqtSignal(float, float, float)

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
else:
    # Use basic canvas when matplotlib is not available
    DicomCanvas = BasicCanvas


class ProfessionalDicomViewer(QMainWindow):
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
        self.original_pixel_data = None
        
        # Enhanced display parameters
        self.window_width = 400
        self.window_level = 40
        self.zoom_factor = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.inverted = False
        self.crosshair = False
        
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
        self._cached_image_params = (None, None, None, None, None, None)
        self._processing_cache = {}
        
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
        main_splitter.setSizes([90, 800, 280])
        
        main_layout.addWidget(main_splitter)
        
        # Show welcome message
        self.status_bar.showMessage("Professional DICOM Viewer Ready - Load DICOM files to begin", 5000)

    def create_professional_toolbar(self, main_splitter):
        """Create professional medical imaging toolbar"""
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
        toolbar_layout.setSpacing(5)
        
        # Simplified tools for basic functionality
        tools = [
            ('windowing', 'Window', '🪟'),
            ('zoom', 'Zoom', '🔍'),
            ('pan', 'Pan', '✋'),
            ('measure', 'Measure', '📏'),
            ('annotate', 'Annotate', '📝'),
            ('crosshair', 'Crosshair', '✚'),
            ('invert', 'Invert', '⚫'),
            ('reset', 'Reset', '🏠'),
        ]

        self.tool_buttons = {}
        for tool_key, tool_label, tool_icon in tools:
            btn = QPushButton(f"{tool_icon}\n{tool_label}")
            btn.setFixedSize(75, 55)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #404040;
                    color: white;
                    border: 1px solid #555555;
                    border-radius: 6px;
                    font-size: 9px;
                    font-weight: bold;
                }
                QPushButton:hover {
                    background-color: #4a4a4a;
                    border-color: #0078d4;
                }
                QPushButton:pressed, QPushButton:checked {
                    background-color: #0078d4;
                    border-color: #005a9e;
                }
            """)
            btn.setCheckable(True)
            btn.clicked.connect(lambda checked, tool=tool_key: self.handle_tool_click(tool))
            toolbar_layout.addWidget(btn)
            self.tool_buttons[tool_key] = btn

        toolbar_layout.addStretch()
        main_splitter.addWidget(toolbar)

    def create_enhanced_top_bar(self, center_layout):
        """Create enhanced top bar"""
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

        # Load buttons
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
        top_layout.addWidget(load_btn)

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
        top_layout.addWidget(folder_btn)

        # Patient information
        self.patient_info_label = QLabel("Ready to load DICOM files...")
        self.patient_info_label.setStyleSheet("""
            QLabel {
                font-size: 11px;
                color: #cccccc;
                font-family: 'Segoe UI', Arial, sans-serif;
                padding: 5px;
            }
        """)
        top_layout.addWidget(self.patient_info_label, 1)

        center_layout.addWidget(top_bar)

    def create_professional_viewport(self, center_layout):
        """Create professional medical imaging viewport"""
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
        
        if hasattr(self.canvas, 'pixel_value_changed'):
            self.canvas.pixel_value_changed.connect(self.on_pixel_value_changed)

        viewport_layout.addWidget(self.canvas)
        center_layout.addWidget(viewport_widget)

    def create_professional_right_panel(self, main_splitter):
        """Create enhanced right panel with controls"""
        right_panel = QWidget()
        right_panel.setFixedWidth(280)
        right_panel.setStyleSheet("""
            QWidget {
                background-color: #2d2d2d;
                border-left: 2px solid #404040;
            }
        """)
        
        panel_layout = QVBoxLayout(right_panel)
        panel_layout.setContentsMargins(10, 10, 10, 10)
        panel_layout.setSpacing(15)
        
        # Window/Level controls
        self.create_window_level_controls(panel_layout)
        
        # Navigation controls
        self.create_navigation_controls(panel_layout)
        
        # Preset buttons
        self.create_preset_controls(panel_layout)
        
        # Image info
        self.create_image_info_controls(panel_layout)
        
        panel_layout.addStretch()
        main_splitter.addWidget(right_panel)

    def create_window_level_controls(self, layout):
        """Create window/level controls"""
        group = QGroupBox("Window/Level")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        
        group_layout = QVBoxLayout(group)
        
        # Window Width
        ww_layout = QHBoxLayout()
        ww_layout.addWidget(QLabel("Width:"))
        self.ww_value_label = QLabel(str(self.window_width))
        self.ww_value_label.setAlignment(Qt.AlignRight)
        ww_layout.addWidget(self.ww_value_label)
        group_layout.addLayout(ww_layout)
        
        self.ww_slider = QSlider(Qt.Horizontal)
        self.ww_slider.setRange(1, 4000)
        self.ww_slider.setValue(self.window_width)
        self.ww_slider.valueChanged.connect(self.handle_window_width_change)
        group_layout.addWidget(self.ww_slider)
        
        # Window Level
        wl_layout = QHBoxLayout()
        wl_layout.addWidget(QLabel("Level:"))
        self.wl_value_label = QLabel(str(self.window_level))
        self.wl_value_label.setAlignment(Qt.AlignRight)
        wl_layout.addWidget(self.wl_value_label)
        group_layout.addLayout(wl_layout)
        
        self.wl_slider = QSlider(Qt.Horizontal)
        self.wl_slider.setRange(-1000, 1000)
        self.wl_slider.setValue(self.window_level)
        self.wl_slider.valueChanged.connect(self.handle_window_level_change)
        group_layout.addWidget(self.wl_slider)
        
        layout.addWidget(group)

    def create_navigation_controls(self, layout):
        """Create navigation controls"""
        group = QGroupBox("Navigation")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        
        group_layout = QVBoxLayout(group)
        
        # Slice navigation
        slice_layout = QHBoxLayout()
        slice_layout.addWidget(QLabel("Slice:"))
        self.slice_value_label = QLabel("1")
        self.slice_value_label.setAlignment(Qt.AlignRight)
        slice_layout.addWidget(self.slice_value_label)
        group_layout.addLayout(slice_layout)
        
        self.slice_slider = QSlider(Qt.Horizontal)
        self.slice_slider.setRange(0, 0)
        self.slice_slider.setValue(0)
        self.slice_slider.valueChanged.connect(self.handle_slice_change_slider)
        group_layout.addWidget(self.slice_slider)
        
        # Zoom
        zoom_layout = QHBoxLayout()
        zoom_layout.addWidget(QLabel("Zoom:"))
        self.zoom_value_label = QLabel("100%")
        self.zoom_value_label.setAlignment(Qt.AlignRight)
        zoom_layout.addWidget(self.zoom_value_label)
        group_layout.addLayout(zoom_layout)
        
        self.zoom_slider = QSlider(Qt.Horizontal)
        self.zoom_slider.setRange(25, 500)
        self.zoom_slider.setValue(100)
        self.zoom_slider.valueChanged.connect(self.handle_zoom_slider)
        group_layout.addWidget(self.zoom_slider)
        
        layout.addWidget(group)

    def create_preset_controls(self, layout):
        """Create window/level preset controls"""
        group = QGroupBox("Window Presets")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        
        group_layout = QGridLayout(group)
        
        # Common presets
        presets = [
            ('lung', 'Lung'), ('bone', 'Bone'), ('soft', 'Soft'), ('brain', 'Brain'),
            ('xray_chest', 'CXR'), ('xray_bone', 'X-Bone'), ('liver', 'Liver'), ('angio', 'Angio')
        ]
        
        for i, (key, label) in enumerate(presets):
            btn = QPushButton(label)
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #404040;
                    color: white;
                    border: 1px solid #555555;
                    border-radius: 3px;
                    padding: 6px;
                    font-size: 10px;
                }
                QPushButton:hover {
                    background-color: #4a4a4a;
                    border-color: #0078d4;
                }
                QPushButton:pressed {
                    background-color: #0078d4;
                }
            """)
            btn.clicked.connect(lambda checked, k=key: self.handle_preset(k))
            group_layout.addWidget(btn, i // 4, i % 4)
        
        layout.addWidget(group)

    def create_image_info_controls(self, layout):
        """Create image information display"""
        group = QGroupBox("Image Information")
        group.setStyleSheet("""
            QGroupBox {
                font-weight: bold;
                border: 1px solid #555555;
                border-radius: 5px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
        """)
        
        group_layout = QVBoxLayout(group)
        
        self.info_labels = {}
        info_items = ['dimensions', 'pixel_spacing', 'series', 'modality']
        
        for item in info_items:
            label = QLabel(f"{item.replace('_', ' ').title()}: -")
            label.setStyleSheet("font-size: 11px; color: #cccccc; padding: 2px;")
            group_layout.addWidget(label)
            self.info_labels[item] = label
        
        layout.addWidget(group)

    def handle_tool_click(self, tool):
        """Handle tool button clicks"""
        logger.info(f"Tool activated: {tool}")
        
        # Handle action tools
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
        
        # Handle persistent tools
        self.active_tool = tool
        
        # Update button states
        for btn_key, btn in self.tool_buttons.items():
            btn.setChecked(btn_key == tool)
        
        # Update status
        self.status_bar.showMessage(f"{tool.title()} tool active", 2000)

    def handle_window_width_change(self, value):
        """Handle window width changes"""
        self.window_width = value
        self.ww_value_label.setText(str(value))
        self.update_display()

    def handle_window_level_change(self, value):
        """Handle window level changes"""
        self.window_level = value
        self.wl_value_label.setText(str(value))
        self.update_display()

    def handle_preset(self, preset_key):
        """Apply window/level preset"""
        if preset_key in self.window_presets:
            preset = self.window_presets[preset_key]
            self.window_width = preset['ww']
            self.window_level = preset['wl']
            
            self.ww_slider.setValue(self.window_width)
            self.wl_slider.setValue(self.window_level)
            
            self.status_bar.showMessage(f"Applied {preset['description']}", 3000)
            self.update_display()

    def handle_slice_change_slider(self, value):
        """Handle slice slider changes"""
        self.current_image_index = value
        self.slice_value_label.setText(str(value + 1))
        self.update_display()

    def handle_slice_change(self, direction):
        """Handle slice navigation"""
        new_index = self.current_image_index + direction
        if 0 <= new_index < len(self.dicom_files):
            self.current_image_index = new_index
            self.slice_slider.setValue(new_index)
            self.update_display()

    def handle_zoom_slider(self, value):
        """Handle zoom slider changes"""
        self.zoom_factor = value / 100.0
        self.zoom_value_label.setText(f"{value}%")
        self.update_display()

    def handle_zoom(self, factor, center_x=None, center_y=None):
        """Handle zoom operations"""
        self.zoom_factor *= factor
        self.zoom_factor = max(0.1, min(10.0, self.zoom_factor))
        zoom_percent = int(self.zoom_factor * 100)
        self.zoom_slider.setValue(zoom_percent)
        self.update_display()

    def adjust_window_level(self, ww_delta, wl_delta):
        """Adjust window/level with delta values"""
        self.window_width = max(1, self.window_width + ww_delta)
        self.window_level = max(-1000, min(1000, self.window_level + wl_delta))
        
        self.ww_slider.setValue(int(self.window_width))
        self.wl_slider.setValue(int(self.window_level))
        
        self.update_display()

    def on_pixel_value_changed(self, x, y, pixel_value):
        """Handle pixel value changes"""
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

    def on_mouse_press(self, x, y):
        """Handle mouse press events"""
        if self.current_image_data is None:
            return
            
        self.drag_start = (x, y)
        
        if self.active_tool == 'measure':
            self.current_measurement = {'start': (x, y), 'end': (x, y)}
        elif self.active_tool == 'annotate':
            text, ok = QInputDialog.getText(self, 'Annotation', 'Enter annotation text:')
            if ok and text:
                self.annotations.append({'pos': (x, y), 'text': text})
                self.update_display()

    def on_mouse_move(self, x, y):
        """Handle mouse move events"""
        if not self.drag_start:
            return
            
        dx = x - self.drag_start[0]
        dy = y - self.drag_start[1]
        
        if self.active_tool == 'windowing':
            self.window_width = max(1, self.window_width + dx * 2)
            self.window_level = max(-1000, min(1000, self.window_level + dy * 2))
            self.drag_start = (x, y)
            self.ww_slider.setValue(int(self.window_width))
            self.wl_slider.setValue(int(self.window_level))
            self.update_display()
        elif self.active_tool == 'zoom':
            zoom_delta = 1 + dy * 0.01
            self.handle_zoom(zoom_delta)
            self.drag_start = (x, y)
        elif self.active_tool == 'pan':
            # Simple pan implementation
            self.pan_x += dx
            self.pan_y += dy
            self.drag_start = (x, y)
            self.update_display()
        elif self.active_tool == 'measure' and self.current_measurement:
            self.current_measurement['end'] = (x, y)
            self.update_display()

    def on_mouse_release(self, x, y):
        """Handle mouse release events"""
        if self.active_tool == 'measure' and self.current_measurement:
            self.current_measurement['end'] = (x, y)
            self.measurements.append(self.current_measurement)
            self.current_measurement = None
            self.update_display()
        
        self.drag_start = None

    def load_dicom_files(self):
        """Load DICOM files"""
        file_dialog = QFileDialog()
        file_paths, _ = file_dialog.getOpenFileNames(
            self, "Select DICOM Files", "", 
            "DICOM Files (*.dcm *.dicom);;All Files (*)"
        )
        
        if file_paths:
            self._load_dicom_paths(file_paths)

    def load_dicom_folder(self):
        """Load DICOM folder"""
        directory = QFileDialog.getExistingDirectory(self, "Select DICOM Folder", "")
        if directory:
            paths = []
            for root, dirs, files in os.walk(directory):
                for name in files:
                    if name.lower().endswith(('.dcm', '.dicom')):
                        paths.append(os.path.join(root, name))
            
            if paths:
                self._load_dicom_paths(paths)
            else:
                QMessageBox.information(self, "No DICOM files", 
                                      "No .dcm or .dicom files found in the selected folder.")

    def _load_dicom_paths(self, paths):
        """Load DICOM files from paths"""
        self.dicom_files = []
        failed_files = 0
        
        for file_path in paths:
            try:
                dicom_data = pydicom.dcmread(file_path)
                self.dicom_files.append(dicom_data)
            except Exception as e:
                failed_files += 1
                logger.warning(f"Could not load {file_path}: {str(e)}")
        
        if self.dicom_files:
            # Sort by instance number
            self.dicom_files.sort(key=lambda x: getattr(x, 'InstanceNumber', 0))
            
            self.current_image_index = 0
            self.slice_slider.setRange(0, len(self.dicom_files) - 1)
            self.slice_slider.setValue(0)
            
            # Set initial window/level from first image
            first_dicom = self.dicom_files[0]
            if hasattr(first_dicom, 'WindowWidth') and hasattr(first_dicom, 'WindowCenter'):
                try:
                    self.window_width = int(first_dicom.WindowWidth)
                    self.window_level = int(first_dicom.WindowCenter)
                    self.ww_slider.setValue(self.window_width)
                    self.wl_slider.setValue(self.window_level)
                except:
                    pass
            
            self.update_patient_info()
            self.update_display()
            
            # Show status
            total_loaded = len(self.dicom_files)
            status_msg = f"Loaded {total_loaded} DICOM file(s)"
            if failed_files > 0:
                status_msg += f" ({failed_files} failed)"
            self.status_bar.showMessage(status_msg, 5000)
        else:
            QMessageBox.warning(self, "Error", "No valid DICOM files could be loaded.")

    def update_patient_info(self):
        """Update patient information display"""
        if not self.dicom_files:
            return
            
        dicom_data = self.dicom_files[self.current_image_index]
        
        # Extract patient information
        patient_name = getattr(dicom_data, 'PatientName', 'Unknown')
        study_date = getattr(dicom_data, 'StudyDate', 'Unknown')
        modality = getattr(dicom_data, 'Modality', 'Unknown')
        
        self.patient_info_label.setText(
            f"Patient: {patient_name} | Study Date: {study_date} | Modality: {modality}"
        )
        
        # Update image info
        if hasattr(self, 'info_labels'):
            rows = getattr(dicom_data, 'Rows', 'Unknown')
            cols = getattr(dicom_data, 'Columns', 'Unknown')
            pixel_spacing = getattr(dicom_data, 'PixelSpacing', ['Unknown', 'Unknown'])
            series_description = getattr(dicom_data, 'SeriesDescription', 'Unknown')
            
            self.info_labels['dimensions'].setText(f"Dimensions: {cols}×{rows}")
            
            if isinstance(pixel_spacing, list) and len(pixel_spacing) >= 2:
                spacing_text = f"{pixel_spacing[0]:.2f}×{pixel_spacing[1]:.2f}mm"
            else:
                spacing_text = str(pixel_spacing)
                
            self.info_labels['pixel_spacing'].setText(f"Pixel Spacing: {spacing_text}")
            self.info_labels['series'].setText(f"Series: {series_description}")
            self.info_labels['modality'].setText(f"Modality: {modality}")

    def update_display(self):
        """Update the display with current image"""
        if not self.dicom_files:
            return
            
        self.current_dicom = self.dicom_files[self.current_image_index]
        
        # Get pixel data
        if hasattr(self.current_dicom, 'pixel_array'):
            try:
                self.current_image_data = self.current_dicom.pixel_array.copy()
                
                # Apply windowing
                windowed_data = self.apply_windowing(self.current_image_data)
                
                # Apply inversion if needed
                if self.inverted:
                    windowed_data = 255 - windowed_data
                
                # Update display
                if MATPLOTLIB_AVAILABLE and hasattr(self.canvas, 'ax'):
                    # Matplotlib display
                    self.canvas.ax.clear()
                    self.canvas.ax.set_facecolor('black')
                    self.canvas.ax.axis('off')
                    
                    h, w = windowed_data.shape
                    self.canvas.ax.imshow(windowed_data, cmap='gray', origin='upper', 
                                        extent=(0, w, h, 0))
                    
                    # Draw overlays
                    self.draw_measurements()
                    self.draw_annotations()
                    if self.crosshair:
                        self.draw_crosshair()
                    
                    self.canvas.draw()
                else:
                    # Basic display
                    if hasattr(self.canvas, 'set_image_data'):
                        self.canvas.set_image_data(windowed_data)
                
                # Update slice info
                self.slice_value_label.setText(f"{self.current_image_index + 1}/{len(self.dicom_files)}")
                
            except Exception as e:
                logger.error(f"Error updating display: {e}")
                self.status_bar.showMessage(f"Error displaying image: {str(e)}", 5000)

    def apply_windowing(self, image_data):
        """Apply window/level to image data"""
        # Convert to float for calculations
        data = image_data.astype(np.float32)
        
        # Apply rescale slope/intercept if available
        if self.current_dicom and hasattr(self.current_dicom, 'RescaleSlope'):
            try:
                slope = float(getattr(self.current_dicom, 'RescaleSlope', 1.0))
                intercept = float(getattr(self.current_dicom, 'RescaleIntercept', 0.0))
                data = data * slope + intercept
            except:
                pass
        
        # Apply window/level
        min_val = self.window_level - self.window_width / 2
        max_val = self.window_level + self.window_width / 2
        
        # Enhanced windowing for X-ray images
        modality = getattr(self.current_dicom, 'Modality', '') if self.current_dicom else ''
        if modality.upper() in ['CR', 'DX', 'DR']:
            # Apply X-ray specific enhancements
            data = self.enhance_xray_image(data)
        
        # Clip and normalize
        data = np.clip(data, min_val, max_val)
        if max_val > min_val:
            data = (data - min_val) / (max_val - min_val) * 255
        else:
            data = np.zeros_like(data)
        
        return data.astype(np.uint8)

    def enhance_xray_image(self, image_data):
        """Enhanced X-ray image processing"""
        try:
            enhanced = image_data.copy()
            
            # Apply contrast stretching
            p2, p98 = np.percentile(enhanced, (2, 98))
            if p98 > p2:
                enhanced = np.clip((enhanced - p2) / (p98 - p2), 0, 1)
                enhanced = enhanced * (image_data.max() - image_data.min()) + image_data.min()
            
            # Apply mild smoothing if scipy is available
            if SCIPY_AVAILABLE:
                enhanced = gaussian_filter(enhanced, sigma=0.5)
            
            logger.info("Applied X-ray enhancement")
            return enhanced
            
        except Exception as e:
            logger.warning(f"X-ray enhancement failed: {e}")
            return image_data

    def draw_measurements(self):
        """Draw measurement overlays"""
        if not MATPLOTLIB_AVAILABLE:
            return
            
        for measurement in self.measurements:
            start = measurement['start']
            end = measurement['end']
            
            # Convert screen coordinates to data coordinates
            try:
                inv = self.canvas.ax.transData.inverted()
                start_data = inv.transform(start)
                end_data = inv.transform(end)
                
                x_data = [start_data[0], end_data[0]]
                y_data = [start_data[1], end_data[1]]
                
                self.canvas.ax.plot(x_data, y_data, 'r-', linewidth=2)
                
                # Calculate distance
                distance = np.sqrt((x_data[1] - x_data[0])**2 + (y_data[1] - y_data[0])**2)
                distance_text = f"{distance:.1f} px"
                
                # Convert to real units if pixel spacing available
                if (self.current_dicom and hasattr(self.current_dicom, 'PixelSpacing')):
                    try:
                        pixel_spacing = self.current_dicom.PixelSpacing
                        if len(pixel_spacing) >= 2:
                            avg_spacing = (float(pixel_spacing[0]) + float(pixel_spacing[1])) / 2
                            distance_mm = distance * avg_spacing
                            distance_text = f"{distance_mm:.1f} mm"
                    except:
                        pass
                
                # Add text
                mid_x = (x_data[0] + x_data[1]) / 2
                mid_y = (y_data[0] + y_data[1]) / 2
                self.canvas.ax.text(mid_x, mid_y, distance_text, color='red', 
                                  fontsize=10, ha='center', va='center',
                                  bbox=dict(boxstyle="round,pad=0.3", facecolor='black', alpha=0.7))
            except:
                pass
        
        # Draw current measurement
        if self.current_measurement:
            start = self.current_measurement['start']
            end = self.current_measurement['end']
            
            try:
                inv = self.canvas.ax.transData.inverted()
                start_data = inv.transform(start)
                end_data = inv.transform(end)
                
                x_data = [start_data[0], end_data[0]]
                y_data = [start_data[1], end_data[1]]
                
                self.canvas.ax.plot(x_data, y_data, 'y--', linewidth=2, alpha=0.7)
            except:
                pass

    def draw_annotations(self):
        """Draw annotation overlays"""
        if not MATPLOTLIB_AVAILABLE:
            return
            
        for annotation in self.annotations:
            pos = annotation['pos']
            text = annotation['text']
            
            try:
                inv = self.canvas.ax.transData.inverted()
                data_pos = inv.transform(pos)
                
                self.canvas.ax.text(data_pos[0], data_pos[1], text, color='yellow', 
                                  fontsize=12, ha='left', va='bottom',
                                  bbox=dict(boxstyle="round,pad=0.5", facecolor='black', alpha=0.8))
            except:
                pass

    def draw_crosshair(self):
        """Draw crosshair overlay"""
        if not MATPLOTLIB_AVAILABLE or self.current_image_data is None:
            return
            
        height, width = self.current_image_data.shape
        center_x = width // 2
        center_y = height // 2
        
        self.canvas.ax.axvline(x=center_x, color='cyan', linewidth=1, alpha=0.7)
        self.canvas.ax.axhline(y=center_y, color='cyan', linewidth=1, alpha=0.7)

    def reset_view(self):
        """Reset view to default"""
        self.zoom_factor = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.zoom_slider.setValue(100)
        self.update_display()
        self.status_bar.showMessage("View reset", 2000)

    def resizeEvent(self, event):
        """Handle window resize"""
        super().resizeEvent(event)
        # Trigger display update after resize
        QTimer.singleShot(100, self.update_display)


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
    app.setApplicationVersion("2.0")

    # Set application icon if available
    try:
        app.setWindowIcon(QIcon('icon.png'))
    except:
        pass

    viewer = ProfessionalDicomViewer()
    viewer.show()

    # Load initial path if provided
    if args.path:
        if os.path.exists(args.path):
            if os.path.isfile(args.path):
                viewer._load_dicom_paths([args.path])
            elif os.path.isdir(args.path):
                viewer.load_dicom_folder()
        else:
            logger.warning(f"Path does not exist: {args.path}")

    # Show startup message
    logger.info("Professional DICOM Viewer started successfully")
    viewer.status_bar.showMessage("Professional DICOM Viewer - Ready for medical imaging", 5000)

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()