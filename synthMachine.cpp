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
 * 6. USB MIDI out over the Seed's second USB PHY (D29/D30), wired to the
 *    USB-C port on both boards
 *
 * Potentiometer Control System:
 * - A0: Wave Shape (Sine, Triangle, Square, Saw); master volume while shift
 *   is held
 * - A1..A4: one of four banks of parameters, chosen with the four pot-mode
 *   buttons (see POT_MODES):
 *     mode 1, envelope (default)  attack, decay, sustain, release
 *     mode 2, effects             filter cutoff, resonance, delay, reverb
 *     mode 3, LFO 1               rate, depth, shape, destination
 *     mode 4, LFO 2               rate, depth, shape, destination
 *   The LFOs (see Lfo) modulate a destination around its knob's value:
 *   shape is sine / triangle / square / ramp / sample-and-hold and the
 *   destination is none / cutoff / resonance / pitch / volume / delay /
 *   reverb. Both LFOs can drive the same destination. While LFO 1 has a
 *   destination and some depth, the Seed's LED blinks at its rate.
 *   A pot is shared between banks, so whenever it is handed to a parameter
 *   it doesn't match, turning it scales the parameter toward the knob
 *   instead of jumping, and the two line up at either end of the sweep
 *   (see Takeover). Switching banks therefore never makes the sound jump.
 *
 * Spare buttons, numbered left to right across the panel (see AUX_MAPPING
 * for which matrix nodes those are on each board):
 * - 1 and 2: octave down and up (two octaves each way, applied to new notes;
 *   held notes keep sounding where they are). They act on release so that
 *   pressing both doesn't first fire an octave change.
 *   Both held = shift. While shifted, the wave-shape pot becomes master
 *   volume, with the same takeover behaviour as the banks.
 * - 3 to 6: select pot bank 1 to 4 for A1..A4, on press.
 *
 * Signal chain: voices (pitch LFO) -> state-variable low-pass filter ->
 * delay -> reverb
 * -> soft limiter -> master volume. The delay and reverb buffers live in the
 * Seed's SDRAM (see the DSY_SDRAM_BSS globals).
 *
 * MIDI Output:
 * - USB MIDI on the EXTERNAL transport: D29 (D-) and D30 (D+), physical pins
 *   36 and 37, which both boards wire to their USB-C port. The Seed's own
 *   micro-USB is then only used for DFU flashing.
 *
 * Audio Output:
 * - Seed AUDIO OUT L/R (pins 18/19) -> MAX98306 class-D amp -> 2x 3W 4ohm
 *   speakers, plus a headphone path that mutes the speakers when a plug is in.
 * - D11 mutes the speaker amp on both boards, but the drive differs (see
 *   SpeakerAmp below). D13/D14 are the headphone detect and headphone amp mute
 *   on the carrier only. Wiring: WIRING.md (prototype), hardware/README.md
 *   (carrier).
 */

// ============================================================================
// Hardware profile
// ============================================================================
// Two units exist. They share the key matrix, pots, codec and the USB-C MIDI
// port on D29/D30, but wire the Seed pins that control the audio path
// differently:
//
//   make              SYNTH_HW_PROTOTYPE  Breadboard with the MAX98306
//   breakout.
//                                         D11 goes straight to the amp's SD
//                                         pin. No headphone jack.
//   make HW=carrier   SYNTH_HW_CARRIER    Carrier board in hardware/. D11 mutes
//                                         through transistor Q1, TPA6138A2
//                                         headphone amp with plug detect on
//                                         D13/D14.
//
// Building with neither define falls back to the prototype.
#if defined(SYNTH_HW_CARRIER) && defined(SYNTH_HW_PROTOTYPE)
#error "Define only one of SYNTH_HW_CARRIER / SYNTH_HW_PROTOTYPE"
#endif
#if !defined(SYNTH_HW_CARRIER) && !defined(SYNTH_HW_PROTOTYPE)
#define SYNTH_HW_PROTOTYPE 1
#endif

// Key-log build (`make KEYLOG=1`): every key event is printed on the Seed's
// micro-USB as a serial port (screen /dev/cu.usbmodem* 115200), to find out
// which matrix node a panel button is wired to. MIDI is off in this build:
// libDaisy's USB stack presents one device class for both ports, so the
// logger and MIDI can't run together. After flashing over DFU, press RESET:
// the Seed does not bring USB up after the DFU handoff.
#ifndef SYNTH_KEY_LOG
#define SYNTH_KEY_LOG 0
#endif

// USB MIDI transport. EXTERNAL is the D29/D30 pair (USB-C on both boards).
// Switch to INTERNAL to get MIDI on the Seed's own micro-USB for a quick test.
static constexpr auto USB_MIDI_PERIPH = MidiUsbTransport::Config::EXTERNAL;

// Pin definitions - must be defined outside the class
static constexpr Pin COL_PINS[6] = {seed::D4, seed::D5, seed::D6,
                                    seed::D7, seed::D8, seed::D9};
static constexpr Pin ROW_PINS[3] = {seed::D1, seed::D2, seed::D3};
static constexpr Pin C4_PIN = seed::D10;

// Speaker amp mute. Same pin on both boards, different drive (see SpeakerAmp).
static constexpr Pin SPEAKER_MUTE_PIN = seed::D11;
#if defined(SYNTH_HW_CARRIER)
static constexpr Pin HP_DET_PIN = seed::D13;  // jack switch: high = plug in
static constexpr Pin HP_MUTE_PIN = seed::D14; // TPA6138A2 ~MUTE, active low
#endif

