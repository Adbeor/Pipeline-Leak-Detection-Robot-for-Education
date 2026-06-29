/**
 * @file main.c
 * @brief ESP32 Dual-Core: 4x Mic Analógico (FFT 13–16 kHz) + 4x HC-SR04
 *
 * ARQUITECTURA:
 *   Core 0 (Task: hcsr04_uart_task)
 *     - Lee 4× HC-SR04 secuencialmente
 *     - Recibe resultado FFT via Queue
 *     - Envía trama UART: MAG:X.XXX,D:XXX.X,P1:X,P2:X,P3:X\n
 *
 *   Core 1 (Task: audio_fft_task)
 *     - Muestrea 4 ADC en secuencia a ~160 kHz total (~40 kHz/canal)
 *     - Aplica ventana Hann + FFT de 1024 puntos por micrófono (esp_dsp)
 *     - Promedia magnitud en banda 13–16 kHz entre los 4 micrófonos
 *     - Envía resultado a Queue compartida
 *
 * PINES (todos en ADC1 para evitar conflicto con WiFi):
 *   Micrófonos:
 *     MIC0 → GPIO32 (ADC1_CH4)
 *     MIC1 → GPIO33 (ADC1_CH5)
 *     MIC2 → GPIO34 (ADC1_CH6)
 *     MIC3 → GPIO35 (ADC1_CH7)
 *
 *   HC-SR04 (TRIGGER / ECHO):
 *     HCSR04_MAIN (envía distancia)  → TRIG: GPIO 4  | ECHO: GPIO 5
 *     HCSR04_P1                      → TRIG: GPIO 18 | ECHO: GPIO 19
 *     HCSR04_P2                      → TRIG: GPIO 21 | ECHO: GPIO 22
 *     HCSR04_P3                      → TRIG: GPIO 23 | ECHO: GPIO 25
 *
 *   UART TX → GPIO 17 (UART2)   [conectar a RX del myRIO]
 *   UART RX → GPIO 16 (UART2)   [no usado, pero declarado]
 *
 * NOTA PINES ADC:
 *   GPIO32 y GPIO33 son bidireccionales; evita pull-ups/pull-downs activos
 *   en esos pines para no distorsionar la lectura analógica.
 *   GPIO34 y GPIO35 son input-only (no tienen driver de salida interno).
 *
 * DEPENDENCIAS (idf_component.yml o CMakeLists):
 *   - esp_adc
 *   - esp_timer
 *   - esp_dsp  (componente oficial: idf-extra-components/esp-dsp)
 *   - driver
 *   - freertos
 *
 * COMPILACIÓN:
 *   idf.py set-target esp32
 *   idf.py build flash monitor
 */

#include <stdio.h>
#include <string.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "freertos/queue.h"
#include "driver/gpio.h"
#include "driver/uart.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "dsps_fft2r.h"   // esp-dsp: FFT radix-2
#include "dsps_wind.h"    // esp-dsp: ventanas

/* ─────────────────────────────────────────────
   CONSTANTES GENERALES
───────────────────────────────────────────── */
#define TAG                 "ESP32_SENSOR"

/* ADC / Audio */
#define NUM_MICS            4
#define FFT_SIZE            1024          // puntos por canal
#define SAMPLE_RATE_HZ      20000         // muestreo por canal (Hz) (bajado a 20 kHz para precisión del ADC)
#define BAND_LOW_HZ         4000
#define BAND_HIGH_HZ        8000

/* Frecuencia de resolución FFT: Fs / N */
#define FFT_FREQ_RES        ((float)SAMPLE_RATE_HZ / (float)FFT_SIZE)

/* Índices de bin correspondientes a 13–16 kHz */
#define BIN_LOW             ((int)(BAND_LOW_HZ  / FFT_FREQ_RES))   // ~333
#define BIN_HIGH            ((int)(BAND_HIGH_HZ / FFT_FREQ_RES))   // ~410

/* HC-SR04 */
#define HCSR04_TIMEOUT_US   25000         // 25 ms → ~4.3 m máximo
#define PROXIMITY_THRESHOLD_CM 10.0f

