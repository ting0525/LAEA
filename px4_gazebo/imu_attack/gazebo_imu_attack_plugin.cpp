/*
 * IMU source-attack plugin for PX4 SITL Gazebo.
 *
 * Drop-in replacement for PX4's stock gazebo_imu_plugin. It reproduces the stock
 * IMU model (true rates + ETH noise model) and publishes the same Imu message on
 * the same Gazebo transport topic, then adds a controlled gyroscope-bias attack
 * before PX4 receives the IMU data.
 *
 * Attack is driven at runtime by attack_scheduler.py -> attack_gazebo_bridge ->
 * laea_attack::attackGzTopic(). A command with source=="imu" mode=="gyro_bias"
 * injects vector = [wx, wy, wz] rad/s onto the angular velocity, modulated by the
 * shared ramp/hold/recovery lifecycle (attack_window.h). Absent any command the
 * plugin behaves exactly like the stock IMU plugin.
 *
 * Original stock logic: Copyright 2015 ASL ETH Zurich (Apache-2.0). Attack hooks
 * added for LAEA.
 */

#include <chrono>
#include <cmath>
#include <iostream>
#include <mutex>
#include <random>
#include <stdio.h>
#include <string>

#include <boost/bind.hpp>

#include <Eigen/Core>
#include "Imu.pb.h"
#include <gazebo/common/common.hh>
#include <gazebo/common/Plugin.hh>
#include <gazebo/gazebo.hh>
#include <gazebo/physics/physics.hh>
#include <ignition/math.hh>
#include "gazebo/msgs/msgs.hh"
#include "gazebo/transport/transport.hh"

#include "common.h"

#include "attack_window.h"
#include "attack_command_json.h"

namespace gazebo {

// Default values for use with ADIS16448 IMU (mirrors the stock plugin).
static constexpr double kDefaultAdisGyroscopeNoiseDensity =
    2.0 * 35.0 / 3600.0 / 180.0 * M_PI;
static constexpr double kDefaultAdisGyroscopeRandomWalk =
    2.0 * 4.0 / 3600.0 / 180.0 * M_PI;
static constexpr double kDefaultAdisGyroscopeBiasCorrelationTime = 1.0e+3;
static constexpr double kDefaultAdisGyroscopeTurnOnBiasSigma =
    0.5 / 180.0 * M_PI;
static constexpr double kDefaultAdisAccelerometerNoiseDensity = 2.0 * 2.0e-3;
static constexpr double kDefaultAdisAccelerometerRandomWalk = 2.0 * 3.0e-3;
static constexpr double kDefaultAdisAccelerometerBiasCorrelationTime = 300.0;
static constexpr double kDefaultAdisAccelerometerTurnOnBiasSigma = 20.0e-3 * 9.8;
static constexpr double kDefaultGravityMagnitude = 9.8068;

static const std::string kDefaultImuTopic = "imu";

struct ImuParameters {
  double gyroscope_noise_density;
  double gyroscope_random_walk;
  double gyroscope_bias_correlation_time;
  double gyroscope_turn_on_bias_sigma;
  double accelerometer_noise_density;
  double accelerometer_random_walk;
  double accelerometer_bias_correlation_time;
  double accelerometer_turn_on_bias_sigma;
  double gravity_magnitude;

  ImuParameters()
      : gyroscope_noise_density(kDefaultAdisGyroscopeNoiseDensity),
        gyroscope_random_walk(kDefaultAdisGyroscopeRandomWalk),
        gyroscope_bias_correlation_time(kDefaultAdisGyroscopeBiasCorrelationTime),
        gyroscope_turn_on_bias_sigma(kDefaultAdisGyroscopeTurnOnBiasSigma),
        accelerometer_noise_density(kDefaultAdisAccelerometerNoiseDensity),
        accelerometer_random_walk(kDefaultAdisAccelerometerRandomWalk),
        accelerometer_bias_correlation_time(kDefaultAdisAccelerometerBiasCorrelationTime),
        accelerometer_turn_on_bias_sigma(kDefaultAdisAccelerometerTurnOnBiasSigma),
        gravity_magnitude(kDefaultGravityMagnitude) {}
};

class GAZEBO_VISIBLE GazeboImuAttackPlugin : public ModelPlugin {
 public:
  GazeboImuAttackPlugin() : ModelPlugin(), velocity_prev_W_(0, 0, 0) {}
  ~GazeboImuAttackPlugin() override { updateConnection_->~Connection(); }

