# Noctis Pro - Standalone Tools

This directory contains standalone desktop applications that complement the web-based Noctis Pro system.

## Standalone DICOM Viewer (C++ Qt)

### Overview

The Standalone DICOM Viewer is a Qt-based desktop application that provides enhanced DICOM viewing capabilities. It offers:

- **Advanced Image Manipulation**: Windowing, zooming, panning
- **Measurement Tools**: Distance measurements
- **Enhanced Display Options**: Multiple window presets (lung, bone, soft tissue, brain, etc.)
- **Multi-series Support**: Navigate through multiple DICOM series
- **Database Integration**: Optional access to Noctis Pro studies

### Build (C++)

1. Ensure Qt6 and CMake are installed
2. Build the viewer:
   ```bash
   cd cpp_viewer
   cmake -S . -B build
   cmake --build build --config Release
   ```

### Usage

- Launch with study ID (database):
  ```bash
  python tools/launch_dicom_viewer.py --study-id 123
  ```
- Launch with DICOM files:
  ```bash
  python tools/launch_dicom_viewer.py /path/to/dicom/files/
  ```
- Debug mode:
  ```bash
  python tools/launch_dicom_viewer.py --debug
  ```

The launcher requires the built binary at `cpp_viewer/build/DicomViewer` (or platform equivalent). It sets `DICOM_VIEWER_BASE_URL` for API compatibility.

### Technical Requirements

- Qt 6 (Widgets, Network)
- CMake 3.20+
- Optional: DCMTK for native DICOM handling (compile-time flag)

### Integration with Noctis Pro

The desktop viewer integrates with the main system through lightweight REST endpoints in `dicom_viewer/api_cpp.py`:
- `/viewer/api/worklist/`
- `/viewer/api/series/<study_uid>/`
- `/viewer/api/dicom-file/<sop_instance_uid>/`
- `/viewer/api/dicom-info/<sop_instance_uid>/`
- `/viewer/api/viewer-sessions/`

### Troubleshooting

- If the launcher reports the C++ binary is missing, build it under `cpp_viewer/build`.
- Ensure the server is running locally (default `http://localhost:8000`). If you run Docker with a different host port (e.g. `WEB_PORT=8001`), set `DICOM_VIEWER_BASE_URL` accordingly.

### File Structure
```
tools/
├── launch_dicom_viewer.py         # Launcher script (C++ only)
└── README.md                      # This documentation
```