/* UART */
#define UART_PORT           UART_NUM_2
#define UART_BAUD           115200
#define UART_TX_PIN         17
#define UART_RX_PIN         16
#define UART_BUF_SIZE       256

/* ─────────────────────────────────────────────
   PINES ADC (canales ADC1)
───────────────────────────────────────────── */
static const adc_channel_t adc_channels[] = {
    ADC_CHANNEL_4,   // GPIO32
    ADC_CHANNEL_5,   // GPIO33
    ADC_CHANNEL_6,   // GPIO34
    ADC_CHANNEL_7,   // GPIO35
};

static const gpio_num_t adc_gpios[] = {
    GPIO_NUM_32,
    GPIO_NUM_33,
    GPIO_NUM_34,
    GPIO_NUM_35,
};

/* ─────────────────────────────────────────────
   PINES HC-SR04
───────────────────────────────────────────── */
typedef struct {
    gpio_num_t trig;
    gpio_num_t echo;
} hcsr04_pins_t;

static const hcsr04_pins_t hcsr04[4] = {
    {GPIO_NUM_4,  GPIO_NUM_5},   // MAIN → envía distancia
    {GPIO_NUM_18, GPIO_NUM_19},  // P1
    {GPIO_NUM_21, GPIO_NUM_22},  // P2
    {GPIO_NUM_23, GPIO_NUM_25},  // P3
};

/* ─────────────────────────────────────────────
   QUEUE INTER-CORE
───────────────────────────────────────────── */
static QueueHandle_t fft_result_queue;

/* ─────────────────────────────────────────────
   BUFFERS GLOBALES (Core 1 los usa exclusivamente)
───────────────────────────────────────────── */
// Cada buffer: parte real [0,2,4,...] y parte imaginaria [1,3,5,...] intercaladas
// esp_dsp trabaja con float interleaved: [r0,i0,r1,i1,...]
static float fft_buf[FFT_SIZE * 2];   // reutilizado para cada mic
static float hann_window[FFT_SIZE];
static int   adc_raw[NUM_MICS][FFT_SIZE];  // muestras crudas

/* ─────────────────────────────────────────────
   HANDLE ADC
───────────────────────────────────────────── */
static adc_oneshot_unit_handle_t adc_handle;

/* ══════════════════════════════════════════════
   FUNCIONES AUXILIARES
══════════════════════════════════════════════ */

/**
 * @brief Inicializa UART2 para comunicación con myRIO.
 */
static void uart_init(void)
{
    uart_config_t cfg = {
        .baud_rate  = UART_BAUD,
        .data_bits  = UART_DATA_8_BITS,
        .parity     = UART_PARITY_DISABLE,
        .stop_bits  = UART_STOP_BITS_1,
        .flow_ctrl  = UART_HW_FLOWCTRL_DISABLE,
    };
    ESP_ERROR_CHECK(uart_param_config(UART_PORT, &cfg));
    ESP_ERROR_CHECK(uart_set_pin(UART_PORT,
                                 UART_TX_PIN, UART_RX_PIN,
                                 UART_PIN_NO_CHANGE, UART_PIN_NO_CHANGE));
    ESP_ERROR_CHECK(uart_driver_install(UART_PORT, UART_BUF_SIZE * 2, 0, 0, NULL, 0));
    ESP_LOGI(TAG, "UART2 inicializado @ %d baud (TX=GPIO%d)", UART_BAUD, UART_TX_PIN);
}

/**
 * @brief Inicializa ADC1 en modo oneshot con atenuación 11 dB (0–3.3 V).
 */
static void adc_init(void)
{
    adc_oneshot_unit_init_cfg_t unit_cfg = {
        .unit_id  = ADC_UNIT_1,
        .ulp_mode = ADC_ULP_MODE_DISABLE,
    };
    ESP_ERROR_CHECK(adc_oneshot_new_unit(&unit_cfg, &adc_handle));

    adc_oneshot_chan_cfg_t chan_cfg = {
        .bitwidth = ADC_BITWIDTH_12,
        .atten    = ADC_ATTEN_DB_12,   // rango completo 0–3.3 V
    };
    for (int i = 0; i < NUM_MICS; i++) {
        ESP_ERROR_CHECK(adc_oneshot_config_channel(adc_handle, adc_channels[i], &chan_cfg));
        // Configurar pull-down para los pines bidireccionales GPIO32 y GPIO33
        if (adc_gpios[i] == GPIO_NUM_32 || adc_gpios[i] == GPIO_NUM_33) {
            gpio_set_pull_mode(adc_gpios[i], GPIO_PULLDOWN_ONLY);
        }
    }
    ESP_LOGI(TAG, "ADC1 inicializado (%d canales, 12-bit, atten 12 dB)", NUM_MICS);
}

