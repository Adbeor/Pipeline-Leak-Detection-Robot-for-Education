"""
ESP32 FFT Real-Time Plotter
Lee datos del puerto serial en formato BEGIN/frecuencia,magnitud/END
y grafica el espectro en tiempo real con matplotlib.
"""

import serial
import matplotlib.pyplot as plt
import matplotlib.animation as animation
import numpy as np
import argparse
import sys

# ── Configuración ────────────────────────────────────────────────────────────
PORT        = "/dev/ttyUSB0"        # Cambia a tu puerto: /dev/ttyUSB0, /dev/ttyACM0, etc.
BAUD_RATE   = 115200
SAMPLE_RATE = 44100
FFT_SIZE    = 1024
MAX_FREQ_HZ = 22000   # o 20000 para excluir el límite de audición humano       # Límite superior del eje X (Nyquist = SAMPLE_RATE/2)
# ─────────────────────────────────────────────────────────────────────────────


def parse_args():
    parser = argparse.ArgumentParser(description="ESP32 FFT Real-Time Plotter")
    parser.add_argument("--port",      default=PORT,        help="Puerto serial")
    parser.add_argument("--baud",      default=BAUD_RATE,   type=int)
    parser.add_argument("--maxfreq",   default=MAX_FREQ_HZ, type=int,
                        help="Frecuencia máxima mostrada en Hz")
    parser.add_argument("--static",    action="store_true",
                        help="Captura un solo frame y lo guarda como PNG")
    return parser.parse_args()


def read_fft_frame(ser: serial.Serial):
    """
    Lee un frame completo del puerto serial.
    Formato esperado:
        BEGIN
        31.2,0.0045
        62.5,0.0120
        ...
        END
    Devuelve (freqs, mags) como arrays numpy, o (None, None) si falla.
    """
    # Espera la línea BEGIN
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line == "BEGIN":
            break

    freqs, mags = [], []
    while True:
        line = ser.readline().decode("utf-8", errors="ignore").strip()
        if line == "END":
            break
        if "," in line:
            try:
                f, m = line.split(",")
                freqs.append(float(f))
                mags.append(float(m))
            except ValueError:
                pass

    if not freqs:
        return None, None
    return np.array(freqs), np.array(mags)


def db_scale(mag: np.ndarray, ref: float = 1.0) -> np.ndarray:
    """Convierte magnitud lineal a dBFS."""
    with np.errstate(divide="ignore"):
        return 20.0 * np.log10(np.maximum(mag / ref, 1e-10))


# ── Modo estático ─────────────────────────────────────────────────────────────

