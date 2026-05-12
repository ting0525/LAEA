#include "RTPSession.h"
#include "PointCloudCodec.h"

#include <pcl_conversions/pcl_conversions.h>
#include <pcl/filters/extract_indices.h>
#include <pcl_ros/transforms.h>

#include "ros/ros.h"
#include "std_msgs/String.h"
#include <sensor_msgs/PointCloud2.h>
#include "nav_msgs/Odometry.h"

RTPSession *sua_session;
ros::Publisher lidar_publisher;

void publish_lidar_msg(ros::Publisher &lidar_publisher, pcl::PointCloud<pcl::PointXYZ>::Ptr &pcloud_data){
    sensor_msgs::PointCloud2 lidar_msg;
    pcl::toROSMsg(*pcloud_data, lidar_msg);

    lidar_msg.header.stamp = ros::Time::now();
    lidar_msg.header.frame_id = "world";

    lidar_publisher.publish(lidar_msg);
}

void lidar_sua_session_thread(RTPSession *session, int stream_id){
    while(true){
        std::vector<Datatype> data;
        data = session->get_data(stream_id, true);
        std::cout << "got data " << std::endl;
        for(auto &_data: data){
            if(std::holds_alternative<pcl::PointCloud<pcl::PointXYZ>::Ptr>(_data)){
                auto point_cloud = std::get<pcl::PointCloud<pcl::PointXYZ>::Ptr>(_data);
                publish_lidar_msg(lidar_publisher, point_cloud);
            }
        }
    }
}

int main(int argc, char **argv){

    ros::init(argc, argv, "LidarSLAM_Device_SUA");
    ros::NodeHandle node_handle;
    lidar_publisher = node_handle.advertise<sensor_msgs::PointCloud2>("velodyne_points", 10);

    int ret;
    sua_session = new RTPSession();
    ret = sua_session->read_json_input_and_init();

    if(ret != 0){
        exit(-1);
    }
    
    std::thread lidar_thread = std::thread(lidar_sua_session_thread, sua_session, 0);
    std::cout << "Start lidar session thread" << std::endl;
    ros::spin();
    return 0;
}