#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Guía de Navegación Robótica para Detección de Fugas en Tiempo Real
Uso: python3 robot_guide.py [puerto_serial]
Requisitos: pip install matplotlib numpy pyserial
"""

import sys
import os
import time
import datetime
import re
import serial
import serial.tools.list_ports
import numpy as np
import matplotlib.pyplot as plt
from collections import deque

def find_esp32_port():
    """Busca automáticamente el puerto COM del ESP32."""
    ports = list(serial.tools.list_ports.comports())
    usb_ports = [p.device for p in ports if any(x in p.description.upper() for x in ['USB', 'UART', 'ACM', 'CH340', 'CP210'])]
    if usb_ports:
        return usb_ports[0]
    elif ports:
        return ports[0].device
    return None

def main():
    # Selección de puerto
    if len(sys.argv) > 1:
        port = sys.argv[1]
    else:
        port = find_esp32_port()
        if not port:
            print("ERROR: No se encontró ningún puerto USB-Serial activo.")
            print("Conecta el ESP32 o especifica el puerto: python3 robot_guide.py /dev/ttyUSB0")
            sys.exit(1)
            
    print(f"Conectando a {port} a 115200 baudios...")
    
    try:
        ser = serial.Serial(port, 115200, timeout=1)
        ser.reset_input_buffer()
    except Exception as e:
        print(f"ERROR: No se pudo abrir el puerto {port}: {e}")
        sys.exit(1)

    # Crear el archivo CSV para registrar los datos del experimento
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("data", exist_ok=True)
    filename = os.path.join("data", f"robot_guide_log_{timestamp_str}.csv")
    
    print(f"Registrando datos en: {filename}")
    try:
        f = open(filename, 'w')
        f.write("Timestamp,Epoch_Time_ms,MAG,D,P1,P2,P3,PCR,PAT,Instruction,Tag\n")
        f.flush()
    except Exception as e:
        print(f"ERROR: No se pudo crear el archivo {filename}: {e}")
        ser.close()
        sys.exit(1)

    # Expresión regular para parsear la trama (con soporte opcional para PCR y PAT)
    data_pattern = re.compile(r"MAG:([-\d.]+),D:([-\d.]+),P1:([-\d]+),P2:([-\d]+),P3:([-\d]+)(?:,PCR:([-\d.]+),PAT:([-\d.]+))?")

    # Configuración de Matplotlib interactivo
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(11, 6))
    fig.canvas.manager.set_window_title("Guía de Navegación Robótica - Detección de Fugas")
    
    # Línea de la señal de magnitud
    line_plot, = ax.plot([], [], color='#00f0ff', linewidth=2.5, label="Magnitud Acústica (MAG)")
    ax.set_ylabel("Magnitud de Fuga (MAG)", color='#00f0ff', fontsize=12)
    ax.set_xlabel("Tiempo (segundos)", fontsize=11, color='#aaaaaa')
    ax.grid(True, linestyle='--', alpha=0.3)
    ax.set_title("Navegador Robótico de Fugas de Aire en Tiempo Real", fontsize=14, fontweight='bold', pad=15)
    
    # Texto de instrucción gigante superpuesto en el gráfico
    bbox_props = dict(boxstyle="round,pad=0.5", fc="#222222", ec="#444444", lw=1.5, alpha=0.9)
    instruction_text = ax.text(0.5, 0.85, "BUSCANDO SEÑAL...", 
                               transform=ax.transAxes, 
                               fontsize=18, fontweight='bold', 
                               ha='center', va='center', 
                               color='#888888', bbox=bbox_props)

    # Historiales locales de datos
    plot_times = []
    plot_mags = []
    start_time_ms = None
    last_plot_update = 0.0
    
    # Buffers deslizantes para el algoritmo de guiado (últimos 40 samples)
    mags_window = deque(maxlen=40)
    times_window = deque(maxlen=40)
    
    # Parámetros del robot
    MAG_NOISE_THRESHOLD = 1500 # Ruido de fondo
    MAG_LEAK_THRESHOLD = 2500  # Nivel para considerar fuga real
    
    cooldown_fuga = 0 # Evita repetir detección de fuga de inmediato
    fuga_marcada_t = None
    
    plt.ion()
    plt.show(block=False)

    print("\n" + "="*80)
    print(" >>> INICIANDO GUÍA ROBÓTICA EN VIVO. Sigue las instrucciones del plotter <<<")
    print("="*80 + "\n")

    samples_count = 0
    try:
        while True:
            if ser.in_waiting > 0:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                except Exception:
                    continue
                
                match = data_pattern.search(line)
                if match:
                    now = datetime.datetime.now()
                    now_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
                    epoch_ms = int(time.time() * 1000)

                    # Obtener primer marca de tiempo
                    if start_time_ms is None:
                        start_time_ms = epoch_ms

                    # Extraer variables de la trama
                    mag_val = float(match.group(1))
                    d_val = float(match.group(2))
                    p1_val = int(match.group(3))
                    p2_val = int(match.group(4))
                    p3_val = int(match.group(5))
                    pcr_val = float(match.group(6)) if match.group(6) is not None else -1.0
                    pat_val = float(match.group(7)) if match.group(7) is not None else -1.0
                    
                    current_t = (epoch_ms - start_time_ms) / 1000.0
                    
                    # Añadir a historiales
                    plot_times.append(current_t)
                    plot_mags.append(mag_val)
                    mags_window.append(mag_val)
                    times_window.append(current_t)
                    
                    # --- ALGORITMO DE NAVEGACIÓN ROBÓTICA ---
                    instruction = "BUSCANDO SEÑAL..."
                    color_code = "\033[90m" # Gris por defecto
                    gui_color = "#888888"
                    tag_str = ""
                    
                    if cooldown_fuga > 0:
                        cooldown_fuga -= 1

                    if mag_val < MAG_NOISE_THRESHOLD:
                        instruction = "BUSCANDO SEÑAL..."
                        color_code = "\033[90m" # Gris
                        gui_color = "#888888"
                    else:
                        # Si tenemos suficientes muestras, calcular la pendiente filtrada
                        if len(mags_window) >= 15:
                            recent_avg = np.mean(list(mags_window)[-5:])
                            past_avg = np.mean(list(mags_window)[-15:-10])
                            slope = recent_avg - past_avg
                            
                            if slope > 150:
                                instruction = "¡ADELANTE! ➡️ (La señal está subiendo)"
                                color_code = "\033[92m\033[1m" # Verde Negrita
                                gui_color = "#55ff55"
                            elif slope < -150:
                                instruction = "¡ATRÁS! ⬅️ (Te alejaste o te pasaste)"
                                color_code = "\033[93m\033[1m" # Amarillo Negrita
                                gui_color = "#ffaa00"
                            else:
                                instruction = "ALINEANDO... ⚠️ (Señal estable)"
                                color_code = "\033[96m" # Cian
                                gui_color = "#00f0ff"
                        
                        # --- DETECCIÓN EN TIEMPO REAL DE VALLE (FUGA DIRECTA) ---
                        if len(mags_window) >= 30 and cooldown_fuga == 0:
                            # Suavizar ventana de análisis
                            recent_vals = list(mags_window)[-30:]
                            smoothed = np.convolve(recent_vals, np.ones(5)/5, mode='valid')
                            
                            if len(smoothed) >= 20:
                                min_idx = np.argmin(smoothed)
                                # Verificar que el mínimo esté bien centrado en el buffer
                                if 4 <= min_idx <= 15:
                                    min_val = smoothed[min_idx]
                                    left_peak = np.max(smoothed[:min_idx])
                                    right_peak = np.max(smoothed[min_idx:])
                                    peak_val = max(left_peak, right_peak)
                                    
                                    # La magnitud máxima debe superar el umbral mínimo de fugas
                                    # y la caída del valle debe ser al menos de un 8% con respecto al pico
                                    if peak_val > MAG_LEAK_THRESHOLD and (peak_val - min_val) / peak_val > 0.08:
                                        # Fuga detectada en la posición del valle
                                        instruction = "🎯 ¡FUGA DETECTADA AQUÍ! 🎯"
                                        color_code = "\033[91m\033[1m\033[5m" # Rojo Brillante / Parpadeante
                                        gui_color = "#ff3333"
                                        tag_str = "FUGA"
                                        cooldown_fuga = 50 # Cooldown de 2 segundos para no repetir
                                        
                                        # Obtener tiempo aproximado del valle
                                        idx_in_window = min_idx + 2
                                        fuga_marcada_t = list(times_window)[-30 + idx_in_window]

                    # Mostrar instrucción en consola
                    print(f"\r{now_str} | MAG: {mag_val:7.1f} | {color_code}{instruction:<42}\033[0m", end="", flush=True)

                    # Guardar fila en CSV
                    f.write(f"{now_str},{epoch_ms},{mag_val},{d_val},{p1_val},{p2_val},{p3_val},{pcr_val},{pat_val},{instruction},{tag_str}\n")
                    f.flush()
                    samples_count += 1

                    # Actualizar gráfico interactivo
                    if plt.fignum_exists(fig.number):
                        try:
                            # Dibujar línea vertical de la fuga si se detectó
                            if tag_str == "FUGA" and fuga_marcada_t is not None:
                                ax.axvline(x=fuga_marcada_t, color='#ff3333', linestyle='--', alpha=0.9, linewidth=2.0)
                                ax.text(fuga_marcada_t, 0.15, '🎯 FUGA DETECTADA', color='#ff3333', fontsize=9, fontweight='bold', ha='right', rotation=90, transform=ax.get_xaxis_transform())
                                # Sonar un pitido de consola rápido para dar feedback de audio
                                print("\a", end="")
                            
                            # Actualizar texto de instrucción
                            instruction_text.set_text(instruction)
                            instruction_text.set_color(gui_color)
                            # Actualizar color del borde del cuadro de texto según instrucción
                            bbox_props["ec"] = gui_color
                            instruction_text.set_bbox(bbox_props)
                            
                            # Mantener gráfico deslizante (últimos 300 puntos)
                            now_time = time.time()
                            if now_time - last_plot_update >= 0.05: # 20 Hz
                                last_plot_update = now_time
                                
                                display_times = plot_times[-300:]
                                display_mags = plot_mags[-300:]
                                
                                line_plot.set_data(display_times, display_mags)
                                
                                # Ajustar límites X y Y
                                min_x = display_times[0]
                                max_x = display_times[-1]
                                ax.set_xlim(min_x, max_x + 0.5 if max_x > min_x else min_x + 1.0)
                                
                                min_y = min(display_mags)
                                max_y = max(display_mags)
                                y_margin = max(1.0, (max_y - min_y) * 0.1)
                                ax.set_ylim(max(0.0, min_y - y_margin), max_y + y_margin)
                                
                                plt.pause(0.001)
                        except Exception:
                            pass
            else:
                time.sleep(0.002)

    except KeyboardInterrupt:
        print("\n\nDeteniendo navegador robótico...")
    finally:
        f.close()
        ser.close()
        try:
            plt.close('all')
        except Exception:
            pass
        print("\n" + "="*80)
        print("PROCESO TERMINADO")
        print(f"Total de muestras grabadas: {samples_count}")
        print(f"Log de guía robótica guardado en: {os.path.abspath(filename)}")
        print("="*80 + "\n")

if __name__ == '__main__':
    main()
