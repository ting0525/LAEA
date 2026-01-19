#ifndef Synchronizer_H
#define Synchronizer_H

#include <iomanip>
#include <ros/ros.h>
#include <message_filters/subscriber.h>
#include <sensor_msgs/Image.h>
#include <sensor_msgs/CameraInfo.h>
#include <sensor_msgs/PointCloud2.h>
#include <geometry_msgs/PoseStamped.h>
#include <nav_msgs/Odometry.h>
#include <message_filters/subscriber.h>
#include <message_filters/time_synchronizer.h>
#include <message_filters/sync_policies/approximate_time.h>
#include <memory>

class Synchronizer{
    public:
        Synchronizer();
        ~Synchronizer();

        void depth_callback(const sensor_msgs::ImageConstPtr& depth_msg);
        void depth_info_callback(const sensor_msgs::CameraInfoConstPtr& camera_info_msg);
        void depthAndInfoCallback(const sensor_msgs::ImageConstPtr& depth_msg, const sensor_msgs::CameraInfoConstPtr& camera_info_msg);
        void depthPoseCallback(
            const sensor_msgs::ImageConstPtr& depth_msg,
            const geometry_msgs::PoseStampedConstPtr& pose_msg);
        void odomCallback(const nav_msgs::OdometryConstPtr& odom_msg);

        ros::Publisher sync_depth_raw_pub;
        ros::Publisher sync_depth_pub;
        ros::Publisher sync_camera_info_pub;
        ros::Publisher sync_pose_pub;
        ros::Publisher sync_odom_pub;

        // Subscriber for sync raw_depth and camera_info
        std::shared_ptr<message_filters::Subscriber<sensor_msgs::Image>> depth_sub_;
        std::shared_ptr<message_filters::Subscriber<sensor_msgs::CameraInfo>> depth_info_sub_;
        std::shared_ptr<message_filters::Subscriber<geometry_msgs::PoseStamped>> pose_sub_;
        std::shared_ptr<message_filters::Subscriber<nav_msgs::Odometry>> odom_sub_;

    private:
        int depth_info_count = 0;

        typedef message_filters::sync_policies::ApproximateTime<sensor_msgs::Image, sensor_msgs::CameraInfo> Image_Info_Sync_Policy;
        typedef std::shared_ptr<message_filters::Synchronizer<Image_Info_Sync_Policy>> Image_Info_Synchronizer;
        Image_Info_Synchronizer sync_;

        typedef message_filters::sync_policies::ApproximateTime<
            sensor_msgs::Image, geometry_msgs::PoseStamped> Depth_Pose_Sync_Policy;
        typedef std::shared_ptr<message_filters::Synchronizer<Depth_Pose_Sync_Policy>> Depth_Pose_Synchronizer;
        Depth_Pose_Synchronizer sync_depth_pose_;
};

#endif // Synchronizer_H
