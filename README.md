# PLDR-Edu: Open-Source Pipeline Leak Detection Robot 🤖💧

<div align="center">
  <img src="images/Assembly.png" width="600" alt="PLDR-Edu Robot">
</div>

This project introduces the **PLDR-Edu**, an open-source mobile robot designed as a project-based learning (PBL) platform for the **Mechatronic Systems Design** course at **UTEC**.

The system addresses the engineering challenge of inspecting a pressurized 3-inch PVC pipe and detecting simulated air leaks without human intervention. The robot encircles the pipe using a rigid two-clamp frame with 3D-printed arms, scanning it acoustically and visually without physical contact. Upon detection, a marker mechanism paints a reference dot directly on the pipe, and an acoustic alarm alerts the operator.

## 📋 Main Features & Contributions
- **Non-Contact Sweep:** The geometric constraint of the frame provides 360-degree coverage at a controlled stand-off distance. 
- **Acoustic Triangulation:** Captures and filters signals using three calibrated microphones targeting the characteristic broadband acoustic signal of pressurized air leaks.
- **Visual Confirmation:** A dedicated vision pipeline processes images to confirm the physical hole.
- **Contributions:** Generic microphone calibration process, vision-to-hardware data pipeline, and scalable scanning processes.
- **License:** CERN-OHL-P

## 🛠️ Hardware Architecture
The robot utilizes a multi-level control and processing architecture:
- **Structure & Actuation:** TETRIX® robotics kit combined with custom 3D-printed extensions.
- **Main Controller:** NI MyRIO running LabVIEW for locomotion and main logic.
- **Acoustic Processing:** ESP32 modules handling the signal from the microphones with band-pass filtering.
- **Computer Vision:** Raspberry Pi 3 (with optional Arty A7 100T FPGA support) dedicated to visual confirmation.

## 📂 Repository Structure
- `/CAD`: Individual CAD files and assemblies (.FCStd and .step formats).
- `/Electronics`: Electronic schematics and hardware files.
- `/Firmware`: Source code for the robot's control system.
- `/images`: Documentation images and renders.
- `/Docs`: Diagrams, schematics, and the full HardwareX article report.

---
*Developed by Adrian Becerra, Andrea Muñoz, Carlos Lam, Kiyomi Takahashi\**