// Functions the spare matrix buttons can have
enum AuxFn {
  AUX_NONE = 0,
  AUX_OCTAVE_DOWN,
  AUX_OCTAVE_UP,
  AUX_POT_MODE_1, // pots A1..A4 = envelope (the default bank)
  AUX_POT_MODE_2, // pots A1..A4 = effects
  AUX_POT_MODE_3, // pots A1..A4 = LFO 1
  AUX_POT_MODE_4  // pots A1..A4 = LFO 2
};

// ============================================================================
// Effects buffers
// ============================================================================
// ReverbSc carries about 400 KB of delay lines and the echo needs another
// 96 KB, more than the app can have of the H7's internal RAM, so both live in
// the Seed's SDRAM. hw.Init() brings the SDRAM up; SynthMachine::Init() then
// calls their Init(), which clears them (.sdram_bss is not zeroed at boot).
static constexpr int AUDIO_SAMPLE_RATE = 48000;
static constexpr size_t DELAY_MAX_SAMPLES = AUDIO_SAMPLE_RATE / 2; // 500 ms
static ReverbSc DSY_SDRAM_BSS reverb;
static DelayLine<float, DELAY_MAX_SAMPLES> DSY_SDRAM_BSS delayLine;

// ============================================================================
// MAX98306 speaker amp control
// ============================================================================
// Both boards mute the amp from the very first instruction so the codec's
// start-up transient never reaches the speakers; main() releases it once audio
// is running.
class SpeakerAmp {
  GPIO pin;

public:
#if defined(SYNTH_HW_CARRIER)
  // Carrier: D11 (net MUTE) feeds the base of Q1 through 10k, and Q1's
  // collector pulls the amp's ~SHDN low. The headphone jack's plug-detect
  // feeds the same base through its own 10k, with only a 100k pull-up behind
  // it. So D11 has three meaningful states:
  //   driven high -> Q1 on, speakers muted regardless of the jack
  //   input       -> Q1 follows the jack: headphones in = speakers muted
  //   driven low  -> Q1 held off, speakers ON even with headphones in,
  //                  because 10k to ground beats the jack's 100k pull-up
  // Never drive it low. "Run" means tri-state, not low.
  void Init() {
    // Set the output latch high while the pin is still an input, then switch
    // to push-pull, so it never drives low even for an instant.
    pin.Init(SPEAKER_MUTE_PIN, GPIO::Mode::INPUT, GPIO::Pull::NOPULL);
    pin.Write(true);
    Mute();
  }
  void Mute() {
    pin.Write(true);
    pin.Init(SPEAKER_MUTE_PIN, GPIO::Mode::OUTPUT, GPIO::Pull::NOPULL);
  }
  void Run() {
    pin.Init(SPEAKER_MUTE_PIN, GPIO::Mode::INPUT, GPIO::Pull::NOPULL);
  }
#else
  // Prototype: D11 goes straight to the breakout's SD pin (active low), which
  // the breakout pulls up to VDD (5 V). Open-drain so the Seed only ever sinks
  // it; writing true releases it to the pull-up. D11 is 5 V tolerant.
  void Init() {
    pin.Init(SPEAKER_MUTE_PIN, GPIO::Mode::OUTPUT_OD, GPIO::Pull::NOPULL);
    Mute();
  }
  void Mute() { pin.Write(false); }
  void Run() { pin.Write(true); }
#endif
};

// ============================================================================
// Headphone jack and TPA6138A2 headphone amp (carrier only)
// ============================================================================
// On the prototype this is a stub and D13/D14 are left untouched.
//
// Speaker muting on plug-in is done in hardware (the jack switch drives Q1),
// so all the firmware has to do is manage the headphone amp's own mute and
// remember whether a plug is in.
class HeadphoneJack {
#if defined(SYNTH_HW_CARRIER)
  GPIO detect; // D13: HP_DET, high = plug inserted
  GPIO hpMute; // D14: TPA6138A2 ~MUTE, low = headphone amp muted
  int level = 0;
  bool pluggedIn = false;
  static const int DEBOUNCE_SAMPLES = 5; // x ~10 ms main-loop period

public:
  void Init() {
    // Mute the headphone amp from the first instruction. Besides the boot
    // pop, this matters while nothing is plugged in: the jack's switch then
    // ties HP_DET to the headphone amp's left output, and audio peaks on
    // that node would turn Q1 on and gate the speaker amp. A muted headphone
    // amp holds the node near ground.
    hpMute.Init(HP_MUTE_PIN, GPIO::Mode::OUTPUT, GPIO::Pull::NOPULL);
    hpMute.Write(false);
    detect.Init(HP_DET_PIN, GPIO::Mode::INPUT, GPIO::Pull::NOPULL);
  }

  // Call once per main-loop pass. Integrating debounce: the count climbs while
  // the pin reads high and falls while it reads low, and the state only flips
  // at the ends of the range. Audio on the node (centred on 0 V) can't hold
  // it high, so an unplug is still recognised while a note is sounding.
  void Update() {
    if (detect.Read()) {
      if (level < DEBOUNCE_SAMPLES)
        level++;
    } else if (level > 0) {
      level--;
    }

    if (!pluggedIn && level >= DEBOUNCE_SAMPLES) {
      pluggedIn = true;
      hpMute.Write(true); // headphones in: run the headphone amp
    } else if (pluggedIn && level <= 0) {
      pluggedIn = false;
      hpMute.Write(false); // headphones out: mute it again
    }
  }

  bool IsPluggedIn() const { return pluggedIn; }
#else
public:
  void Init() {}
  void Update() {}
  bool IsPluggedIn() const { return false; }
#endif
};

class SynthMachine {
private:
  // Hardware configuration
  DaisySeed hw;
  MidiUsbHandler midi; // USB MIDI handler
  SpeakerAmp speakerAmp;
  HeadphoneJack headphoneJack;

