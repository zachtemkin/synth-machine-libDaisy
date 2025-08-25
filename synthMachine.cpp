#include "daisy.h"
#include "daisy_patch.h"
#include "daisy_seed.h"
#include "daisysp.h"

using namespace daisy;
using namespace daisysp;
using namespace daisy::seed;

/*
 * Polyphony with Grid - DaisyLib C++ Implementation for Daisy Seed
 *
 * Ported from Arduino DaisyDuino code to native DaisyLib
 * Optimized version with improved debouncing and timing for polyphony
 *
 * Key improvements:
 * 1. Optimized debouncing with configurable timing
 * 2. Reduced serial logging for better performance
 * 3. Improved pin stabilization timing
 * 4. Better matrix scanning efficiency
 * 5. Fixed potentiometer functionality for Daisy Seed
 * 6. Added MIDI out over UART (pins 29 and 30) for USB-C breakout
 *
 * Potentiometer Control System:
 * - A0: Wave Shape (Sine, Triangle, Square, Saw)
 * - A1: Attack Time (1ms to 1s)
 * - A2: Decay Time (10ms to 1s)
 * - A3: Sustain Level (0% to 100%)
 * - A4: Release Time (10ms to 2s)
 *
 * MIDI Output:
 * - USB MIDI over built-in USB port (pins 29 D-, 30 D+ are the USB FS data
 * pair)
 */

// Pin definitions - must be defined outside the class
static constexpr Pin COL_PINS[6] = {seed::D4, seed::D5, seed::D6,
                                    seed::D7, seed::D8, seed::D9};
static constexpr Pin ROW_PINS[3] = {seed::D1, seed::D2, seed::D3};
static constexpr Pin C4_PIN = seed::D10;

// MIDI USB pins - Pins 29 (D-) and 30 (D+) are the USB FS data pair
// connected to STM32H7's internal USB OTG FS PHY

class SynthMachine {
private:
  // Hardware configuration
  DaisySeed hw;
  MidiUsbHandler midi; // USB MIDI handler

  // Audio parameters
  static const int NUM_VOICES = 13;
  static const int SAMPLE_RATE = 48000;
  static const int BLOCK_SIZE = 48;

  // Button matrix configuration - using DaisyPod pin definitions
  static const int MATRIX_COLS = 6;
  static const int MATRIX_ROWS = 3;

  // GPIO objects for matrix scanning
  GPIO colGpios[MATRIX_COLS];
  GPIO rowGpios[MATRIX_ROWS];
  GPIO c4Gpio;

  // Matrix button states (true = pressed, false = not pressed)
  bool buttonStates[MATRIX_COLS][MATRIX_ROWS] = {false};
  bool lastButtonStates[MATRIX_COLS][MATRIX_ROWS] = {false};

  // Optimized debouncing - balanced for musical responsiveness and reliability
  static const unsigned long DEBOUNCE_DELAY =
      20; // 20ms - increased for better reliability
  unsigned long lastDebounceTime[MATRIX_COLS][MATRIX_ROWS] = {0};

  // Note mapping: [col][row] -> note index
  // Note indices: 0=C5, 1=B5, 2=A#/Bb, 3=A5, 4=G#/Ab, 5=G4, 6=F#/Gb, 7=F4,
  // 8=E4, 9=D#/Eb, 10=D4, 11=C#/Db, 12=C4
  const int NOTE_MAPPING[MATRIX_COLS][MATRIX_ROWS] = {
      {-1, -1, 0}, // Column 0 (D1): none, none, C5
      {-1, 2, 1},  // Column 1 (D2): none, A#/Bb, B5
      {-1, 4, 3},  // Column 2 (D3): none, G#/Ab, A5
      {-1, 6, 5},  // Column 3 (D4): none, F#/Gb, G4
      {-1, 9, 7},  // Column 4 (D5): none, D#/Eb, F4
      {11, 10, 8}  // Column 5 (D6): C#/Db, D4, E4
  };

  // Direct note pin (C4) - defined outside class

  // ADC pins for potentiometers - actual hardware connections
  static const int WAVESHAPE_PIN = 0; // A0 for wave shape control
  static const int ATTACK_PIN = 1;    // A1 for attack
  static const int DECAY_PIN = 2;     // A2 for decay
  static const int SUSTAIN_PIN = 3;   // A3 for sustain
  static const int RELEASE_PIN = 4;   // A4 for release

