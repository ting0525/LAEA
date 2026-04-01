cmake_minimum_required(VERSION 3.0.2)
project(laea_ditto_bridge)

find_package(catkin REQUIRED COMPONENTS
  gazebo_msgs
  geometry_msgs
  mavros_msgs
  rospy
  sensor_msgs
  std_msgs
)

catkin_package(
  CATKIN_DEPENDS gazebo_msgs geometry_msgs mavros_msgs rospy sensor_msgs std_msgs
)

include_directories(
  ${catkin_INCLUDE_DIRS}
)

catkin_install_python(
  PROGRAMS
    scripts/ditto_bridge.py
  DESTINATION ${CATKIN_PACKAGE_BIN_DESTINATION}
)