  // Audio parameters
  static const int NUM_VOICES = 13;
  static const int SAMPLE_RATE = AUDIO_SAMPLE_RATE;
  static const int BLOCK_SIZE = 48;

  // Button matrix: 6 columns (D4..D9) driven low one at a time, 3 rows
  // (D1..D3) read with pull-ups. A diode per key, cathode to the column.
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

  // Note mapping: [col][row] -> note index, -1 = not a note (see AUX_MAPPING)
  // Note indices: 0=C5, 1=B4, 2=A#4/Bb4, 3=A4, 4=G#4/Ab4, 5=G4, 6=F#4/Gb4,
  // 7=F4, 8=E4, 9=D#4/Eb4, 10=D4, 11=C#4/Db4, 12=C4 (C4 is the direct D10 key)
  // BTN1..BTN6 are the carrier board's names for the six spare nodes.
  const int NOTE_MAPPING[MATRIX_COLS][MATRIX_ROWS] = {
      {-1, -1, 0}, // Column 0 (D4): BTN1, BTN2, C5
      {-1, 2, 1},  // Column 1 (D5): BTN3, A#4, B4
      {-1, 4, 3},  // Column 2 (D6): BTN4, G#4, A4
      {-1, 6, 5},  // Column 3 (D7): BTN5, F#4, G4
      {-1, 9, 7},  // Column 4 (D8): BTN6, D#4, F4
      {11, 10, 8}  // Column 5 (D9): C#4, D4, E4
  };

  // Spare-button functions: [col][row] -> AuxFn, for nodes that are -1 above.
  // Left to right on the panel: octave down, octave up, then pot modes 1 to
  // 4. The boards wire them to different nodes. On the carrier they are
  // BTN1..BTN6 in order (c0 r0, c0 r1, c1 r0, c2 r0, c3 r0, c4 r0). The
  // prototype's spare buttons run right-to-left through the carrier's
  // numbering: its left pair was measured as c4 r0 and c3 r0 with
  // `make KEYLOG=1`, and the four mode buttons below follow on from that
  // (c2 r0, c1 r0, c0 r1, c0 r0) without having been measured yet.
#if defined(SYNTH_HW_CARRIER)
  const AuxFn AUX_MAPPING[MATRIX_COLS][MATRIX_ROWS] = {
      {AUX_OCTAVE_DOWN, AUX_OCTAVE_UP, AUX_NONE}, // Column 0: BTN1, BTN2
      {AUX_POT_MODE_1, AUX_NONE, AUX_NONE},       // Column 1: BTN3
      {AUX_POT_MODE_2, AUX_NONE, AUX_NONE},       // Column 2: BTN4
      {AUX_POT_MODE_3, AUX_NONE, AUX_NONE},       // Column 3: BTN5
      {AUX_POT_MODE_4, AUX_NONE, AUX_NONE},       // Column 4: BTN6
      {AUX_NONE, AUX_NONE, AUX_NONE},             // Column 5
  };
#else
  const AuxFn AUX_MAPPING[MATRIX_COLS][MATRIX_ROWS] = {
      {AUX_POT_MODE_4, AUX_POT_MODE_3, AUX_NONE}, // Column 0: 6th, 5th spare
      {AUX_POT_MODE_2, AUX_NONE, AUX_NONE},       // Column 1: 4th spare
      {AUX_POT_MODE_1, AUX_NONE, AUX_NONE},       // Column 2: 3rd spare
      {AUX_OCTAVE_UP, AUX_NONE, AUX_NONE},        // Column 3: 2nd spare
      {AUX_OCTAVE_DOWN, AUX_NONE, AUX_NONE},      // Column 4: leftmost spare
      {AUX_NONE, AUX_NONE, AUX_NONE},             // Column 5
  };
#endif

#if SYNTH_KEY_LOG
  const char *const NOTE_NAMES[13] = {"C5", "B4",  "A#4", "A4", "G#4",
                                      "G4", "F#4", "F4",  "E4", "D#4",
                                      "D4", "C#4", "C4"};
  const char *const SPARE_NAMES[MATRIX_COLS][MATRIX_ROWS] = {
      {"BTN1", "BTN2", "-"}, {"BTN3", "-", "-"}, {"BTN4", "-", "-"},
      {"BTN5", "-", "-"},    {"BTN6", "-", "-"}, {"-", "-", "-"},
  };
#endif

  // Octave shift, applied to notes as they start
  static const int OCTAVE_MIN = -2;
  static const int OCTAVE_MAX = 2;
  int octave = 0;
  bool octDownHeld = false;
  bool octUpHeld = false;
  bool shiftActive = false;    // both octave buttons held right now
  bool shiftChordUsed = false; // this press became a shift, so no octave step
  int activeMidiNote[13];      // MIDI number sent at noteOn, reused at noteOff

  // ADC channels for the potentiometers: A0 is the wave-shape / volume pot,
  // A1..A4 are the bank of four whose meaning the pot-mode buttons choose.
  static const int WAVESHAPE_PIN = 0;
  static const int BANK_FIRST_PIN = 1;
  static const int BANK_POTS = 4;

  // Every pot-controlled parameter. Each is stored in pot units (0..1) and
  // mapped onto the synth by applyParam().
  enum Param {
    P_NONE = -1,
    P_WAVESHAPE = 0,
    P_VOLUME,
    P_ATTACK,
    P_DECAY,
    P_SUSTAIN,
    P_RELEASE,
    P_CUTOFF,
    P_RESONANCE,
    P_DELAY,
    P_REVERB,
    P_LFO1_RATE,
    P_LFO1_DEPTH,
    P_LFO1_SHAPE,
    P_LFO1_DEST,
    P_LFO2_RATE,
    P_LFO2_DEPTH,
    P_LFO2_SHAPE,
    P_LFO2_DEST,
    NUM_PARAMS
  };

