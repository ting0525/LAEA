/*
 * GPS source-attack plugin for PX4 SITL Gazebo.
 *
 * This is intentionally separate from PX4's stock gazebo_gps_plugin.cpp.
 * It publishes the same SITLGps message on the same Gazebo transport topic,
 * then applies controlled runtime attacks before PX4 EKF2 receives GPS data.
 */

#include <algorithm>
#include <cctype>
#include <cmath>
#include <cstdlib>
#include <mutex>
#include <queue>
#include <random>
#include <string>
#include <vector>

#include <boost/algorithm/string.hpp>

#include <SITLGps.pb.h>
#include <common.h>

#include <gazebo/common/Plugin.hh>
#include <gazebo/gazebo.hh>
#include <gazebo/msgs/msgs.hh>
#include <gazebo/physics/physics.hh>
#include <gazebo/sensors/GpsSensor.hh>
#include <gazebo/sensors/SensorTypes.hh>
#include <gazebo/transport/transport.hh>
#include <gazebo/util/system.hh>
#include <ignition/math.hh>
#include <sdf/sdf.hh>

namespace gazebo {
namespace {
static constexpr double kDefaultUpdateRate = 5.0;
static constexpr double kDefaultGpsXYRandomWalk = 2.0;
static constexpr double kDefaultGpsZRandomWalk = 4.0;
static constexpr double kDefaultGpsXYNoiseDensity = 2.0e-4;
static constexpr double kDefaultGpsZNoiseDensity = 4.0e-4;
static constexpr double kDefaultGpsVXYNoiseDensity = 0.2;
static constexpr double kDefaultGpsVZNoiseDensity = 0.4;
static constexpr double kGpsDelay = 0.12;
static constexpr int kGpsBufferSizeMax = 1000;
static constexpr double kGpsCorrelationTime = 60.0;

std::string lower_copy(std::string value)
{
  std::transform(value.begin(), value.end(), value.begin(),
                 [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
  return value;
}

double env_double(const char *name, double fallback)
{
  const char *value = std::getenv(name);
  if (!value || !*value) {
    return fallback;
  }

  try {
    return std::stod(value);
  } catch (...) {
    gzerr << "[gazebo_gps_attack_plugin] Ignoring invalid " << name << "=" << value << "\n";
    return fallback;
  }
}

std::string env_string(const char *name, const std::string &fallback)
{
  const char *value = std::getenv(name);
  return (value && *value) ? std::string(value) : fallback;
}

double clamp01(double value)
{
  if (value < 0.0) {
    return 0.0;
  }
  if (value > 1.0) {
    return 1.0;
  }
  return value;
}
}  // namespace

class GAZEBO_VISIBLE GpsAttackPlugin : public SensorPlugin {
 public:
  GpsAttackPlugin() = default;
  ~GpsAttackPlugin() override
  {
    if (updateSensorConnection_) {
      updateSensorConnection_->~Connection();
    }
    parentSensor_.reset();
    if (world_) {
      world_->Reset();
    }
  }

 protected:
  void Load(sensors::SensorPtr parent, sdf::ElementPtr sdf) override
  {
    parentSensor_ = std::dynamic_pointer_cast<sensors::GpsSensor>(parent);
    if (!parentSensor_) {
      gzthrow("GpsAttackPlugin requires a GPS Sensor as its parent");
    }

    const std::string scoped_name = parent->ParentName();
    std::vector<std::string> names;
    boost::split(names, scoped_name, boost::is_any_of("::"));
    names.erase(std::remove_if(names.begin(), names.end(),
                               [](const std::string &name) { return name.empty(); }),
                names.end());

    const std::string root_model_name = names.front();
    model_name_ = names.front();
    const std::string parent_sensor_model_name = names.rbegin()[1];

    if (sdf->HasElement("topic")) {
      gps_topic_ = sdf->GetElement("topic")->Get<std::string>();
    } else {
      gps_topic_ = parent_sensor_model_name;
      gzwarn << "[gazebo_gps_attack_plugin] " << root_model_name << "::"
             << parent_sensor_model_name << " using gps topic \"" << gps_topic_ << "\"\n";
    }

    world_ = physics::get_world(parentSensor_->WorldName());

#if GAZEBO_MAJOR_VERSION >= 9
    last_time_ = world_->SimTime();
    last_gps_time_ = world_->SimTime();
    start_time_ = world_->StartTime();
#else
    last_time_ = world_->GetSimTime();
    last_gps_time_ = world_->GetSimTime();
    start_time_ = world_->GetStartTime();
#endif

    if (sdf->HasElement("gpsNoise")) {
      getSdfParam<bool>(sdf, "gpsNoise", gps_noise_, gps_noise_);
    } else {
      gps_noise_ = false;
    }

    const bool world_has_origin =
        checkWorldHomePosition(world_, world_latitude_, world_longitude_, world_altitude_);

    const char *env_lat = std::getenv("PX4_HOME_LAT");
    const char *env_lon = std::getenv("PX4_HOME_LON");
    const char *env_alt = std::getenv("PX4_HOME_ALT");

    if (env_lat) {
      lat_home_ = std::stod(env_lat) * M_PI / 180.0;
    } else if (world_has_origin) {
      lat_home_ = world_latitude_;
    } else if (sdf->HasElement("homeLatitude")) {
      double latitude = 0.0;
      getSdfParam<double>(sdf, "homeLatitude", latitude, lat_home_);
      lat_home_ = latitude * M_PI / 180.0;
    }

    if (env_lon) {
      lon_home_ = std::stod(env_lon) * M_PI / 180.0;
    } else if (world_has_origin) {
      lon_home_ = world_longitude_;
    } else if (sdf->HasElement("homeLongitude")) {
      double longitude = 0.0;
      getSdfParam<double>(sdf, "homeLongitude", longitude, lon_home_);
      lon_home_ = longitude * M_PI / 180.0;
    }

    if (env_alt) {
      alt_home_ = std::stod(env_alt);
    } else if (world_has_origin) {
      alt_home_ = world_altitude_;
    } else if (sdf->HasElement("homeAltitude")) {
      getSdfParam<double>(sdf, "homeAltitude", alt_home_, alt_home_);
    }

    getSdfParam<double>(sdf, "gpsXYRandomWalk", gps_xy_random_walk_, kDefaultGpsXYRandomWalk);
    getSdfParam<double>(sdf, "gpsZRandomWalk", gps_z_random_walk_, kDefaultGpsZRandomWalk);
    getSdfParam<double>(sdf, "gpsXYNoiseDensity", gps_xy_noise_density_, kDefaultGpsXYNoiseDensity);
    getSdfParam<double>(sdf, "gpsZNoiseDensity", gps_z_noise_density_, kDefaultGpsZNoiseDensity);
    getSdfParam<double>(sdf, "gpsVXYNoiseDensity", gps_vxy_noise_density_, kDefaultGpsVXYNoiseDensity);
    getSdfParam<double>(sdf, "gpsVZNoiseDensity", gps_vz_noise_density_, kDefaultGpsVZNoiseDensity);

    namespace_.clear();
    if (sdf->HasElement("robotNamespace")) {
      namespace_ = sdf->GetElement("robotNamespace")->Get<std::string>();
    }

    if (sdf->HasElement("update_rate")) {
      getSdfParam<double>(sdf, "update_rate", update_rate_, kDefaultUpdateRate);
    } else {
      update_rate_ = kDefaultUpdateRate;
    }
    parentSensor_->SetUpdateRate(update_rate_);

    load_attack_params(sdf);

    node_handle_ = transport::NodePtr(new transport::Node());
    node_handle_->Init(namespace_);

    parentSensor_->SetActive(false);
    updateSensorConnection_ =
        parentSensor_->ConnectUpdated(boost::bind(&GpsAttackPlugin::OnSensorUpdate, this));
    parentSensor_->SetActive(true);

    updateWorldConnection_ = event::Events::ConnectWorldUpdateBegin(
        boost::bind(&GpsAttackPlugin::OnWorldUpdate, this, _1));

    gps_pub_ =
        node_handle_->Advertise<sensor_msgs::msgs::SITLGps>("~/" + root_model_name + "/link/" + gps_topic_, 10);

    gzmsg << "[gazebo_gps_attack_plugin] loaded topic=~/" << root_model_name << "/link/"
          << gps_topic_ << " mode=" << attack_mode_ << " start=" << attack_start_sec_
          << " end=" << attack_end_sec_ << "\n";
  }

  void OnWorldUpdate(const common::UpdateInfo &)
  {
    if (model_ == nullptr) {
#if GAZEBO_MAJOR_VERSION >= 9
      model_ = world_->ModelByName(model_name_);
#else
      model_ = world_->GetModel(model_name_);
#endif
    }

#if GAZEBO_MAJOR_VERSION >= 9
    common::Time current_time = world_->SimTime();
    ignition::math::Pose3d pose_w_i = model_->WorldPose();
    ignition::math::Vector3d velocity_current_w = model_->WorldLinearVel();
#else
    common::Time current_time = world_->GetSimTime();
    ignition::math::Pose3d pose_w_i = ignitionFromGazeboMath(model_->GetWorldPose());
    ignition::math::Vector3d velocity_current_w = ignitionFromGazeboMath(model_->GetWorldLinearVel());
#endif

    const double sim_time_sec = current_time.Double();
    const double dt = (current_time - last_time_).Double();

    ignition::math::Vector3d pos_w_i = pose_w_i.Pos();
    ignition::math::Vector3d velocity_current_w_xy = velocity_current_w;
    velocity_current_w_xy.Z() = 0.0;

    if (gps_noise_) {
      noise_gps_pos_.X() = gps_xy_noise_density_ * std::sqrt(dt) * randn_(rand_);
      noise_gps_pos_.Y() = gps_xy_noise_density_ * std::sqrt(dt) * randn_(rand_);
      noise_gps_pos_.Z() = gps_z_noise_density_ * std::sqrt(dt) * randn_(rand_);
      noise_gps_vel_.X() = gps_vxy_noise_density_ * std::sqrt(dt) * randn_(rand_);
      noise_gps_vel_.Y() = gps_vxy_noise_density_ * std::sqrt(dt) * randn_(rand_);
      noise_gps_vel_.Z() = gps_vz_noise_density_ * std::sqrt(dt) * randn_(rand_);
      random_walk_gps_.X() = gps_xy_random_walk_ * std::sqrt(dt) * randn_(rand_);
      random_walk_gps_.Y() = gps_xy_random_walk_ * std::sqrt(dt) * randn_(rand_);
      random_walk_gps_.Z() = gps_z_random_walk_ * std::sqrt(dt) * randn_(rand_);
    } else {
      noise_gps_pos_.Set(0.0, 0.0, 0.0);
      noise_gps_vel_.Set(0.0, 0.0, 0.0);
      random_walk_gps_.Set(0.0, 0.0, 0.0);
    }

    gps_bias_.X() += random_walk_gps_.X() * dt - gps_bias_.X() / kGpsCorrelationTime;
    gps_bias_.Y() += random_walk_gps_.Y() * dt - gps_bias_.Y() / kGpsCorrelationTime;
    gps_bias_.Z() += random_walk_gps_.Z() * dt - gps_bias_.Z() / kGpsCorrelationTime;

    ignition::math::Vector3d attack_pos_offset(0.0, 0.0, 0.0);
    ignition::math::Vector3d attack_vel_offset(0.0, 0.0, 0.0);
    const bool active = attack_active(sim_time_sec);

    if (active) {
      if (!attack_active_logged_) {
        gzmsg << "[gazebo_gps_attack_plugin] GPS attack active mode=" << attack_mode_
              << " t=" << sim_time_sec << "\n";
        attack_active_logged_ = true;
      }
      apply_attack(sim_time_sec, attack_pos_offset, attack_vel_offset);
    } else if (attack_active_logged_ && !attack_end_logged_) {
      gzmsg << "[gazebo_gps_attack_plugin] GPS attack inactive t=" << sim_time_sec << "\n";
      attack_end_logged_ = true;
    }

    ignition::math::Vector3d pos_with_noise = pos_w_i + noise_gps_pos_ + gps_bias_ + attack_pos_offset;
    auto latlon = reproject(pos_with_noise, lat_home_, lon_home_, alt_home_);

    sensor_msgs::msgs::SITLGps gps_msg;
    gps_msg.set_time_usec(sim_time_sec * 1e6);
    gps_msg.set_time_utc_usec((sim_time_sec + start_time_.Double()) * 1e6);
    gps_msg.set_latitude_deg(latlon.first * 180.0 / M_PI);
    gps_msg.set_longitude_deg(latlon.second * 180.0 / M_PI);
    gps_msg.set_altitude(pos_w_i.Z() + alt_home_ - noise_gps_pos_.Z() + gps_bias_.Z() + attack_pos_offset.Z());
    gps_msg.set_eph(1.0);
    gps_msg.set_epv(1.0);
    gps_msg.set_velocity_east(velocity_current_w.X() + noise_gps_vel_.Y() + attack_vel_offset.X());
    gps_msg.set_velocity(velocity_current_w_xy.Length());
    gps_msg.set_velocity_north(velocity_current_w.Y() + noise_gps_vel_.X() + attack_vel_offset.Y());
    gps_msg.set_velocity_up(velocity_current_w.Z() - noise_gps_vel_.Z() + attack_vel_offset.Z());

    if (active && attack_mode_ == "freeze") {
      if (!freeze_valid_) {
        freeze_msg_ = gps_msg;
        freeze_valid_ = true;
      }
      gps_msg = freeze_msg_;
      gps_msg.set_time_usec(sim_time_sec * 1e6);
      gps_msg.set_time_utc_usec((sim_time_sec + start_time_.Double()) * 1e6);
    } else if (!active) {
      freeze_valid_ = false;
    }

    {
      std::lock_guard<std::mutex> lock(data_mutex_);
      gps_delay_buffer_.push(gps_msg);
      current_time_ = current_time;
    }

    last_time_ = current_time;
  }

  void OnSensorUpdate()
  {
    std::lock_guard<std::mutex> lock(data_mutex_);

    if ((current_time_ - last_gps_time_).Double() <= 1 / parentSensor_->UpdateRate()) {
      return;
    }
    last_gps_time_ = current_time_;

    if (gps_delay_buffer_.empty()) {
      return;
    }

    sensor_msgs::msgs::SITLGps gps_msg;
    while (true) {
      if (gps_delay_buffer_.empty()) {
        break;
      }

      gps_msg = gps_delay_buffer_.front();
      double gps_current_delay = current_time_.Double() - gps_delay_buffer_.front().time_usec() / 1e6f;

      if (gps_current_delay >= kGpsDelay) {
        gps_delay_buffer_.pop();
      } else if (gps_delay_buffer_.size() > kGpsBufferSizeMax) {
        gps_delay_buffer_.pop();
      } else {
        break;
      }
    }

    gps_pub_->Publish(gps_msg);
  }

 private:
  void load_attack_params(sdf::ElementPtr sdf)
  {
    if (sdf->HasElement("attackMode")) {
      attack_mode_ = sdf->GetElement("attackMode")->Get<std::string>();
    }
    getSdfParam<double>(sdf, "attackStartSec", attack_start_sec_, attack_start_sec_);
    getSdfParam<double>(sdf, "attackEndSec", attack_end_sec_, attack_end_sec_);
    getSdfParam<double>(sdf, "attackRampSec", attack_ramp_sec_, attack_ramp_sec_);
    getSdfParam<double>(sdf, "eastBiasM", east_bias_m_, east_bias_m_);
    getSdfParam<double>(sdf, "northBiasM", north_bias_m_, north_bias_m_);
    getSdfParam<double>(sdf, "upBiasM", up_bias_m_, up_bias_m_);
    getSdfParam<double>(sdf, "jumpEastM", jump_east_m_, jump_east_m_);
    getSdfParam<double>(sdf, "jumpNorthM", jump_north_m_, jump_north_m_);
    getSdfParam<double>(sdf, "jumpUpM", jump_up_m_, jump_up_m_);
    getSdfParam<double>(sdf, "noisePositionStdM", noise_position_std_m_, noise_position_std_m_);
    getSdfParam<double>(sdf, "noiseVelocityStdMps", noise_velocity_std_mps_, noise_velocity_std_mps_);
    getSdfParam<double>(sdf, "velocityEastBiasMps", velocity_east_bias_mps_, velocity_east_bias_mps_);
    getSdfParam<double>(sdf, "velocityNorthBiasMps", velocity_north_bias_mps_, velocity_north_bias_mps_);
    getSdfParam<double>(sdf, "velocityUpBiasMps", velocity_up_bias_mps_, velocity_up_bias_mps_);

    attack_mode_ = lower_copy(env_string("GPS_ATTACK_MODE", attack_mode_));
    attack_start_sec_ = env_double("GPS_ATTACK_START_SEC", attack_start_sec_);
    attack_end_sec_ = env_double("GPS_ATTACK_END_SEC", attack_end_sec_);
    attack_ramp_sec_ = env_double("GPS_ATTACK_RAMP_SEC", attack_ramp_sec_);
    east_bias_m_ = env_double("GPS_ATTACK_EAST_BIAS_M", east_bias_m_);
    north_bias_m_ = env_double("GPS_ATTACK_NORTH_BIAS_M", north_bias_m_);
    up_bias_m_ = env_double("GPS_ATTACK_UP_BIAS_M", up_bias_m_);
    jump_east_m_ = env_double("GPS_ATTACK_JUMP_EAST_M", jump_east_m_);
    jump_north_m_ = env_double("GPS_ATTACK_JUMP_NORTH_M", jump_north_m_);
    jump_up_m_ = env_double("GPS_ATTACK_JUMP_UP_M", jump_up_m_);
    noise_position_std_m_ = env_double("GPS_ATTACK_NOISE_POSITION_STD_M", noise_position_std_m_);
    noise_velocity_std_mps_ = env_double("GPS_ATTACK_NOISE_VELOCITY_STD_MPS", noise_velocity_std_mps_);
    velocity_east_bias_mps_ = env_double("GPS_ATTACK_VELOCITY_EAST_BIAS_MPS", velocity_east_bias_mps_);
    velocity_north_bias_mps_ = env_double("GPS_ATTACK_VELOCITY_NORTH_BIAS_MPS", velocity_north_bias_mps_);
    velocity_up_bias_mps_ = env_double("GPS_ATTACK_VELOCITY_UP_BIAS_MPS", velocity_up_bias_mps_);
  }

  bool attack_active(double sim_time_sec) const
  {
    if (attack_mode_ == "none" || attack_mode_.empty()) {
      return false;
    }
    if (sim_time_sec < attack_start_sec_) {
      return false;
    }
    return attack_end_sec_ <= 0.0 || sim_time_sec <= attack_end_sec_;
  }

  void apply_attack(double sim_time_sec, ignition::math::Vector3d &pos_offset,
                    ignition::math::Vector3d &vel_offset)
  {
    if (attack_mode_ == "bias") {
      double scale = 1.0;
      if (attack_ramp_sec_ > 0.0) {
        scale = clamp01((sim_time_sec - attack_start_sec_) / attack_ramp_sec_);
      }
      pos_offset.Set(east_bias_m_ * scale, north_bias_m_ * scale, up_bias_m_ * scale);
      return;
    }

    if (attack_mode_ == "jump") {
      pos_offset.Set(jump_east_m_, jump_north_m_, jump_up_m_);
      return;
    }

    if (attack_mode_ == "noise") {
      pos_offset.Set(noise_position_std_m_ * randn_(rand_),
                     noise_position_std_m_ * randn_(rand_),
                     noise_position_std_m_ * randn_(rand_));
      vel_offset.Set(noise_velocity_std_mps_ * randn_(rand_),
                     noise_velocity_std_mps_ * randn_(rand_),
                     noise_velocity_std_mps_ * randn_(rand_));
      return;
    }

    if (attack_mode_ == "velocity_bias") {
      vel_offset.Set(velocity_east_bias_mps_, velocity_north_bias_mps_, velocity_up_bias_mps_);
      return;
    }

    if (attack_mode_ != "freeze") {
      gzerr << "[gazebo_gps_attack_plugin] Unknown GPS_ATTACK_MODE=" << attack_mode_
            << "; publishing unmodified GPS\n";
      attack_mode_ = "none";
    }
  }

  std::string namespace_;
  std::string model_name_;
  std::string gps_topic_;

  bool gps_noise_{false};
  sensors::GpsSensorPtr parentSensor_;
  physics::ModelPtr model_;
  physics::WorldPtr world_;
  event::ConnectionPtr updateWorldConnection_;
  event::ConnectionPtr updateSensorConnection_;
  transport::NodePtr node_handle_;
  transport::PublisherPtr gps_pub_;

  double update_rate_{kDefaultUpdateRate};
  common::Time last_gps_time_;
  common::Time last_time_;
  common::Time current_time_;
  common::Time start_time_;
  std::mutex data_mutex_;
  std::queue<sensor_msgs::msgs::SITLGps> gps_delay_buffer_;

  double lat_home_{kDefaultHomeLatitude};
  double lon_home_{kDefaultHomeLongitude};
  double alt_home_{kDefaultHomeAltitude};
  double world_latitude_{0.0};
  double world_longitude_{0.0};
  double world_altitude_{0.0};

  ignition::math::Vector3d gps_bias_;
  ignition::math::Vector3d noise_gps_pos_;
  ignition::math::Vector3d noise_gps_vel_;
  ignition::math::Vector3d random_walk_gps_;
  std::default_random_engine rand_;
  std::normal_distribution<float> randn_;
  double gps_xy_random_walk_{kDefaultGpsXYRandomWalk};
  double gps_z_random_walk_{kDefaultGpsZRandomWalk};
  double gps_xy_noise_density_{kDefaultGpsXYNoiseDensity};
  double gps_z_noise_density_{kDefaultGpsZNoiseDensity};
  double gps_vxy_noise_density_{kDefaultGpsVXYNoiseDensity};
  double gps_vz_noise_density_{kDefaultGpsVZNoiseDensity};

  std::string attack_mode_{"none"};
  double attack_start_sec_{0.0};
  double attack_end_sec_{-1.0};
  double attack_ramp_sec_{10.0};
  double east_bias_m_{0.0};
  double north_bias_m_{0.0};
  double up_bias_m_{0.0};
  double jump_east_m_{0.0};
  double jump_north_m_{0.0};
  double jump_up_m_{0.0};
  double noise_position_std_m_{0.0};
  double noise_velocity_std_mps_{0.0};
  double velocity_east_bias_mps_{0.0};
  double velocity_north_bias_mps_{0.0};
  double velocity_up_bias_mps_{0.0};
  bool attack_active_logged_{false};
  bool attack_end_logged_{false};
  bool freeze_valid_{false};
  sensor_msgs::msgs::SITLGps freeze_msg_;
};

GZ_REGISTER_SENSOR_PLUGIN(GpsAttackPlugin)
}  // namespace gazebo
