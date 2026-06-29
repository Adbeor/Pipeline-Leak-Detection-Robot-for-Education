#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Graficador Automático de Logs de Fugas
Uso: python3 plot_log.py <ruta_del_archivo.csv>
Requisitos: pip install matplotlib numpy
"""

import sys
import os
import numpy as np
import matplotlib.pyplot as plt

def parse_csv(csv_path):
    """Lee y parsea las columnas del log CSV."""
    times_ms = []
    mags = []
    dists = []
    p1, p2, p3 = [], [], []
    pcr, pat = [], []
    tags = []

    try:
        with open(csv_path, 'r') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"ERROR: No se pudo leer el archivo: {e}")
        sys.exit(1)

    for line in lines[1:]: # Ignorar la cabecera
        parts = line.strip().split(',')
        if len(parts) < 7:
            continue
        try:
            times_ms.append(float(parts[1]))
            mags.append(float(parts[2]))
            dists.append(float(parts[3]))
            p1.append(int(parts[4]))
            p2.append(int(parts[5]))
            p3.append(int(parts[6]))
            
            # PCR y PAT opcionales (9 columnas de datos + 1 opcional de Tag = 10 columnas max)
            if len(parts) >= 9:
                pcr.append(float(parts[7]))
                pat.append(float(parts[8]))
            else:
                pcr.append(-1.0)
                pat.append(-1.0)

            # Columna de etiqueta (Tag)
            if len(parts) >= 10:
                tags.append(parts[9].strip())
            elif len(parts) == 8: # Compatibilidad con logs anteriores que tenían Tag en la columna 8
                tags.append(parts[7].strip())
            else:
                tags.append("")
        except ValueError:
            pass

    return (np.array(times_ms), np.array(mags), np.array(dists),
            np.array(p1), np.array(p2), np.array(p3),
            np.array(pcr), np.array(pat), tags)

def find_peaks_and_valleys(time_sec, mags):
    """Detecta automáticamente picos y valles locales significativos en MAG."""
    # Filtro de media móvil para suavizar el ruido
    window_size = 15
    smoothed = np.convolve(mags, np.ones(window_size)/window_size, mode='same')
    
    # Parámetros para la detección
    min_mag = np.min(mags)
    max_mag = np.max(mags)
    threshold = min_mag + (max_mag - min_mag) * 0.15 # Umbral mínimo de detección
    
    peaks = []
    valleys = []

    # 1. Encontrar máximos locales (Picos)
    for i in range(1, len(smoothed) - 1):
        if smoothed[i] > smoothed[i-1] and smoothed[i] > smoothed[i+1]:
            if smoothed[i] > threshold:
                peaks.append(i)

    # Filtrar picos demasiado cercanos (juntar si están a menos de 2 segundos)
    filtered_peaks = []
    if peaks:
        filtered_peaks.append(peaks[0])
        for p in peaks[1:]:
            last_p = filtered_peaks[-1]
            time_diff = time_sec[p] - time_sec[last_p]
            # Si están cerca, mantener el más alto
            if time_diff < 2.0:
                if smoothed[p] > smoothed[last_p]:
                    filtered_peaks[-1] = p
            else:
                filtered_peaks.append(p)

    # 2. Encontrar valles (agujeros) entre picos significativos (detección de zona valle)
    # Si tenemos dos picos seguidos, el agujero real está en el punto mínimo entre ellos
    for k in range(len(filtered_peaks) - 1):
        p_start = filtered_peaks[k]
        p_end = filtered_peaks[k+1]
        
        # Si la separación en tiempo es menor a 9 segundos (duración de pasada típica)
        time_diff = time_sec[p_end] - time_sec[p_start]
        if time_diff < 9.0:
            sub_signal = smoothed[p_start:p_end]
            valley_in_sub = np.argmin(sub_signal)
            valley_idx = p_start + valley_in_sub
            
            val_start = smoothed[p_start]
            val_end = smoothed[p_end]
            val_valley = smoothed[valley_idx]
            
            # Criterio de zona valle:
            # 1. El menor de los dos picos debe superar el umbral de fugas (2200) para descartar ruido base.
            # 2. El desplome al valle debe ser significativo (al menos 12% de caída desde ambos picos).
            peak_min_height = min(val_start, val_end)
            drop_start = (val_start - val_valley) / val_start
            drop_end = (val_end - val_valley) / val_end
            
            if peak_min_height > 2200 and drop_start > 0.12 and drop_end > 0.12:
                valleys.append((p_start, valley_idx, p_end))

    return smoothed, filtered_peaks, valleys

def main():
    if len(sys.argv) < 2:
        print("ERROR: Debes especificar el archivo log CSV como argumento.")
        print("Uso: python3 plot_log.py sensor_log_20260618_175549.csv")
        sys.exit(1)

    csv_path = sys.argv[1]
    if not os.path.exists(csv_path):
        print(f"ERROR: El archivo '{csv_path}' no existe.")
        sys.exit(1)

    print(f"Procesando {csv_path}...")
    times_ms, mags, dists, p1, p2, p3, pcrs, pats, tags = parse_csv(csv_path)

    if len(times_ms) == 0:
        print("ERROR: El archivo está vacío o no tiene el formato correcto.")
        sys.exit(1)

    # Calcular tiempo relativo en segundos
    time_sec = (times_ms - times_ms[0]) / 1000.0

    # Detección inteligente de hitos
    smoothed, peaks, valleys = find_peaks_and_valleys(time_sec, mags)

    # Configuración de gráfico premium oscuro
    plt.style.use('dark_background')
    fig, ax1 = plt.subplots(figsize=(12, 6))
    
    # Nombre de ventana con el nombre del log
    log_name = os.path.basename(csv_path)
    fig.canvas.manager.set_window_title(f"Analizador de Fugas: {log_name}")

    # Espectro MAG de la Fuga (Eje Único)
    ax1.plot(time_sec, mags, 'o', color='#00f0ff', alpha=0.2, markersize=3, label="Datos Crudos")
    ax1.plot(time_sec, smoothed, color='#00f0ff', linewidth=2.0, label="Magnitud Suavizada (FFT)")
    ax1.set_ylabel("Magnitud de Fuga (MAG)", color='#00f0ff', fontsize=11)
    ax1.set_xlabel("Tiempo Transcurrido (segundos)", fontsize=11, color='#aaaaaa')
    ax1.tick_params(axis='y', labelcolor='#00f0ff')
    ax1.grid(True, linestyle='--', alpha=0.3)
    ax1.set_title(f"Perfil de Intensidad Acústica: {log_name}", fontsize=12, fontweight='bold')

    # Dibujar zonas de fuga (valles) entre picos (sombreado de área + línea central)
    for idx, v_info in enumerate(valleys):
        p_start, v_idx, p_end = v_info
        
        # Sombrear la zona del valle completa (del pico izquierdo al pico derecho)
        ax1.axvspan(time_sec[p_start], time_sec[p_end], color='#ff3333', alpha=0.15)
        
        # Línea central del valle (posición física del agujero)
        ax1.axvline(x=time_sec[v_idx], color='#ff3333', linestyle='--', alpha=0.9, linewidth=1.5)
        ax1.annotate("AGUJERO DE FUGA\n(Valle por Soplido)", xy=(time_sec[v_idx], smoothed[v_idx]),
                    xytext=(time_sec[v_idx], smoothed[v_idx] - (np.max(mags)*0.15) if smoothed[v_idx] > np.max(mags)*0.2 else smoothed[v_idx] + (np.max(mags)*0.15)),
                    arrowprops=dict(facecolor='#ff3333', shrink=0.08, width=1.0, headwidth=6),
                    fontsize=9, color='#ff3333', fontweight='bold', ha='center')

    # Agregar leyenda con etiquetas si hay detecciones
    if len(valleys) > 0:
        from matplotlib.lines import Line2D
        from matplotlib.patches import Patch
        custom_lines = [
            Line2D([0], [0], color='#00f0ff', lw=2, label='Magnitud Suavizada (FFT)'),
            Patch(facecolor='#ff3333', edgecolor='none', alpha=0.25, label='Zona de Fuga (Muestreo)'),
            Line2D([0], [0], color='#ff3333', lw=1.5, ls='--', label='Centro de Agujero (Aut.)')
        ]
        ax1.legend(handles=custom_lines, loc='upper right')

    plt.tight_layout()

    # Guardar imagen PNG en la misma carpeta del log
    img_output_path = os.path.splitext(csv_path)[0] + ".png"
    plt.savefig(img_output_path, dpi=150)
    print(f"\n>>> Gráfico guardado con éxito como imagen en: {img_output_path}")
    print(">>> Abriendo ventana del gráfico interactivo. Cierra la ventana en tu laptop para finalizar.")
    
    # Mostrar gráfico en pantalla
    plt.show()

if __name__ == '__main__':
    main()