  // Stepped parameters (a few zones across the sweep, like the wave shape)
  // get a coarser change threshold than continuous ones.
  static bool isStepped(Param p) {
    return p == P_WAVESHAPE || p == P_LFO1_SHAPE || p == P_LFO1_DEST ||
           p == P_LFO2_SHAPE || p == P_LFO2_DEST;
  }

  // What A1..A4 control in each pot mode. P_NONE would leave a pot idle.
  static const int NUM_POT_MODES = 4;
  const Param POT_MODES[NUM_POT_MODES][BANK_POTS] = {
      {P_ATTACK, P_DECAY, P_SUSTAIN, P_RELEASE},  // mode 1: envelope (default)
      {P_CUTOFF, P_RESONANCE, P_DELAY, P_REVERB}, // mode 2: effects
      {P_LFO1_RATE, P_LFO1_DEPTH, P_LFO1_SHAPE, P_LFO1_DEST}, // mode 3
      {P_LFO2_RATE, P_LFO2_DEPTH, P_LFO2_SHAPE, P_LFO2_DEST}, // mode 4
  };
  int potMode = 0;

  // A pot serves several parameters, so the knob's position rarely matches
  // the one it has just been handed. Until they meet, turning the knob moves
  // the parameter by the same fraction of its remaining travel in that
  // direction, so the knob always responds, nothing ever jumps, and the two
  // line up at either end of the sweep (or within TAKEOVER_WINDOW).
  struct Takeover {
    float value;   // where the parameter is (pot units, 0..1)
    bool tracking; // pot currently controls it
    float lastPot; // previous pot reading, for the crossing test
  };
  static constexpr float TAKEOVER_WINDOW = 0.02f;

  // Per-parameter state, indexed by Param. The envelope bank starts out
  // tracking so the knobs take it over at once on boot, as the pots always
  // did; everything else waits for its knob to catch up.
  Takeover params[NUM_PARAMS] = {
      {0.0f, true, 0.0f},    // P_WAVESHAPE: sine
      {1.0f, false, 0.0f},   // P_VOLUME: full
      {0.009f, true, 0.0f},  // P_ATTACK: 10 ms
      {0.0909f, true, 0.0f}, // P_DECAY: 100 ms
      {0.7f, true, 0.0f},    // P_SUSTAIN: 70%
      {0.0201f, true, 0.0f}, // P_RELEASE: 50 ms
      {1.0f, false, 0.0f},   // P_CUTOFF: wide open
      {0.0f, false, 0.0f},   // P_RESONANCE: none
      {0.0f, false, 0.0f},   // P_DELAY: off
      {0.0f, false, 0.0f},   // P_REVERB: off
      {0.5f, false, 0.0f},   // P_LFO1_RATE: 1 Hz
      {0.0f, false, 0.0f},   // P_LFO1_DEPTH: off
      {0.0f, false, 0.0f},   // P_LFO1_SHAPE: sine
      {0.0f, false, 0.0f},   // P_LFO1_DEST: none
      {0.5f, false, 0.0f},   // P_LFO2_RATE: 1 Hz
      {0.0f, false, 0.0f},   // P_LFO2_DEPTH: off
      {0.0f, false, 0.0f},   // P_LFO2_SHAPE: sine
      {0.0f, false, 0.0f},   // P_LFO2_DEST: none
  };

  // ADSR envelope parameters, in seconds / level
  float attackTime = 0.01f;  // 10ms attack
  float decayTime = 0.1f;    // 100ms decay
  float sustainLevel = 0.7f; // 70% sustain level
  float releaseTime = 0.05f; // 50ms release

  // Wave shape parameter
  float waveShape = 0.0f;

  // Master volume: pot position (0..1) and the gain the audio callback
  // applies, which is the square of it for a more even sweep. The callback
  // smooths its way to volumeGain to avoid zipper noise.
  float masterVolume = 1.0f;
  float volumeGain = 1.0f;
  float gainSmoothed = 1.0f;

  // Effects. The main loop writes the targets; the audio callback eases its
  // own copies toward them once per block (1 ms) so knob moves don't zipper.
  //   Cutoff: 10 octaves from CUTOFF_MIN_HZ, so the knob is exponential.
  //   Resonance: capped below Svf's self-oscillation point. The filter runs
  //          with drive 0: DaisySP's drive term is a cubic that diverges to
  //          infinity when the state exceeds about 1.4, and the NaN would
  //          then poison the delay and reverb lines for good. The mix is
  //          also soft-limited before it reaches the filter.
  //   Delay: one knob sets the echo level and, with it, the feedback, so a
  //          closed knob lets the line run out. Fixed delay time.
  //   Reverb: one knob sets the wet level of a fixed-size room.
  static constexpr float CUTOFF_MIN_HZ = 20.0f;
  static constexpr float CUTOFF_OCTAVES = 10.0f;
  static constexpr float RES_MAX = 0.9f;
  static constexpr float DELAY_TIME_S = 0.35f;
  static constexpr float DELAY_FEEDBACK_MAX = 0.7f;
  static constexpr float REVERB_FEEDBACK = 0.87f;
  static constexpr float REVERB_LP_HZ = 9000.0f;
  static constexpr float REVERB_WET_SCALE = 0.6f;
  static constexpr float FX_SMOOTHING = 0.05f; // per block, ~20 ms
  Svf filter;
  float filterCutoffHz = CUTOFF_MIN_HZ * 1024.0f;
  float filterRes = 0.0f;
  float delayWet = 0.0f;
  float reverbWet = 0.0f;
  float cutoffSmoothed = CUTOFF_MIN_HZ * 1024.0f;
  float resSmoothed = 0.0f;
  float delayWetSmoothed = 0.0f;
  float reverbWetSmoothed = 0.0f;

