#!/usr/bin/env python3
"""
script_principal.py

Script multiplataforma (Windows / Linux) que permite seleccionar interactiva
el archivo de origen y el destino, y convertirlo a MP4 usando ffmpeg.

Añadido: opción para "comprimir" la salida a un tamaño objetivo (MB) usando
codificación en dos pases, o especificar bitrate para el vídeo.
"""

import argparse
import glob
import math
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time

# Intentamos importar tkinter para la GUI y para usar dialogs desde CLI si es necesario
try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, scrolledtext
    import customtkinter as ctk
    TK_AVAILABLE = True
    CTK_AVAILABLE = True
except Exception:
    TK_AVAILABLE = False
    CTK_AVAILABLE = False

FFMPEG_PATH = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE_PATH = shutil.which("ffprobe") or "ffprobe"


def check_ffmpeg():
    """Verifica que ffmpeg esté disponible."""
    if FFMPEG_PATH == "ffmpeg" and shutil.which("ffmpeg") is None:
        return False, None
    try:
        proc = subprocess.run([FFMPEG_PATH, "-version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode == 0:
            first_line = proc.stdout.splitlines()[0] if proc.stdout else proc.stderr.splitlines()[0]
            return True, first_line
    except Exception:
        pass
    return False, None


def open_file_dialog(initialdir=".", title="Seleccionar archivo"):
    if not TK_AVAILABLE:
        raise RuntimeError("Tkinter no disponible")
    root = tk.Tk()
    root.withdraw()
    root.lift()
    root.attributes("-topmost", True)
    root.focus_force()
    root.update()
    path = filedialog.askopenfilename(initialdir=initialdir, title=title)
    root.attributes("-topmost", False)
    root.destroy()
    return path


def save_file_dialog(initialdir=".", title="Guardar como"):
    if not TK_AVAILABLE:
        raise RuntimeError("Tkinter no disponible")
    root = tk.Tk()
    root.withdraw()
    root.lift()
    root.attributes("-topmost", True)
    root.focus_force()
    root.update()
    path = filedialog.asksaveasfilename(initialdir=initialdir, title=title, defaultextension=".mp4", filetypes=[("MP4 files", "*.mp4"), ("All files", "*.*")])
    root.attributes("-topmost", False)
    root.destroy()
    return path


def run_command_show_progress(cmd, on_line=None):
    """
    Ejecuta comando y muestra output en tiempo real.
    on_line: si es callable se le pasará cada línea de stderr (ffmpeg escribe progreso a stderr).
    Retorna tuple (returncode, stderr_combined).
    """
    stderr_lines = []
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, universal_newlines=True)
    except FileNotFoundError as e:
        raise RuntimeError(f"No se encontró ffmpeg en la ruta: {FFMPEG_PATH}") from e

    def reader():
        for line in proc.stderr:
            stderr_lines.append(line)
            if on_line:
                on_line(line)
        proc.stderr.close()

    t = threading.Thread(target=reader, daemon=True)
    t.start()
    proc.wait()
    t.join()
    return proc.returncode, "".join(stderr_lines)


def ensure_parent_dir(path):
    parent = os.path.dirname(path)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)


def build_ffmpeg_command(input_path, output_path, reencode=True, crf=23, preset="medium", faststart=True):
    cmd = [FFMPEG_PATH, "-y", "-i", input_path]

    if reencode:
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf)]
        cmd += ["-pix_fmt", "yuv420p"]
        cmd += ["-c:a", "aac", "-b:a", "128k"]
    else:
        cmd += ["-c", "copy"]

    if faststart:
        cmd += ["-movflags", "+faststart"]

    cmd += [output_path]
    return cmd


