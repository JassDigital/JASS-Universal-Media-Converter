import sys, os, json, shutil, subprocess, time
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction, QFont
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFileDialog, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox,
    QCheckBox, QProgressBar, QTableWidget, QTableWidgetItem, QMessageBox,
    QTabWidget, QGroupBox, QFormLayout, QPlainTextEdit, QHeaderView, QAbstractItemView
)
from jass_media_converter.engine import MediaEngine, ConversionOptions, probe_media
from jass_media_converter.history import HistoryStore

APP_NAME = "JASS Universal Media Converter"
APP_VERSION = "1.0.1"

@dataclass
class Job:
    source: str
    output: str
    options: ConversionOptions

class ConversionWorker(QThread):
    progress = Signal(int, str)
    log = Signal(str)
    completed = Signal(bool, str, str)
    def __init__(self, job: Job, ffmpeg="ffmpeg", ffprobe="ffprobe"):
        super().__init__()
        self.job = job
        self.engine = MediaEngine(ffmpeg=ffmpeg, ffprobe=ffprobe)
    def run(self):
        try:
            self.engine.convert(
                self.job.source, self.job.output, self.job.options,
                progress_callback=lambda p, msg: self.progress.emit(p, msg),
                log_callback=self.log.emit,
                cancel_check=self.isInterruptionRequested
            )
            self.completed.emit(True, self.job.output, "Conversion completed.")
        except Exception as exc:
            self.completed.emit(False, self.job.output, str(exc))

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME}  |  v{APP_VERSION}")
        self.resize(1180, 780)
        self.setMinimumSize(950, 650)
        self.history = HistoryStore()
        self.queue = []
        self.worker = None
        self.current_row = None
        self.source_duration = 0
        self.source_size_mb = 0
        self._build_ui()
        self._style()
        self.refresh_history()
        self.check_tools()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        header = QHBoxLayout()
        title = QLabel("JASS UNIVERSAL MEDIA CONVERTER")
        title.setObjectName("brand")
        subtitle = QLabel("Convert • Compress • Resize • Batch process")
        subtitle.setObjectName("subtitle")
        brandbox = QVBoxLayout()
        brandbox.addWidget(title); brandbox.addWidget(subtitle)
        header.addLayout(brandbox); header.addStretch()
        self.tool_status = QLabel("Checking FFmpeg…")
        self.tool_status.setObjectName("status")
        header.addWidget(self.tool_status)
        outer.addLayout(header)

        self.tabs = QTabWidget()
        outer.addWidget(self.tabs, 1)
        self.tabs.addTab(self._build_convert_tab(), "Converter")
        self.tabs.addTab(self._build_queue_tab(), "Batch Queue")
        self.tabs.addTab(self._build_history_tab(), "History")
        self.tabs.addTab(self._build_tools_tab(), "Settings & Tools")

        self.statusbar = self.statusBar()
        self.statusbar.showMessage("Ready")

    def _build_convert_tab(self):
        w = QWidget(); layout = QVBoxLayout(w)
        source_box = QGroupBox("Source and destination")
        grid = QGridLayout(source_box)
        self.source_edit = QLineEdit(); self.source_edit.setPlaceholderText("Choose a video, audio or image file…")
        browse = QPushButton("Browse…"); browse.clicked.connect(self.choose_source)
        self.output_edit = QLineEdit(); self.output_edit.setPlaceholderText("Output folder (defaults to source folder)")
        outbrowse = QPushButton("Folder…"); outbrowse.clicked.connect(self.choose_output_folder)
        grid.addWidget(QLabel("Input file"),0,0); grid.addWidget(self.source_edit,0,1); grid.addWidget(browse,0,2)
        grid.addWidget(QLabel("Output folder"),1,0); grid.addWidget(self.output_edit,1,1); grid.addWidget(outbrowse,1,2)
        layout.addWidget(source_box)

        self.info_label = QLabel("Media details will appear here after selecting a source.")
        self.info_label.setWordWrap(True); self.info_label.setObjectName("info")
        layout.addWidget(self.info_label)
        self.estimate_label = QLabel("Estimated output size: select a source file to begin.")
        self.estimate_label.setWordWrap(True); self.estimate_label.setObjectName("estimate")
        layout.addWidget(self.estimate_label)

        settings = QGroupBox("Conversion settings")
        form = QGridLayout(settings)
        self.category = QComboBox(); self.category.addItems(["Video", "Audio only", "Image"]); self.category.setCurrentText("Video")
        self.format_box = QComboBox()
        self.codec_box = QComboBox()
        self.resolution = QComboBox()
        self.resolution.addItems(["Keep original", "3840x2160 (4K)", "2560x1440 (1440p)", "1920x1080 (1080p)", "1280x720 (720p)", "854x480 (480p)", "Custom"])
        self.custom_w = QSpinBox(); self.custom_w.setRange(16, 7680); self.custom_w.setValue(1920)
        self.custom_h = QSpinBox(); self.custom_h.setRange(16, 4320); self.custom_h.setValue(1080)
        self.aspect = QComboBox(); self.aspect.addItems(["Preserve / fit", "Crop to fill", "Stretch", "16:9", "9:16", "1:1", "4:3"])
        self.fps = QComboBox(); self.fps.addItems(["Keep original", "24", "25", "30", "50", "60"])
        self.quality = QComboBox(); self.quality.addItems(["High quality", "Balanced", "Smaller file", "Fast encode"])
        self.audio_bitrate = QComboBox(); self.audio_bitrate.addItems(["96k", "128k", "160k", "192k", "256k", "320k"])
        self.target_enable = QCheckBox("Target output size")
        self.target_size = QDoubleSpinBox(); self.target_size.setRange(0.1, 100000); self.target_size.setDecimals(1); self.target_size.setValue(50); self.target_size.setSuffix(" MB")
        self.two_pass = QCheckBox("Use two-pass encoding (more accurate size)")
        self.mute = QCheckBox("Remove audio")
        self.overwrite = QCheckBox("Overwrite existing output")
        self.overwrite.setChecked(False)
        self.trim_start = QLineEdit("0"); self.trim_start.setPlaceholderText("HH:MM:SS")
        self.trim_end = QLineEdit(); self.trim_end.setPlaceholderText("Optional HH:MM:SS")
        self.speed = QComboBox(); self.speed.addItems(["0.25x","0.5x","0.75x","1x","1.25x","1.5x","2x","3x","5x"]); self.speed.setCurrentText("1x")
        self.output_name = QLineEdit(); self.output_name.setPlaceholderText("Optional output filename (without extension)")
        rows = [
            ("Type",self.category,"Format",self.format_box),
            ("Video codec",self.codec_box,"Resolution",self.resolution),
            ("Custom width",self.custom_w,"Custom height",self.custom_h),
            ("Aspect handling",self.aspect,"Frame rate",self.fps),
            ("Quality preset",self.quality,"Audio bitrate",self.audio_bitrate),
            ("Target size",self.target_enable,"Size",self.target_size),
            ("Trim start",self.trim_start,"Trim end",self.trim_end),
            ("Playback speed",self.speed,"Output name",self.output_name),
        ]
        for r,row in enumerate(rows):
            form.addWidget(QLabel(row[0]),r,0); form.addWidget(row[1],r,1)
            form.addWidget(QLabel(row[2]),r,2); form.addWidget(row[3],r,3)
        form.addWidget(self.two_pass,8,0,1,2)
        form.addWidget(self.mute,8,2)
        form.addWidget(self.overwrite,9,0,1,2)
        layout.addWidget(settings)
        self.category.currentTextChanged.connect(self.update_formats)
        self.update_formats()
        self.resolution.currentTextChanged.connect(self.toggle_custom_resolution)
        self.toggle_custom_resolution()
        self.target_enable.toggled.connect(self.update_estimate)
        self.target_size.valueChanged.connect(self.update_estimate)
        self.audio_bitrate.currentTextChanged.connect(self.update_estimate)
        self.category.currentTextChanged.connect(self.update_estimate)
        self.resolution.currentTextChanged.connect(self.update_estimate)
        self.two_pass.setText("Two-pass encoding (automatic for target-size mode)")
        self.two_pass.setChecked(True)
        self.two_pass.setEnabled(False)

        controls = QHBoxLayout()
        self.add_btn = QPushButton("Add to queue"); self.add_btn.clicked.connect(self.add_to_queue)
        self.convert_btn = QPushButton("Convert now"); self.convert_btn.clicked.connect(self.convert_now)
        self.cancel_btn = QPushButton("Cancel"); self.cancel_btn.clicked.connect(self.cancel_current); self.cancel_btn.setEnabled(False)
        controls.addWidget(self.add_btn); controls.addWidget(self.convert_btn); controls.addWidget(self.cancel_btn); controls.addStretch()
        layout.addLayout(controls)
        self.progress = QProgressBar(); self.progress.setValue(0)
        layout.addWidget(self.progress)
        self.log_view = QPlainTextEdit(); self.log_view.setReadOnly(True); self.log_view.setMaximumBlockCount(1000); self.log_view.setMaximumHeight(110)
        layout.addWidget(self.log_view)
        return w

    def _build_queue_tab(self):
        w=QWidget(); l=QVBoxLayout(w)
        self.queue_table=QTableWidget(0,4); self.queue_table.setHorizontalHeaderLabels(["Input","Output","Status","Progress"])
        self.queue_table.horizontalHeader().setSectionResizeMode(0,QHeaderView.Stretch)
        self.queue_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        self.queue_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        l.addWidget(self.queue_table)
        row=QHBoxLayout()
        add=QPushButton("Add current settings"); add.clicked.connect(self.add_to_queue)
        run=QPushButton("Run queue"); run.clicked.connect(self.run_queue)
        remove=QPushButton("Remove selected"); remove.clicked.connect(self.remove_selected)
        clear=QPushButton("Clear queue"); clear.clicked.connect(self.clear_queue)
        for b in (add,run,remove,clear): row.addWidget(b)
        l.addLayout(row)
        return w

    def _build_history_tab(self):
        w=QWidget(); l=QVBoxLayout(w)
        self.history_table=QTableWidget(0,4); self.history_table.setHorizontalHeaderLabels(["Date","Source","Output","Result"])
        self.history_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        self.history_table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
        l.addWidget(self.history_table)
        b=QPushButton("Refresh history"); b.clicked.connect(self.refresh_history); l.addWidget(b,alignment=Qt.AlignRight)
        return w

    def _build_tools_tab(self):
        w=QWidget(); l=QVBoxLayout(w)
        box=QGroupBox("External tools"); f=QFormLayout(box)
        self.ffmpeg_path=QLineEdit(shutil.which("ffmpeg") or "")
        self.ffprobe_path=QLineEdit(shutil.which("ffprobe") or "")
        b1=QPushButton("Browse…"); b1.clicked.connect(lambda: self.pick_tool(self.ffmpeg_path))
        b2=QPushButton("Browse…"); b2.clicked.connect(lambda: self.pick_tool(self.ffprobe_path))
        r1=QHBoxLayout(); r1.addWidget(self.ffmpeg_path); r1.addWidget(b1)
        r2=QHBoxLayout(); r2.addWidget(self.ffprobe_path); r2.addWidget(b2)
        f.addRow("FFmpeg executable",r1); f.addRow("FFprobe executable",r2)
        save=QPushButton("Save tool paths"); save.clicked.connect(self.save_tool_paths)
        test=QPushButton("Test installation"); test.clicked.connect(self.check_tools)
        l.addWidget(box); l.addWidget(save,alignment=Qt.AlignLeft); l.addWidget(test,alignment=Qt.AlignLeft)
        note=QLabel("FFmpeg and FFprobe are required for video/audio conversion. Pillow is included for image conversion. Install FFmpeg from ffmpeg.org or use the bundled Windows setup instructions.")
        note.setWordWrap(True); note.setObjectName("info"); l.addWidget(note)
        l.addStretch()
        return w

    def _style(self):
        self.setStyleSheet("""
        QMainWindow, QWidget { background:#171b24; color:#e7eaf0; font-size:13px; }
        QTabWidget::pane { border:1px solid #343b49; border-radius:8px; }
        QTabBar::tab { background:#222938; padding:10px 18px; margin-right:3px; border-top-left-radius:6px; border-top-right-radius:6px; }
        QTabBar::tab:selected { background:#35435b; color:white; }
        QGroupBox { border:1px solid #394354; border-radius:8px; margin-top:10px; padding:12px; font-weight:600; }
        QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; }
        QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QPlainTextEdit, QTableWidget { background:#222938; border:1px solid #3a4558; border-radius:5px; padding:7px; min-height:22px; selection-background-color:#42618c; }
        QComboBox QAbstractItemView { background:#222938; selection-background-color:#42618c; padding:4px; }
        QPushButton { background:#304b70; border:1px solid #49678e; border-radius:6px; padding:9px 15px; font-weight:600; }
        QPushButton:hover { background:#3b5e8c; } QPushButton:disabled { background:#303642; color:#818894; }
        QProgressBar { border:1px solid #3a4558; border-radius:5px; text-align:center; background:#222938; height:18px; }
        QProgressBar::chunk { background:#4c9b78; border-radius:4px; }
        QLabel#brand { font-size:22px; font-weight:800; letter-spacing:1px; color:#f2f5fa; }
        QLabel#subtitle { color:#9eabc0; } QLabel#status { color:#9fd8b4; padding:8px; }
        QLabel#info { background:#202a39; border:1px solid #36445a; border-radius:6px; padding:8px; color:#b8c6d9; }
        QLabel#estimate { background:#1f332d; border:1px solid #38644f; border-radius:6px; padding:8px; color:#b9e4cf; }
        QHeaderView::section { background:#2a3445; padding:7px; border:0; }
        """)
    def update_formats(self):
        category=self.category.currentText()
        self.format_box.clear(); self.codec_box.clear()
        if category=="Video":
            self.format_box.addItems(["mp4","mkv","mov","avi","webm","ts"])
            self.codec_box.addItems(["H.264 (libx264)","H.265 / HEVC (libx265)","VP9","AV1 (libaom-av1)"])
        elif category=="Audio only":
            self.format_box.addItems(["mp3","m4a","aac","wav","flac","ogg","opus"])
            self.codec_box.addItems(["Automatic"])
        else:
            self.format_box.addItems(["jpg","png","webp","tiff","bmp"])
            self.codec_box.addItems(["Pillow default"])
        self.target_enable.setEnabled(category=="Video")
        self.mute.setEnabled(category=="Video")
    def toggle_custom_resolution(self):
        custom=self.resolution.currentText()=="Custom"
        self.custom_w.setEnabled(custom); self.custom_h.setEnabled(custom)
    def choose_source(self):
        path,_=QFileDialog.getOpenFileName(self,"Select media file","", "Media files (*.mp4 *.mkv *.avi *.mov *.webm *.flv *.mp3 *.wav *.m4a *.flac *.jpg *.jpeg *.png *.webp *.tif *.tiff *.bmp);;All files (*)")
        if path:
            self.source_edit.setText(path); self.inspect_source(path)
    def inspect_source(self,path):
        try:
            info=probe_media(path, self.get_tool("ffprobe"))
            streams=info.get("streams",[])
            v=next((s for s in streams if s.get("codec_type")=="video"),{})
            a=next((s for s in streams if s.get("codec_type")=="audio"),{})
            dur=float(info.get("format",{}).get("duration",0) or 0)
            size=os.path.getsize(path)/1048576
            self.source_duration = dur
            self.source_size_mb = size
            self.info_label.setText(f"{Path(path).name}  •  {size:.1f} MB  •  {dur/60:.2f} min  •  {v.get('width','—')}×{v.get('height','—')}  •  Video: {v.get('codec_name','—')}  •  Audio: {a.get('codec_name','—')}")
            self.update_estimate()
        except Exception as e:
            self.source_duration = 0
            self.source_size_mb = 0
            self.info_label.setText(f"Could not inspect media: {e}")
            self.update_estimate()
    def update_estimate(self, *_):
        if not hasattr(self, "estimate_label"):
            return
        if not self.source_edit.text().strip():
            self.estimate_label.setText("Estimated output size: select a source file to begin.")
            return
        if self.target_enable.isChecked() and self.category.currentText() == "Video":
            target = self.target_size.value()
            source = getattr(self, "source_size_mb", 0)
            reduction = ((1 - target/source) * 100) if source > 0 else 0
            detail = f"Original: {source:.1f} MB  •  Expected reduction: {reduction:.1f}%" if source > 0 else "Original size unavailable"
            self.estimate_label.setText(
                f"Target output: approximately {target:.1f} MB  •  {detail}  •  "
                "Two-pass bitrate encoding will be used; actual size may vary slightly."
            )
        else:
            self.estimate_label.setText(
                "Estimated output size depends on codec, resolution, duration and content. "
                "Enable Target output size for a bitrate-based estimate."
            )

    def choose_output_folder(self):
        folder=QFileDialog.getExistingDirectory(self,"Select output folder")
        if folder: self.output_edit.setText(folder)
    def pick_tool(self,edit):
        p,_=QFileDialog.getOpenFileName(self,"Select executable")
        if p: edit.setText(p)
    def get_tool(self,name):
        cfg=self.load_config()
        return cfg.get(name) or (self.ffmpeg_path.text().strip() if name=="ffmpeg" else self.ffprobe_path.text().strip()) or name
    def config_path(self):
        base=Path(os.getenv("APPDATA",str(Path.home()))) / "JASS" / "UniversalMediaConverter"
        base.mkdir(parents=True,exist_ok=True)
        return base/"settings.json"
    def load_config(self):
        try: return json.loads(self.config_path().read_text(encoding="utf-8"))
        except Exception: return {}
    def save_tool_paths(self):
        cfg=self.load_config(); cfg["ffmpeg"]=self.ffmpeg_path.text().strip(); cfg["ffprobe"]=self.ffprobe_path.text().strip()
        self.config_path().write_text(json.dumps(cfg,indent=2),encoding="utf-8")
        QMessageBox.information(self,"Settings saved","Tool paths saved.")
        self.check_tools()
    def check_tools(self):
        ff=self.get_tool("ffmpeg"); fp=self.get_tool("ffprobe")
        try:
            a=subprocess.run([ff,"-version"],capture_output=True,text=True,timeout=5)
            b=subprocess.run([fp,"-version"],capture_output=True,text=True,timeout=5)
            if a.returncode==0 and b.returncode==0:
                self.tool_status.setText("FFmpeg ready"); self.statusbar.showMessage("FFmpeg and FFprobe detected.")
            else: raise RuntimeError("Version check failed")
        except Exception:
            self.tool_status.setText("FFmpeg not configured")
            self.statusbar.showMessage("Install FFmpeg and FFprobe, then set their paths in Settings & Tools.")
    def build_job(self,source=None):
        src=source or self.source_edit.text().strip()
        if not src or not Path(src).is_file(): raise ValueError("Choose an existing input file.")
        category=self.category.currentText(); fmt=self.format_box.currentText()
        outdir=Path(self.output_edit.text().strip() or Path(src).parent)
        outdir.mkdir(parents=True,exist_ok=True)
        stem=self.output_name.text().strip() or Path(src).stem+"_converted"
        output=str(outdir/f"{stem}.{fmt}")
        opts=ConversionOptions(
            category=category.lower().replace(" only",""),
            output_format=fmt,
            video_codec=self.codec_box.currentText(),
            resolution=self.resolution.currentText(),
            custom_width=self.custom_w.value(), custom_height=self.custom_h.value(),
            aspect=self.aspect.currentText(), fps=self.fps.currentText(),
            quality=self.quality.currentText(), audio_bitrate=self.audio_bitrate.currentText(),
            target_size_mb=self.target_size.value() if self.target_enable.isChecked() else None,
            two_pass=self.two_pass.isChecked(), mute=self.mute.isChecked(),
            overwrite=self.overwrite.isChecked(), trim_start=self.trim_start.text().strip(),
            trim_end=self.trim_end.text().strip(), speed=self.speed.currentText()
        )
        if Path(src).resolve()==Path(output).resolve(): raise ValueError("Output cannot overwrite the source file.")
        if Path(output).exists() and not opts.overwrite:
            output=str(outdir/f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}.{fmt}")
        return Job(src,output,opts)
    def add_to_queue(self):
        try: job=self.build_job()
        except Exception as e: QMessageBox.warning(self,"Cannot add job",str(e)); return
        self.queue.append(job); row=self.queue_table.rowCount(); self.queue_table.insertRow(row)
        for col,val in enumerate([job.source,job.output,"Queued","0%"]): self.queue_table.setItem(row,col,QTableWidgetItem(val))
        self.statusbar.showMessage(f"Added {Path(job.source).name} to queue.")
    def convert_now(self):
        if self.worker and self.worker.isRunning(): return
        try: job=self.build_job()
        except Exception as e: QMessageBox.warning(self,"Cannot convert",str(e)); return
        self.start_job(job,None)
    def run_queue(self):
        if self.worker and self.worker.isRunning(): return
        if not self.queue: QMessageBox.information(self,"Queue empty","Add one or more jobs first."); return
        self.process_next_queue()
    def process_next_queue(self):
        if not self.queue: self.statusbar.showMessage("Queue completed."); return
        job=self.queue.pop(0)
        row=None
        for i in range(self.queue_table.rowCount()):
            if self.queue_table.item(i,1) and self.queue_table.item(i,1).text()==job.output:
                row=i; break
        self.start_job(job,row,continue_queue=True)
    def start_job(self,job,row,continue_queue=False):
        self.current_row=row; self.progress.setValue(0); self.log_view.clear()
        self.convert_btn.setEnabled(False); self.cancel_btn.setEnabled(True)
        if row is not None: self.queue_table.setItem(row,2,QTableWidgetItem("Running"))
        self.worker=ConversionWorker(job, self.get_tool("ffmpeg"), self.get_tool("ffprobe"))
        self.worker.progress.connect(self.on_progress); self.worker.log.connect(self.append_log)
        self.worker.completed.connect(lambda ok,out,msg: self.on_completed(ok,out,msg,continue_queue))
        self.worker.start()
    def on_progress(self,p,msg):
        self.progress.setValue(p); self.statusbar.showMessage(msg)
        if self.current_row is not None: self.queue_table.setItem(self.current_row,3,QTableWidgetItem(f"{p}%"))
    def append_log(self,msg): self.log_view.appendPlainText(msg)
    def on_completed(self,ok,out,msg,continue_queue):
        self.convert_btn.setEnabled(True); self.cancel_btn.setEnabled(False)
        self.append_log(msg)
        if ok:
            try:
                src = self.worker.job.source if self.worker else ""
                source_bytes = Path(src).stat().st_size if src and Path(src).exists() else 0
                output_bytes = Path(out).stat().st_size if Path(out).exists() else 0
                if source_bytes and output_bytes:
                    saved = source_bytes - output_bytes
                    pct = abs(saved) / source_bytes * 100
                    summary = (
                        f"\\n\\nConversion summary:\\n"
                        f"Original: {source_bytes/1048576:.2f} MB\\n"
                        f"Output: {output_bytes/1048576:.2f} MB\\n"
                        f"{'Saved' if saved >= 0 else 'Size increase'}: {abs(saved)/1048576:.2f} MB ({pct:.1f}%)"
                    )
                    msg += summary
                    self.append_log(summary)
            except Exception:
                pass
        if self.current_row is not None:
            self.queue_table.setItem(self.current_row,2,QTableWidgetItem("Completed" if ok else "Failed"))
        self.history.add(self.worker.job.source if self.worker else "", out, ok, msg)
        self.refresh_history()
        QMessageBox.information(self,"Conversion complete" if ok else "Conversion failed",msg+(f"\n\nOutput: {out}" if ok else ""))
        self.current_row=None
        if continue_queue: self.process_next_queue()
    def cancel_current(self):
        if self.worker and self.worker.isRunning():
            self.worker.requestInterruption(); self.append_log("Cancellation requested…")
    def remove_selected(self):
        rows=sorted({i.row() for i in self.queue_table.selectedIndexes()},reverse=True)
        for r in rows:
            out=self.queue_table.item(r,1).text() if self.queue_table.item(r,1) else ""
            self.queue=[j for j in self.queue if j.output!=out]
            self.queue_table.removeRow(r)
    def clear_queue(self):
        if self.worker and self.worker.isRunning(): QMessageBox.warning(self,"Busy","Cancel the active conversion before clearing the queue."); return
        self.queue.clear(); self.queue_table.setRowCount(0)
    def refresh_history(self):
        if not hasattr(self,"history_table"): return
        rows=self.history.list()
        self.history_table.setRowCount(0)
        for item in rows:
            r=self.history_table.rowCount(); self.history_table.insertRow(r)
            vals=[item["created_at"],item["source"],item["output"],item["result"]]
            for c,v in enumerate(vals): self.history_table.setItem(r,c,QTableWidgetItem(str(v)))
    def closeEvent(self,event):
        if self.worker and self.worker.isRunning():
            reply=QMessageBox.question(self,"Conversion running","A conversion is still running. Request cancellation and exit?")
            if reply!=QMessageBox.Yes: event.ignore(); return
            self.worker.requestInterruption(); self.worker.wait(3000)
        event.accept()

def main():
    app=QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setFont(QFont("Segoe UI",10))
    window=MainWindow(); window.show()
    sys.exit(app.exec())

if __name__=="__main__": main()