  // Two LFOs, stepped once per audio block (1 kHz). Each pushes its
  // destination around the knob's value; the knob's own value is never
  // touched, so takeover keeps working and zero depth lands back on the knob.
  // Full depth means: cutoff +-LFO_CUTOFF_OCTAVES, pitch +-LFO_PITCH_OCTAVES
  // (squared, so the first third of the knob is vibrato), volume dips to
  // silence (tremolo only goes down), the rest +-the whole knob range.
  enum LfoShape {
    LFO_SINE = 0,
    LFO_TRI,
    LFO_SQUARE,
    LFO_RAMP,
    LFO_SH,
    NUM_LFO_SHAPES
  };
  enum LfoDest {
    DEST_NONE = 0,
    DEST_CUTOFF,
    DEST_RESONANCE,
    DEST_PITCH,
    DEST_VOLUME,
    DEST_DELAY,
    DEST_REVERB,
    NUM_LFO_DESTS
  };
  struct Lfo {
    // Settings, written by the main loop from the pots
    float rateHz;
    float depth; // 0..1
    LfoShape shape;
    LfoDest dest;
    // Running state, owned by the audio callback
    float phase;  // 0..1
    float held;   // current sample-and-hold value
    float out;    // this block's output, -1..1
    uint32_t rng; // for sample-and-hold
  };
  static const int NUM_LFOS = 2;
  Lfo lfos[NUM_LFOS] = {
      {1.0f, 0.0f, LFO_SINE, DEST_NONE, 0.0f, 0.0f, 0.0f, 0x1234567u},
      {1.0f, 0.0f, LFO_SINE, DEST_NONE, 0.0f, 0.0f, 0.0f, 0x89abcdefu},
  };
  static constexpr float LFO_RATE_MIN_HZ = 0.05f;
  static constexpr float LFO_RATE_RANGE = 400.0f; // ratio max/min: to 20 Hz
  static constexpr float LFO_CUTOFF_OCTAVES = 5.0f;
  static constexpr float LFO_PITCH_OCTAVES = 1.0f;
  static constexpr float BLOCK_SECONDS = (float)BLOCK_SIZE / SAMPLE_RATE;

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

  // Musical note frequencies at octave 0 (C4 to C5, sharps/flats included)
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

  // Frequency multiplier per octave step, indexed by octave - OCTAVE_MIN
  const float OCTAVE_SCALE[5] = {0.25f, 0.5f, 1.0f, 2.0f, 4.0f};

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