# ---------------- Media info / duration ----------------
def get_media_duration(input_path):
    """
    Intenta obtener la duración del archivo en segundos.
    Primero usa ffprobe si está disponible; si no, intenta parsear la salida de ffmpeg -i.
    Retorna float (segundos) o None si no pudo determinarlo.
    """
    # Try ffprobe
    if shutil.which(FFPROBE_PATH):
        try:
            proc = subprocess.run([FFPROBE_PATH, "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", input_path],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            if proc.returncode == 0 and proc.stdout.strip():
                try:
                    return float(proc.stdout.strip())
                except Exception:
                    pass
        except Exception:
            pass

    # Fallback: parse ffmpeg -i output
    try:
        proc = subprocess.run([FFMPEG_PATH, "-i", input_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        out = proc.stderr
        for line in out.splitlines():
            if "Duration:" in line:
                # formato: Duration: 00:01:23.45, start: ...
                try:
                    part = line.split("Duration:")[1].split(",")[0].strip()
                    h, m, s = part.split(":")
                    seconds = float(h) * 3600.0 + float(m) * 60.0 + float(s)
                    return seconds
                except Exception:
                    pass
    except Exception:
        pass

    return None


# ---------------- Two-pass conversion (target size) ----------------
def convert_to_target_size(input_path, output_path, target_mb, preset="medium", audio_bitrate_k=128, on_line=None):
    """
    Intenta codificar el archivo para que el tamaño final esté cercano a target_mb (megabytes).
    Usa two-pass encoding: calcula bitrate total necesario y ejecuta dos pases.
    on_line: callback para cada línea de ffmpeg stderr.
    """
    duration = get_media_duration(input_path)
    if duration is None or duration <= 0:
        raise RuntimeError("No se pudo determinar la duración del archivo; no se puede calcular bitrate para tamaño objetivo.")

    # Convertir target_mb (MiB) a kilobits totales: MB * 1024 * 1024 * 8 bits -> kilobits = /1000
    # Para simplicidad usamos kilobits (kbps) con base 1024*8 => kilobits_total = target_mb * 8192
    # kbps necesario = kilobits_total / duration_seconds
    kilobits_total = target_mb * 8192.0
    kbps_total = kilobits_total / duration
    # audio_kbps:
    audio_kbps = float(audio_bitrate_k)
    video_kbps = kbps_total - audio_kbps
    if video_kbps < 100:
        video_kbps = 100.0  # mínimo para mantener algo de calidad

    video_bitrate_k = int(math.floor(video_kbps))
    audio_bitrate_k = int(audio_bitrate_k)

    # Prepara archivos de two-pass
    devnull = "NUL" if os.name == "nt" else "/dev/null"
    passlog = tempfile.NamedTemporaryFile(delete=False).name  # prefix para passlogfile
    # ffmpeg agrega sufijos al crear los logs; we'll try to clean them later with glob.

    # Primer pase (sin audio)
    pass1_cmd = [
        FFMPEG_PATH, "-y", "-i", input_path,
        "-c:v", "libx264", "-b:v", f"{video_bitrate_k}k", "-preset", preset,
        "-pass", "1", "-an", "-f", "mp4", devnull
    ]
    if on_line:
        on_line(f"Two-pass: duración {duration:.2f}s, objetivo {target_mb}MB -> video {video_bitrate_k}k, audio {audio_bitrate_k}k\n")
        on_line("Ejecutando pase 1...\n")
    # Ejecutar primer pase con passlogfile
    try:
        rc1 = subprocess.run(["-passlogfile"] , stdout=subprocess.PIPE)  # noop to appease analyzers (we'll construct full cmd below)
    except Exception:
        pass
    # Insert -passlogfile option before -pass 1 (ffmpeg supports -passlogfile <file>)
    pass1_cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-passlogfile", passlog, "-c:v", "libx264", "-b:v", f"{video_bitrate_k}k", "-preset", preset, "-pass", "1", "-an", "-f", "mp4", devnull]
    rc, stderr = run_command_show_progress(pass1_cmd, on_line=on_line)
    if rc != 0:
        # try to continue but warn
        raise RuntimeError(f"Pase 1 de two-pass falló (código {rc}). Salida:\n{stderr[:2000]}")

    # Segundo pase: con audio y salida final
    if on_line:
        on_line("Ejecutando pase 2...\n")
    pass2_cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-passlogfile", passlog,
                 "-c:v", "libx264", "-b:v", f"{video_bitrate_k}k", "-preset", preset,
                 "-pass", "2", "-c:a", "aac", "-b:a", f"{audio_bitrate_k}k", "-movflags", "+faststart", output_path]
    rc2, stderr2 = run_command_show_progress(pass2_cmd, on_line=on_line)

    # Limpiar archivos de passlog
    try:
        for f in glob.glob(passlog + "*"):
            try:
                os.remove(f)
            except Exception:
                pass
    except Exception:
        pass

    return rc2, stderr2


# ----------------- CLI flow -----------------
def cli_interactive():
    ok, ver = check_ffmpeg()
    if not ok:
        print("ERROR: ffmpeg no está disponible en PATH. Instálalo y vuelve a intentarlo.")
        return

    print("Conversor a MP4 - modo CLI")
    print(f"ffmpeg detectado: {ver}")

    input_path = None
    while input_path is None:
        inp = input("Ruta del archivo de origen o 'browse' para dialog: ").strip()
        if inp.lower() == "browse":
            if TK_AVAILABLE:
                try:
                    path = open_file_dialog()
                    if path:
                        input_path = path
                        print(f"Archivo seleccionado: {path}")
                    else:
                        print("No se seleccionó archivo.")
                except Exception as e:
                    print(f"Error al abrir diálogo: {e}")
            else:
                print("Tkinter no disponible para abrir diálogo.")
        elif inp.lower() == "exit":
            print("Saliendo...")
            return
        elif os.path.isfile(inp):
            input_path = inp
        else:
            print("Archivo no encontrado. Intenta de nuevo.")

    default_dest = os.path.splitext(os.path.basename(input_path))[0] + ".mp4"
    videos_folder = os.path.join(os.environ.get('USERPROFILE', '.'), 'Videos')
    default_output_path = os.path.join(videos_folder, default_dest)
    print(f"El archivo se guardará en: {default_output_path}")
    output_path = None
    while not output_path:
        out = input(f"Ruta de salida [enter para usar '{default_output_path}'] ('browse' para dialog): ").strip()
        if out == "":
            output_path = default_output_path
        elif out.lower() == "browse":
            if TK_AVAILABLE:
                try:
                    path = save_file_dialog(initialdir=videos_folder, title="Guardar como")
                    if path:
                        output_path = path
                        print(f"Archivo se guardará en: {path}")
                    else:
                        print("No se seleccionó ubicación.")
                except Exception as e:
                    print(f"Error al abrir diálogo: {e}")
            else:
                print("Tkinter no disponible para abrir diálogo.")
        else:
            output_path = out

    # Preguntar si desea compresión por tamaño o bitrate
    compress_mode = None
    while True:
        choice = input("¿Quieres comprimir a tamaño objetivo (MB), usar bitrate (kbps) o no comprimir? (tamaño/bitrate/no) [no]: ").strip().lower() or "no"
        if choice in ("tamaño", "tamano", "size", "t", "tamaño", "tamanio", "size_mb", "tamaño") :
            compress_mode = "size"
            break
        if choice in ("bitrate", "b", "br"):
            compress_mode = "bitrate"
            break
        if choice in ("no", "n", "none", ""):
            compress_mode = None
            break
        print("Respuesta no entendida. Escribe 'tamaño', 'bitrate' o 'no'.")

    ensure_parent_dir(output_path)

    if compress_mode == "size":
        try:
            mb_in = input("Tamaño objetivo en MB (por ejemplo 10.5): ").strip()
            target_mb = float(mb_in)
            audio_bitrate = input("Bitrate de audio en kbps [128]: ").strip() or "128"
            audio_bitrate_k = int(audio_bitrate)
        except Exception:
            print("Valores inválidos. Cancelando.")
            return
        print(f"Intentando comprimir a ~{target_mb} MB (audio {audio_bitrate_k} kbps). Esto usará codificación two-pass.")
        def on_line(line):
            sys.stdout.write(line)
            sys.stdout.flush()
        try:
            rc, stderr = convert_to_target_size(input_path, output_path, target_mb, preset="medium", audio_bitrate_k=audio_bitrate_k, on_line=on_line)
            if rc == 0:
                print("\nConversión finalizada correctamente.")
            else:
                print("\nffmpeg finalizó con código:", rc)
        except Exception as e:
            print("Error durante conversión:", e)
    elif compress_mode == "bitrate":
        try:
            vb = input("Bitrate de vídeo en kbps (ej. 1000) [1500]: ").strip() or "1500"
            vb_k = int(vb)
            audio_bitrate = input("Bitrate de audio en kbps [128]: ").strip() or "128"
            ab_k = int(audio_bitrate)
        except Exception:
            print("Valores inválidos. Cancelando.")
            return
        print(f"Codificando con video {vb_k} kbps, audio {ab_k} kbps (single-pass).")
        cmd = [FFMPEG_PATH, "-y", "-i", input_path, "-c:v", "libx264", "-b:v", f"{vb_k}k", "-preset", "medium", "-c:a", "aac", "-b:a", f"{ab_k}k", "-movflags", "+faststart", output_path]
        print("Ejecutando ffmpeg:", " ".join(cmd))
        rc, full_err = run_command_show_progress(cmd, on_line=lambda l: (sys.stdout.write(l), sys.stdout.flush()))
        if rc == 0:
            print("\nConversión finalizada correctamente.")
        else:
            print("\nffmpeg finalizó con código:", rc)
    else:
        # No compression: preguntar si reencode o copy
        while True:
            choice2 = input("Re-encode a H.264+AAC o intentar remux (copiar streams) si es posible? (reencode/remux) [reencode]: ").strip().lower() or "reencode"
            if choice2 in ("reencode", "r", "encode"):
                reencode = True
                break
            if choice2 in ("remux", "copy"):
                reencode = False
                break
            print("Respuesta no entendida.")
        if reencode:
            crf = 23
            try:
                crf_in = input("CRF (calidad) para H.264 (18 mejor, 23 por defecto): ").strip()
                if crf_in:
                    crf = int(crf_in)
            except Exception:
                pass
            preset = "medium"
            preset_in = input("Preset x264 [medium]: ").strip()
            if preset_in:
                preset = preset_in
            cmd = build_ffmpeg_command(input_path, output_path, reencode=True, crf=crf, preset=preset)
        else:
            cmd = build_ffmpeg_command(input_path, output_path, reencode=False)
        print("Ejecutando ffmpeg:")
        print(" ".join(cmd))
        rc, full_err = run_command_show_progress(cmd, on_line=lambda l: (sys.stdout.write(l), sys.stdout.flush()))
        if rc == 0:
            print("\nConversión finalizada correctamente.")
        else:
            print("\nffmpeg finalizó con código:", rc)


# ----------------- GUI -----------------
class ConverterGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("Convertir a MP4 - FFmpeg (con compresión)")
        self.root.resizable(False, False)

        self.src_var = tk.StringVar()
        self.dst_var = tk.StringVar()
        self.reencode_var = tk.BooleanVar(value=True)
        self.crf_var = tk.StringVar(value="23")  # change to string for entry
        self.preset_var = tk.StringVar(value="medium")
        self.compress_mb_var = tk.StringVar(value="")   # si se llena, usa two-pass para target size
        self.vbr_k_var = tk.StringVar(value="")        # bitrate video (kbps) opcional
        self.ab_k_var = tk.StringVar(value="128")      # audio bitrate

        padx = 6
        pady = 6
        row = 0
        ctk.CTkLabel(root, text="Archivo origen:").grid(row=row, column=0, sticky="w", padx=padx, pady=pady)
        ctk.CTkEntry(root, textvariable=self.src_var, width=300).grid(row=row, column=1, padx=padx, pady=pady)
        ctk.CTkButton(root, text="Buscar...", command=self.browse_src).grid(row=row, column=2, padx=padx, pady=pady)

        row += 1
        ctk.CTkLabel(root, text="Archivo destino:").grid(row=row, column=0, sticky="w", padx=padx, pady=pady)
        ctk.CTkEntry(root, textvariable=self.dst_var, width=300).grid(row=row, column=1, padx=padx, pady=pady)
        ctk.CTkButton(root, text="Guardar como...", command=self.browse_dst).grid(row=row, column=2, padx=padx, pady=pady)

        row += 1
        ctk.CTkCheckBox(root, text="Re-encode (H.264 + AAC)", variable=self.reencode_var).grid(row=row, column=0, columnspan=2, sticky="w", padx=padx, pady=pady)
        ctk.CTkLabel(root, text="CRF:").grid(row=row, column=1, sticky="e", padx=padx, pady=pady)
        ctk.CTkEntry(root, textvariable=self.crf_var, width=50).grid(row=row, column=2, sticky="w", padx=padx, pady=pady)

        row += 1
        ctk.CTkLabel(root, text="Preset:").grid(row=row, column=0, sticky="w", padx=padx, pady=pady)
        presets = ["ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower", "veryslow"]
        ctk.CTkOptionMenu(root, variable=self.preset_var, values=presets).grid(row=row, column=1, sticky="w", padx=padx, pady=pady)

        row += 1
        ctk.CTkLabel(root, text="Comprimir a (MB) - dejar vacío para no usar:").grid(row=row, column=0, sticky="w", padx=padx, pady=pady)
        ctk.CTkEntry(root, textvariable=self.compress_mb_var, width=100).grid(row=row, column=1, sticky="w", padx=padx, pady=pady)
        ctk.CTkLabel(root, text="Bitrate audio (kbps):").grid(row=row, column=2, sticky="w", padx=padx, pady=pady)
        ctk.CTkEntry(root, textvariable=self.ab_k_var, width=50).grid(row=row, column=2, sticky="e", padx=(0, 60), pady=pady)

        row += 1
        ctk.CTkLabel(root, text="(Opcional) Bitrate video (kbps):").grid(row=row, column=0, sticky="w", padx=padx, pady=pady)
        ctk.CTkEntry(root, textvariable=self.vbr_k_var, width=100).grid(row=row, column=1, sticky="w", padx=padx, pady=pady)
        ctk.CTkLabel(root, text="Dejar vacío para usar CRF").grid(row=row, column=2, sticky="w", padx=padx, pady=pady)

        row += 1
        self.convert_btn = ctk.CTkButton(root, text="Convertir", command=self.start_conversion, fg_color="#4CAF50", text_color="white")
        self.convert_btn.grid(row=row, column=0, columnspan=3, sticky="we", padx=padx, pady=pady)

        row += 1
        ctk.CTkLabel(root, text="Salida/Registro:").grid(row=row, column=0, sticky="w", padx=padx, pady=pady)
        row += 1
        self.log = ctk.CTkTextbox(root, wrap="word", width=600, height=300)
        self.log.grid(row=row, column=0, columnspan=3, padx=padx, pady=pady)

    def browse_src(self):
        try:
            p = filedialog.askopenfilename(title="Selecciona archivo de origen")
            if p:
                self.src_var.set(p)
                if not self.dst_var.get():
                    default = os.path.splitext(os.path.basename(p))[0] + ".mp4"
                    self.dst_var.set(os.path.join(os.getcwd(), default))
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir dialog: {e}")

    def browse_dst(self):
        try:
            p = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4 files", "*.mp4")], title="Guardar como")
            if p:
                self.dst_var.set(p)
        except Exception as e:
            messagebox.showerror("Error", f"No se pudo abrir dialog: {e}")

    def log_write(self, text):
        self.log.insert("end", text)
        self.log.see("end")

    def start_conversion(self):
        src = self.src_var.get().strip()
        dst = self.dst_var.get().strip()
        if not src or not os.path.isfile(src):
            messagebox.showwarning("Advertencia", "Selecciona un archivo de origen válido.")
            return
        if not dst:
            messagebox.showwarning("Advertencia", "Selecciona un destino.")
            return
        ok, ver = check_ffmpeg()
        if not ok:
            messagebox.showerror("ffmpeg no encontrado", "No se encontró ffmpeg. Instálalo y vuelve a intentar.")
            return

        reencode = bool(self.reencode_var.get())
        crf = int(self.crf_var.get())
        preset = self.preset_var.get()
        compress_mb = self.compress_mb_var.get().strip()
        vbr_k = self.vbr_k_var.get().strip()
        ab_k = self.ab_k_var.get().strip() or "128"

        self.convert_btn.configure(state="disabled")
        self.log.delete("1.0", "end")

        def on_line(line):
            self.root.after(0, self.log_write, line)

        def worker():
            ensure_parent_dir(dst)
            try:
                if compress_mb:
                    try:
                        target_mb = float(compress_mb)
                        audio_bitrate_k = int(ab_k)
                    except Exception:
                        self.root.after(0, messagebox.showerror, "Error", "Valores de compresión inválidos.")
                        self.root.after(0, self.convert_btn.configure, {"state": "normal"})
                        return
                    self.root.after(0, self.log_write, f"Comprimir a ~{target_mb} MB (audio {audio_bitrate_k} kbps)\n")
                    rc, stderr = convert_to_target_size(src, dst, target_mb, preset=preset, audio_bitrate_k=audio_bitrate_k, on_line=on_line)
                    if rc == 0:
                        self.root.after(0, self.log_write, "\nConversión finalizada correctamente.\n")
                        self.root.after(0, messagebox.showinfo, "Listo", "Conversión finalizada correctamente.")
                    else:
                        self.root.after(0, self.log_write, f"\nffmpeg finalizó con código {rc}\n")
                        self.root.after(0, messagebox.showerror, "Error", f"ffmpeg finalizó con código {rc}. Revisa el log.")
                else:
                    if vbr_k:
                        try:
                            vb_k = int(vbr_k)
                            ab_k_int = int(ab_k)
                        except Exception:
                            self.root.after(0, messagebox.showerror, "Error", "Bitrates inválidos.")
                            self.root.after(0, self.convert_btn.configure, {"state": "normal"})
                            return
                        cmd = [FFMPEG_PATH, "-y", "-i", src, "-c:v", "libx264", "-b:v", f"{vb_k}k", "-preset", preset, "-c:a", "aac", "-b:a", f"{ab_k_int}k", "-movflags", "+faststart", dst]
                    else:
                        if reencode:
                            cmd = build_ffmpeg_command(src, dst, reencode=True, crf=crf, preset=preset)
                        else:
                            cmd = build_ffmpeg_command(src, dst, reencode=False)
                    self.root.after(0, self.log_write, f"Ejecutando: {' '.join(cmd)}\n\n")
                    rc, stderr = run_command_show_progress(cmd, on_line=on_line)
                    if rc == 0:
                        self.root.after(0, self.log_write, "\nConversión finalizada correctamente.\n")
                        self.root.after(0, messagebox.showinfo, "Listo", "Conversión finalizada correctamente.")
                    else:
                        self.root.after(0, self.log_write, f"\nffmpeg finalizó con código {rc}\n")
                        self.root.after(0, messagebox.showerror, "Error", f"ffmpeg finalizó con código {rc}. Revisa el log.")
            except Exception as e:
                self.root.after(0, messagebox.showerror, "Error", str(e))
            finally:
                self.root.after(0, self.convert_btn.configure, {"state": "normal"})

        t = threading.Thread(target=worker, daemon=True)
        t.start()


def run_gui():
    if not TK_AVAILABLE:
        print("Tkinter no está disponible en este entorno. Instala tkinter para usar la GUI.")
        return
    if CTK_AVAILABLE:
        ctk.set_appearance_mode("System")
        ctk.set_default_color_theme("blue")
        root = ctk.CTk()
    else:
        root = tk.Tk()
    app = ConverterGUI(root)
    root.mainloop()


def ensure_dependencies():
    global TK_AVAILABLE, FFMPEG_PATH, FFPROBE_PATH
    print("Verificando dependencias necesarias...")
    print("1. Verificando ffmpeg...")
    ok, ver = check_ffmpeg()
    if ok:
        print(f"   ffmpeg detectado: {ver}")
    else:
        if os.name == 'nt':  # Windows
            print("   ffmpeg no encontrado. Instalándolo automáticamente con Chocolatey...")
            try:
                if not shutil.which("choco"):
                    print("   Instalando Chocolatey...")
                    subprocess.check_call([
                        "powershell", "-Command",
                        "Set-ExecutionPolicy Bypass -Scope Process -Force; iwr https://community.chocolatey.org/install.ps1 -UseBasicParsing | iex"
                    ], shell=True)
                    print("   Chocolatey instalado.")
                print("   Instalando ffmpeg...")
                subprocess.check_call(["powershell", "-Command", "choco install ffmpeg -y"], shell=True)
                print("   ffmpeg instalado.")
                FFMPEG_PATH = shutil.which("ffmpeg")
                FFPROBE_PATH = shutil.which("ffprobe")
            except subprocess.CalledProcessError as e:
                print(f"   Error instalando automáticamente: {e}")
                print("   Inténtalo manualmente abriendo PowerShell como administrador y ejecutando:")
                print("   1. Set-ExecutionPolicy Bypass -Scope Process -Force")
                print("   2. iwr https://community.chocolatey.org/install.ps1 -UseBasicParsing | iex")
                print("   3. choco install ffmpeg -y")
                print("   Luego vuelve a ejecutar este programa.")
                sys.exit(1)
            # Verificar
            ok, ver = check_ffmpeg()
            if not ok:
                print("   Error: ffmpeg aún no disponible. Asegúrate de que esté en PATH.")
                sys.exit(1)
        else:
            print("   ffmpeg no encontrado. Descargándolo automáticamente...")
            try:
                # For other OS (fallback)
                import urllib.request
                import tempfile
                import zipfile
                # Download essentials build (assuming Linux or similar)
                url = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"
                print("   Descargando ffmpeg...")
                with tempfile.TemporaryDirectory() as temp_dir:
                    zip_path = os.path.join(temp_dir, "ffmpeg.zip")
                    urllib.request.urlretrieve(url, zip_path)
                    print("   Extrayendo...")
                    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                        zip_ref.extractall(temp_dir)
                    # Find ffmpeg and move to a global location, say beside python or /usr/local/bin if possible
                    python_dir = os.path.dirname(sys.executable)
                    # For simplicity, try python dir
                    for root, dirs, files in os.walk(temp_dir):
                        for file in files:
                            if file == "ffmpeg":
                                dest = os.path.join(python_dir, file)
                                if not os.path.exists(dest):
                                    shutil.move(os.path.join(root, file), dest)
                                    print(f"   Instalado: {dest}")
                                    os.chmod(dest, 0o755)
                                break
                        else:
                            continue
                        break
                    # Update global
                    FFMPEG_PATH = shutil.which("ffmpeg") or dest
                    FFPROBE_PATH = shutil.which("ffprobe") or dest.replace("ffmpeg", "ffprobe") if dest else None
                    ok, ver = check_ffmpeg()
                    if ok:
                        print(f"   ffmpeg instalado correctamente: {ver}")
                    else:
                        raise Exception("Instalación falló")
            except Exception as e:
                print(f"   Error instalando ffmpeg: {e}")
                print("   Por favor instala ffmpeg manualmente.")
                sys.exit(1)

    print("2. Verificando tkinter...")
    if TK_AVAILABLE:
        print("   tkinter disponible.")
    else:
        print("   tkinter no disponible. Intentando instalar...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", "pip"])
            subprocess.check_call([sys.executable, "-m", "pip", "install", "tk"])
            print("   tkinter instalado.")
            # Import again
            import tkinter as tk
            from tkinter import filedialog, messagebox, scrolledtext
            TK_AVAILABLE = True
        except subprocess.CalledProcessError as e:
            print(f"   Error instalando tkinter: {e}")
            print("   tkinter es parte de Python estándar. Asegúrate de tener Python con tcl/tk.")

    print("Verificación completada.")


def parse_args():
    p = argparse.ArgumentParser(description="Convertir archivos a MP4 (requiere ffmpeg).")
    p.add_argument("--cli", action="store_true", help="Usar interfaz de comandos")
    return p.parse_args()


def main():
    ensure_dependencies()
    args = parse_args()
    if args.cli:
        cli_interactive()
    else:
        run_gui()


if __name__ == "__main__":
    main()