def capture_static(args):
    print(f"Conectando a {args.port} @ {args.baud} baud…")
    with serial.Serial(args.port, args.baud, timeout=3) as ser:
        print("Esperando frame…")
        freqs, mags = read_fft_frame(ser)

    if freqs is None:
        print("No se recibieron datos.")
        sys.exit(1)

    mask = freqs <= args.maxfreq
    freqs, mags = freqs[mask], mags[mask]
    mags_db = db_scale(mags)

    fig, axes = plt.subplots(2, 1, figsize=(12, 7))
    fig.patch.set_facecolor("#0d0d0d")
    for ax in axes:
        ax.set_facecolor("#0d0d0d")
        ax.tick_params(colors="#cccccc")
        ax.xaxis.label.set_color("#cccccc")
        ax.yaxis.label.set_color("#cccccc")
        ax.title.set_color("#ffffff")
        for spine in ax.spines.values():
            spine.set_edgecolor("#333333")

    # Magnitud lineal
    axes[0].fill_between(freqs, mags, alpha=0.4, color="#00e5ff")
    axes[0].plot(freqs, mags, color="#00e5ff", linewidth=1)
    axes[0].set_title("Espectro FFT — Magnitud lineal", fontsize=13, pad=10)
    axes[0].set_xlabel("Frecuencia (Hz)")
    axes[0].set_ylabel("Amplitud")
    axes[0].set_xlim(0, args.maxfreq)

    # dBFS
    axes[1].fill_between(freqs, mags_db, alpha=0.4, color="#ff4081")
    axes[1].plot(freqs, mags_db, color="#ff4081", linewidth=1)
    axes[1].set_title("Espectro FFT — dBFS", fontsize=13, pad=10)
    axes[1].set_xlabel("Frecuencia (Hz)")
    axes[1].set_ylabel("dBFS")
    axes[1].set_xlim(0, args.maxfreq)

    plt.tight_layout()
    os.makedirs("data", exist_ok=True)
    out = os.path.join("data", "fft_capture.png")
    plt.savefig(out, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    print(f"Guardado: {out}")
    plt.show()


# ── Modo en tiempo real ───────────────────────────────────────────────────────

def realtime(args):
    print(f"Conectando a {args.port} @ {args.baud} baud…")
    ser = serial.Serial(args.port, args.baud, timeout=3)
    print("Streaming FFT en tiempo real. Cierra la ventana para salir.")

    # Número de bins que se mostrarán
    freq_res  = SAMPLE_RATE / FFT_SIZE
    n_bins    = int(args.maxfreq / freq_res)
    freqs_ref = np.arange(1, n_bins + 1) * freq_res

    fig, (ax_lin, ax_db) = plt.subplots(2, 1, figsize=(12, 7))
    fig.patch.set_facecolor("#0d0d0d")

    for ax in (ax_lin, ax_db):
        ax.set_facecolor("#0d0d0d")
        ax.tick_params(colors="#cccccc")
        ax.xaxis.label.set_color("#cccccc")
        ax.yaxis.label.set_color("#cccccc")
        ax.title.set_color("#ffffff")
        for spine in ax.spines.values():
            spine.set_edgecolor("#333333")

    zeros = np.zeros(n_bins)

    fill_lin  = ax_lin.fill_between(freqs_ref, zeros, alpha=0.35, color="#00e5ff")
    line_lin, = ax_lin.plot(freqs_ref, zeros, color="#00e5ff", linewidth=1)
    ax_lin.set_title("Espectro FFT — Magnitud lineal (tiempo real)", fontsize=12)
    ax_lin.set_xlabel("Frecuencia (Hz)")
    ax_lin.set_ylabel("Amplitud")
    ax_lin.set_xlim(0, args.maxfreq)
    ax_lin.set_ylim(0, 0.5)

    fill_db_data = db_scale(zeros + 1e-10)
    fill_db  = ax_db.fill_between(freqs_ref, fill_db_data, alpha=0.35, color="#ff4081")
    line_db, = ax_db.plot(freqs_ref, fill_db_data, color="#ff4081", linewidth=1)
    ax_db.set_title("Espectro FFT — dBFS (tiempo real)", fontsize=12)
    ax_db.set_xlabel("Frecuencia (Hz)")
    ax_db.set_ylabel("dBFS")
    ax_db.set_xlim(0, args.maxfreq)
    ax_db.set_ylim(-80, 0)

    peak_text = ax_lin.text(
        0.98, 0.93, "", transform=ax_lin.transAxes,
        ha="right", va="top", fontsize=10,
        color="#ffffff",
        bbox=dict(boxstyle="round,pad=0.3", facecolor="#111111", edgecolor="#444444")
    )

    plt.tight_layout()

    # Suavizado exponencial para reducir flickering
    ALPHA     = 0.6
    smoothed  = np.zeros(n_bins)

    def update(_frame):
        nonlocal smoothed, fill_lin, fill_db

        freqs, mags = read_fft_frame(ser)
        if freqs is None:
            return line_lin, line_db

        # Alinea bins recibidos con los esperados
        mask = freqs <= args.maxfreq
        freqs_in  = freqs[mask]
        mags_in   = mags[mask]

        # Interpola si el número de bins no coincide exactamente
        if len(mags_in) != n_bins:
            mags_aligned = np.interp(freqs_ref, freqs_in, mags_in,
                                     left=0.0, right=0.0)
        else:
            mags_aligned = mags_in

        # Suavizado exponencial
        smoothed = ALPHA * mags_aligned + (1 - ALPHA) * smoothed
        mags_db  = db_scale(smoothed)

        # Actualiza líneas
        line_lin.set_ydata(smoothed)
        line_db.set_ydata(mags_db)

        # Actualiza áreas rellenas (se recrean)
        fill_lin.remove()
        fill_db.remove()
        fill_lin = ax_lin.fill_between(freqs_ref, smoothed, alpha=0.35, color="#00e5ff")
        fill_db  = ax_db.fill_between(freqs_ref, mags_db,   alpha=0.35, color="#ff4081")

        # Autoescala eje Y lineal
        peak_mag = smoothed.max()
        ax_lin.set_ylim(0, max(peak_mag * 1.2, 0.01))

        # Texto pico
        peak_idx = smoothed.argmax()
        peak_text.set_text(
            f"Pico: {freqs_ref[peak_idx]:.1f} Hz  |  {mags_db[peak_idx]:.1f} dBFS"
        )

        return line_lin, line_db, peak_text

    ani = animation.FuncAnimation(
        fig, update,
        interval=50,        # ms entre frames de matplotlib
        blit=False,
        cache_frame_data=False
    )

    try:
        plt.show()
    finally:
        ser.close()
        print("Puerto cerrado.")


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    args = parse_args()
    if args.static:
        capture_static(args)
    else:
        realtime(args)
