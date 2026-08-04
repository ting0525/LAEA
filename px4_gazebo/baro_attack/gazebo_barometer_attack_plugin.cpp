/*
 * Barometer source-attack plugin for PX4 SITL Gazebo.
 *
 * Drop-in replacement for PX4's stock gazebo_barometer_plugin. It reproduces the
 * stock ISA pressure model + noise and publishes the same Pressure message on the
 * same Gazebo transport topic, then adds a controlled barometer-drift attack
 * before PX4 receives the data.
 *
 * Attack is driven at runtime by attack_scheduler.py -> attack_gazebo_bridge ->
 * laea_attack::attackGzTopic(). A command with source=="barometer" mode=="drift"
 * injects scalar = altitude-equivalent offset [m]: the reported pressure altitude
 * is shifted by +scalar*scale and the absolute pressure is shifted consistently
 * (dP = -rho*g*dh), modulated by the shared ramp/hold/recovery lifecycle
 * (attack_window.h). Absent any command the plugin behaves exactly like stock.
 *
 * Original stock logic: Copyright (c) 2018 PX4 Development Team (BSD-3). Attack
 * hooks added for LAEA.
 */

#include <cmath>
#include <mutex>
#include <random>
#include <string>

#include <boost/bind.hpp>

#include <common.h>
#include <sdf/sdf.hh>

#include <gazebo/common/Plugin.hh>
#include <gazebo/gazebo.hh>
#include <gazebo/msgs/msgs.hh>
#include <gazebo/physics/physics.hh>
#include <gazebo/transport/transport.hh>
#include <gazebo/util/system.hh>
#include <ignition/math.hh>

#include <Pressure.pb.h>

#include "attack_window.h"
#include "attack_command_json.h"

namespace gazebo {

static constexpr auto kDefaultBarometerTopic = "/baro";
static constexpr auto kDefaultPubRate = 50.0;   // [Hz]
static constexpr auto kDefaultAltHome = 488.0;  // meters

class GAZEBO_VISIBLE BarometerAttackPlugin : public ModelPlugin {
 public:
  BarometerAttackPlugin()
      : ModelPlugin(), baro_rnd_y2_(0.0), baro_rnd_use_last_(false), baro_drift_pa_(0.0) {}
  ~BarometerAttackPlugin() override { update_connection_->~Connection(); }

 protected:
  void getSdfParams(sdf::ElementPtr sdf)
  {
    const char *env_alt = std::getenv("PX4_HOME_ALT");
    if (env_alt) {
      alt_home_ = std::stod(env_alt);
    } else {
      alt_home_ = kDefaultAltHome;
    }

    namespace_.clear();
    if (sdf->HasElement("robotNamespace")) {
      namespace_ = sdf->GetElement("robotNamespace")->Get<std::string>();
    } else {
      gzerr << "[gazebo_barometer_attack_plugin] Please specify a robotNamespace.\n";
    }

    if (sdf->HasElement("pubRate")) {
      pub_rate_ = sdf->GetElement("pubRate")->Get<unsigned int>();
    } else {
      pub_rate_ = kDefaultPubRate;
    }

    if (sdf->HasElement("baroTopic")) {
      baro_topic_ = sdf->GetElement("baroTopic")->Get<std::string>();
    } else {
      baro_topic_ = kDefaultBarometerTopic;
    }

    if (sdf->HasElement("baroDriftPaPerSec")) {
      baro_drift_pa_per_sec_ = sdf->GetElement("baroDriftPaPerSec")->Get<double>();
    } else {
      baro_drift_pa_per_sec_ = 0.0;
    }
  }

  void Load(physics::ModelPtr model, sdf::ElementPtr sdf) override
  {
    getSdfParams(sdf);

    model_ = model;
    world_ = model_->GetWorld();
#if GAZEBO_MAJOR_VERSION >= 9
    last_time_ = world_->SimTime();
    last_pub_time_ = world_->SimTime();
    pose_model_start_ = model_->WorldPose();
#else
    last_time_ = world_->GetSimTime();
    last_pub_time_ = world_->GetSimTime();
    pose_model_start_ = ignitionFromGazeboMath(model_->GetWorldPose());
#endif

    node_handle_ = transport::NodePtr(new transport::Node());
    node_handle_->Init(namespace_);

    update_connection_ = event::Events::ConnectWorldUpdateBegin(
        boost::bind(&BarometerAttackPlugin::OnUpdate, this, _1));

    pub_baro_ = node_handle_->Advertise<sensor_msgs::msgs::Pressure>(
        "~/" + model_->GetName() + baro_topic_, 10);

    // Runtime attack command relayed from attack_scheduler via the bridge.
    cmd_sub_ = node_handle_->Subscribe(laea_attack::attackGzTopic(),
                                       &BarometerAttackPlugin::OnAttackCommand, this);

    standard_normal_distribution_ = std::normal_distribution<double>(0.0, 1.0);
    gravity_W_ = world_->Gravity();

    gzmsg << "[gazebo_barometer_attack_plugin] loaded topic=~/" << model_->GetName()
          << baro_topic_ << " cmd_topic=" << laea_attack::attackGzTopic() << "\n";
  }

