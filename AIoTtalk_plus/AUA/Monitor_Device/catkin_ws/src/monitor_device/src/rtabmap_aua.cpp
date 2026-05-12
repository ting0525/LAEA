#include "RTPSession.h"

#include <pcl_conversions/pcl_conversions.h>
#include "ros/ros.h"
#include "std_msgs/String.h"
#include <sensor_msgs/PointCloud2.h>

ros::Publisher lidar_publisher;

void publish_lidar_msg(ros::Publisher &lidar_publisher, pcl::PointCloud<pcl::PointXYZ>::Ptr &pcloud_data){
    sensor_msgs::PointCloud2 lidar_msg;
    pcl::toROSMsg(*pcloud_data, lidar_msg);

    lidar_msg.header.stamp = ros::Time::now();
    lidar_msg.header.frame_id = "camera_init";

    lidar_publisher.publish(lidar_msg);
}


void map_session_thread(RTPSession *session, int stream_id){
    while(true){
        std::vector<Datatype> data;
        data = session->get_data(stream_id, true);
        
        for(auto &_data: data){
            if(std::holds_alternative<pcl::PointCloud<pcl::PointXYZ>::Ptr>(_data)){
                auto point_cloud = std::get<pcl::PointCloud<pcl::PointXYZ>::Ptr>(_data);
                publish_lidar_msg(lidar_publisher, point_cloud);
            }
        }
        std::cout << "---- Got map data ----" << std::endl;
    }
}

void odometry_session_thread(RTPSession *session, int stream_id){
    while(true){
        std::vector<Datatype> data;
        data = session->get_data(stream_id, false);
        
        for(auto &_data: data){
            if(std::holds_alternative<Binary_Data *>(_data)){
                auto odometry = std::get<Binary_Data *>(_data);
            }
        }
        std::cout << "---- Got odometry data ----" << std::endl;
    }
}

int main(int argc, char **argv){
    ros::init(argc, argv, "AUA_Device");
    ros::NodeHandle node_handle;
    lidar_publisher = node_handle.advertise<sensor_msgs::PointCloud2>("/map_points", 10);

    int ret;
    std::string local_ip = "127.0.0.1";
    std::string remote_ip = "127.0.0.1";

    RTPSession *session = new RTPSession();
    ret = session->create_session(local_ip, remote_ip);
    
    // map stream
    std::map<std::string, int> map_pointcloud_codec_format = {
        {"PCL", 98}
    };
    std::map<std::string, std::string> map_pointcloud_codec_params = {
        {"fields", "xyzrgb"}
    };

    ret = session->create_stream(
        0, 10100, 10500,
        "RGBD map stream",
        "recvonly",
        "pointcloud",
        map_pointcloud_codec_format,
        map_pointcloud_codec_params
    );
    if(ret != 0) {exit(0);}
    
    // odometry stream
    std::map<std::string, int> odometry_codec_format = {
        {"raw_bytes", 99}
    };
    std::map<std::string, std::string> odometry_codec_params;

    ret = session->create_stream(
        1, 10200, 10500,
        "RGBD odometry stream",
        "recvonly",
        "raw_bytes",
        odometry_codec_format,
        odometry_codec_params
    );
    if(ret != 0) {exit(0);}

    std::thread map_thread (map_session_thread, session, 0);
    std::thread odometry_thread(odometry_session_thread, session, 1);

    map_thread.join();
    odometry_thread.join();
    

    return 0;
}