  // ADSR envelope parameters
  float attackTime = 0.01f;  // 10ms attack
  float decayTime = 0.1f;    // 100ms decay
  float sustainLevel = 0.7f; // 70% sustain level
  float releaseTime = 0.05f; // 50ms release

  // Wave shape parameter
  float waveShape = 0.0f;

  // Voice structure
  struct Voice {
    Oscillator osc;
    Adsr env;
    float frequency;
    bool isActive;
    int note;
    bool gate;
    float lastEnvOut;
    bool needsReset;
  };

  // Global variables
  Voice voices[NUM_VOICES];
  int currentVoice = 0;
  bool voiceFinishedFlags[NUM_VOICES] = {false};
  bool adsrParamsChanged = false;
  bool waveShapeChanged = false;

  // Musical note frequencies (C4 to C5, 1 octave with sharps/flats)
  // MIDI note numbers: C4=60, C#/Db=61, D4=62, D#/Eb=63, E4=64, F4=65,
  // F#/Gb=66, G4=67, G#/Ab=68, A4=69, A#/Bb=70, B4=71, C5=72
  const int midiNoteNumbers[13] = {
      72, // C5
      71, // B4
      70, // A#/Bb
      69, // A4
      68, // G#/Ab
      67, // G4
      66, // F#/Gb
      65, // F4
      64, // E4
      63, // D#/Eb
      62, // D4
      61, // C#/Db
      60  // C4
  };

  const float noteFrequencies[13] = {
      523.25, // C5
      493.88, // B4
      466.16, // A#/Bb
      440.00, // A4
      415.30, // G#/Ab
      392.00, // G4
      369.99, // F#/Gb
      349.23, // F4
      329.63, // E4
      311.13, // D#/Eb
      293.66, // D4
      277.18, // C#/Db
      261.63  // C4
  };

public:
  SynthMachine() {
    // Initialize all voices
    for (int i = 0; i < NUM_VOICES; i++) {
      voices[i].osc.Init(SAMPLE_RATE);
      voices[i].osc.SetWaveform(Oscillator::WAVE_SIN);
      voices[i].osc.SetFreq(440.0f);
      voices[i].env.Init(SAMPLE_RATE);
      voices[i].env.SetAttackTime(attackTime);
      voices[i].env.SetDecayTime(decayTime);
      voices[i].env.SetSustainLevel(sustainLevel);
      voices[i].env.SetReleaseTime(releaseTime);

      voices[i].isActive = false;
      voices[i].note = -1;
      voices[i].gate = false;
      voices[i].lastEnvOut = 0.0f;
      voices[i].needsReset = false;
      voices[i].frequency = 440.0f;
    }

    // Test oscillator frequency setting
    for (int i = 0; i < NUM_VOICES; i++) {
      voices[i].osc.SetFreq(noteFrequencies[i]);
    }
  }

  void Init() {
    // Initialize Daisy Seed
    hw.Init();
    hw.SetAudioBlockSize(BLOCK_SIZE);

    // Initialize ADC for external potentiometers
    AdcChannelConfig adcConfig[5];
    adcConfig[0].InitSingle(seed::A0); // Wave shape
    adcConfig[1].InitSingle(seed::A1); // Attack
    adcConfig[2].InitSingle(seed::A2); // Decay
    adcConfig[3].InitSingle(seed::A3); // Sustain
    adcConfig[4].InitSingle(seed::A4); // Release
    hw.adc.Init(adcConfig, 5);
    hw.adc.Start();

    // Initialize matrix pins for new scanning strategy
    // Columns: start as INPUT_PULLUP, will be changed to OUTPUT during scanning
    // Rows: start as INPUT, will be changed to INPUT_PULLUP during scanning
    for (int c = 0; c < MATRIX_COLS; ++c) {
      colGpios[c].Init(COL_PINS[c], GPIO::Mode::INPUT, GPIO::Pull::PULLUP);
    }
    for (int r = 0; r < MATRIX_ROWS; ++r) {
      rowGpios[r].Init(ROW_PINS[r], GPIO::Mode::INPUT, GPIO::Pull::NOPULL);
    }

    // Initialize C4 direct pin
    c4Gpio.Init(C4_PIN, GPIO::Mode::INPUT, GPIO::Pull::PULLUP);

    // Add a delay to let all pins stabilize
    System::Delay(100);

    // Initialize MIDI USB interface
    MidiUsbHandler::Config midi_cfg;
    midi_cfg.transport_config.periph = MidiUsbTransport::Config::INTERNAL;
    // Optional: tweak retries if you blast back-to-back messages
    midi_cfg.transport_config.tx_retry_count = 3;
    midi.Init(midi_cfg);
    System::Delay(100);
  }

