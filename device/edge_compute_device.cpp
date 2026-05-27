#include "app.h"
#include <iostream>
#include <csignal>
#include <string>

static volatile bool g_running = true;

static void signal_handler(int signo) {
    if (signo == SIGINT || signo == SIGTERM) {
        std::cout << "\n[main] Received signal " << signo << ", shutting down..." << std::endl;
        g_running = false;
    }
}

int main(int argc, char* argv[]) {
    // Config path relative to tdl_sdk/sample/edge_compute_device/.
    std::string config_path = "config/milkv_config.yaml";
    if (argc > 1) {
        config_path = argv[1];
    }

    // Register signal handlers.
    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    std::cout << "=== Edge Compute - Device Service (Milk-V) ===" << std::endl;
    std::cout << "Config: " << config_path << std::endl;

    // Initialize application.
    App app;
    if (!app.init(config_path)) {
        std::cerr << "[main] App initialization failed" << std::endl;
        return 1;
    }

    std::cout << "[main] Device service started. Press Ctrl+C to stop." << std::endl;

    // Main loop runs in app.run(). This blocks until shutdown.
    // The signal handler sets g_running = false, but app.run() has its own running_ flag.
    // For clean shutdown, we could run app.run() in a thread and wait for signal.
    // For simplicity on embedded device, run inline.
    app.run();

    app.shutdown();
    std::cout << "[main] Device service stopped." << std::endl;
    return 0;
}
