#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Registrador de Datos en Tiempo Real (Data Logger) para ESP32
Guarda la trama de datos con marcas de tiempo precisas en un archivo CSV.
Requisitos: pip install pyserial
Uso: python3 log_data.py [puerto_serial]
"""

import sys
import os
import time
import datetime
import re
import serial
import serial.tools.list_ports

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
            print("Conecta el ESP32 o especifica el puerto: python3 log_data.py /dev/ttyUSB0")
            sys.exit(1)
            
    print(f"Conectando a {port} a 115200 baudios...")
    
    try:
        ser = serial.Serial(port, 115200, timeout=1)
        ser.reset_input_buffer()
    except Exception as e:
        print(f"ERROR: No se pudo abrir el puerto {port}: {e}")
        sys.exit(1)

    # Crear el archivo CSV
    timestamp_str = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs("data", exist_ok=True)
    filename = os.path.join("data", f"sensor_log_{timestamp_str}.csv")
    
    print(f"Creando archivo de registro: {filename}")
    try:
        f = open(filename, 'w')
        f.write("Timestamp,Epoch_Time_ms,MAG,D,P1,P2,P3,PCR,PAT,Tag\n")
        f.flush()
    except Exception as e:
        print(f"ERROR: No se pudo crear el archivo {filename}: {e}")
        ser.close()
        sys.exit(1)

    # Expresión regular para parsear la trama: MAG:%.4f,D:%.1f,P1:%d,P2:%d,P3:%d (opcionalmente con PCR y PAT)
    data_pattern = re.compile(r"MAG:([-\d.]+),D:([-\d.]+),P1:([-\d]+),P2:([-\d]+),P3:([-\d]+)(?:,PCR:([-\d.]+),PAT:([-\d.]+))?")

    # Inicializar matplotlib para tiempo real de forma segura (tolerante a fallos de DISPLAY)
    has_matplotlib = False
    try:
        import matplotlib
        import matplotlib.pyplot as plt
        from matplotlib.widgets import Button
        
        plt.style.use('dark_background')
        fig, ax = plt.subplots(figsize=(10, 5))
        fig.canvas.manager.set_window_title(f"Registro en Vivo: {filename}")
        
        # Dejar espacio en la parte inferior para el botón
        plt.subplots_adjust(bottom=0.22)
        
        line_plot, = ax.plot([], [], color='#00f0ff', linewidth=2.0, label="Magnitud (MAG)")
        ax.set_ylabel("Magnitud de Fuga (MAG)", color='#00f0ff', fontsize=11)
        ax.set_xlabel("Tiempo Relativo (segundos)", fontsize=11, color='#aaaaaa')
        ax.grid(True, linestyle='--', alpha=0.3)
        ax.set_title("Monitoreo de Intensidad Acústica en Tiempo Real", fontsize=12, fontweight='bold')
        
        # Crear botón interactivo para marcar fugas
        ax_btn = plt.axes([0.4, 0.04, 0.2, 0.075])
        btn_fuga = Button(ax_btn, '¡MARCAR FUGA!', color='#ff3333', hovercolor='#ff5555')
        btn_fuga.label.set_color('white')
        btn_fuga.label.set_weight('bold')
        
        manual_leak_flag = False
        def on_click(event):
            nonlocal manual_leak_flag
            manual_leak_flag = True
            print("\n[MARCA MANUAL] >>> ¡Fuga marcada por el usuario! <<<")
            
        btn_fuga.on_clicked(on_click)
        
        plot_times = []
        plot_mags = []
        start_time_ms = None
        last_plot_update = 0.0
        
        plt.ion()
        plt.show(block=False)
        has_matplotlib = True
        print(">>> Gráfico en tiempo real con botón interactivo activado.")
    except Exception as e:
        print(f"ADVERTENCIA: No se pudo iniciar el gráfico en tiempo real ({e}).")
        print("El registro continuará únicamente en la consola y en el archivo CSV.")

    print("\n>>> INICIANDO REGISTRO DE DATOS. Presiona Ctrl+C para detener y finalizar.")
    print("-" * 85)
    print(f"{'Marca de Tiempo':<24} | {'MAG':<10} | {'Dist. (D)':<10} | {'P1':<5} | {'P2':<5} | {'P3':<5}")
    print("-" * 85)

    samples_count = 0
    try:
        while True:
            if ser.in_waiting > 0:
                try:
                    # Leer línea y decodificar
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                except Exception:
                    continue
                
                # Buscar patrón en la línea
                match = data_pattern.search(line)
                if match:
                    # Obtener marcas de tiempo de la laptop
                    now = datetime.datetime.now()
                    now_str = now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3] # Con milisegundos
                    epoch_ms = int(time.time() * 1000)

                    # Extraer variables (y valores opcionales PCR/PAT continuos)
                    mag_val = match.group(1)
                    d_val = match.group(2)
                    p1_val = match.group(3)
                    p2_val = match.group(4)
                    p3_val = match.group(5)
                    pcr_val = match.group(6) if match.group(6) is not None else "-1.0"
                    pat_val = match.group(7) if match.group(7) is not None else "-1.0"

                    # Determinar si hay etiqueta manual
                    tag_str = ""
                    if has_matplotlib and manual_leak_flag:
                        tag_str = "FUGA"

                    # Guardar en CSV
                    f.write(f"{now_str},{epoch_ms},{mag_val},{d_val},{p1_val},{p2_val},{p3_val},{pcr_val},{pat_val},{tag_str}\n")
                    f.flush() # Guardar inmediatamente en disco
                    samples_count += 1

                    # Imprimir en consola en tiempo real
                    if tag_str == "FUGA":
                        print(f"{now_str:<24} | {mag_val:<10} | {d_val + ' cm':<10} | {p1_val:<5} | {p2_val:<5} | {p3_val:<5} | <<< FUGA MANUAL >>>")
                    else:
                        print(f"{now_str:<24} | {mag_val:<10} | {d_val + ' cm':<10} | {p1_val:<5} | {p2_val:<5} | {p3_val:<5}")

                    # Actualizar gráfico en tiempo real
                    if has_matplotlib and plt.fignum_exists(fig.number):
                        if start_time_ms is None:
                            start_time_ms = epoch_ms
                        
                        try:
                            mag_float = float(mag_val)
                            current_time_sec = (epoch_ms - start_time_ms) / 1000.0
                            
                            plot_times.append(current_time_sec)
                            plot_mags.append(mag_float)
                            
                            # Si se acaba de marcar una fuga, dibujar la línea vertical permanente
                            if tag_str == "FUGA":
                                ax.axvline(x=current_time_sec, color='#ff00ff', linestyle='-.', alpha=0.8, linewidth=1.5)
                                ax.text(current_time_sec, 0.85, 'FUGA MANUAL', color='#ff00ff', fontsize=8, fontweight='bold', ha='right', rotation=90, transform=ax.get_xaxis_transform())
                                manual_leak_flag = False # Consumir el flag
                            
                            # Limitar actualizaciones a máx 20 FPS (cada 50 ms) para no sobrecargar
                            now_time = time.time()
                            if now_time - last_plot_update >= 0.05:
                                last_plot_update = now_time
                                
                                # Gráfico deslizante (últimos 200 puntos, aprox. 10-20 segundos de historial visible)
                                display_times = plot_times[-200:]
                                display_mags = plot_mags[-200:]
                                
                                line_plot.set_data(display_times, display_mags)
                                
                                # Ajustar límites de visualización
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
                # Dar respiro al CPU
                time.sleep(0.002)
                    
    except KeyboardInterrupt:
        print("\n\nDeteniendo el registro de datos...")
    finally:
        f.close()
        ser.close()
        if has_matplotlib:
            try:
                plt.close('all')
            except Exception:
                pass
        print("-" * 85)
        print(f"REGISTRO FINALIZADO EXITOSAMENTE.")
        print(f"Total de muestras guardadas: {samples_count}")
        print(f"Archivo guardado en: {os.path.abspath(filename)}")
        print("-" * 85)

if __name__ == '__main__':
    main()