/**
 * @brief Inicializa GPIO de todos los HC-SR04.
 */
static void hcsr04_gpio_init(void)
{
    for (int i = 0; i < 4; i++) {
        gpio_reset_pin(hcsr04[i].trig);
        gpio_set_direction(hcsr04[i].trig, GPIO_MODE_OUTPUT);
        gpio_set_level(hcsr04[i].trig, 0);

        gpio_reset_pin(hcsr04[i].echo);
        gpio_set_direction(hcsr04[i].echo, GPIO_MODE_INPUT);
    }
    ESP_LOGI(TAG, "HC-SR04 GPIOs inicializados");
}

/**
 * @brief Mide distancia con HC-SR04.
 * @param idx  Índice del sensor (0–3)
 * @return Distancia en cm, o -1.0f si hay timeout.
 */
static float hcsr04_measure_cm(int idx)
{
    /* Pulso TRIGGER: 10 µs */
    gpio_set_level(hcsr04[idx].trig, 1);
    esp_rom_delay_us(10);
    gpio_set_level(hcsr04[idx].trig, 0);

    /* Esperar flanco de subida en ECHO */
    int64_t t_start = esp_timer_get_time();
    while (gpio_get_level(hcsr04[idx].echo) == 0) {
        if ((esp_timer_get_time() - t_start) > HCSR04_TIMEOUT_US) {
            return -1.0f;
        }
    }

    /* Medir duración del pulso ECHO */
    int64_t echo_start = esp_timer_get_time();
    while (gpio_get_level(hcsr04[idx].echo) == 1) {
        if ((esp_timer_get_time() - echo_start) > HCSR04_TIMEOUT_US) {
            return -1.0f;
        }
    }
    int64_t echo_end = esp_timer_get_time();

    /* Distancia: tiempo_us × velocidad_sonido / 2 */
    float duration_us = (float)(echo_end - echo_start);
    return (duration_us * 0.0343f) / 2.0f;   // cm
}