  void OnUpdate(const common::UpdateInfo &)
  {
#if GAZEBO_MAJOR_VERSION >= 9
    const common::Time current_time = world_->SimTime();
#else
    const common::Time current_time = world_->GetSimTime();
#endif
    const double dt = (current_time - last_pub_time_).Double();

    if (dt > 1.0 / pub_rate_) {
#if GAZEBO_MAJOR_VERSION >= 9
      const ignition::math::Pose3d pose_model_world = model_->WorldPose();
#else
      const ignition::math::Pose3d pose_model_world = ignitionFromGazeboMath(model_->GetWorldPose());
#endif
      ignition::math::Pose3d pose_model;
      pose_model.Pos().Z() = pose_model_world.Pos().Z() - pose_model_start_.Pos().Z();

      const float pose_n_z = -pose_model.Pos().Z();  // ENU -> NED

      // ISA model for the troposphere (valid up to 11km above MSL).
      const float lapse_rate = 0.0065f;
      const float temperature_msl = 288.0f;
      const float alt_msl = (float)alt_home_ - pose_n_z;
      const float temperature_local = temperature_msl - lapse_rate * alt_msl;
      const float pressure_ratio = powf(temperature_msl / temperature_local, 5.256f);
      const float pressure_msl = 101325.0f;
      const float absolute_pressure = pressure_msl / pressure_ratio;

      // Density (needed both for the altitude conversion and the attack offset).
      const float density_ratio = powf(temperature_msl / temperature_local, 4.256f);
      const float rho = 1.225f / density_ratio;
      const float g = gravity_W_.Length();

      // Gaussian noise (polar Box-Muller), same as stock.
      double y1;
      {
        double x1, x2, w;
        if (!baro_rnd_use_last_) {
          do {
            x1 = 2.0 * standard_normal_distribution_(random_generator_) - 1.0;
            x2 = 2.0 * standard_normal_distribution_(random_generator_) - 1.0;
            w = x1 * x1 + x2 * x2;
          } while (w >= 1.0);
          w = sqrt((-2.0 * log(w)) / w);
          y1 = x1 * w;
          baro_rnd_y2_ = x2 * w;
          baro_rnd_use_last_ = true;
        } else {
          y1 = baro_rnd_y2_;
          baro_rnd_use_last_ = false;
        }
      }

      const float abs_pressure_noise = 1.0f * (float)y1;  // 1 Pa RMS noise
      baro_drift_pa_ += baro_drift_pa_per_sec_ * dt;

      // ---- LAEA barometer-drift attack ----
      // delta_h [m] reported-altitude offset; convert to a consistent pressure
      // perturbation dP = -rho*g*delta_h so absolute pressure and pressure
      // altitude stay physically consistent.
      const double delta_h = computeBaroAltitudeOffset(current_time.Double());
      const float attack_pa = -(float)delta_h * g * rho;

      const float pressure_perturbation = abs_pressure_noise + baro_drift_pa_ + attack_pa;
      const float absolute_pressure_noisy = absolute_pressure + pressure_perturbation;

      baro_msg_.set_absolute_pressure(absolute_pressure_noisy * 0.01f);  // hPa
      baro_msg_.set_pressure_altitude(alt_msl - pressure_perturbation / (g * rho));
      baro_msg_.set_temperature(temperature_local - 273.0f);
      baro_msg_.set_time_usec(current_time.Double() * 1e6);

      last_pub_time_ = current_time;
      pub_baro_->Publish(baro_msg_);
    }
  }

 private:
  // Runs on a transport thread; guard shared state.
  void OnAttackCommand(const boost::shared_ptr<const msgs::GzString> &msg)
  {
    laea_attack::AttackCommand cmd;
    if (!laea_attack::parseAttackCommandJson(msg->data(), cmd)) {
      return;
    }
    std::lock_guard<std::mutex> lock(cmd_mutex_);
    cmd_ = cmd;
    has_command_ = true;
  }

  // Reported-altitude offset [m] for this step from the active command, or 0.
  double computeBaroAltitudeOffset(double sim_time_sec)
  {
    laea_attack::AttackCommand cmd;
    {
      std::lock_guard<std::mutex> lock(cmd_mutex_);
      if (!has_command_) {
        return 0.0;
      }
      cmd = cmd_;
    }

    if (!cmd.enabled || cmd.source != "barometer") {
      return 0.0;
    }
    if (cmd.mode != "drift" && cmd.mode != "bias") {
      return 0.0;
    }
    const double scale = laea_attack::attackScale(sim_time_sec, cmd);
    if (scale <= 0.0) {
      if (attack_active_logged_) {
        gzmsg << "[gazebo_barometer_attack_plugin] baro attack inactive sim_t=" << sim_time_sec << "\n";
        attack_active_logged_ = false;
      }
      return 0.0;
    }
    if (!attack_active_logged_) {
      gzmsg << "[gazebo_barometer_attack_plugin] baro drift attack active sim_t=" << sim_time_sec << "\n";
      attack_active_logged_ = true;
    }
    return cmd.scalar * scale;
  }

  std::string namespace_;
  physics::ModelPtr model_;
  physics::WorldPtr world_;
  event::ConnectionPtr update_connection_;
  std::string baro_topic_;

  transport::NodePtr node_handle_;
  transport::PublisherPtr pub_baro_;
  transport::SubscriberPtr cmd_sub_;

  std::mutex cmd_mutex_;
  laea_attack::AttackCommand cmd_;
  bool has_command_{false};
  bool attack_active_logged_{false};

  sensor_msgs::msgs::Pressure baro_msg_;
  unsigned int pub_rate_;

  std::default_random_engine random_generator_;
  std::normal_distribution<double> standard_normal_distribution_;

  common::Time last_pub_time_;
  common::Time last_time_;

  ignition::math::Pose3d pose_model_start_;
  ignition::math::Vector3d gravity_W_;
  double alt_home_;

  double baro_rnd_y2_;
  bool baro_rnd_use_last_;

  double baro_drift_pa_per_sec_;
  double baro_drift_pa_;
};

GZ_REGISTER_MODEL_PLUGIN(BarometerAttackPlugin)
}  // namespace gazebo