  // Function to read potentiometer and map to ADSR range
  float readPotentiometer(int pin, float minVal, float maxVal) {
    // Read from the specified ADC pin (A0-A4)
    float value = hw.adc.GetFloat(pin);
    return minVal + (value * (maxVal - minVal));
  }

  // Function to update ADSR parameters from potentiometers
  void updateADSRParameters() {
    // Read wave shape potentiometer (A0)
    float newWaveShape = readPotentiometer(WAVESHAPE_PIN, 0.0f, 1.0f);

    // Read ADSR potentiometers (A1-A4)
    float newAttackTime = readPotentiometer(ATTACK_PIN, 0.001f, 1.0f);
    float newDecayTime = readPotentiometer(DECAY_PIN, 0.01f, 1.0f);
    float newSustainLevel = readPotentiometer(SUSTAIN_PIN, 0.0f, 1.0f);
    float newReleaseTime = readPotentiometer(RELEASE_PIN, 0.01f, 2.0f);

    // Check if wave shape has changed significantly
    if (fabs(newWaveShape - waveShape) > 0.01f) {
      waveShape = newWaveShape;
      waveShapeChanged = true;
    }

    // Only update if ADSR parameters have changed significantly
    if (fabs(newAttackTime - attackTime) > 0.001f ||
        fabs(newDecayTime - decayTime) > 0.001f ||
        fabs(newSustainLevel - sustainLevel) > 0.001f ||
        fabs(newReleaseTime - releaseTime) > 0.001f) {

      attackTime = newAttackTime;
      decayTime = newDecayTime;
      sustainLevel = newSustainLevel;
      releaseTime = newReleaseTime;
      adsrParamsChanged = true;
    }
  }

  // Function to scan the button matrix with new scanning strategy
  // Columns are outputs driven LOW (sink), rows are inputs with pullup (source)
  // This creates a ground path when a button is pressed, making the row read
  // LOW
  void scanButtonMatrix() {
    // Button Deck scanning
    for (int columnIndex = 0; columnIndex < MATRIX_COLS; columnIndex++) {
      int currentColumn = columnIndex;

      // Set current column to OUTPUT mode and drive LOW
      colGpios[currentColumn].Init(COL_PINS[currentColumn], GPIO::Mode::OUTPUT,
                                   GPIO::Pull::NOPULL);
      colGpios[currentColumn].Write(false);

      for (int rowIndex = 0; rowIndex < MATRIX_ROWS; rowIndex++) {
        int currentRow = rowIndex;

        // Set current row to INPUT_PULLUP mode
        rowGpios[currentRow].Init(ROW_PINS[currentRow], GPIO::Mode::INPUT,
                                  GPIO::Pull::PULLUP);

        // Delay to give pin modes time to change state
        System::DelayUs(25);

        // Read button state (invert due to INPUT_PULLUP)
        bool buttonState = !rowGpios[currentRow].Read();

        // Check if button is active and passes debounce
        if (buttonState == true &&
            (System::GetNow() - lastDebounceTime[columnIndex][rowIndex]) >
                DEBOUNCE_DELAY) {
          // Button is pressed
          if (!buttonStates[columnIndex][rowIndex]) {
            buttonStates[columnIndex][rowIndex] = true;

            // Handle button press
            int noteIndex = NOTE_MAPPING[columnIndex][rowIndex];
            if (noteIndex >= 0) {
              noteOn(noteIndex);
            }
          }

          lastDebounceTime[columnIndex][rowIndex] = System::GetNow();
        }

        // Check if button is released
        if (buttonState == false && buttonStates[columnIndex][rowIndex]) {
          buttonStates[columnIndex][rowIndex] = false;

          // Handle button release
          int noteIndex = NOTE_MAPPING[columnIndex][rowIndex];
          if (noteIndex >= 0) {
            noteOff(noteIndex);
          }
        }

        // Set row pin back to INPUT mode
        rowGpios[currentRow].Init(ROW_PINS[currentRow], GPIO::Mode::INPUT,
                                  GPIO::Pull::NOPULL);
      }

      // Set column pin back to INPUT mode
      colGpios[currentColumn].Init(COL_PINS[currentColumn], GPIO::Mode::INPUT,
                                   GPIO::Pull::PULLUP);
    }
  }

