// sendPeriodOnTrig
// On each rising edge on pin 2 (INT0), captures Timer1 and sends a 12-byte framed
// serial message to the host.
//
// Frame layout (12 bytes):
//   Header  : 0x88 0x88 0x88 0x88
//   Type    : 0x00 0x02
//   Payload : MSB LSB  (Timer1 count at trigger time)
//   Footer  : 0xFF 0xFF 0xFF 0xFF

#include <avr/io.h>
#include <avr/interrupt.h>

#define BAUD_RATE 128000
#define TRIG_PIN  2   // INT0

volatile uint16_t captured_period = 0;
volatile bool     frame_ready     = false;

void setup() {
  Serial.begin(BAUD_RATE);

  // Timer1: normal mode, no prescaler (16 MHz tick)
  TCCR1A = 0;
  TCCR1B = (1 << CS10);   // prescaler = 1
  TCNT1  = 0;

  // INT0: rising edge
  attachInterrupt(digitalPinToInterrupt(TRIG_PIN), onTrigger, RISING);
}

void onTrigger() {
  captured_period = TCNT1;
  TCNT1           = 0;
  frame_ready     = true;
}

void sendFrame(uint16_t value) {
  uint8_t frame[12] = {
    0x88, 0x88, 0x88, 0x88,         // header
    0x00, 0x02,                     // type
    (uint8_t)(value >> 8),          // MSB
    (uint8_t)(value & 0xFF),        // LSB
    0xFF, 0xFF, 0xFF, 0xFF          // footer
  };
  Serial.write(frame, 12);
}

void loop() {
  if (frame_ready) {
    uint16_t val;
    noInterrupts();
    val        = captured_period;
    frame_ready = false;
    interrupts();
    sendFrame(val);
  }
}
