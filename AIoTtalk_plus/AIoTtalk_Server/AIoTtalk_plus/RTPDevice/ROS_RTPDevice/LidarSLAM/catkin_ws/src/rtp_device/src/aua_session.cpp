#include "RTPSession.h"
#include "PointCloudCodec.h"

#include <pcl_conversions/pcl_conversions.h>
#include <pcl/filters/extract_indices.h>
#include <pcl_ros/transforms.h>

#include "ros/ros.h"
#include "std_msgs/String.h"
#include <sensor_msgs/PointCloud2.h>
#include "nav_msgs/Odometry.h"

RTPSession *aua_session;
ros::Subscriber map_subscriber, odometry_subscriber;

int main(int argc, char **argv){
    return 0;
}