  void Update() {
    // Listen for MIDI events (required for USB MIDI to work properly)
    midi.Listen();

    // Update ADSR parameters from potentiometers
    updateADSRParameters();

    // Update LED feedback for parameter mode
    // Removed parameter mode update
    // hw.led1.Update(); // Removed LED update
    // hw.led2.Update(); // Removed LED update

    // Update wave shape for all voices if changed
    if (waveShapeChanged) {
      for (int i = 0; i < NUM_VOICES; i++) {
        // Map waveShape (0-1) to oscillator waveforms
        if (waveShape < 0.25f) {
          voices[i].osc.SetWaveform(Oscillator::WAVE_SIN);
        } else if (waveShape < 0.5f) {
          voices[i].osc.SetWaveform(Oscillator::WAVE_TRI);
        } else if (waveShape < 0.75f) {
          voices[i].osc.SetWaveform(Oscillator::WAVE_SQUARE);
        } else {
          voices[i].osc.SetWaveform(Oscillator::WAVE_SAW);
        }
      }
      waveShapeChanged = false;
    }

    // Update ADSR parameters for all voices if changed
    if (adsrParamsChanged) {
      for (int i = 0; i < NUM_VOICES; i++) {
        voices[i].env.SetAttackTime(attackTime);
        voices[i].env.SetDecayTime(decayTime);
        voices[i].env.SetSustainLevel(sustainLevel);
        voices[i].env.SetReleaseTime(releaseTime);
      }
      adsrParamsChanged = false;
    }

    // Handle voice cleanup from audio callback
    for (int v = 0; v < NUM_VOICES; v++) {
      if (voiceFinishedFlags[v] || voices[v].needsReset) {
        // Reset envelope state
        voices[v].env.Process(false);
        voices[v].isActive = false;
        voices[v].note = -1;
        voices[v].gate = false;
        voiceFinishedFlags[v] = false;
        voices[v].lastEnvOut = 0.0f;
        voices[v].needsReset = false;
      }
    }

    // Scan the button matrix
    scanButtonMatrix();

    // Scan C4 direct pin
    static bool lastC4State = false;
    bool currentC4State = !c4Gpio.Read();

    if (currentC4State != lastC4State) {
      if (currentC4State) {
        noteOn(12); // C4 is note index 12
        // Debug: C4 note ON detected
      } else {
        noteOff(12);
        // Debug: C4 note OFF detected
      }
      lastC4State = currentC4State;
    }

    // Debug: track active voices for debugging
    static int debugCounter = 0;
    debugCounter++;
    if (debugCounter % 1000 ==
        0) { // Update every 1000 updates (roughly every 10 seconds)
      int activeVoices = 0;
      for (int i = 0; i < NUM_VOICES; i++) {
        if (voices[i].isActive)
          activeVoices++;
      }

      // Debug: show current parameter values and knob readings
      // Removed knob reading as KNOB_1 and KNOB_2 are removed
      // float knob1 = hw.GetKnobValue(hw.KNOB_1);
      // float knob2 = hw.GetKnobValue(hw.KNOB_2);

      // You can observe these values through the audio output or add serial
      // output if needed Current mode: currentParameterMode Knob 1: knob1 (0.0
      // to 1.0) Knob 2: knob2 (0.0 to 1.0) Wave shape: waveShape Attack:
      // attackTime Decay: decayTime Sustain: sustainLevel Release: releaseTime
    }

    // Process digital controls to update button states
    // Removed hw.ProcessDigitalControls();
  }

