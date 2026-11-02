import os, re, json, shutil, subprocess, tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

def _which(executable):
    if os.path.isfile(executable): return executable
    return shutil.which(executable)

def probe_media(path, ffprobe="ffprobe"):
    exe=_which(ffprobe)
    if not exe: raise RuntimeError("FFprobe not found. Configure its path in Settings & Tools.")
    cmd=[exe,"-v","error","-show_format","-show_streams","-of","json",str(path)]
    p=subprocess.run(cmd,capture_output=True,text=True)
    if p.returncode: raise RuntimeError(p.stderr.strip() or "FFprobe could not read this file.")
    return json.loads(p.stdout)

def parse_duration(value):
    if not value: return 0.0
    if re.fullmatch(r"\d+(\.\d+)?",value): return float(value)
    parts=value.split(":")
    try:
        parts=[float(x) for x in parts]
        if len(parts)==3: return parts[0]*3600+parts[1]*60+parts[2]
        if len(parts)==2: return parts[0]*60+parts[1]
    except ValueError: pass
    raise ValueError("Time must be seconds or HH:MM:SS.")

@dataclass
class ConversionOptions:
    category: str = "video"
    output_format: str = "mp4"
    video_codec: str = "H.264 (libx264)"
    resolution: str = "Keep original"
    custom_width: int = 1920
    custom_height: int = 1080
    aspect: str = "Preserve / fit"
    fps: str = "Keep original"
    quality: str = "High quality"
    audio_bitrate: str = "192k"
    target_size_mb: Optional[float] = None
    two_pass: bool = False
    mute: bool = False
    overwrite: bool = False
    trim_start: str = "0"
    trim_end: str = ""
    speed: str = "1x"

