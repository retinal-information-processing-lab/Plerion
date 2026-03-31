// luciole_arduino
// Synchronises LED DAC outputs with DMD trigger pulses.
//
// Protocol (host → Arduino):
//   1. 'S' + mask_byte            — start: mask selects active wavelengths
//   2. 99 mixes × N_active × 2   — initial circular buffer fill (uint16 big-endian)
//   3. Arduino replies 'R'        — ready handshake
//
// During run (host → Arduino):
//   On MSG_REFILL request: host sends N more mixes
//
// Arduino → host messages:
//   MSG_REFILL  (0x01) + uint8  count  — request more mixes
//   MSG_FREQ    (0x02) + uint16 hz     — measured trigger frequency
//   MSG_TRIG_ERR(0x03) + uint32 us     — trigger timing error (µs)

#include <Arduino.h>
#include "ColorSetupLib.h"

#define BAUD_RATE     115200
#define TRIG_PIN      A2

#define MSG_REFILL    0x01
#define MSG_FREQ      0x02
#define MSG_TRIG_ERR  0x03

#define BUF_CAPACITY  128   // circular buffer slots

static uint8_t  led_mask     = 0;
static uint8_t  n_active     = 0;
static uint16_t circ_buf[BUF_CAPACITY][N_WAVELENGTHS];
static uint8_t  buf_head     = 0;   // next slot to consume
static uint8_t  buf_tail     = 0;   // next slot to fill
static uint8_t  buf_count    = 0;

static unsigned long last_trig_us = 0;
static bool          armed        = false;

// ── helpers ────────────────────────────────────────────────────────────────

static uint8_t countBits(uint8_t v) {
  uint8_t c = 0;
  while (v) { c += v & 1; v >>= 1; }
  return c;
}

static void bufferPush(const uint16_t* mix) {
  if (buf_count >= BUF_CAPACITY) return;   // overflow: drop
  memcpy(circ_buf[buf_tail], mix, n_active * sizeof(uint16_t));
  buf_tail  = (buf_tail + 1) % BUF_CAPACITY;
  buf_count++;
}

static bool bufferPop(uint16_t* mix) {
  if (buf_count == 0) return false;
  memcpy(mix, circ_buf[buf_head], n_active * sizeof(uint16_t));
  buf_head  = (buf_head + 1) % BUF_CAPACITY;
  buf_count--;
  return true;
}

// ── serial helpers ──────────────────────────────────────────────────────────

static void readMix(uint16_t* out) {
  for (uint8_t i = 0; i < n_active; i++) {
    while (Serial.available() < 2) {}
    uint8_t hi = Serial.read();
    uint8_t lo = Serial.read();
    out[i] = ((uint16_t)hi << 8) | lo;
  }
}

static void sendMsg1(uint8_t type, uint8_t val) {
  Serial.write(type);
  Serial.write(val);
}

static void sendMsg2(uint8_t type, uint16_t val) {
  Serial.write(type);
  Serial.write((uint8_t)(val >> 8));
  Serial.write((uint8_t)(val & 0xFF));
}

static void sendMsg4(uint8_t type, uint32_t val) {
  Serial.write(type);
  Serial.write((uint8_t)(val >> 24));
  Serial.write((uint8_t)(val >> 16));
  Serial.write((uint8_t)(val >>  8));
  Serial.write((uint8_t)(val & 0xFF));
}

// ── setup ───────────────────────────────────────────────────────────────────

void setup() {
  Serial.begin(BAUD_RATE);
  colorSetupInit();
  pinMode(TRIG_PIN, INPUT);

  // Wait for 'S' + mask byte
  while (Serial.available() < 2) {}
  char cmd = Serial.read();
  if (cmd != 'S') return;   // unexpected — stay idle
  led_mask = Serial.read();
  n_active = countBits(led_mask);

  // Receive initial buffer: 99 mixes
  uint16_t mix[N_WAVELENGTHS];
  for (uint8_t i = 0; i < 99; i++) {
    readMix(mix);
    bufferPush(mix);
  }

  // Handshake
  Serial.write('R');
  armed = true;
}

// ── main loop ───────────────────────────────────────────────────────────────

void loop() {
  if (!armed) return;

  // Detect rising edge on trigger pin (polled, ~µs resolution)
  static bool prev_trig = false;
  bool cur_trig = digitalRead(TRIG_PIN);

  if (cur_trig && !prev_trig) {
    unsigned long now = micros();

    uint16_t mix[N_WAVELENGTHS] = {0};
    if (!bufferPop(mix)) {
      // Buffer underrun — report error with zero delta
      sendMsg4(MSG_TRIG_ERR, 0);
    } else {
      colorSetupWriteMix(mix, n_active);

      // Report frequency
      if (last_trig_us != 0) {
        unsigned long period_us = now - last_trig_us;
        uint16_t      hz        = (uint16_t)(1000000UL / period_us);
        sendMsg2(MSG_FREQ, hz);
      }
      last_trig_us = now;

      // Request refill when buffer is low
      if (buf_count < 10) {
        uint8_t needed = BUF_CAPACITY - buf_count;
        sendMsg1(MSG_REFILL, needed);
      }
    }
  }

  prev_trig = cur_trig;

  // Receive refill mixes if available
  if (Serial.available() >= n_active * 2) {
    uint16_t mix[N_WAVELENGTHS];
    readMix(mix);
    bufferPush(mix);
  }
}
