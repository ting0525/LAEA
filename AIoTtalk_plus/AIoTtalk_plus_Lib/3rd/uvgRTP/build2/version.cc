#include "uvgrtp/version.hh"

#include <cstdint>
#include <string>

namespace uvgrtp {

#ifdef RTP_RELEASE_COMMIT
    std::string get_version() { return "3.1.1-release"; }
#else
    std::string get_version() { return "3.1.1-source"; }
#endif

uint16_t get_version_major() { return 3; }

uint16_t get_version_minor() { return 1; }

uint16_t get_version_patch() { return 1; }

std::string get_git_hash() {return "source";}
} // namespace uvgrtp
