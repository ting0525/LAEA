// Dependency-free parser for the attack command JSON emitted by
// attack_scheduler.py on /laea/attack/command_json and forwarded onto a Gazebo
// transport topic by attack_gazebo_bridge. Kept dependency-free (no nlohmann)
// so it can be compiled inside the PX4 sitl_gazebo tree alongside the plugins.
//
// The payload is flat (one nested array, "vector") and produced by Python
// json.dumps(sort_keys=True), so this does targeted per-key extraction rather
// than full JSON parsing. Keys: source, mode, severity, enabled,
// scheduled_start, ramp_s, duration_s, recovery_s, vector[3], scalar, seed.

#ifndef LAEA_ATTACK_COMMAND_JSON_H
#define LAEA_ATTACK_COMMAND_JSON_H

#include <cstddef>
#include <cstdlib>
#include <string>

#include "attack_window.h"

namespace laea_attack {
namespace detail {

// Position just past `"key":` (tolerating whitespace), or npos.
inline std::size_t findValuePos(const std::string& s, const std::string& key) {
  const std::string token = "\"" + key + "\"";
  std::size_t k = s.find(token);
  if (k == std::string::npos) return std::string::npos;
  std::size_t c = s.find(':', k + token.size());
  if (c == std::string::npos) return std::string::npos;
  ++c;
  while (c < s.size() && (s[c] == ' ' || s[c] == '\t' || s[c] == '\n')) ++c;
  return c;
}

inline bool getString(const std::string& s, const std::string& key, std::string& out) {
  std::size_t p = findValuePos(s, key);
  if (p == std::string::npos || p >= s.size() || s[p] != '"') return false;
  ++p;
  std::string v;
  while (p < s.size() && s[p] != '"') {
    if (s[p] == '\\' && p + 1 < s.size()) ++p;  // skip escape
    v.push_back(s[p++]);
  }
  out = v;
  return true;
}

inline bool getDouble(const std::string& s, const std::string& key, double& out) {
  std::size_t p = findValuePos(s, key);
  if (p == std::string::npos) return false;
  out = std::strtod(s.c_str() + p, nullptr);
  return true;
}

inline bool getBool(const std::string& s, const std::string& key, bool& out) {
  std::size_t p = findValuePos(s, key);
  if (p == std::string::npos) return false;
  out = (s.compare(p, 4, "true") == 0);
  return true;
}

// "vector": [x, y, z]
inline bool getVector3(const std::string& s, double& x, double& y, double& z) {
  std::size_t p = findValuePos(s, "vector");
  if (p == std::string::npos || p >= s.size() || s[p] != '[') return false;
  char* end = nullptr;
  x = std::strtod(s.c_str() + p + 1, &end);
  std::size_t q = s.find(',', static_cast<std::size_t>(end - s.c_str()));
  if (q == std::string::npos) return false;
  y = std::strtod(s.c_str() + q + 1, &end);
  q = s.find(',', static_cast<std::size_t>(end - s.c_str()));
  if (q == std::string::npos) return false;
  z = std::strtod(s.c_str() + q + 1, nullptr);
  return true;
}

}  // namespace detail

// Fill cmd from the command JSON. Missing fields keep their current value.
// Returns true if "source" was present (a minimally valid command).
inline bool parseAttackCommandJson(const std::string& json, AttackCommand& cmd) {
  using namespace detail;
  bool ok = false;
  std::string sval;
  if (getString(json, "source", sval)) { cmd.source = sval; ok = true; }
  if (getString(json, "mode", sval)) cmd.mode = sval;
  if (getString(json, "severity", sval)) cmd.severity = sval;

  bool bval = false;
  if (getBool(json, "enabled", bval)) cmd.enabled = bval;

  double d = 0.0;
  if (getDouble(json, "scheduled_start", d)) cmd.scheduled_start_sec = d;
  if (getDouble(json, "ramp_s", d)) cmd.ramp_sec = d;
  if (getDouble(json, "duration_s", d)) cmd.duration_sec = d;
  if (getDouble(json, "recovery_s", d)) cmd.recovery_sec = d;
  if (getDouble(json, "scalar", d)) cmd.scalar = d;
  if (getDouble(json, "seed", d)) cmd.seed = static_cast<unsigned int>(d);

  getVector3(json, cmd.vx, cmd.vy, cmd.vz);
  return ok;
}

}  // namespace laea_attack

#endif  // LAEA_ATTACK_COMMAND_JSON_H
