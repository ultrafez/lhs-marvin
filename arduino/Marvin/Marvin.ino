#include <Servo.h>
#include <Wire.h>

#define OFF 0
#define RED 1
#define GREEN 2
#define AMBER 3
#define STEADY 0
#define FLASH 1
#define FAST1 2
#define FAST2 3
#define SILENT 0
#define SOUND 1

#define PIR 2
#define LASER 3
#define PANSERVO 6
#define SIGN 8
#define INTERNALDOOR A3
#define EXTERNALDOOR A2
#define BELL 4

#define SIGN_OFF 0
#define SIGN_ON 1
#define BELL_OFF 0
#define BELL_ON 1

char input[10];
char last;
int count;
Servo pan;
int panangle=90;
bool seen_ping;
unsigned long bell_timer;

void Write (void) {
  pinMode(9, OUTPUT);     
  pinMode(10, OUTPUT);     
  pinMode(11, OUTPUT);     
  pinMode(12, OUTPUT);     
  pinMode(13, OUTPUT);     
};

void Done (void) {
  delay(50);
  pinMode(9, INPUT); 
  digitalWrite(9, LOW);
  pinMode(10, INPUT);     
  digitalWrite(10, LOW);
  pinMode(11, INPUT);     
  digitalWrite(11, LOW);
  pinMode(12, INPUT);     
  digitalWrite(12, LOW);
  pinMode(13, INPUT);  
  digitalWrite(13, LOW);
};

void SetColour (int colour)
{
    switch (colour) {
      case OFF:
        digitalWrite(9,LOW);
        digitalWrite(10,LOW);
        break;
      case RED:
        digitalWrite(9,HIGH);
        digitalWrite(10,LOW);
        break;
      case GREEN:
        digitalWrite(9,LOW);
        digitalWrite(10,HIGH);
        break;
      case AMBER:
        digitalWrite(9,HIGH);
        digitalWrite(10,HIGH);
        break;
    };
};

void SetFlash (int flash)
{
    switch (flash) {
      case STEADY:
        digitalWrite(11,LOW);
        digitalWrite(12,LOW);
        break;
      case FLASH:
        digitalWrite(11,HIGH);
        digitalWrite(12,LOW);
        break;
      case FAST1:
        digitalWrite(11,LOW);
        digitalWrite(12,HIGH);
        break;
      case FAST2:
        digitalWrite(11,HIGH);
        digitalWrite(12,HIGH);
        break;
    };
};

void SetSound (int sound)
{
    switch (sound) {
      case SILENT:
        digitalWrite(13,LOW);
        break;
      case SOUND:
        digitalWrite(13,HIGH);
        break;
    };
};

int ReadTemp(void)
{
  int temperature;
  
  Wire.beginTransmission(0x4D); //begin transmission to the temp sensor (TC74A5) - Change the address for other sensors
  
  Wire.write(0); //send command byte
  
  Wire.requestFrom(0x4D, 1); //request temperature data
  
  if(!Wire.available())
    return 0;
  //if sensor responds
  temperature = Wire.read(); //receive data and assign to temperature variable
  if(temperature > 150){ //if temperature is measured as more than 150C then map for negative values
    //when the temperature goes below zero, temp values start decreasing from 255. Therefore they need to be mapped to negative numbers:
    temperature = map(temperature, 255, 155, -1, -100);
  }
  return temperature-1; //return measured temperature
}

void FireLaser (int pulses)
{
  for (int pulse=0;pulse<=pulses;pulse++)
  {
    digitalWrite(LASER, HIGH);
    delay(50);
    digitalWrite(LASER, LOW);
    delay(50);
  };
};


void setup()
{                
  // Set PIR pin to input, enable pullups;
  pinMode(9, OUTPUT);     
  pinMode(10, OUTPUT);     
  pinMode(11, OUTPUT);     
  pinMode(12, OUTPUT);     
  pinMode(13, OUTPUT);     
  pinMode(PIR, INPUT_PULLUP);
  pinMode(LASER, OUTPUT);
  pinMode(INTERNALDOOR, INPUT_PULLUP);
  pinMode(SIGN, OUTPUT);
  pinMode(BELL, OUTPUT);
  digitalWrite(SIGN, SIGN_OFF);
  digitalWrite(BELL, BELL_OFF);
  FireLaser(10);
  pan.attach(PANSERVO);
  pan.write(panangle);
  Serial.begin(9600);
  Wire.begin(0x00);
  count=0;
}

void loop()                     
{ 
  long delta;
  if (bell_timer) {
    delta = bell_timer - millis();
    if (delta < 0) {
      digitalWrite(BELL, BELL_OFF);
      bell_timer = 0;
    }
  }
  if (Serial.available() > 0)
  {
    last=Serial.read();
    if (last=='\n' || last == '\r')
    {
      input[count]=0;
      //Process string
      Write();
      switch (input[0])
      {
        case 'M': //Moflash
          switch (input[1])
          {
            case 'O':
              SetColour(OFF);
              break;
            case 'R':
              SetColour(RED);
              break;
            case 'A':
              SetColour(AMBER);
              break;
            case 'G':
              SetColour(GREEN);
              break;
          };
          switch (input[3])
          {
            case '0':
              SetSound(SILENT);
              break;
            case '1':
              SetSound(SOUND);
              break;
          };
          switch (input[2])
          {
            case '0':
              SetFlash(STEADY);
              break;
            case '1':
              SetFlash(FLASH);
              break;
            case '2':
              SetFlash(FAST1);
              break;
            case '3':
              SetFlash(FAST2);
              break;
          };
          Done();
          break;
        case 'L': //Laser
          FireLaser(10);
          break;
        case 'W': //Webcam
	  if (input[1] == 0) {
	      Serial.print("ANGLE=");
	      Serial.println(panangle);
	  } else {
	    panangle=atoi(input+1);
	    pan.write(panangle);
	    Serial.println("OK");
	  }
          break;
        case 'Z': //Laser Scan
          pan.write(0);
          delay(100);
          digitalWrite(LASER, HIGH);
          for (float x=0;x<180;x+=0.2)
          {
            pan.write(x);
            delay(15);
          };
          digitalWrite(LASER, LOW);
          pan.write(panangle);
          break;
        case 'T': //Temp Sensor
          Serial.print("TEMP=");
          Serial.println(ReadTemp());
          break;
        case 'P': //PIR
          if (digitalRead(PIR)==LOW) {
            Serial.println("PIR=0");
          } else {
            Serial.println("PIR=1");
          };
          break;
        case 'D': //Doors (internal, external, doorbell)
          if (digitalRead(INTERNALDOOR)==LOW) {
            Serial.print("DOORS=0");
          } else {
            Serial.print("DOORS=1");
          };
          Serial.println(",0,0");
          break;
	case 'S':
	  digitalWrite(SIGN, (input[1] == '1') ? SIGN_ON : SIGN_OFF);
	  Serial.println("OK");
	  break;
	case 'B':
	  digitalWrite(BELL, BELL_ON);
      bell_timer = atoi(&input[1])*1000+millis();
	  Serial.println("OK");
	  break;
	case 'X':
	  /* Ignore/reset.  */
	  break;
	case '?':
	  if (input[1] == 0) {
	    Serial.print("Marvin 1.5");
	    if (!seen_ping) {
	      Serial.print("+");
	      seen_ping = true;
	    }
	    Serial.println();
	  }
	  break;
      };
      count=0;
    } else {
      // Store character
      input[count]=last;
      if (count<9) {
        count++;
      };
    };
  };
};

