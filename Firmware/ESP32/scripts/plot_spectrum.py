#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Intérprete y Visualizador de Calibración de Frecuencias (Optimizado para Promedio)
Requisitos: pip install pyserial matplotlib numpy
Uso: python3 plot_spectrum.py [puerto_serial]
"""

import sys
import time
import serial
import serial.tools.list_ports
import numpy as np
import matplotlib.pyplot as plt

# Frecuencias para las 32 bandas (0 Hz a 10000 Hz, 312.5 Hz por banda)
BANDS_COUNT = 32
FS = 20000
NYQUIST = FS / 2
BAND_WIDTH = NYQUIST / BANDS_COUNT
x_frequencies = np.arange(BANDS_COUNT) * BAND_WIDTH + (BAND_WIDTH / 2)

# Color premium del gráfico
CHART_COLOR = '#00f0ff' # Cyan brillante

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
    if len(sys.argv) > 1:
        port = sys.argv[1]
    else:
        port = find_esp32_port()
        if not port:
            print("ERROR: No se encontró ningún puerto USB-Serial activo.")
            print("Conecta el ESP32 o especifica el puerto: python3 plot_spectrum.py /dev/ttyUSB0")
            sys.exit(1)
            
    print(f"Conectando a {port} a 115200 baudios...")
    
    try:
        ser = serial.Serial(port, 115200, timeout=1)
        ser.reset_input_buffer()
    except Exception as e:
        print(f"ERROR: No se pudo abrir el puerto {port}: {e}")
        sys.exit(1)

    # Configuración de Matplotlib para un solo gráfico grande de alto rendimiento
    plt.style.use('dark_background')
    fig, ax = plt.subplots(figsize=(10, 6))
    fig.canvas.manager.set_window_title('Calibración de Fugas: Espectro Consolidado')
    
    ax.set_title("Espectro Promedio de Micrófonos Activos", color='white', fontsize=14, pad=15)
    ax.set_xlim(0, NYQUIST)
    ax.set_ylim(0, 100)
    ax.set_xlabel("Frecuencia (Hz)", fontsize=11, color='#aaaaaa')
    ax.set_ylabel("Magnitud Promedio (FFT)", fontsize=11, color='#aaaaaa')
    ax.grid(True, linestyle='--', alpha=0.3)
    
    # Dibujar barras iniciales
    bar = ax.bar(x_frequencies, np.zeros(BANDS_COUNT), width=BAND_WIDTH * 0.8, color=CHART_COLOR, alpha=0.85)
    
    # Texto de aviso central
    txt = ax.text(0.5, 0.5, '', transform=ax.transAxes,
                  ha='center', va='center', fontsize=20, color='#ff3333', fontweight='bold')

    plt.tight_layout()
    
    # Historial para guardar firmas
    spectra_history = []
    
    def on_key(event):
        if event.key in ['s', 'S']:
            if len(spectra_history) > 0:
                timestamp = int(time.time())
                os.makedirs("data", exist_ok=True)
                filename = os.path.join("data", f"leak_signature_{timestamp}.csv")
                print(f"\n[CALIBRACIÓN] Guardando firma promedio actual en: {filename}...")
                
                # Obtener el último espectro registrado
                last_spectrum = spectra_history[-1]
                
                with open(filename, 'w') as f:
                    f.write("Frecuencia_Hz,Magnitud\n")
                    for b in range(BANDS_COUNT):
                        f.write(f"{x_frequencies[b]:.1f},{last_spectrum[b]:.4f}\n")
                
                print(f"[CALIBRACIÓN] ¡Firma guardada correctamente en {filename}!")
            else:
                print("\n[CALIBRACIÓN] Error: No hay datos activos de espectro para guardar.")

    fig.canvas.mpl_connect('key_press_event', on_key)
    print("\n>>> LISTO. Graficando en tiempo real a alta velocidad.")
    print("Presiona la tecla 'S' en la ventana para registrar la firma promedio en un archivo CSV.")

    try:
        while plt.fignum_exists(fig.number):
            if ser.in_waiting > 0:
                try:
                    line = ser.readline().decode('utf-8', errors='ignore').strip()
                except Exception:
                    continue
                
                # Formato: FFT_DATA:AVG:val0,val1,...
                if line.startswith("FFT_DATA:AVG:"):
                    data_str = line.replace("FFT_DATA:AVG:", "")
                    
                    if data_str == "DISCONNECTED":
                        for rect in bar:
                            rect.set_height(0)
                        txt.set_text("TODOS LOS MICRÓFONOS DESCONECTADOS")
                        ax.set_facecolor('#1a0808')
                    else:
                        try:
                            magnitudes = np.array([float(x) for x in data_str.split(',')])
                            if len(magnitudes) == BANDS_COUNT:
                                for rect, h in zip(bar, magnitudes):
                                    rect.set_height(h)
                                txt.set_text("")
                                ax.set_facecolor('#000000')
                                
                                # Escala dinámica inteligente
                                max_val = np.max(magnitudes)
                                current_ylim = ax.get_ylim()[1]
                                if max_val > current_ylim * 0.9:
                                    ax.set_ylim(0, max_val * 1.3)
                                elif max_val < current_ylim * 0.4 and current_ylim > 50:
                                    ax.set_ylim(0, max_val * 2.0 if max_val > 10 else 50)
                                    
                                spectra_history.append(magnitudes)
                                if len(spectra_history) > 10:
                                    spectra_history.pop(0)
                        except Exception:
                            pass
            
            plt.pause(0.005)
            
    except KeyboardInterrupt:
        print("\nCerrando visualizador...")
    finally:
        ser.close()
        print("Puerto serial liberado.")

if __name__ == '__main__':
    main()