    for (int i = 0; i < 13; i++) {
      activeMidiNote[i] = midiNoteNumbers[i];
    }
  }

  void Init() {
    // Silence both amps before anything else. libDaisy's GPIO driver enables
    // its own port clock, so this works ahead of hw.Init(), and hw.Init() is
    // where the codec is brought up, which is the source of the start-up pop.
    speakerAmp.Init();
    headphoneJack.Init();

    // Initialize Daisy Seed (this also brings up the SDRAM)
    hw.Init();
    hw.SetAudioBlockSize(BLOCK_SIZE);

    // Effects chain
    filter.Init(SAMPLE_RATE);
    filter.SetDrive(0.0f); // linear: see the note on the effects above
    filter.SetFreq(filterCutoffHz);
    filter.SetRes(filterRes);
    delayLine.Init();
    delayLine.SetDelay(DELAY_TIME_S * SAMPLE_RATE);
    reverb.Init(SAMPLE_RATE);
    reverb.SetFeedback(REVERB_FEEDBACK);
    reverb.SetLpFreq(REVERB_LP_HZ);

#if SYNTH_KEY_LOG
    // Serial log on the Seed's micro-USB; MIDI is off in this build
    hw.StartLog(false);
    hw.PrintLine(
        "synthMachine key log: KEY <col> <row> <carrier name> down|up");
#endif

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

#if !SYNTH_KEY_LOG
    // Initialize MIDI USB interface (see USB_MIDI_PERIPH)
    MidiUsbHandler::Config midi_cfg;
    midi_cfg.transport_config.periph = USB_MIDI_PERIPH;
    // Optional: tweak retries if you blast back-to-back messages
    midi_cfg.transport_config.tx_retry_count = 3;
    midi.Init(midi_cfg);
#endif
    System::Delay(100);
  }

  // Read one of the pots (ADC channel 0..4) as 0..1
  float readPot(int pin) { return hw.adc.GetFloat(pin); }

  // Feed one pot reading to a takeover-guarded parameter. Returns true when
  // the parameter's value changed.
  bool takeoverUpdate(Takeover &t, float pot, float threshold) {
    float prev = t.lastPot;
    t.lastPot = pot;

    if (!t.tracking && fabs(pot - t.value) < TAKEOVER_WINDOW) {
      t.tracking = true; // knob and value have met
    }

    if (t.tracking) {
      if (fabs(pot - t.value) > threshold) {
        t.value = pot;
        return true;
      }
      return false;
    }

    // Not tracking yet: scale the knob's movement onto the value's remaining
    // travel in the same direction.
    float d = pot - prev;
    if (fabs(d) < 0.002f) {
      return false; // ADC noise
    }
    if (d > 0.0f) {
      float room = 1.0f - prev;
      if (room > 0.001f) {
        t.value += (1.0f - t.value) * d / room;
      }
    } else {
      if (prev > 0.001f) {
        t.value += t.value * d / prev;
      }
    }
    if (t.value < 0.0f) {
      t.value = 0.0f;
    }
    if (t.value > 1.0f) {
      t.value = 1.0f;
    }
    if (fabs(pot - t.value) < TAKEOVER_WINDOW) {
      t.tracking = true;
    }
    return true;
  }

  // Hand a pot to a parameter: the parameter waits for the knob to come back
  // to it (scaling toward it meanwhile) before following it again.
  void handoff(Param p, int pin) {
    if (p == P_NONE) {
      return;
    }
    params[p].tracking = false;
    params[p].lastPot = readPot(pin);
  }

  // Shift changed: both of the A0 parameters wait for the knob.
  void onShiftChanged() {
    handoff(P_WAVESHAPE, WAVESHAPE_PIN);
    handoff(P_VOLUME, WAVESHAPE_PIN);
  }

  // A pot-mode button: hand A1..A4 to the new bank's parameters.
  void setPotMode(int mode) {
    if (mode == potMode) {
      return;
    }
    potMode = mode;
    for (int i = 0; i < BANK_POTS; i++) {
      handoff(POT_MODES[mode][i], BANK_FIRST_PIN + i);
    }
#if SYNTH_KEY_LOG
    hw.PrintLine("pot mode %d", mode + 1);
#endif
  }

  // Map a parameter's pot-units value (0..1) onto the synth
  void applyParam(Param p, float v) {
    switch (p) {
    case P_WAVESHAPE:
      waveShape = v;
      waveShapeChanged = true;
      break;
    case P_VOLUME:
      masterVolume = v;
      volumeGain = masterVolume * masterVolume;
      break;
    case P_ATTACK: // 1 ms to 1 s
      attackTime = 0.001f + v * (1.0f - 0.001f);
      adsrParamsChanged = true;
      break;
    case P_DECAY: // 10 ms to 1 s
      decayTime = 0.01f + v * (1.0f - 0.01f);
      adsrParamsChanged = true;
      break;
    case P_SUSTAIN: // 0 to 100%
      sustainLevel = v;
      adsrParamsChanged = true;
      break;
    case P_RELEASE: // 10 ms to 2 s
      releaseTime = 0.01f + v * (2.0f - 0.01f);
      adsrParamsChanged = true;
      break;
    case P_CUTOFF:
      filterCutoffHz = CUTOFF_MIN_HZ * powf(2.0f, v * CUTOFF_OCTAVES);
      break;
    case P_RESONANCE:
      filterRes = v * RES_MAX;
      break;
    case P_DELAY:
      delayWet = v;
      break;
    case P_REVERB:
      reverbWet = v;
      break;
    case P_LFO1_RATE:
    case P_LFO2_RATE:
      lfos[p >= P_LFO2_RATE].rateHz = LFO_RATE_MIN_HZ * powf(LFO_RATE_RANGE, v);
      break;
    case P_LFO1_DEPTH:
    case P_LFO2_DEPTH:
      lfos[p >= P_LFO2_RATE].depth = v;
      break;
    case P_LFO1_SHAPE:
    case P_LFO2_SHAPE:
      lfos[p >= P_LFO2_RATE].shape = (LfoShape)stepped(v, NUM_LFO_SHAPES);
      break;
    case P_LFO1_DEST:
    case P_LFO2_DEST:
      lfos[p >= P_LFO2_RATE].dest = (LfoDest)stepped(v, NUM_LFO_DESTS);
      break;
    default:
      break;
    }
  }

  // Split a 0..1 pot into n equal zones
  static int stepped(float v, int n) {
    int i = (int)(v * n);
    return i < 0 ? 0 : (i >= n ? n - 1 : i);
  }

  // Function to update parameters from the potentiometers
  void updatePotentiometers() {
    // A0: wave shape, or master volume while shift is held. The wave-shape
    // threshold is coarser because it only has four steps.
    Param p0 = shiftActive ? P_VOLUME : P_WAVESHAPE;
    float pot0 = readPot(WAVESHAPE_PIN);
    if (takeoverUpdate(params[p0], pot0, isStepped(p0) ? 0.01f : 0.002f)) {
      applyParam(p0, params[p0].value);
    }

    // A1..A4: whatever the current pot mode assigns them
    for (int i = 0; i < BANK_POTS; i++) {
      Param p = POT_MODES[potMode][i];
      if (p == P_NONE) {
        continue;
      }
      float pot = readPot(BANK_FIRST_PIN + i);
      if (takeoverUpdate(params[p], pot, isStepped(p) ? 0.01f : 0.002f)) {
        applyParam(p, params[p].value);
      }
    }
  }

  void setOctave(int value) {
    if (value < OCTAVE_MIN)
      value = OCTAVE_MIN;
    if (value > OCTAVE_MAX)
      value = OCTAVE_MAX;
    octave = value;
#if SYNTH_KEY_LOG
    hw.PrintLine("octave %d", octave);
#endif
  }

  // Octave buttons. A single button steps the octave on release; holding
  // both is shift. Once a press has been part of a shift chord it no longer
  // steps the octave, so shift can be used without side effects.
  void auxButton(AuxFn fn, bool pressed) {
    if (fn >= AUX_POT_MODE_1 && fn <= AUX_POT_MODE_4) {
      if (pressed) {
        setPotMode(fn - AUX_POT_MODE_1);
      }
      return;
    }

    if (fn == AUX_OCTAVE_DOWN) {
      octDownHeld = pressed;
    } else if (fn == AUX_OCTAVE_UP) {
      octUpHeld = pressed;
    } else {
      return;
    }

    bool both = octDownHeld && octUpHeld;
    if (both) {
      shiftChordUsed = true;
    }

    if (!pressed && !shiftChordUsed) {
      setOctave(octave + (fn == AUX_OCTAVE_UP ? 1 : -1));
    }
    if (!octDownHeld && !octUpHeld) {
      shiftChordUsed = false;
    }

    if (both != shiftActive) {
      shiftActive = both;
      onShiftChanged();
#if SYNTH_KEY_LOG
      hw.PrintLine("shift %s", shiftActive ? "on" : "off");
#endif
    }
  }

  // A matrix node changed state: dispatch to a note or a spare-button function
  void keyEvent(int col, int row, bool pressed) {
    int noteIndex = NOTE_MAPPING[col][row];
#if SYNTH_KEY_LOG
    hw.PrintLine("KEY c%d r%d  %-4s %s", col, row,
                 noteIndex >= 0 ? NOTE_NAMES[noteIndex] : SPARE_NAMES[col][row],
                 pressed ? "down" : "up");
#endif
    if (noteIndex >= 0) {
      if (pressed) {
        noteOn(noteIndex);
      } else {
        noteOff(noteIndex);
      }
      return;
    }
    AuxFn fn = AUX_MAPPING[col][row];
    if (fn != AUX_NONE) {
      auxButton(fn, pressed);
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
            keyEvent(columnIndex, rowIndex, true);
          }

          lastDebounceTime[columnIndex][rowIndex] = System::GetNow();
        }

        // Check if button is released
        if (buttonState == false && buttonStates[columnIndex][rowIndex]) {
          buttonStates[columnIndex][rowIndex] = false;
          keyEvent(columnIndex, rowIndex, false);
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
#if !SYNTH_KEY_LOG
    // Listen for MIDI events (required for USB MIDI to work properly)
    midi.Listen();
#endif

    // Track the headphone jack (no-op on the prototype)
    headphoneJack.Update();

    // Update parameters from potentiometers
    updatePotentiometers();

    // LED: solid while running, blinking at LFO 1's rate while it does
    // something, as the only visible sign of the LFO banks.
    bool lfo1Active = lfos[0].dest != DEST_NONE && lfos[0].depth > 0.0f;
    hw.SetLed(!lfo1Active || lfos[0].out > 0.0f);

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
#if SYNTH_KEY_LOG
      hw.PrintLine("KEY D10    C4   %s", currentC4State ? "down" : "up");
#endif
      if (currentC4State) {
        noteOn(12); // C4 is note index 12
      } else {
        noteOff(12);
      }
      lastC4State = currentC4State;
    }
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

    // Set up the voice at the current octave
    voices[voiceIndex].frequency =
        noteFrequencies[note] * OCTAVE_SCALE[octave - OCTAVE_MIN];
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

    // Send MIDI Note On over USB. Remember the number so the Note Off
    // matches even if the octave changes while the key is held.
    if (note >= 0 && note < 13) {
      activeMidiNote[note] = midiNoteNumbers[note] + 12 * octave;
      // Note On: 0x90 = NoteOn channel 1, note number, velocity
#if !SYNTH_KEY_LOG
      uint8_t note_on[] = {0x90 | 0x00, (uint8_t)activeMidiNote[note], 127};
      midi.SendMessage(note_on, sizeof(note_on));
#endif
    }
  }

  void noteOff(int note) {
    // Find ALL voices playing this note and turn them off
    for (int i = 0; i < NUM_VOICES; i++) {
      if (voices[i].isActive && voices[i].note == note) {
        voices[i].gate = false;
      }
    }

    // Send MIDI Note Off over USB
    if (note >= 0 && note < 13) {
      // Note Off: 0x80 = NoteOff channel 1, note number, velocity 0
#if !SYNTH_KEY_LOG
      uint8_t note_off[] = {0x80 | 0x00, (uint8_t)activeMidiNote[note], 0};
      midi.SendMessage(note_off, sizeof(note_off));
#endif
    }
  }

  // Soft knee above 0.9 so a loud chord folds over rather than clipping
  static float softLimit(float x) {
    if (x > 0.9f) {
      return 0.9f + (x - 0.9f) * 0.1f;
    }
    if (x < -0.9f) {
      return -0.9f + (x + 0.9f) * 0.1f;
    }
    return x;
  }

  // Advance an LFO by one block and leave its output in lfo.out
  static void stepLfo(Lfo &lfo) {
    lfo.phase += lfo.rateHz * BLOCK_SECONDS;
    if (lfo.phase >= 1.0f) {
      lfo.phase -= (int)lfo.phase;
      lfo.rng = lfo.rng * 1664525u + 1013904223u;
      lfo.held = (float)(lfo.rng >> 8) * (2.0f / 16777216.0f) - 1.0f;
    }
    switch (lfo.shape) {
    case LFO_SINE:
      lfo.out = sinf(lfo.phase * TWOPI_F);
      break;
    case LFO_TRI:
      lfo.out =
          lfo.phase < 0.5f ? 4.0f * lfo.phase - 1.0f : 3.0f - 4.0f * lfo.phase;
      break;
    case LFO_SQUARE:
      lfo.out = lfo.phase < 0.5f ? 1.0f : -1.0f;
      break;
    case LFO_RAMP:
      lfo.out = 2.0f * lfo.phase - 1.0f;
      break;
    default:
      lfo.out = lfo.held;
      break;
    }
  }

  static float clamp01(float x) {
    return x < 0.0f ? 0.0f : (x > 1.0f ? 1.0f : x);
  }

  void AudioCallback(AudioHandle::InterleavingInputBuffer in,
                     AudioHandle::InterleavingOutputBuffer out, size_t size) {
    // Ease the effect controls toward their targets once per block
    cutoffSmoothed += (filterCutoffHz - cutoffSmoothed) * FX_SMOOTHING;
    resSmoothed += (filterRes - resSmoothed) * FX_SMOOTHING;
    delayWetSmoothed += (delayWet - delayWetSmoothed) * FX_SMOOTHING;
    reverbWetSmoothed += (reverbWet - reverbWetSmoothed) * FX_SMOOTHING;

    // Step the LFOs and gather what each destination gets this block
    float cutoffOctaves = 0.0f, pitchOctaves = 0.0f, resMod = 0.0f;
    float delayMod = 0.0f, reverbMod = 0.0f, volMult = 1.0f;
    for (int l = 0; l < NUM_LFOS; l++) {
      Lfo &lfo = lfos[l];
      stepLfo(lfo);
      float m = lfo.out * lfo.depth;
      switch (lfo.dest) {
      case DEST_CUTOFF:
        cutoffOctaves += m * LFO_CUTOFF_OCTAVES;
        break;
      case DEST_RESONANCE:
        resMod += m;
        break;
      case DEST_PITCH:
        pitchOctaves += lfo.out * lfo.depth * lfo.depth * LFO_PITCH_OCTAVES;
        break;
      case DEST_VOLUME:
        volMult *= 1.0f - lfo.depth * (1.0f - lfo.out) * 0.5f;
        break;
      case DEST_DELAY:
        delayMod += m;
        break;
      case DEST_REVERB:
        reverbMod += m;
        break;
      default:
        break;
      }
    }

    // Effective values for this block: the knob's smoothed value plus the LFOs
    float cutoffHz = cutoffSmoothed * powf(2.0f, cutoffOctaves);
    float cutoffMax = CUTOFF_MIN_HZ * powf(2.0f, CUTOFF_OCTAVES);
    cutoffHz = cutoffHz < CUTOFF_MIN_HZ
                   ? CUTOFF_MIN_HZ
                   : (cutoffHz > cutoffMax ? cutoffMax : cutoffHz);
    float res = clamp01((resSmoothed + resMod * RES_MAX) / RES_MAX) * RES_MAX;
    float delayLevel = clamp01(delayWetSmoothed + delayMod);
    float reverbLevel =
        clamp01(reverbWetSmoothed + reverbMod) * REVERB_WET_SCALE;
    filter.SetFreq(cutoffHz);
    filter.SetRes(res);
    float delayFeedback = delayLevel * DELAY_FEEDBACK_MAX;

    // Pitch: retune the sounding voices around their note
    float pitchMult = powf(2.0f, pitchOctaves);
    for (int v = 0; v < NUM_VOICES; v++) {
      if (voices[v].isActive) {
        voices[v].osc.SetFreq(voices[v].frequency * pitchMult);
      }
    }

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

      // Keep the mix within the filter's safe range, then low-pass it. If
      // the filter state has gone non-finite anyway, restart it clean rather
      // than let the NaN spread into the delay and reverb lines.
      output = softLimit(output);
      filter.Process(output);
      output = filter.Low();
      if (!(output == output)) {
        filter.Init(SAMPLE_RATE);
        filter.SetDrive(0.0f);
        filter.SetFreq(cutoffHz);
        filter.SetRes(res);
        output = 0.0f;
      }

      // Echo: the line holds the dry signal plus its own decaying repeats
      float echo = delayLine.Read();
      delayLine.Write(output + echo * delayFeedback);
      output += echo * delayLevel;

      // Reverb, which is where the two channels part ways
      float verbL, verbR;
      reverb.Process(output, output, &verbL, &verbR);
      float left = softLimit(output + verbL * reverbLevel);
      float right = softLimit(output + verbR * reverbLevel);

      // Master volume, eased over ~40 ms so turning the knob doesn't zipper
      gainSmoothed += (volumeGain - gainSmoothed) * 0.0005f;

      out[i] = left * gainSmoothed * volMult;
      out[i + 1] = right * gainSmoothed * volMult;
    }
  }

  // Speaker amp on/off (true = let the speakers play). On the carrier "on"
  // still defers to the headphone jack, which mutes the speakers in hardware
  // while a plug is in.
  void SetSpeakersEnabled(bool enabled) {
    if (enabled) {
      speakerAmp.Run();
    } else {
      speakerAmp.Mute();
    }
  }

  // True while a headphone plug is detected (always false on the prototype)
  bool HeadphonesPluggedIn() const { return headphoneJack.IsPluggedIn(); }

  // Getter for hardware reference
  DaisySeed &GetHardware() { return hw; }
};