  void noteOn(int note) {
    // Find an available voice
    int voiceIndex = -1;
    for (int i = 0; i < NUM_VOICES; i++) {
      if (!voices[i].isActive) {
        voiceIndex = i;
        break;
      }
    }

    // If no free voice, steal the oldest one (round-robin)
    if (voiceIndex == -1) {
      voiceIndex = currentVoice;
      currentVoice = (currentVoice + 1) % NUM_VOICES;

      // Force immediate reset of the stolen voice
      voices[voiceIndex].gate = false;
      voices[voiceIndex].env.Process(false);
      voices[voiceIndex].isActive = false;
      voices[voiceIndex].note = -1;
      voices[voiceIndex].lastEnvOut = 0.0f;
      voices[voiceIndex].needsReset = false;

      // Reinitialize the oscillator to ensure clean state
      voices[voiceIndex].osc.Init(SAMPLE_RATE);
      voices[voiceIndex].osc.SetWaveform(Oscillator::WAVE_SIN);
    }

    // Set up the voice
    voices[voiceIndex].frequency = noteFrequencies[note];
    voices[voiceIndex].osc.SetFreq(voices[voiceIndex].frequency);

    // Set waveform based on current waveShape
    if (waveShape < 0.25f) {
      voices[voiceIndex].osc.SetWaveform(Oscillator::WAVE_SIN);
    } else if (waveShape < 0.5f) {
      voices[voiceIndex].osc.SetWaveform(Oscillator::WAVE_TRI);
    } else if (waveShape < 0.75f) {
      voices[voiceIndex].osc.SetWaveform(Oscillator::WAVE_SQUARE);
    } else {
      voices[voiceIndex].osc.SetWaveform(Oscillator::WAVE_SAW);
    }

    voices[voiceIndex].note = note;
    voices[voiceIndex].isActive = true;
    voices[voiceIndex].gate = true;
    voiceFinishedFlags[voiceIndex] = false;
    voices[voiceIndex].lastEnvOut = 0.0f;
    voices[voiceIndex].needsReset = false;

    // Debug: note ON event - voice is now active
    // The audio output will confirm this is working

    // Send MIDI Note On message via external USB port
    if (note >= 0 && note < 13) {
      // Note On: 0x90 = NoteOn channel 1, note number, velocity
      uint8_t note_on[] = {0x90 | 0x00, (uint8_t)midiNoteNumbers[note], 127};
      midi.SendMessage(note_on, sizeof(note_on));
    }
  }

  void noteOff(int note) {
    // Find ALL voices playing this note and turn them off
    for (int i = 0; i < NUM_VOICES; i++) {
      if (voices[i].isActive && voices[i].note == note) {
        voices[i].gate = false;
        // Debug: note OFF event - voice will fade out
      }
    }

    // Send MIDI Note Off message via external USB port
    if (note >= 0 && note < 13) {
      // Note Off: 0x80 = NoteOff channel 1, note number, velocity 0
      uint8_t note_off[] = {0x80 | 0x00, (uint8_t)midiNoteNumbers[note], 0};
      midi.SendMessage(note_off, sizeof(note_off));
    }
  }

  void AudioCallback(AudioHandle::InterleavingInputBuffer in,
                     AudioHandle::InterleavingOutputBuffer out, size_t size) {
    for (size_t i = 0; i < size; i += 2) {
      float output = 0.0f;

      // Process all voices
      for (int v = 0; v < NUM_VOICES; v++) {
        if (voices[v].isActive) {
          // Get envelope output first
          float envOut = voices[v].env.Process(voices[v].gate);

          // Cache the envelope output for this voice
          voices[v].lastEnvOut = envOut;

          // Check if envelope is finished
          if (envOut <= 0.005f && !voices[v].gate) {
            voiceFinishedFlags[v] = true;
            continue;
          }

          // Process oscillator and apply envelope only if envelope is
          // significant
          if (envOut > 0.005f) {
            float oscOut = voices[v].osc.Process();
            float voiceOut = oscOut * envOut;
            output += voiceOut;
          }
        }
      }

      // Apply soft limiting to prevent clipping
      if (output > 0.9f) {
        output = 0.9f + (output - 0.9f) * 0.1f;
      } else if (output < -0.9f) {
        output = -0.9f + (output + 0.9f) * 0.1f;
      }

      // Output to both channels of audio out 1 (stereo)
      out[i] = output;     // Left channel
      out[i + 1] = output; // Right channel

      // Note: DaisyPod only has 2 audio outputs (stereo), not 4
      // The original code was trying to output to 4 channels which doesn't
      // exist
    }
  }

  // Getter for hardware reference
  DaisySeed &GetHardware() { return hw; }
};

// Global instance
SynthMachine synth;

// Audio callback function for DaisyLib
void AudioCallback(AudioHandle::InterleavingInputBuffer in,
                   AudioHandle::InterleavingOutputBuffer out, size_t size) {
  synth.AudioCallback(in, out, size);
}

// Main function
int main(void) {
  // Initialize the synth
  synth.Init();

  // Set the audio callback
  synth.GetHardware().StartAudio(AudioCallback);
  synth.GetHardware().SetAudioBlockSize(48);

  // Main loop
  while (1) {
    synth.Update();
    System::Delay(10); // Reduced delay since optimized scanning is much faster
  }
}
