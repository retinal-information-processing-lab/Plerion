/*
 *  A chaque trig (switch/pullup) sur pin 2 : L'état de la LED est inversé et le contenu de timer 1 est envoyé sur la liaison série et remis à 0.
 *  En cas d'overflow de timer1 létat de la sortie 12 est inversé
 */

//Version 1.0

const byte led_pin       = 13;
const byte overflow_pin  = 12;
const byte trigIn_pin    =  2;

volatile bool         trigFlg       = false;  //trigFlg et overflowFlg sont passé à true pendant les IT et si vrai dans la boucle infinie du main alors les output sont mise à jour
volatile bool         overflowFlg   = false; 
volatile byte         LED_sate      = LOW;
volatile byte         overflow_sate = LOW;
volatile unsigned int time          = 0;      //Variable de capture du timer1 pendant l'IT 

//Composition de la trame : entête = 4x0x88 ; 1 bytes pour la taille du message (en byte msb,lsb) ; le message ; fin de trame = 4x0xFF
int const usbBufferSize = 12;
char usbBuffer[usbBufferSize] = {0x88, 0x88, 0x88, 0x88, 0x00, 0x02, 0x00, 0x00, 0xFF, 0xFF, 0xFF, 0xFF};

void timer_init(){
  //Timer1 - init config
  TCCR1A = 0;
  TCCR1B = 0;
  
  //Timer1 - prescale 1 :001 - prescale 1024 :101
  //Resolution de comptage = 1/16MHz x prescale
  //Perscale 1 : resolution = 1/16Mhz = 62.5ns ; overflow = 65536 * 62.5ns = 4096µs
  //Perscale 1024 : resolution =  1024/16MHz = 64µs ; overflow = 65536 * 64µs = 4.194s
  
  
  //TCCR1B &= ~(1 << CS12);
  TCCR1B |=  (1 << CS12);
  TCCR1B &= ~(1 << CS11);
  TCCR1B |=  (1 << CS10);

  //Timer1 - overflow IT enable
  TIMSK1 |= (1 << TOIE1);

  //Timer1 - preload
  TCNT1 = 0;   
}

void trigger_init(){
  //pin 2 (INT0) en entrée
  pinMode(trigIn_pin, INPUT);
  PORTD |= (1 << PORTD2);   // turn On the Pull-up pour un trig sur un witch (et non un ttl)

  ////External Interrupt Mask Register - EIMSK - is for enabling INT[6;3:0] interrupts, INT0 is disabled to avoid false interrupts when mainuplating EICRA
  EIMSK &= ~(1 << INT0); 
  //External Interrupt Control Register A - EICRA - defines the interrupt edge profile, here configured to trigger on rising edge
  //INT0 - ISC01/ISC00 : 0/1 : any logique change 1/0 falling edge 1/1 : rising edge 
  EICRA &= ~(bit(ISC00) | bit (ISC01));  // clear existing flags
  EICRA |= (1 << ISC01)|(1 << ISC00);
  //EICRA &= ~(bit(ISC00));

  //External Interrupt Flag Register - EIFR controls interrupt flags on INT[6;3:0], here it is cleared
  EIFR &= ~(1 << INTF0); 
  
  //Trigger - IT enable
  EIMSK |= (1 << INT0);  
}

void setup() {
  noInterrupts(); // disable all interrupts
  //EIMSK = 0;      //external interrupt mask register : block all IT

  //Serial config
  Serial.begin(128000);         
  
  //I/O configuraiton    
  pinMode(led_pin,      OUTPUT);
  pinMode(overflow_pin, OUTPUT);   
  
  trigger_init();
  timer_init();
 
  interrupts();   // enable all interrupts
}

ISR(TIMER1_OVF_vect)        // interrupt service routine that wraps a user defined function supplied by attachInterrupt
{
  overflow_sate = !overflow_sate;
  overflowFlg = true;
}

ISR(INT0_vect)
{
    time = TCNT1;
    TCNT1 = 0;
    LED_sate = !LED_sate;
    trigFlg = true;

    //EIFR &= ~(1 << INTF0); //Clear interrupt flag
}

int main(){
  
  setup();
  
  while (1) {
      if(trigFlg){
        digitalWrite(led_pin,       LED_sate);   
        trigFlg = false;
        usbBuffer[6] = (8>>time) & 0xFF;  //msb
        usbBuffer[7] = (time & 0xFF);       //lsb
        
        Serial.write(usbBuffer, usbBufferSize);
        
      }
      if(overflowFlg){
        digitalWrite(overflow_pin,  overflow_sate);
        overflowFlg = false;
      }      
    }
  
  return 0;
}
