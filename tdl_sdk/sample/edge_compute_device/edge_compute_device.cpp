#include "app.h"
#include <iostream>
#include <csignal>
#include <string>

static App* g_app = nullptr;

static void signal_handler(int signo) {
    if (signo == SIGINT || signo == SIGTERM) {
        std::cout << "\n[main] Received signal " << signo << ", shutting down..." << std::endl;
        if (g_app) {
            g_app->shutdown();
        }
    }
}

int main(int argc, char* argv[]) {
    std::string config_path = "config/milkv_config.yaml";
    if (argc > 1) {
        config_path = argv[1];
    }

    signal(SIGINT, signal_handler);
    signal(SIGTERM, signal_handler);

    std::cout << "=== Edge Compute - Device Service (Milk-V) ===" << std::endl;
    std::cout << "Config: " << config_path << std::endl;

    App app;
    g_app = &app;

    if (!app.init(config_path)) {
        std::cerr << "[main] App initialization failed" << std::endl;
        return 1;
    }

    std::cout << "[main] Device service started. Press Ctrl+C to stop." << std::endl;

    app.run();

    app.shutdown();
    std::cout << "[main] Device service stopped." << std::endl;
    return 0;
}
