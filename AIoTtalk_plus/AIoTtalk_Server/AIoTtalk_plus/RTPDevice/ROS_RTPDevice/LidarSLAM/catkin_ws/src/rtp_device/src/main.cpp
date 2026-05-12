#include "RTPSession.h"
#include "PointCloudCodec.h"

#include <pcl_conversions/pcl_conversions.h>
#include <pcl/filters/extract_indices.h>
#include <pcl_ros/transforms.h>

#include "ros/ros.h"
#include "std_msgs/String.h"
#include <sensor_msgs/PointCloud2.h>
#include "nav_msgs/Odometry.h"

RTPSession *sua_session, *aua_session;
ros::Publisher lidar_publisher;
ros::Subscriber map_subscriber, odometry_subscriber;

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

// ROS callbacks
// havent found way to pass other arguments as ros callbacks arguments
// the rtpsession and stream id are hard-coding in the callbacks
void lidar_map_data_callback(const sensor_msgs::PointCloud2ConstPtr &pcloud_msg){
    
    pcl::PCLPointCloud2 temp_pcloud;
    pcl_conversions::toPCL(*pcloud_msg, temp_pcloud);
    pcl::PointCloud<pcl::PointXYZ>::Ptr pcloud(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::fromPCLPointCloud2(temp_pcloud, *pcloud);
    
    Datatype data = pcloud;
    if(aua_session->send_data(0, data, true) != 0){
        exit(0);
    }

    std::cout << "send map data" << std::endl;

}

void lidar_odometry_data_callback(const nav_msgs::Odometry::ConstPtr &msg){
    
    std::stringstream odometry_str;
    odometry_str << *msg;
    std::string data_str = odometry_str.str();
    
    Binary_Data *binary_data;
    binary_data = new Binary_Data(data_str);

    Datatype data = binary_data;

    if (aua_session->send_data(1, data, false) != 0){
        exit(0);
    }
}

int main(int argc, char **argv){
    
    ros::init(argc, argv, "LidarSLAM_Device");
    ros::NodeHandle node_handle;
    lidar_publisher = node_handle.advertise<sensor_msgs::PointCloud2>("velodyne_points", 10);
    map_subscriber = node_handle.subscribe("laser_cloud_surround", 0, lidar_map_data_callback);
    odometry_subscriber = node_handle.subscribe("integrated_to_init", 200, lidar_odometry_data_callback);

    int ret;
    std::string local_ip = "127.0.0.1";
    std::string remote_ip = "127.0.0.1";

    uint16_t local_port = 12000;
    uint16_t remote_port = 10000;
    
    sua_session = new RTPSession();
    aua_session = new RTPSession();

    ret = sua_session->create_session("127.0.0.1", "127.0.0.1");
    ret = aua_session->create_session("127.0.0.1", "127.0.0.1");
    
    // lidar stream 
    std::map<std::string, int> lidar_pointcloud_codec_format = {
        {"PCL", 98}
    };
    std::map<std::string, std::string> lidar_pointcloud_codec_params = {
        {"fields", "xyz"}
    };
    
    ret = sua_session->create_stream(
        0, local_port, remote_port,
        "Lidar point cloud stream",
        "recvonly",
        "pointcloud",
        lidar_pointcloud_codec_format,
        lidar_pointcloud_codec_params
    );
    if(ret != 0) {exit(0);}
    
    // map stream
    std::map<std::string, int> map_pointcloud_codec_format = {
        {"PCL", 98}
    };
    std::map<std::string, std::string> map_pointcloud_codec_params = {
        {"fields", "xyz"}
    };
    ret = aua_session->create_stream(
        0, 10500, 10100,
        "Lidar map stream",
        "sendonly",
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

    ret = aua_session->create_stream(
        1, 10500, 10200,
        "Lidar odometry stream",
        "sendonly",
        "raw_bytes",
        odometry_codec_format,
        odometry_codec_params
    );
    if(ret != 0) {exit(0);}

    std::thread lidar_thread = std::thread(lidar_sua_session_thread, sua_session, 0);
    ros::spin();

    return 0;
}