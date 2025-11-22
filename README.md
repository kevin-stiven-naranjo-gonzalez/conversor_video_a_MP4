# Conversor a MP4 - FFmpeg Tool

## Descripción

Este es un script multiplataforma (Windows/Linux) escrito en Python que permite convertir archivos de vídeo a formato MP4 usando FFmpeg. Incluye opciones avanzadas de compresión, interfaz gráfica opcional y verificación automática de dependencias.

## Características Principales

- **Conversión automática a MP4** con H.264 y AAC
- **Compresión por tamaño objetivo** en MB (codificación two-pass)
- **Compresión por bitrate** personalizado
- **Opciones de re-encoding o remux**
- **Interfaz gráfica personalizada** (GUI)
- **Interfaz de línea de comandos** (CLI) con opciones interactivas
- **Diálogos de selección de archivos** con Windows explorer
- **Instalación automática de dependencias** (ffmpeg, tkinter)
- **Detección automática de carpeta Videos** del usuario
- **Salida por defecto a carpeta Videos**

## Requisitos

- **Python 3.6+**
- FFmpeg (se instala automáticamente si no está presente)
- Tkinter para diálogos gráficos (se instala automáticamente si necesario)

## Instalación

1. **Clona o descarga el script** `video_to_MP4/convert_to_mp4_Version2.py`

2. **Ejecuta el script** por primera vez:
   ```bash
   python video_to_MP4/convert_to_mp4_Version2.py
   ```

3. **Instalación automática**: El script verificará e instalará automáticamente:
   - FFmpeg desde gyan.dev (build esenciales para Windows)
   - Tkinter via pip si no está disponible

   Si hay errores en la instalación automática, instala manualmente:
   - FFmpeg: Descarga de https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip y descomprime
   - Tkinter: Asegúrate que Python tenga tcl/tk

## Uso

### Modo GUI (Recomendado - Automático)

El script inicia automáticamente en modo gráfico. Ejecuta:

```bash
python video_to_MP4/convert_to_mp4_Version2.py
```

### Modo CLI Interactivo

```bash
python video_to_MP4/convert_to_mp4_Version2.py --gui  # Si se arranca en CLI por alguna razón
```

El script puede ser ejecutado en modo CLI con:

```bash
python video_to_MP4/convert_to_mp4_Version2.py  # Sin argumentos para CLI
```

## Funcionalidad del Script

### Verificación de Dependencias

Al iniciar, el script verifica:
1. **FFmpeg**: Busca en PATH, instala automáticamente si no encontrado
2. **Tkinter**: Intenta importar, instala via pip si faltante

### Selección de Archivo de Entrada

- **escribir 'browse'**: Abre diálogo de Windows para seleccionar archivo
- **escribir ruta completa**: Uso directo
- El diálogo se fuerza al frente de otras ventanas

### Selección de Archivo de Salida

- **Enter**: Usa ruta por defecto (carpeta Videos del usuario)
- **escribir ruta completa**: Personalizada
- **escribir 'browse'**: Diálogo de guardar como

### Opciones de Compresión

1. **Comprimir por tamaño (MB)**: Codificación two-pass para alcanzar tamaño exacto
2. **Comprimir por bitrate (kbps)**: Codificación single-pass con bitrate específico
3. **No comprimir**: Opciones de re-encoding o remux

### GUI (Interfaz Gráfica)

Incluye campos para:
- Selección de archivo origen (con botón "Buscar...")
- Selección de archivo destino (con botón "Guardar como...")
- Casillas para opciones de codificación
- Campos para CRF, presets, bitrate video/audio

## Cambios Realizados During Development

### Versión Inicial
- Script básico con CLI modo texto
- Soporte para conversión MP4 con FFmpeg
- Opciones básicas de compresión CRF preset

### Cambios Implementados

1. **Eliminación de soporte YouTube**:
   - Removido código de yt-dlp y descarga de URLs YouTube
   - Simplificado prompt de entrada a solo archivos locales

2. **Habilitado 'browse' para CLI**:
   - Agregado funcionalidad para abrir diálogos de selección de archivo en modo CLI
   - Importación automática de tkinter
   - Manejo de errores con mensajes claros

3. **Salida por defecto a Videos**:
   - Detección automática de carpeta Videos del usuario (C:\Users\USERNAME\Videos)
   - Mensaje informativo de ubicación de salida
   - Opciones para elegir ubicación personalizada

4. **Diálogos al frente**:
   - Agregado `root.lift()`, `root.attributes("-topmost", True)`, `root.focus_force()`, `root.update()`
   - Diálogos aparecen por encima de otras ventanas
   - Funcionamiento como diálogos Windows nativos

5. **Instalación automática de dependencias**:
   - Función `ensure_dependencies()` verifica FFmpeg y tkinter
   - Descarga automática de FFmpeg desde gyan.dev
   - Instalación de tkinter via pip
   - Mensajes de progreso detallados

6. **Corrección de errores de sintaxis**:
   - Schema global TK_AVAILABLE corregido
   - Alineación correcta de código después de cambios

7. **Interfaz GUI como defecto**:
   - Script inicia automáticamente en GUI
   - CLI disponible pero GUI prioritizada

## Estructura del Código

### Funciones Principales

- `check_ffmpeg()`: Verifica presencia de FFmpeg
- `open_file_dialog()`: Diálogo de selección de archivo
- `save_file_dialog()`: Diálogo de guardar archivo
- `ensure_dependencies()`: Verificación e instalación automática de dependencias
- `cli_interactive()`: Modo CLI interactivo
- `run_gui()`: Lanza interfaz gráfica
- `convert_to_target_size()`: Codificación two-pass

### Clases

- `ConverterGUI`: Interfaz gráfica con Tkinter

## Manejo de Errores

- Mensajes claros en español
- Instalación manual como fallback
- Verificación robusta de dependencias
- Manejo de excepciones en diálogos

## Licencia

Este proyecto es de uso libre sin restricciones específicas.

## Soporte

Si encuentras problemas, verifica:
1. Python versión 3.6+
2. Conexión internet para descarga automática
3. Permisos escritura en directorio de Python
4. Windows con tcl/tk para GUI