class MediaEngine:
    def __init__(self, ffmpeg="ffmpeg", ffprobe="ffprobe"):
        self.ffmpeg=ffmpeg; self.ffprobe=ffprobe
    def _run(self,cmd,log_callback=None,cancel_check=None,progress_callback=None,duration=0):
        if log_callback: log_callback("Command: "+" ".join(str(x) for x in cmd))
        proc=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,bufsize=1)
        import threading, queue
        q=queue.Queue()
        def reader():
            for line in proc.stderr: q.put(line)
            q.put(None)
        threading.Thread(target=reader,daemon=True).start()
        while True:
            if cancel_check and cancel_check():
                proc.terminate()
                try: proc.wait(timeout=3)
                except subprocess.TimeoutExpired: proc.kill()
                raise RuntimeError("Conversion cancelled.")
            try: line=q.get(timeout=0.15)
            except queue.Empty:
                if proc.poll() is not None and q.empty(): break
                continue
            if line is None: break
            line=line.strip()
            if log_callback and line: log_callback(line)
            if progress_callback and duration>0:
                m=re.search(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)",line)
                if m:
                    sec=int(m.group(1))*3600+int(m.group(2))*60+float(m.group(3))
                    progress_callback(min(99,max(0,int(sec/duration*100))),"Encoding…")
        code=proc.wait()
        if code: raise RuntimeError(f"FFmpeg exited with code {code}. Check the log for details.")
        if progress_callback: progress_callback(100,"Finished.")
    def _video_filter(self,o):
        filters=[]
        if o.resolution!="Keep original":
            if o.resolution=="Custom": w,h=o.custom_width,o.custom_height
            else:
                m=re.search(r"(\d+)x(\d+)",o.resolution); w,h=map(int,m.groups())
            if o.aspect=="Crop to fill":
                filters.append(f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}")
            elif o.aspect=="Stretch":
                filters.append(f"scale={w}:{h}")
            elif o.aspect in ("9:16","16:9","1:1","4:3"):
                # Treat the selected resolution as the long edge for portrait/square
                # and as the width for landscape presets.
                long_edge=max(w,h)
                if o.aspect=="9:16": tw,th=round(long_edge*9/16),long_edge
                elif o.aspect=="16:9": tw,th=long_edge,round(long_edge*9/16)
                elif o.aspect=="1:1": tw,th=long_edge,long_edge
                else: tw,th=long_edge,round(long_edge*3/4)
                filters.append(f"scale={tw}:{th}:force_original_aspect_ratio=decrease,pad={tw}:{th}:(ow-iw)/2:(oh-ih)/2")
            else:
                filters.append(f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
        if o.fps!="Keep original": filters.append(f"fps={o.fps}")
        speed=float(o.speed.replace("x",""))
        if speed!=1: filters.append(f"setpts={1/speed}*PTS")
        return ",".join(filters) if filters else None
    def convert(self,source,output,o,progress_callback=None,log_callback=None,cancel_check=None):
        source=Path(source); output=Path(output)
        if not source.is_file(): raise FileNotFoundError(source)
        if source.resolve()==output.resolve(): raise ValueError("Input and output paths must be different.")
        if output.exists() and not o.overwrite: raise FileExistsError(f"Output already exists: {output}")
        output.parent.mkdir(parents=True,exist_ok=True)
        if o.category=="image":
            self._convert_image(source,output,o,progress_callback,log_callback,cancel_check); return
        ff=_which(self.ffmpeg)
        if not ff: raise RuntimeError("FFmpeg not found. Install FFmpeg or configure its executable path.")
        meta=probe_media(source,self.ffprobe)
        duration=float(meta.get("format",{}).get("duration",0) or 0)
        start=parse_duration(o.trim_start)
        end=parse_duration(o.trim_end) if o.trim_end else duration
        clip_duration=max(0.1,end-start) if o.trim_end else max(0.1,duration-start)
        if start<0 or (o.trim_end and end<=start): raise ValueError("Trim end must be later than trim start.")
        if o.target_size_mb and o.category!="audio":
            self._target_video(ff,source,output,o,start,clip_duration,progress_callback,log_callback,cancel_check)
            return
        cmd=[ff,"-hide_banner","-y" if o.overwrite else "-n"]
        if start>0: cmd += ["-ss",str(start)]
        cmd += ["-i",str(source)]
        if o.trim_end: cmd += ["-t",str(clip_duration)]
        if o.category=="audio":
            cmd += ["-vn","-b:a",o.audio_bitrate]
            if o.output_format=="mp3": cmd += ["-c:a","libmp3lame"]
            elif o.output_format=="flac": cmd += ["-c:a","flac"]
            elif o.output_format=="opus": cmd += ["-c:a","libopus"]
            elif o.output_format=="ogg": cmd += ["-c:a","libvorbis"]
            elif o.output_format=="wav": cmd += ["-c:a","pcm_s16le"]
            else: cmd += ["-c:a","aac"]
        else:
            vcodec=self._codec(o.video_codec)
            cmd += ["-c:v",vcodec]
            crf,preset={"High quality":("18","slow"),"Balanced":("23","medium"),"Smaller file":("28","slow"),"Fast encode":("25","veryfast")}[o.quality]
            if vcodec in ("libx264","libx265"): cmd += ["-crf",crf,"-preset",preset]
            elif vcodec=="libvpx-vp9": cmd += ["-crf",crf,"-b:v","0"]
            elif vcodec=="libaom-av1": cmd += ["-crf",crf,"-b:v","0","-cpu-used","6"]
            vf=self._video_filter(o)
            if vf: cmd += ["-vf",vf]
            if not o.mute: cmd += ["-c:a","aac","-b:a",o.audio_bitrate]
            else: cmd += ["-an"]
            if o.output_format in ("mp4","mov"): cmd += ["-movflags","+faststart"]
        cmd += [str(output)]
        self._run(cmd,log_callback,cancel_check,progress_callback,clip_duration)
    def _codec(self,label):
        return {"H.264 (libx264)":"libx264","H.265 / HEVC (libx265)":"libx265","VP9":"libvpx-vp9","AV1 (libaom-av1)":"libaom-av1"}.get(label,"libx264")
    def _target_video(self,ff,source,output,o,start,duration,progress,log,cancel):
        # Calculate total bitrate from target bytes and clip duration; reserve container overhead.
        total_kbps=max(80,int((o.target_size_mb*8*1024*0.97)/duration))
        audio_kbps=int(o.audio_bitrate.lower().replace("k",""))
        video_kbps=total_kbps-audio_kbps
        if video_kbps<80:
            raise ValueError("Target size is too small for this duration and selected audio bitrate. Increase target size or lower audio bitrate.")
        codec=self._codec(o.video_codec)
        if codec not in ("libx264","libx265"):
            raise ValueError("Target-size mode currently supports H.264 and H.265 for predictable two-pass bitrate encoding.")
        vf=self._video_filter(o)
        common=[ff,"-hide_banner","-y" if o.overwrite else "-n"]
        if start>0: common += ["-ss",str(start)]
        common += ["-i",str(source),"-t",str(duration)]
        if vf: common += ["-vf",vf]
        passlog=str(output.parent/(output.stem+"_jass_pass"))
        # Two-pass is used automatically for target size, even if the checkbox is off;
        # the checkbox is retained as an explicit UI indicator of the recommended mode.
        for passno in (1,2):
            cmd=common+["-c:v",codec,"-b:v",f"{video_kbps}k","-preset","medium","-pass",str(passno),"-passlogfile",passlog]
            if passno==1: cmd += ["-an","-f","null",os.devnull]
            else:
                if o.mute: cmd += ["-an"]
                else: cmd += ["-c:a","aac","-b:a",o.audio_bitrate]
                if o.output_format in ("mp4","mov"): cmd += ["-movflags","+faststart"]
                cmd += [str(output)]
            if log: log(f"Target size: {o.target_size_mb:.1f} MB | estimated video bitrate: {video_kbps} kbps | pass {passno}/2")
            self._run(cmd,log,cancel,progress,duration)
        try:
            for p in output.parent.glob(output.stem+"_jass_pass*"): p.unlink(missing_ok=True)
        except Exception: pass
        if progress: progress(100,"Target-size encode finished.")
    def _convert_image(self,source,output,o,progress,log,cancel):
        try: from PIL import Image
        except ImportError: raise RuntimeError("Pillow is required for image conversion. Install with: pip install Pillow")
        if cancel and cancel(): raise RuntimeError("Conversion cancelled.")
        with Image.open(source) as im:
            im=im.convert("RGB") if output.suffix.lower() in (".jpg",".jpeg") else im.copy()
            if o.resolution!="Keep original":
                if o.resolution=="Custom": size=(o.custom_width,o.custom_height)
                else:
                    m=re.search(r"(\d+)x(\d+)",o.resolution); size=tuple(map(int,m.groups()))
                im.thumbnail(size,Image.Resampling.LANCZOS)
            saveopts={}
            if output.suffix.lower() in (".jpg",".jpeg"): saveopts={"quality":92,"optimize":True}
            elif output.suffix.lower()==".webp": saveopts={"quality":90,"method":6}
            im.save(output,**saveopts)
        if log: log(f"Saved image: {output}")
        if progress: progress(100,"Image conversion finished.")
