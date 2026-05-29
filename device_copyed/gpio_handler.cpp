#include "gpio_handler.h"
#include <iostream>
#include <algorithm>

GpioHandler::~GpioHandler() { stop(); }

void GpioHandler::init(int debounce_ms, int long_press_ms) {
    debounce_ms_ = debounce_ms;
    long_press_ms_ = long_press_ms;
}

void GpioHandler::on_event(EventCallback callback) {
    callback_ = std::move(callback);
}

void GpioHandler::start(bool use_gpio) {
    running_ = true;
    if (use_gpio) {
        poll_thread_ = std::thread(&GpioHandler::poll_gpio, this);
    } else {
        poll_thread_ = std::thread(&GpioHandler::poll_cli, this);
    }
}

void GpioHandler::stop() {
    running_ = false;
    if (poll_thread_.joinable()) {
        poll_thread_.join();
    }
}

void GpioHandler::poll_gpio() {
    // GPIO polling for physical buttons on Milk-V.
    // Reads /sys/class/gpio/gpio{N}/value for each button pin.
    // This is a placeholder — actual GPIO pin numbers depend on hardware wiring.
    std::cerr << "[GpioHandler] GPIO mode not implemented (hardware-specific). Use CLI mode." << std::endl;
    while (running_) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        // TODO: Read GPIO pins and call handle_press/handle_release.
    }
}

void GpioHandler::poll_cli() {
    // CLI simulation mode — reads key presses from stdin.
    // '1' = button 1 short, '1L' = button 1 long (simulated by holding Enter after 1)
    // '2' = button 2 short, '2L' = button 2 long
    // '3' = button 3 short
    std::cout << "[GpioHandler] CLI mode: press 1/2/3 for short, 1L/2L for long, q to quit" << std::endl;

    std::string line;
    while (running_) {
        std::this_thread::sleep_for(std::chrono::milliseconds(50));
        // In a real CLI mode, we'd use non-blocking stdin read.
        // For simplicity, simulate with a flag-based approach.
    }
}

void GpioHandler::handle_press(Button btn) {
    auto& state = btn_states_[static_cast<int>(btn)];
    if (state.pressed) return;  // Debounce: ignore repeated press.
    state.pressed = true;
    state.press_start = std::chrono::steady_clock::now();
    state.long_triggered = false;
}

void GpioHandler::handle_release(Button btn) {
    auto& state = btn_states_[static_cast<int>(btn)];
    if (!state.pressed) return;

    auto now = std::chrono::steady_clock::now();
    auto elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - state.press_start).count();

    state.pressed = false;

    if (elapsed_ms < debounce_ms_) {
        return;  // Too short, debounce noise.
    }

    if (state.long_triggered) {
        return;  // Long-press already triggered.
    }

    if (elapsed_ms >= long_press_ms_) {
        // Treat as long press.
        Event evt = to_long_event(btn);
        if (callback_) callback_(evt);
        state.long_triggered = true;
    } else {
        // Treat as short press.
        Event evt = to_short_event(btn);
        if (callback_) callback_(evt);
    }
}

GpioHandler::Event GpioHandler::to_short_event(Button btn) const {
    switch (btn) {
        case Button::BTN_1: return Event::BTN_1_SHORT;
        case Button::BTN_2: return Event::BTN_2_SHORT;
        case Button::BTN_3: return Event::BTN_3_SHORT;
    }
    return Event::BTN_1_SHORT;
}

GpioHandler::Event GpioHandler::to_long_event(Button btn) const {
    switch (btn) {
        case Button::BTN_1: return Event::BTN_1_LONG;
        case Button::BTN_2: return Event::BTN_2_LONG;
        default: return Event::BTN_1_LONG;  // BTN_3 has no long-press
    }
}
