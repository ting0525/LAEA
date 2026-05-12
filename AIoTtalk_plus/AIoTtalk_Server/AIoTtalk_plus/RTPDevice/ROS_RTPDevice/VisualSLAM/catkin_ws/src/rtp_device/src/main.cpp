#include "RTPSession.h"
#include "KinectPublisher.h"
#include "AirsimClient.h"
#include "DepthImageCodec.h"

#include "ros/ros.h"
#include "std_msgs/String.h"

#include <pcl_conversions/pcl_conversions.h>
#include <tf2_ros/static_transform_broadcaster.h>
#include <sensor_msgs/Image.h>
#include <sensor_msgs/CameraInfo.h>
#include "nav_msgs/Odometry.h"

RTPSession *sua_session, *aua_session;
KinectPublisher kinect_publihser;

ros::Publisher rgb_image_publisher, depth_image_publisher;
ros::Publisher rgb_camera_info_publisher, depth_camera_info_publisher;
ros::Subscriber map_subscriber, odometry_subscriber;

std::queue<cv::Mat> rgb_images_queue, depth_images_queue;
std::mutex rgb_images_queue_lock, depth_images_queue_lock;

void depth_image_sua_session_thread(RTPSession *session, int stream_id){
    std::cout << "depth_image session thread start" << std::endl;
    
    while(true){
        std::vector<Datatype> data;
        data = session->get_data(stream_id, true);

        for(auto &_data: data){
            if(std::holds_alternative<cv::Mat>(_data)){
                auto depth_image = std::get<cv::Mat>(_data);
                std::lock_guard<std::mutex> _lock_guard(depth_images_queue_lock);
                {
                    depth_images_queue.push(depth_image);
                    std::cout << "Got depth image" << std::endl;
                }
            }
        }
    }
}

void rgb_image_sua_session_thread(RTPSession *session, int stream_id){
    std::cout << "rgb_image session thread start" << std::endl;

    while(true){
        std::vector<Datatype> data;
        data = session->get_data(stream_id, true);
        for(auto &_data:data){
            if(std::holds_alternative<cv::Mat>(_data)){
                auto rgb_image = std::get<cv::Mat>(_data);
                std::lock_guard<std::mutex> _lock_guard(rgb_images_queue_lock);
                {
                    rgb_images_queue.push(rgb_image);
                    std::cout << "Got rgb image" << std::endl;
                }
            }
        }
    }
}

void rgbd_map_data_callback(const sensor_msgs::PointCloud2ConstPtr &pcloud_msg){
    pcl::PCLPointCloud2 temp_pcloud;
    pcl_conversions::toPCL(*pcloud_msg, temp_pcloud);
    pcl::PointCloud<pcl::PointXYZRGB>::Ptr pcloud(new pcl::PointCloud<pcl::PointXYZRGB>);
    pcl::fromPCLPointCloud2(temp_pcloud, *pcloud);
    //std::cout << "hi" << std::endl;
    Datatype data = pcloud;
    if(aua_session->send_data(0, data, true) != 0){
        //std::cout << "lol" << std::endl;
    }

    std::cout << "send map data" << std::endl;
}

void rgbd_odometry_data_callback(const nav_msgs::Odometry::ConstPtr &msg){
    std::stringstream odometry_str;
    odometry_str << *msg;
    //std::cout << odometry_str.str() << std::endl;
    //std::cout << "hi" << std::endl;
    std::string data_str = odometry_str.str();

    Binary_Data *binary_data;
    binary_data = new Binary_Data(data_str);

    Datatype data = binary_data;

    if(aua_session->send_data(1, data, false) != 0){
        exit(0);
    }
    //std::cout << "send odometry data" << std::endl;
}

void publish_rgbd_image(){
    std::cout << "publish_rgbd_image start" << std::endl;
    tf2_ros::TransformBroadcaster tf_broadcaster;
    while(true){
        //tf2_ros::TransformBroadcaster tf_broadcaster;
        if(rgb_images_queue.size() > 0 && depth_images_queue.size() > 0){
            cv::Mat rgb_image, depth_image;
            std::lock_guard<std::mutex> _lock_guard(rgb_images_queue_lock);
            {
                std::lock_guard<std::mutex> _lock_guard(depth_images_queue_lock);
                {
                    rgb_image = rgb_images_queue.front();
                    depth_image = depth_images_queue.front();
                    kinect_publihser.get_current_time();
            kinect_publihser.publish_rgb_message(rgb_image_publisher, rgb_image);
            kinect_publihser.publish_depth_message(depth_image_publisher, depth_image);
            kinect_publihser.publish_tf_message(tf_broadcaster);
            kinect_publihser.publish_camera_info(rgb_camera_info_publisher);
            kinect_publihser.publish_camera_info(depth_camera_info_publisher);
                    rgb_images_queue.pop();
                    depth_images_queue.pop();
                }
            }
            
        }
    }
}

