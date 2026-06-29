cmake_minimum_required(VERSION 3.16)

# Registrar el componente esp-dsp (debe estar en managed_components o components/)
# Si usas idf-component-manager, agrega al idf_component.yml en su lugar.

include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(mic_fft_hcsr04)
