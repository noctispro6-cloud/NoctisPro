#!/usr/bin/env python3
"""
Noctis Pro - Python DICOM Viewer Launcher
=========================================

This script launches the Python (PyQt5) standalone DICOM viewer application.

Usage:
    python tools/launch_dicom_viewer.py [options] [dicom_file_or_directory]

Examples:
    python tools/launch_dicom_viewer.py
    python tools/launch_dicom_viewer.py /path/to/dicom/files/
    python tools/launch_dicom_viewer.py study.dcm
    python tools/launch_dicom_viewer.py --study-id 123
    python tools/launch_dicom_viewer.py --debug
"""

import sys
import os
import argparse
import subprocess

# Add the project root to the Python path
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)


def main():
    parser = argparse.ArgumentParser(
        description='Launch the Noctis Pro Python DICOM Viewer',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('path', nargs='?', help='Path to DICOM file or directory to open')
    parser.add_argument('--study-id', type=int, help='Database study ID to load (optional)')
    parser.add_argument('--debug', action='store_true', help='Enable debug mode')

    args = parser.parse_args()

    # Path to the Python viewer script
    python_viewer_path = os.path.join(project_root, 'tools', 'python_viewer.py')
    if not os.path.exists(python_viewer_path):
        print('Error: Python viewer script not found at tools/python_viewer.py')
        sys.exit(1)

    env = os.environ.copy()
    # Provide base URL env for potential backend integration (optional)
    env.setdefault('DICOM_VIEWER_BASE_URL', 'http://127.0.0.1:8000/viewer')

    argv = [sys.executable, python_viewer_path]
    if args.path:
        argv += ['--path', args.path]
    if args.study_id is not None:
        argv += ['--study-id', str(args.study_id)]

    if args.debug:
        print(f"Launching Python viewer: {' '.join(argv)}")
        print(f"Using base URL: {env['DICOM_VIEWER_BASE_URL']}")

    try:
        # Spawn the GUI in a separate process and return immediately
        subprocess.Popen(argv, env=env, cwd=os.path.dirname(python_viewer_path))
        return
    except Exception as e:
        print(f"Failed to launch Python viewer: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()