 protected:
  void Load(physics::ModelPtr _model, sdf::ElementPtr _sdf) override
  {
    model_ = _model;
    world_ = model_->GetWorld();

    namespace_.clear();
    if (_sdf->HasElement("robotNamespace")) {
      namespace_ = _sdf->GetElement("robotNamespace")->Get<std::string>();
    } else {
      gzerr << "[gazebo_imu_attack_plugin] Please specify a robotNamespace.\n";
    }
    node_handle_ = transport::NodePtr(new transport::Node());
    node_handle_->Init(namespace_);

    if (_sdf->HasElement("linkName")) {
      link_name_ = _sdf->GetElement("linkName")->Get<std::string>();
    } else {
      gzerr << "[gazebo_imu_attack_plugin] Please specify a linkName.\n";
    }
    link_ = model_->GetLink(link_name_);
    if (link_ == NULL) {
      gzthrow("[gazebo_imu_attack_plugin] Couldn't find specified link \"" << link_name_ << "\".");
    }

    frame_id_ = link_name_;

    getSdfParam<std::string>(_sdf, "imuTopic", imu_topic_, kDefaultImuTopic);
    getSdfParam<double>(_sdf, "gyroscopeNoiseDensity",
                        imu_parameters_.gyroscope_noise_density,
                        imu_parameters_.gyroscope_noise_density);
    getSdfParam<double>(_sdf, "gyroscopeRandomWalk",
                        imu_parameters_.gyroscope_random_walk,
                        imu_parameters_.gyroscope_random_walk);
    getSdfParam<double>(_sdf, "gyroscopeBiasCorrelationTime",
                        imu_parameters_.gyroscope_bias_correlation_time,
                        imu_parameters_.gyroscope_bias_correlation_time);
    assert(imu_parameters_.gyroscope_bias_correlation_time > 0.0);
    getSdfParam<double>(_sdf, "gyroscopeTurnOnBiasSigma",
                        imu_parameters_.gyroscope_turn_on_bias_sigma,
                        imu_parameters_.gyroscope_turn_on_bias_sigma);
    getSdfParam<double>(_sdf, "accelerometerNoiseDensity",
                        imu_parameters_.accelerometer_noise_density,
                        imu_parameters_.accelerometer_noise_density);
    getSdfParam<double>(_sdf, "accelerometerRandomWalk",
                        imu_parameters_.accelerometer_random_walk,
                        imu_parameters_.accelerometer_random_walk);
    getSdfParam<double>(_sdf, "accelerometerBiasCorrelationTime",
                        imu_parameters_.accelerometer_bias_correlation_time,
                        imu_parameters_.accelerometer_bias_correlation_time);
    assert(imu_parameters_.accelerometer_bias_correlation_time > 0.0);
    getSdfParam<double>(_sdf, "accelerometerTurnOnBiasSigma",
                        imu_parameters_.accelerometer_turn_on_bias_sigma,
                        imu_parameters_.accelerometer_turn_on_bias_sigma);

#if GAZEBO_MAJOR_VERSION >= 9
    last_time_ = world_->SimTime();
#else
    last_time_ = world_->GetSimTime();
#endif

    updateConnection_ = event::Events::ConnectWorldUpdateBegin(
        boost::bind(&GazeboImuAttackPlugin::OnUpdate, this, _1));

    imu_pub_ = node_handle_->Advertise<sensor_msgs::msgs::Imu>(
        "~/" + model_->GetName() + imu_topic_, 10);

    // Runtime attack command relayed from attack_scheduler via the bridge.
    cmd_sub_ = node_handle_->Subscribe(laea_attack::attackGzTopic(),
                                       &GazeboImuAttackPlugin::OnAttackCommand, this);

    for (int i = 0; i < 9; i++) {
      switch (i) {
        case 0:
        case 4:
        case 8:
          imu_message_.add_angular_velocity_covariance(
              imu_parameters_.gyroscope_noise_density *
              imu_parameters_.gyroscope_noise_density);
          imu_message_.add_orientation_covariance(-1.0);
          imu_message_.add_linear_acceleration_covariance(
              imu_parameters_.accelerometer_noise_density *
              imu_parameters_.accelerometer_noise_density);
          break;
        default:
          imu_message_.add_angular_velocity_covariance(0.0);
          imu_message_.add_orientation_covariance(-1.0);
          imu_message_.add_linear_acceleration_covariance(0.0);
          break;
      }
    }

    gravity_W_ = world_->Gravity();
    imu_parameters_.gravity_magnitude = gravity_W_.Length();

    standard_normal_distribution_ = std::normal_distribution<double>(0.0, 1.0);

    gyroscope_bias_.setZero();
    accelerometer_bias_.setZero();

    gzmsg << "[gazebo_imu_attack_plugin] loaded topic=~/" << model_->GetName()
          << imu_topic_ << " cmd_topic=" << laea_attack::attackGzTopic() << "\n";
  }

