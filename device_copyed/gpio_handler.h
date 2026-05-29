#pragma once
#include <string>
#include <functional>
#include <atomic>
#include <thread>
#include <chrono>

// Button handling with 500ms debounce and 2s long-press detection.
// Supports both GPIO (polling) and CLI simulation (stdin).
class GpioHandler {
public:
    enum class Button {
        BTN_1 = 1,  // Short: switch policy. Long: force local mode.
        BTN_2 = 2,  // Short: face_attendance. Long: behavior_analyze.
        BTN_3 = 3,  // Short: report_generate.
    };

    enum class Event {
        BTN_1_SHORT,
        BTN_1_LONG,
        BTN_2_SHORT,
        BTN_2_LONG,
        BTN_3_SHORT,
    };

    using EventCallback = std::function<void(Event)>;

    GpioHandler() = default;
    ~GpioHandler();

    // Configure debounce and long-press timing.
    void init(int debounce_ms = 500, int long_press_ms = 2000);

    // Register event callback.
    void on_event(EventCallback callback);

    // Start polling (GPIO or CLI mode).
    void start(bool use_gpio = false);
    void stop();

private:
    int debounce_ms_ = 500;
    int long_press_ms_ = 2000;
    std::atomic<bool> running_{false};
    std::thread poll_thread_;
    EventCallback callback_;

    // Per-button press state for debounce + long-press tracking.
    struct ButtonState {
        std::chrono::steady_clock::time_point press_start;
        bool pressed = false;
        bool long_triggered = false;
    };
    ButtonState btn_states_[4];  // 1-indexed

    void poll_gpio();
    void poll_cli();  // Reads stdin for simulated key presses
    void handle_press(Button btn);
    void handle_release(Button btn);
    Event to_short_event(Button btn) const;
    Event to_long_event(Button btn) const;
};