/* ══════════════════════════════════════════════
   TASK CORE 1 — AUDIO + FFT
══════════════════════════════════════════════ */
static void audio_fft_task(void *pvParameters)
{
    ESP_LOGI(TAG, "[Core1] audio_fft_task iniciado");

    /* Inicializar tabla FFT de esp_dsp (obligatorio una sola vez) */
    ESP_ERROR_CHECK(dsps_fft2r_init_fc32(NULL, FFT_SIZE));

    /* Generar ventana Hann */
    dsps_wind_hann_f32(hann_window, FFT_SIZE);

    /* Período entre muestras para mantener 20 kHz (50 µs) */
    const int64_t sample_period_us = 1000000LL / SAMPLE_RATE_HZ;

    while (1) {
        float band_magnitude_sum = 0.0f;
        int active_mics_count = 0;
        static uint32_t last_log_time[4] = {0, 0, 0, 0};

        for (int m = 0; m < NUM_MICS; m++) {
            /* ── 1. MUESTREO secuencial de 1024 muestras para el micrófono 'm' ── */
            for (int n = 0; n < FFT_SIZE; n++) {
                int64_t t_sample = esp_timer_get_time();
                adc_oneshot_read(adc_handle, adc_channels[m], &adc_raw[m][n]);
                
                /* Esperar para mantener los 20 kHz por canal */
                int64_t elapsed = esp_timer_get_time() - t_sample;
                if (elapsed < sample_period_us) {
                    esp_rom_delay_us((uint32_t)(sample_period_us - elapsed));
                }
            }

            /* ── Chequeo de conexión/funcionamiento del micrófono ── */
            float sum_raw = 0.0f;
            for (int n = 0; n < FFT_SIZE; n++) {
                sum_raw += adc_raw[m][n];
            }
            float avg_raw = sum_raw / FFT_SIZE;

            float sum_diff = 0.0f;
            for (int n = 0; n < FFT_SIZE; n++) {
                sum_diff += fabsf((float)adc_raw[m][n] - avg_raw);
            }
            float avg_diff = sum_diff / FFT_SIZE;

            // Si está desconectado (pull-down a 0V o corto a 3.3V)
            if (avg_raw < 500.0f || avg_raw > 3500.0f) {
                uint32_t now = esp_log_timestamp();
                if (now - last_log_time[m] > 5000) {
                    ESP_LOGW(TAG, "Mic %d Disconnected (Out of Bounds): avg_raw=%.1f, avg_diff=%.1f", m, avg_raw, avg_diff);
                    last_log_time[m] = now;
                }
                continue; // saltear procesamiento de este mic y seguir con el siguiente
            }

            /* ── 2. Cargar muestras en el buffer e implementar ventana Hann ── */
            for (int n = 0; n < FFT_SIZE; n++) {
                float sample = (float)(adc_raw[m][n] - 2048);  // centro en 0
                fft_buf[2 * n]     = sample * hann_window[n];  // parte real
                fft_buf[2 * n + 1] = 0.0f;                     // parte imaginaria
            }

            /* ── 3. FFT radix-2 y ordenamiento bit-reverse ── */
            dsps_fft2r_fc32(fft_buf, FFT_SIZE);
            dsps_bit_rev_fc32(fft_buf, FFT_SIZE);

            /* ── 4. Acumular magnitud en rango [BIN_LOW, BIN_HIGH] ── */
            float mic_band_sum = 0.0f;
            int   bin_count    = BIN_HIGH - BIN_LOW + 1;
            for (int k = BIN_LOW; k <= BIN_HIGH; k++) {
                float re = fft_buf[2 * k];
                float im = fft_buf[2 * k + 1];
                mic_band_sum += sqrtf(re * re + im * im);
            }
            float avg_target = mic_band_sum / bin_count;

            /* ── 5. Acumular magnitud del resto del espectro (ruido de fondo) ── */
            float mic_env_sum = 0.0f;
            int   env_count   = 0;
            // Bins bajos: evitamos 0-4 para ignorar el offset DC y zumbidos de baja frecuencia
            for (int k = 5; k < BIN_LOW; k++) {
                float re = fft_buf[2 * k];
                float im = fft_buf[2 * k + 1];
                mic_env_sum += sqrtf(re * re + im * im);
                env_count++;
            }
            // Bins altos: de BIN_HIGH+1 hasta el límite Nyquist (512)
            int nyquist_bin = FFT_SIZE / 2;
            for (int k = BIN_HIGH + 1; k < nyquist_bin; k++) {
                float re = fft_buf[2 * k];
                float im = fft_buf[2 * k + 1];
                mic_env_sum += sqrtf(re * re + im * im);
                env_count++;
            }
            float avg_env = mic_env_sum / env_count;

            /* Magnitud Relativa: relación entre la banda objetivo y el ruido ambiente */
            // Evitamos división por cero asegurando un ruido mínimo de 0.01f
            float rel_magnitude = avg_target / (avg_env > 0.01f ? avg_env : 0.01f);
            band_magnitude_sum += rel_magnitude;
            active_mics_count++;
        }

        /* Promedio final entre los micrófonos conectados/activos */
        float avg_magnitude;
        if (active_mics_count > 0) {
            avg_magnitude = band_magnitude_sum / active_mics_count;
        } else {
            avg_magnitude = -1.0f; // Todos están desconectados
        }

        /* ── 3. Enviar resultado a Core 0 via Queue ── */
        // Bloqueo máximo 0 ms: si la queue está llena, se descarta y se recalcula
        if (xQueueOverwrite(fft_result_queue, &avg_magnitude) != pdTRUE) {
            ESP_LOGW(TAG, "Queue FFT llena, dato descartado");
        }
        // Nota: xQueueOverwrite siempre sobreescribe (queue de longitud 1)

        // Evitar que se active el Watchdog (TWDT) en el Core 1 y reducir uso de CPU
        vTaskDelay(pdMS_TO_TICKS(50));
    }
}

