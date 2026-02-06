#!/usr/bin/env bash

gnome-terminal -- bash -c "
                            roslaunch px4_gazebo laea_gazebo_lidar.launch;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch px4_gazebo controller.launch;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch rtp_gazebo rtp_receiver.launch use_iottalk:=true use_sip:=false;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch rtp_gazebo rtp_sender.launch use_iottalk:=true use_sip:=false;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            python3 /home/tim/laea/src/LAEA/iottalk/sip.py;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch octomap_server scan_mapping.launch;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch exploration_manager explore_test.launch;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch exploration_manager rviz_alg.launch;
                            exec bash
                        "

sleep 5

gnome-terminal -- bash -c "
                            rosrun mavros mavsys mode -c OFFBOARD;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            rosrun mavros mavsafety arm;
                            exec bash
                          "

sleep 5

gnome-terminal -- bash -c "
                            roslaunch laea_twin_tools slam_kpi_logger.launch
                            exec bash
                          "
