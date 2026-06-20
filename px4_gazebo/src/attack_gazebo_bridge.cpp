// attack_gazebo_bridge: relays the attack command from ROS to Gazebo transport.
//
// The source-layer attack plugins live in the PX4 sitl_gazebo build tree where
// roscpp is not available, so they cannot subscribe to ROS directly. This node
// (built in the catkin workspace, where both roscpp and gazebo transport exist)
// forwards the scheduler's /laea/attack/command_json (std_msgs/String) verbatim
// inside a gazebo::msgs::GzString on attackGzTopic(); the plugins parse it.
//
// Serialization stays single-sourced in attack_scheduler.py; this node adds no
// schema. The latest command is re-published at a low rate so a plugin that
// connects (or restarts) after an edge still converges to the current command.

#include <string>

#include <ros/ros.h>
#include <std_msgs/String.h>

#include <gazebo/gazebo_client.hh>
#include <gazebo/msgs/msgs.hh>
#include <gazebo/transport/transport.hh>

#include "attack_window.h"

namespace {
gazebo::transport::PublisherPtr g_gz_pub;
std::string g_last_json;
bool g_have_last = false;

void publishToGz(const std::string& json) {
  if (!g_gz_pub) return;
  gazebo::msgs::GzString gz;
  gz.set_data(json);
  g_gz_pub->Publish(gz);
}

void onCommandJson(const std_msgs::String::ConstPtr& msg) {
  g_last_json = msg->data;
  g_have_last = true;
  publishToGz(g_last_json);
}

void onRepublishTimer(const ros::TimerEvent&) {
  if (g_have_last) publishToGz(g_last_json);
}
}  // namespace

int main(int argc, char** argv) {
  ros::init(argc, argv, "attack_gazebo_bridge");
  ros::NodeHandle nh("~");

  const std::string ros_topic =
      nh.param<std::string>("command_json_topic", "/laea/attack/command_json");
  const double republish_hz = nh.param<double>("republish_hz", 1.0);

  // Connect to the gazebo master as a transport client.
  gazebo::client::setup(argc, argv);
  gazebo::transport::NodePtr gz_node(new gazebo::transport::Node());
  gz_node->Init();
  g_gz_pub = gz_node->Advertise<gazebo::msgs::GzString>(laea_attack::attackGzTopic());

  ROS_INFO("[attack_gazebo_bridge] relaying %s (ROS) -> %s (gz)",
           ros_topic.c_str(), laea_attack::attackGzTopic());

  ros::Subscriber sub = nh.subscribe(ros_topic, 10, onCommandJson);
  ros::Timer timer;
  if (republish_hz > 0.0) {
    timer = nh.createTimer(ros::Duration(1.0 / republish_hz), onRepublishTimer);
  }

  ros::spin();

  g_gz_pub.reset();
  gazebo::client::shutdown();
  return 0;
}