  void addNoise(Eigen::Vector3d *linear_acceleration,
                Eigen::Vector3d *angular_velocity, const double dt)
  {
    assert(dt > 0.0);

    double tau_g = imu_parameters_.gyroscope_bias_correlation_time;
    double sigma_g_d = 1 / sqrt(dt) * imu_parameters_.gyroscope_noise_density;
    double sigma_b_g = imu_parameters_.gyroscope_random_walk;
    double sigma_b_g_d =
        sqrt(-sigma_b_g * sigma_b_g * tau_g / 2.0 * (exp(-2.0 * dt / tau_g) - 1.0));
    double phi_g_d = exp(-1.0 / tau_g * dt);
    for (int i = 0; i < 3; ++i) {
      gyroscope_bias_[i] = phi_g_d * gyroscope_bias_[i] +
                           sigma_b_g_d * standard_normal_distribution_(random_generator_);
      (*angular_velocity)[i] = (*angular_velocity)[i] + gyroscope_bias_[i] +
                               sigma_g_d * standard_normal_distribution_(random_generator_);
    }

    double tau_a = imu_parameters_.accelerometer_bias_correlation_time;
    double sigma_a_d = 1 / sqrt(dt) * imu_parameters_.accelerometer_noise_density;
    double sigma_b_a = imu_parameters_.accelerometer_random_walk;
    double sigma_b_a_d =
        sqrt(-sigma_b_a * sigma_b_a * tau_a / 2.0 * (exp(-2.0 * dt / tau_a) - 1.0));
    double phi_a_d = exp(-1.0 / tau_a * dt);
    for (int i = 0; i < 3; ++i) {
      accelerometer_bias_[i] = phi_a_d * accelerometer_bias_[i] +
                               sigma_b_a_d * standard_normal_distribution_(random_generator_);
      (*linear_acceleration)[i] = (*linear_acceleration)[i] + accelerometer_bias_[i] +
                                  sigma_a_d * standard_normal_distribution_(random_generator_);
    }
  }

