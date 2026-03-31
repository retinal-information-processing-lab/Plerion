// ColorSetupLib — DAC SPI helper for luciole_arduino

#include "ColorSetupLib.h"

// CS pin assignments for each wavelength channel [385, 420, 490, 530, 625]
// Adjust to match the actual board wiring.
const uint8_t DAC_CS_PINS[N_WAVELENGTHS] = {4, 5, 6, 7, 8};

// MCP4822: 16-bit SPI word  |  /A=1,  BUF=0,  /GA=1 (1x),  /SHDN=1  |  D[11:0]
static uint16_t makeDacWord(uint16_t value12) {
  // Channel A, unbuffered, gain=1, active
  return (0x3000) | (value12 & 0x0FFF);
}

void colorSetupInit() {
  SPI.begin();
  for (uint8_t i = 0; i < N_WAVELENGTHS; i++) {
    pinMode(DAC_CS_PINS[i], OUTPUT);
    digitalWrite(DAC_CS_PINS[i], HIGH);
  }
}

void colorSetupWrite(uint8_t idx, uint16_t value) {
  if (idx >= N_WAVELENGTHS) return;
  uint16_t word = makeDacWord(value);
  SPI.beginTransaction(SPISettings(8000000, MSBFIRST, SPI_MODE0));
  digitalWrite(DAC_CS_PINS[idx], LOW);
  SPI.transfer16(word);
  digitalWrite(DAC_CS_PINS[idx], HIGH);
  SPI.endTransaction();
}

void colorSetupWriteMix(const uint16_t* values, uint8_t n) {
  uint8_t count = (n < N_WAVELENGTHS) ? n : N_WAVELENGTHS;
  for (uint8_t i = 0; i < count; i++) {
    colorSetupWrite(i, values[i]);
  }
}
