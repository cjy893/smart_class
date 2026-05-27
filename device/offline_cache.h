#pragma once
#include <string>
#include <vector>
#include <mutex>
#include <fstream>

// Appends person_count results to a JSON lines file while offline.
// On reconnect, replays all cached records and deletes the file.
class OfflineCache {
public:
    OfflineCache() = default;
    ~OfflineCache();

    bool init(const std::string& cache_path);

    // Append a person_count record to the cache file.
    void append(const std::string& json_record);

    // Read all cached records. Returns empty vector if file doesn't exist or is empty.
    std::vector<std::string> read_all();

    // Delete the cache file (after successful sync).
    void clear();

    bool has_data() const;

private:
    std::string cache_path_;
    std::mutex mutex_;
    std::ofstream file_;
};