  void OnUpdate(const common::UpdateInfo &_info)
  {
#if GAZEBO_MAJOR_VERSION >= 9
    common::Time current_time = world_->SimTime();
#else
    common::Time current_time = world_->GetSimTime();
#endif
    double dt = (current_time - last_time_).Double();
    last_time_ = current_time;

#if GAZEBO_MAJOR_VERSION >= 9
    ignition::math::Pose3d T_W_I = link_->WorldPose();
#else
    ignition::math::Pose3d T_W_I = ignitionFromGazeboMath(link_->GetWorldPose());
#endif
    ignition::math::Quaterniond C_W_I = T_W_I.Rot();

    gazebo::msgs::Quaternion *orientation = new gazebo::msgs::Quaternion();
    orientation->set_x(C_W_I.X());
    orientation->set_y(C_W_I.Y());
    orientation->set_z(C_W_I.Z());
    orientation->set_w(C_W_I.W());

#if GAZEBO_MAJOR_VERSION >= 9
    ignition::math::Vector3d acceleration_I =
        link_->RelativeLinearAccel() - C_W_I.RotateVectorReverse(gravity_W_);
    ignition::math::Vector3d angular_vel_I = link_->RelativeAngularVel();
#else
    ignition::math::Vector3d acceleration_I = ignitionFromGazeboMath(
        link_->GetRelativeLinearAccel() - C_W_I.RotateVectorReverse(gravity_W_));
    ignition::math::Vector3d angular_vel_I =
        ignitionFromGazeboMath(link_->GetRelativeAngularVel());
#endif

    Eigen::Vector3d linear_acceleration_I(acceleration_I.X(), acceleration_I.Y(),
                                          acceleration_I.Z());
    Eigen::Vector3d angular_velocity_I(angular_vel_I.X(), angular_vel_I.Y(),
                                       angular_vel_I.Z());

    addNoise(&linear_acceleration_I, &angular_velocity_I, dt);

    // ---- LAEA gyroscope-bias attack ----
    ignition::math::Vector3d gyro_bias = computeGyroBias(current_time.Double());
    angular_velocity_I[0] += gyro_bias.X();
    angular_velocity_I[1] += gyro_bias.Y();
    angular_velocity_I[2] += gyro_bias.Z();

    gazebo::msgs::Vector3d *linear_acceleration = new gazebo::msgs::Vector3d();
    linear_acceleration->set_x(linear_acceleration_I[0]);
    linear_acceleration->set_y(linear_acceleration_I[1]);
    linear_acceleration->set_z(linear_acceleration_I[2]);

    gazebo::msgs::Vector3d *angular_velocity = new gazebo::msgs::Vector3d();
    angular_velocity->set_x(angular_velocity_I[0]);
    angular_velocity->set_y(angular_velocity_I[1]);
    angular_velocity->set_z(angular_velocity_I[2]);

    imu_message_.set_time_usec(_info.simTime.sec * 1000000 + _info.simTime.nsec / 1000);
    imu_message_.set_seq(seq_++);
    imu_message_.set_allocated_orientation(orientation);
    imu_message_.set_allocated_linear_acceleration(linear_acceleration);
    imu_message_.set_allocated_angular_velocity(angular_velocity);

    imu_pub_->Publish(imu_message_);
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

  // Gyro bias [rad/s] for this step from the active command, or zero.
  ignition::math::Vector3d computeGyroBias(double sim_time_sec)
  {
    laea_attack::AttackCommand cmd;
    {
      std::lock_guard<std::mutex> lock(cmd_mutex_);
      if (!has_command_) {
        return ignition::math::Vector3d::Zero;
      }
      cmd = cmd_;
    }

    if (!cmd.enabled || cmd.source != "imu") {
      return ignition::math::Vector3d::Zero;
    }
    if (cmd.mode != "gyro_bias" && cmd.mode != "bias") {
      return ignition::math::Vector3d::Zero;
    }
    const double scale = laea_attack::attackScale(sim_time_sec, cmd);
    if (scale <= 0.0) {
      if (attack_active_logged_) {
        gzmsg << "[gazebo_imu_attack_plugin] IMU attack inactive sim_t=" << sim_time_sec << "\n";
        attack_active_logged_ = false;
      }
      return ignition::math::Vector3d::Zero;
    }
    if (!attack_active_logged_) {
      gzmsg << "[gazebo_imu_attack_plugin] IMU gyro attack active sim_t=" << sim_time_sec << "\n";
      attack_active_logged_ = true;
    }
    return ignition::math::Vector3d(cmd.vx * scale, cmd.vy * scale, cmd.vz * scale);
  }

  std::string namespace_;
  std::string imu_topic_;
  transport::NodePtr node_handle_;
  transport::PublisherPtr imu_pub_;
  transport::SubscriberPtr cmd_sub_;
  std::string frame_id_;
  std::string link_name_;

  std::mutex cmd_mutex_;
  laea_attack::AttackCommand cmd_;
  bool has_command_{false};
  bool attack_active_logged_{false};

  std::default_random_engine random_generator_;
  std::normal_distribution<double> standard_normal_distribution_;

  physics::WorldPtr world_;
  physics::ModelPtr model_;
  physics::LinkPtr link_;
  event::ConnectionPtr updateConnection_;

  common::Time last_time_;

  sensor_msgs::msgs::Imu imu_message_;

  ignition::math::Vector3d gravity_W_;
  ignition::math::Vector3d velocity_prev_W_;

  Eigen::Vector3d gyroscope_bias_;
  Eigen::Vector3d accelerometer_bias_;

  ImuParameters imu_parameters_;

  uint64_t seq_ = 0;
};

GZ_REGISTER_MODEL_PLUGIN(GazeboImuAttackPlugin);
}  // namespace gazebo
