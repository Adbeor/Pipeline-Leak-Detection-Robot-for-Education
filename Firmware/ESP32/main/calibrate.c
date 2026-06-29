/**
 * @file calibrate.c
 * @brief Firmware de Calibración Optimizado: Promedia los micrófonos activos y los envía en una sola línea.
 */

#include <stdio.h>
#include <string.h>
#include <math.h>
#include "freertos/FreeRTOS.h"
#include "freertos/task.h"
#include "driver/gpio.h"
#include "esp_adc/adc_oneshot.h"
#include "esp_timer.h"
#include "esp_log.h"
#include "dsps_fft2r.h"
#include "dsps_wind.h"

#define TAG                 "ESP32_CALIBRATE"

#define NUM_MICS            1
#define FFT_SIZE            1024          // puntos por canal
#define SAMPLE_RATE_HZ      20000         // muestreo por canal (Hz)
#define BANDS_COUNT         32
#define BINS_PER_BAND       ( (FFT_SIZE / 2) / BANDS_COUNT ) // 512 / 32 = 16 bins por banda (~312.5 Hz)

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

static float fft_buf[FFT_SIZE * 2];
static float hann_window[FFT_SIZE];
static int   adc_raw[NUM_MICS][FFT_SIZE];
static adc_oneshot_unit_handle_t adc_handle;

/**
 * @brief Inicializa el ADC1 con atenuación de 11 dB.
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
        .atten    = ADC_ATTEN_DB_12,
    };
    for (int i = 0; i < NUM_MICS; i++) {
        ESP_ERROR_CHECK(adc_oneshot_config_channel(adc_handle, adc_channels[i], &chan_cfg));
        if (adc_gpios[i] == GPIO_NUM_32 || adc_gpios[i] == GPIO_NUM_33) {
            gpio_set_pull_mode(adc_gpios[i], GPIO_PULLDOWN_ONLY);
        }
    }
}

/**
 * @brief Tarea de análisis de audio optimizada.
 */
static void calibrate_task(void *pvParameters)
{
    ESP_ERROR_CHECK(dsps_fft2r_init_fc32(NULL, FFT_SIZE));
    dsps_wind_hann_f32(hann_window, FFT_SIZE);

    const int64_t sample_period_us = 1000000LL / SAMPLE_RATE_HZ;

    while (1) {
        float avg_bands[BANDS_COUNT] = {0};
        int active_mics = 0;

        for (int m = 0; m < NUM_MICS; m++) {
            /* ── Quick Check Conexión (Evita muestrear si está desconectado) ── */
            int quick_val;
            adc_oneshot_read(adc_handle, adc_channels[m], &quick_val);
            if (quick_val < 500 || quick_val > 3500) {
                continue; // Saltear inmediatamente (toma < 10 microsegundos)
            }

            /* ── 1. MUESTREO ── */
            for (int n = 0; n < FFT_SIZE; n++) {
                int64_t t_sample = esp_timer_get_time();
                adc_oneshot_read(adc_handle, adc_channels[m], &adc_raw[m][n]);
                int64_t elapsed = esp_timer_get_time() - t_sample;
                if (elapsed < sample_period_us) {
                    esp_rom_delay_us((uint32_t)(sample_period_us - elapsed));
                }
            }

            /* ── 2. Cargar Hann y FFT ── */
            for (int n = 0; n < FFT_SIZE; n++) {
                float sample = (float)(adc_raw[m][n] - 2048);
                fft_buf[2 * n]     = sample * hann_window[n];
                fft_buf[2 * n + 1] = 0.0f;
            }

            dsps_fft2r_fc32(fft_buf, FFT_SIZE);
            dsps_bit_rev_fc32(fft_buf, FFT_SIZE);

            /* ── 3. Calcular magnitudes y acumular en bandas ── */
            for (int b = 0; b < BANDS_COUNT; b++) {
                float sum_mag = 0.0f;
                int start_bin = b * BINS_PER_BAND;
                int end_bin = (b + 1) * BINS_PER_BAND;

                for (int k = start_bin; k < end_bin; k++) {
                    if (k < 5) {
                        continue; // Ignorar zumbido DC y muy bajas frecuencias
                    }
                    float re = fft_buf[2 * k];
                    float im = fft_buf[2 * k + 1];
                    sum_mag += sqrtf(re * re + im * im);
                }

                int actual_bins = (b == 0) ? (BINS_PER_BAND - 5) : BINS_PER_BAND;
                float band_val = (actual_bins > 0) ? (sum_mag / actual_bins) : 0.0f;
                avg_bands[b] += band_val;
            }
            active_mics++;
        }

        /* ── 4. Promediar e imprimir espectro consolidado ── */
        if (active_mics > 0) {
            printf("FFT_DATA:AVG:");
            for (int b = 0; b < BANDS_COUNT; b++) {
                avg_bands[b] /= active_mics;
                printf("%.2f%s", avg_bands[b], (b == BANDS_COUNT - 1) ? "" : ",");
            }
            printf("\n");
        } else {
            printf("FFT_DATA:AVG:DISCONNECTED\n");
        }

        // Delay pequeño para ceder CPU y mantener una tasa de refresco fluida (~10-15 Hz)
        vTaskDelay(pdMS_TO_TICKS(30));
    }
}

void app_main(void)
{
    ESP_LOGI(TAG, "Iniciando modo de Calibración Optimizado (AVG)...");
    adc_init();

    xTaskCreatePinnedToCore(
        calibrate_task,
        "calibrate_audio",
        8192,
        NULL,
        5,
        NULL,
        1 // Core 1
    );
}