/* ══════════════════════════════════════════════
   TASK CORE 0 — HC-SR04 + UART
══════════════════════════════════════════════ */
static void hcsr04_uart_task(void *pvParameters)
{
    ESP_LOGI(TAG, "[Core0] hcsr04_uart_task iniciado");

    char uart_buf[UART_BUF_SIZE];
    float fft_magnitude = 0.0f;

    while (1) {
        /* ── 1. Leer último resultado FFT disponible (no bloqueante) ── */
        xQueuePeek(fft_result_queue, &fft_magnitude, 0);

        /* ── 2. Leer HC-SR04 MAIN (índice 0) → distancia ── */
        float dist_main = hcsr04_measure_cm(0);
        vTaskDelay(pdMS_TO_TICKS(10));   // espera entre sensores (evita interferencia acústica)

        /* ── 3. Leer HC-SR04 P1, P2, P3 → proximidad ── */
        int prox[3];
        for (int i = 1; i <= 3; i++) {
            float d = hcsr04_measure_cm(i);
            if (d < 0.0f) {
                prox[i - 1] = -1;  // Desconectado o error
            } else if (d <= PROXIMITY_THRESHOLD_CM) {
                prox[i - 1] = 1;   // Obstáculo detectado
            } else {
                prox[i - 1] = 0;   // Sin obstáculo
            }
            vTaskDelay(pdMS_TO_TICKS(10));
        }

        /* ── 4. Armar y enviar trama UART y Logs ── */
        int len = snprintf(uart_buf, sizeof(uart_buf),
                           "MAG:%.4f,D:%.1f,P1:%d,P2:%d,P3:%d\n",
                           fft_magnitude, dist_main, prox[0], prox[1], prox[2]);
        
        /* Enviar trama cruda a myRIO por UART2 (Termina en \n) */
        uart_write_bytes(UART_PORT, uart_buf, len);

        /* Enviar a la Laptop por el cable USB usando el sistema de Logs de ESP-IDF */
        // Nota: Le quitamos el '\n' al string original pasándolo con "%.*s" y (len - 1)
        // porque ESP_LOGI ya añade su propio salto de línea al final de forma automática.
        ESP_LOGI(TAG, "DATA -> %.*s", len - 1, uart_buf);

        // Pequeño yield para no bloquear el scheduler del Core 0
        vTaskDelay(pdMS_TO_TICKS(1));
    }
}

/* ══════════════════════════════════════════════
   APP MAIN
══════════════════════════════════════════════ */
void app_main(void)
{
    ESP_LOGI(TAG, "=== ESP32 Mic-FFT + HC-SR04 ===");
    ESP_LOGI(TAG, "FFT: %d pts | Fs: %d Hz | Banda: %d–%d Hz (bins %d–%d)",
             FFT_SIZE, SAMPLE_RATE_HZ, BAND_LOW_HZ, BAND_HIGH_HZ, BIN_LOW, BIN_HIGH);

    /* ── Inicializar periféricos ── */
    uart_init();
    adc_init();
    hcsr04_gpio_init();

    /* ── Queue de longitud 1 (siempre tiene el último valor FFT) ── */
    fft_result_queue = xQueueCreate(1, sizeof(float));
    configASSERT(fft_result_queue);

    /* ── Rellenar queue con 0 para que Core 0 no quede bloqueado ── */
    float init_val = 0.0f;
    xQueueSend(fft_result_queue, &init_val, 0);

    /* ── Crear tareas pinned a su core ── */
    xTaskCreatePinnedToCore(
        audio_fft_task,
        "audio_fft",
        8192,           // stack (bytes): FFT necesita bastante
        NULL,
        5,              // prioridad alta
        NULL,
        1               // Core 1
    );

    xTaskCreatePinnedToCore(
        hcsr04_uart_task,
        "hcsr04_uart",
        4096,
        NULL,
        5,
        NULL,
        0               // Core 0
    );

    ESP_LOGI(TAG, "Tasks creadas. Sistema corriendo.");
    // app_main puede terminar; las tasks siguen vivas
}
