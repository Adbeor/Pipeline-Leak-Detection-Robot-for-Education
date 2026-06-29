# ==============================================================================
# SELECCIONA QUÉ FIRMWARE COMPILAR DESCOMENTANDO LA LÍNEA CORRESPONDIENTE:
# ==============================================================================

# 1. Firmware de Producción (FFT + Ultrasonidos + Envío de Trama Completa)
idf_component_register(SRCS "main.c" REQUIRES esp-dsp esp_adc esp_timer esp_driver_gpio esp_driver_uart driver)

# 2. Firmware de Calibración (Solo espectro FFT de 32 bandas para calibrar firmas de fugas)
# idf_component_register(SRCS "calibrate.c" REQUIRES esp-dsp esp_adc esp_timer esp_driver_gpio esp_driver_uart driver)