int main(int argc, char **argv){
    int ret;

    ros::init(argc, argv, "VisualSLAM_Device");
    ros::NodeHandle node_handle;
    rgb_image_publisher = node_handle.advertise<sensor_msgs::Image>("/camera/rgb/image_rect_color", 100);
    depth_image_publisher = node_handle.advertise<sensor_msgs::Image>("/camera/depth_registered/image_raw", 100);

    rgb_camera_info_publisher = node_handle.advertise<sensor_msgs::CameraInfo>("/camera/rgb/camera_info", 100);
    depth_camera_info_publisher = node_handle.advertise<sensor_msgs::CameraInfo>("/camera/depth/camera_info", 100);

    map_subscriber = node_handle.subscribe("/rtabmap/cloud_map", 0, rgbd_map_data_callback);
    odometry_subscriber = node_handle.subscribe("/rtabmap/odom", 0, rgbd_odometry_data_callback);

    sua_session = new RTPSession();
    aua_session = new RTPSession();

    ret = sua_session->create_session("127.0.0.1", "127.0.0.1");
    ret = aua_session->create_session("127.0.0.1", "127.0.0.1");
    
    //rgb image stream
    std::map<std::string, int> rgb_image_codec_format = {
        {"H264", 96}
    };
    std::map<std::string, std::string> rgb_image_codec_params = {
        {"resolution", "640*480"}  
    }; 
    ret = sua_session->create_stream(
        0, 14000, 13000,
        "RGB image stream",
        "recvonly",
        "video",
        rgb_image_codec_format,
        rgb_image_codec_params
    );
    if(ret != 0){ exit(0); }
    
    // depth image stream
    std::map<std::string, int> depth_image_codec_format = {
        {"Zdepth", 97}
    };
    std::map<std::string, std::string> depth_image_codec_params = {
        {"resolution", "640*480"}  
    };
    ret = sua_session->create_stream(
        1, 16000, 15000,
        "Depth image stream",
        "recvonly",
        "depth_image",
        depth_image_codec_format,
        depth_image_codec_params
    );
    if(ret != 0){ exit(0); }
    
    // map stream
    std::map<std::string, int> map_pointcloud_codec_format = {
        {"PCL", 98}
    };
    std::map<std::string, std::string> map_pointcloud_codec_params = {
        {"fields", "xyzrgb"}
    };
    ret = aua_session->create_stream(
        0, 10500, 10100,
        "RGBD map stream",
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
        "RGBD odometry stream",
        "sendonly",
        "raw_bytes",
        odometry_codec_format,
        odometry_codec_params
    );
    if(ret != 0) {exit(0);}
    

    


    std::thread rgb_image_thread = std::thread(rgb_image_sua_session_thread, sua_session, 0);
    std::thread depth_image_thread = std::thread(depth_image_sua_session_thread, sua_session, 1);
    std::thread publish_rgbd_image_thread = std::thread(publish_rgbd_image);
    
    // AirsimClient airsim_client;
    // airsim_client.start();
    // std::vector<ImageResponse> image_response;
    
    // //DepthImageCodec depth_codec(640, 480);

    // for(int i = 0; i < 1200; i++){
    //     airsim_client.get_image_data(image_response);
    //     cv::Mat *rgb_image = new cv::Mat(
    //         image_response.at(0).height, image_response.at(0).width, CV_8UC3,
    //         (void*) image_response.at(0).image_data_uint8.data()
    //     );

    //     cv::Mat *depth_image = new cv::Mat(
    //         image_response.at(1).height, image_response.at(1).width, CV_32FC1,
    //         (void*) image_response.at(1).image_data_float.data()
    //     );

    //     // Datatype d_data = *depth_image;
    //     // depth_codec 
    //     rgb_images_queue.push(*rgb_image);
    //     depth_images_queue.push(*depth_image);
    //     std::cout << "frame: " << i << std::endl;
    // }
    
    ros::spin();
    return 0;
}