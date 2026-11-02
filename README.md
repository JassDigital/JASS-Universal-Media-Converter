# JASS Universal Media Converter

**Version:** 1.0.1  
**Platform:** Windows 10/11 (source is cross-platform)  
**UI:** PySide6 | **Media engine:** FFmpeg / FFprobe

A standalone desktop application for video/audio conversion, image conversion, resizing, trimming, speed changes, compression and batch jobs. It does not depend on or modify any other JASS application.

## Features in this build

- Video output: MP4, MKV, MOV, AVI, WebM, TS
- Audio output: MP3, M4A, AAC, WAV, FLAC, OGG, Opus
- Image output: JPG, PNG, WebP, TIFF, BMP
- Video codecs: H.264, H.265/HEVC, VP9, AV1 (availability depends on FFmpeg build)
- Resolution presets: 4K, 1440p, 1080p, 720p, 480p and custom dimensions
- Fit/pad, crop-to-fill and stretch modes; portrait, landscape, square and 4:3 canvases
- Frame rate selection: 24/25/30/50/60
- Quality presets, audio bitrate, mute, trim and playback speed
- Target file-size encoding with calculated bitrate and automatic two-pass H.264/H.265 encoding
- Live target-size estimate, source/output size comparison and post-conversion savings summary
- Video is the default conversion category
- Batch queue, progress, cancellation request, conversion history
- Configurable FFmpeg and FFprobe executable paths
- Image conversion and resizing through Pillow

## Requirements

- Python 3.10 or newer
- FFmpeg and FFprobe installed and available on PATH, or their executable paths configured in the app
- Windows: install Python from python.org and enable the Python launcher (`py`)

## Run on Windows

1. Install FFmpeg. Download a trusted Windows build and ensure `ffmpeg.exe` and `ffprobe.exe` are available.
2. Extract this project folder.
3. Double-click `run_windows.bat`.

The first run installs Python dependencies. No virtual environment is created.

## Build a Windows executable

Run `build_windows.bat`. PyInstaller output will be created in `dist/`. FFmpeg is a separate dependency and is not bundled by this build.

## Target file-size mode

Target size is a bitrate target, not a hard mathematical guarantee. The application reserves a small amount for container overhead, subtracts the selected audio bitrate, and runs two-pass encoding for H.264/H.265. Actual size can differ due to container metadata, audio duration, stream characteristics and encoder behavior. Very small targets may be rejected when the resulting video bitrate would be impractically low.

For best results:
- Use MP4 + H.264 for broad compatibility.
- Select an audio bitrate appropriate to the content.
- Keep the target size realistic for duration and resolution.
- Do not expect a tiny file to retain source-level detail.

## Important limitations in v1.0

- Target-size mode supports H.264/H.265 only.
- Hardware encoding is not yet exposed in the UI; CPU encoding is supported.
- Batch queue uses the current conversion settings for each queued job; add each job after configuring its source and settings.
- The image converter currently resizes proportionally (thumbnail/fit) and does not implement image cropping.
- The current history table records output/result; source path may be blank in this first build.
- Some codec/container combinations depend on the installed FFmpeg build.

## Project structure

```text
JASS-Universal-Media-Converter/
├── main.py
├── jass_media_converter/
│   ├── __init__.py
│   ├── engine.py
│   └── history.py
├── requirements.txt
├── run_windows.bat
├── run_linux.sh
├── build_windows.bat
└── README.md
```

## Safety

- Source and output paths are checked to prevent direct self-overwrite.
- Existing output files are not overwritten unless explicitly enabled.
- Conversion runs in a worker thread so the UI remains responsive.
- Cancel requests terminate the FFmpeg process.
