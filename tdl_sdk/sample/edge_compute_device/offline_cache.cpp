#include "offline_cache.h"
#include <fstream>
#include <sstream>
#include <sys/stat.h>

bool OfflineCache::init(const std::string& cache_path) {
    cache_path_ = cache_path;
    return true;
}

OfflineCache::~OfflineCache() {
    if (file_.is_open()) {
        file_.close();
    }
}

void OfflineCache::append(const std::string& json_record) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!file_.is_open()) {
        file_.open(cache_path_, std::ios::app);
    }
    if (file_.is_open()) {
        file_ << json_record << std::endl;
        file_.flush();
    }
}

std::vector<std::string> OfflineCache::read_all() {
    std::lock_guard<std::mutex> lock(mutex_);
    std::vector<std::string> records;

    if (file_.is_open()) {
        file_.close();
    }

    std::ifstream in(cache_path_);
    if (!in.is_open()) {
        return records;
    }

    std::string line;
    while (std::getline(in, line)) {
        if (!line.empty()) {
            records.push_back(line);
        }
    }
    in.close();
    return records;
}

void OfflineCache::clear() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (file_.is_open()) {
        file_.close();
    }
    std::remove(cache_path_.c_str());
}

bool OfflineCache::has_data() const {
    struct stat st;
    if (stat(cache_path_.c_str(), &st) != 0) {
        return false;
    }
    return st.st_size > 0;
}