// Global instance
SynthMachine synth;

// Did the ROM bootloader jump straight into us after a DFU flash, rather
// than a reset? The bootloader leaves its USB clock enabled; a cold boot never
// has one enabled this early. Read before anything else touches RCC.
static bool BootedFromDfu() {
  return (RCC->AHB1ENR & (RCC_AHB1ENR_USB2OTGFSEN | RCC_AHB1ENR_USB1OTGHSEN)) !=
         0;
}

// Audio callback function for DaisyLib
void AudioCallback(AudioHandle::InterleavingInputBuffer in,
                   AudioHandle::InterleavingOutputBuffer out, size_t size) {
  synth.AudioCallback(in, out, size);
}

// Main function
int main(void) {
  bool fromDfu = BootedFromDfu();

  // Initialize the synth
  synth.Init();

  // Set the audio callback
  synth.GetHardware().StartAudio(AudioCallback);
  synth.GetHardware().SetAudioBlockSize(48);

  // Let the codec settle, then let the speakers play
  System::Delay(200);
  synth.SetSpeakersEnabled(true);

  // Status on the Seed's LED: three blinks if we were entered straight from
  // the DFU bootloader, then solid on = initialised and running.
  DaisySeed &led = synth.GetHardware();
  for (int i = 0; fromDfu && i < 3; i++) {
    led.SetLed(true);
    System::Delay(150);
    led.SetLed(false);
    System::Delay(150);
  }
  led.SetLed(true);

  // Main loop
  while (1) {
    synth.Update();
    System::Delay(10); // Reduced delay since optimized scanning is much faster
  }
}
