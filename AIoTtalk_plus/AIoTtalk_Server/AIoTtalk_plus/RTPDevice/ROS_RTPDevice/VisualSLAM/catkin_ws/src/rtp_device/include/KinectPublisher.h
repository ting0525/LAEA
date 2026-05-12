#ifndef _KinectPublisher_H_
#define _KinectPublisher_H_

#include "ros/ros.h"
#include "std_msgs/String.h"
#include <sensor_msgs/PointCloud2.h>
#include <sensor_msgs/Image.h>
#include <sensor_msgs/CameraInfo.h>
#include <sensor_msgs/distortion_models.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.h>
#include <tf2_ros/static_transform_broadcaster.h>
#include <tf2_ros/transform_broadcaster.h>
#include <tf2_ros/transform_listener.h>
#include <geometry_msgs/PoseStamped.h>
#include <geometry_msgs/TransformStamped.h>
#include "std_msgs/Header.h"

#include <opencv2/opencv.hpp>
#include <cv_bridge/cv_bridge.h>

#define CAMERA_FX 320
#define CAMERA_FY 320
#define CAMERA_CX 320
#define CAMERA_CY 240

#define CAMERA_K1 -0.000591
#define CAMERA_K2 0.000519
#define CAMERA_P1 0.000001
#define CAMERA_P2 -0.000030
#define CAMERA_P3 0.0

#define IMAGE_WIDTH 640 
#define IMAGE_HEIGHT 480

class KinectPublisher{
    public:
        KinectPublisher();
        ~KinectPublisher();

    public:
        ros::Time ros_time;
    
    public:
        void publish_tf_message(tf2_ros::TransformBroadcaster tf_broadcaster);
        void publish_rgb_message(ros::Publisher &publisher, cv::Mat &rgb_image);
        void publish_depth_message(ros::Publisher &publisher, cv::Mat &depth_image);
        void publish_camera_info(ros::Publisher &publisher);
        void get_current_time();
};

#endif