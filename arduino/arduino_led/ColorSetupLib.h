// ColorSetupLib — DAC SPI helper for luciole_arduino
// Drives a MCP4822 dual 12-bit DAC (or compatible) over SPI for each LED wavelength.

#ifndef COLOR_SETUP_LIB_H
#define COLOR_SETUP_LIB_H

#include <Arduino.h>
#include <SPI.h>

// Number of supported wavelength channels
#define N_WAVELENGTHS 5

// SPI chip-select pins, one per DAC (adjust to match hardware)
extern const uint8_t DAC_CS_PINS[N_WAVELENGTHS];

// Initialise SPI and CS pins.  Call once from setup().
void colorSetupInit();

// Output a 12-bit value (0–4095) on channel idx via SPI.
void colorSetupWrite(uint8_t idx, uint16_t value);

// Output one complete mix (N_WAVELENGTHS values) at once.
void colorSetupWriteMix(const uint16_t* values, uint8_t n);

#endif // COLOR_SETUP_LIB_H
