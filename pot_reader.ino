// solar_tracker.ino
// Reads potentiometer on A0 and sends angle over Serial to laptop.
// Laptop runs tracker.py which controls the power supply via HID.
// No PWM output needed here — the laptop → HID → PSU handles power directly.

const int POT_PIN   = A0;
const int LED_PIN   = 13;     // built-in LED blinks on each send

// Calibration — measure these by rotating panel to physical limits
// and printing analogRead(A0) at each end
const int   ADC_MIN     = 0;
const int   ADC_MAX     = 1023;
const float ANGLE_MIN   = -45.0;   // degrees at ADC_MIN
const float ANGLE_MAX   =  45.0;   // degrees at ADC_MAX

// Smoothing — average N readings to reduce noise
const int SMOOTH_N = 8;

float smooth_buffer[SMOOTH_N];
int   smooth_index = 0;
bool  buffer_full  = false;

void setup() {
  Serial.begin(9600);
  pinMode(LED_PIN, OUTPUT);

  // Pre-fill smoothing buffer
  int raw = analogRead(POT_PIN);
  float angle = raw_to_angle(raw);
  for (int i = 0; i < SMOOTH_N; i++) {
    smooth_buffer[i] = angle;
  }
}

void loop() {
  // 1. Read potentiometer
  int raw = analogRead(POT_PIN);
  float angle = raw_to_angle(raw);

  // 2. Apply moving average smoothing
  smooth_buffer[smooth_index] = angle;
  smooth_index = (smooth_index + 1) % SMOOTH_N;

  float sum = 0;
  for (int i = 0; i < SMOOTH_N; i++) {
    sum += smooth_buffer[i];
  }
  float smoothed_angle = sum / SMOOTH_N;

  // 3. Send angle to laptop over Serial (one value per line)
  Serial.println(smoothed_angle, 2);   // 2 decimal places

  // 4. Blink LED so you can see it's running
  digitalWrite(LED_PIN, !digitalRead(LED_PIN));

  delay(50);   // 20 Hz — matches LOOP_HZ in tracker.py
}

// Map raw ADC value to panel angle in degrees
float raw_to_angle(int raw) {
  raw = constrain(raw, ADC_MIN, ADC_MAX);
  return ANGLE_MIN + (float)(raw - ADC_MIN)
         / (float)(ADC_MAX - ADC_MIN)
         * (ANGLE_MAX - ANGLE_MIN);
}
