// Shared attack lifecycle for LAEA source-layer sensor attack plugins.
//
// Header-only and dependency-free so it can be included both by the Gazebo
// sensor plugins (compiled inside the PX4 sitl_gazebo tree) and by the
// ROS->Gazebo bridge (compiled in the catkin workspace). The install scripts
// copy this header next to the plugin sources in ${SITL_DIR}/src/.
//
// All times are seconds on the simulation clock. Under use_sim_time this is the
// same clock as gazebo world SimTime and rospy.Time.now(); the scheduler emits
// scheduled_start on that clock. Verify this alignment before trusting onset
// timing (see attack_layer_plan: A1 sim_time check).

#ifndef LAEA_ATTACK_WINDOW_H
#define LAEA_ATTACK_WINDOW_H

#include <string>

namespace laea_attack {

// One decoded attack command, source-agnostic. vx/vy/vz and scalar carry the
// magnitude; their meaning depends on source+mode (see attack_profiles.yaml):
//   gps  bias          -> [east, north, up] position bias (m)
//   gps  velocity_bias -> [vx, vy, vz] velocity bias (m/s)
//   imu  gyro_bias     -> [wx, wy, wz] gyro bias (rad/s)
//   baro drift         -> scalar = altitude-equivalent offset (m)
struct AttackCommand {
  bool enabled = false;
  std::string source;    // "gps" | "imu" | "barometer"
  std::string mode;
  std::string severity;  // "low" | "high"
  double scheduled_start_sec = 0.0;  // absolute sim onset; <= 0 => unscheduled
  double ramp_sec = 0.0;
  double duration_sec = 0.0;  // length of the main window; <= 0 => open-ended
  double recovery_sec = 0.0;  // fade-out tail after the main window
  double vx = 0.0;
  double vy = 0.0;
  double vz = 0.0;
  double scalar = 0.0;
  unsigned int seed = 0;
};

// Gazebo transport topic the bridge publishes on and every source-layer attack
// plugin subscribes to. Shared so both ends cannot drift apart.
inline const char* attackGzTopic() { return "/laea/attack/command"; }

inline double clamp01(double value) {
  if (value < 0.0) return 0.0;
  if (value > 1.0) return 1.0;
  return value;
}

// Intensity in [0, 1] over the lifecycle:
//   t < 0                         : 0           (before onset)
//   0 .. ramp                     : t / ramp    (ramp up, inside the window)
//   ramp .. duration              : 1           (full)
//   duration .. duration+recovery : fade 1 -> 0 (recovery tail)
//   otherwise                     : 0
// ramp is contained within duration so the scheduler's active window
// [onset, onset+duration] matches the main injection window; recovery is a tail.
inline double attackScale(double now_sec, const AttackCommand& cmd) {
  if (!cmd.enabled || cmd.scheduled_start_sec <= 0.0) return 0.0;

  const double t = now_sec - cmd.scheduled_start_sec;
  if (t < 0.0) return 0.0;

  // Open-ended: ramp up then stay on until the command is cleared.
  if (cmd.duration_sec <= 0.0) {
    return cmd.ramp_sec > 0.0 ? clamp01(t / cmd.ramp_sec) : 1.0;
  }

  // Main window (ramp happens inside it).
  if (t < cmd.duration_sec) {
    return cmd.ramp_sec > 0.0 ? clamp01(t / cmd.ramp_sec) : 1.0;
  }

  // Recovery tail.
  if (cmd.recovery_sec > 0.0 && t < cmd.duration_sec + cmd.recovery_sec) {
    return 1.0 - clamp01((t - cmd.duration_sec) / cmd.recovery_sec);
  }

  return 0.0;
}

inline bool attackActive(double now_sec, const AttackCommand& cmd) {
  return attackScale(now_sec, cmd) > 0.0;
}

}  // namespace laea_attack

#endif  // LAEA_ATTACK_WINDOW_H
