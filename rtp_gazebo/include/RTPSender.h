#ifndef RTP_SENDER_H
#define RTP_SENDER_H

#include <iomanip>
#include <ros/ros.h>
#include <message_filters/subscriber.h>
#include <sensor_msgs/Image.h>
#include <sensor_msgs/CameraInfo.h>
#include <sensor_msgs/PointCloud2.h>
#include <std_msgs/String.h>
#include "visualization_msgs/Marker.h"
#include "quadrotor_msgs/PositionCommand.h"
#include <nav_msgs/Odometry.h>
#include <geometry_msgs/PoseStamped.h>
#include <cv_bridge/cv_bridge.h>
#include <opencv2/opencv.hpp>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <pcl_conversions/pcl_conversions.h>
#include <memory> // for std::shared_ptr
#include <iostream>
#include <string>
#include <pjsua2.hpp>
#include <vector>
#include <regex>
#include <StreamData.h>

// 點雲 structure
struct point_cloud {
    float x, y, z, r;
    point_cloud(float x0, float y0, float z0, float r0) {
        x = float(x0);
        y = float(y0);
        z = float(z0);
        r = float(r0);
    }
};

class RTP_Sender {
public:
    RTP_Sender();
    ~RTP_Sender();

    // On/Off switch
    bool start_rtp_sender_ = false;

    // Init subscriber function
    void init_subscriber(ros::NodeHandle &nh);
    
    // Start RTP Sender
    void start_rtp_sender();

    // Callback function
    void depth_callback(const sensor_msgs::ImageConstPtr& depth_msg);
    void rgb_callback(const sensor_msgs::ImageConstPtr& rgb_msg);
    void depth_info_callback(const sensor_msgs::CameraInfoConstPtr& depth_info_msg);
    void depth_point_cloud_callback(const sensor_msgs::PointCloud2ConstPtr& pcloud_msg);
    void scan_point_cloud_callback(const sensor_msgs::PointCloud2ConstPtr& pcloud_msg);
    void map_point_cloud_callback(const sensor_msgs::PointCloud2ConstPtr& pcloud_msg);
    void position_vis_callback(const visualization_msgs::Marker::ConstPtr& position_vis_msg);
    void position_command_callback(const quadrotor_msgs::PositionCommand::ConstPtr& position_command_msg);
    void local_odom_callback(const nav_msgs::Odometry::ConstPtr& local_odom_msg);
    void pose_callback(const geometry_msgs::PoseStamped::ConstPtr& pose_msg);

    // RTP Packet Packetization
    void send_rgb_stream(int stream_id, cv::Mat rgb_image);
    void send_depth_stream(int stream_id, cv::Mat depth_image);
    void send_pcloud_stream(int stream_id, pcl::PointCloud<pcl::PointXYZ>::Ptr pcloud);
    void send_camera_info_stream(int stream_id, sensor_msgs::CameraInfo camera_info);
    void send_position_vis_stream(int stream_id, visualization_msgs::Marker position_vis);
    void send_position_command_stream(int stream_id, quadrotor_msgs::PositionCommand position_command);
    void send_local_odom_stream(int stream_id, nav_msgs::Odometry local_odom);
    void send_pose_stream(int stream_id, geometry_msgs::PoseStamped pose);

    // Process depth image by making it 16-bit unsigned integer
    void process_depth_data(cv::Mat &depth_image, cv::Mat &depth_image_uint16);

    // Add StreamData
    void add_stream_data(StreamData stream_data);

private:
    std::shared_ptr<message_filters::Subscriber<sensor_msgs::Image>> depth_sub_; // depth image
    std::shared_ptr<message_filters::Subscriber<sensor_msgs::Image>> rgb_sub_; // rgb image

    // camera_info
    std::shared_ptr<message_filters::Subscriber<sensor_msgs::CameraInfo>> depth_info_sub_;

    // point cloud
    std::shared_ptr<message_filters::Subscriber<sensor_msgs::PointCloud2>> pcloud_sub_;
    std::shared_ptr<message_filters::Subscriber<sensor_msgs::PointCloud2>> scan_sub_;
    std::shared_ptr<message_filters::Subscriber<sensor_msgs::PointCloud2>> map_pcloud_sub_;

    // position visualization
    std::shared_ptr<message_filters::Subscriber<visualization_msgs::Marker>> position_vis_sub_;

    // position command
    std::shared_ptr<message_filters::Subscriber<quadrotor_msgs::PositionCommand>> position_command_sub_;

    // local odometry
    std::shared_ptr<message_filters::Subscriber<nav_msgs::Odometry>> local_odom_sub_;

    // pose
    std::shared_ptr<message_filters::Subscriber<geometry_msgs::PoseStamped>> pose_sub_;

    // RTP Packet Packetization
    double last_depth_time;

    // Stream Data vector
    std::vector<StreamData> stream_data;
};

class SIP_Sender{
public:
    SIP_Sender(RTP_Sender *rtp_sender);
    ~SIP_Sender();

    // SIP
    pj::AccountConfig SIP_account_config();
    pj::Account SIP_account_init();
    void SIP_call(pj::Account &acc, const std::string remote_uri);
    void SIP_sender_main();
    void Start_Stream();
    void Process_Stream(std::string whole_msg);
    void Process_Stream2(std_msgs::String::ConstPtr sdp_msg);
    void send_ack(pj::Call &call);
private:
    pj::Endpoint ep;
    bool first_OK = false;
    int started_port = 10000;
    std::vector<StreamData> stream_info;
    RTP_Sender *rtp_sender_; // When the call is confirmed, start the stream

    // Subscribers
    std::shared_ptr<message_filters::Subscriber<std_msgs::String>> sdp_sub_;
};


class my_pj_call : public pj::Call {
public:
    my_pj_call(pj::Account &acc, int call_id = PJSUA_INVALID_ID, SIP_Sender *sip_sender = nullptr) : pj::Call(acc, call_id), sip_sender_(sip_sender) {}

    // My onCallState() callback
    void onCallState(pj::OnCallStateParam &prm) override{
        pj::CallInfo ci = getInfo();
        std::cout << "Call State: " << ci.stateText << std::endl;
        
        // Print the source of call
        std::cout << "Call source: " << ci.remoteUri << std::endl;

        // Invitation is sent
        if(ci.state == PJSIP_INV_STATE_CALLING) {
            std::cout << "Call is calling" << std::endl;
        }

        // ACK is sent
        if(ci.state == PJSIP_INV_STATE_CONFIRMED) {
            std::cout << "Call is confirmed" << std::endl;

            // Start the stream
            sip_sender_->Start_Stream();            
        }

        // 2xx response is received
        if(ci.state == PJSIP_INV_STATE_CONNECTING) {
            std::cout << "Connecting" << std::endl;
        }

        if(ci.state == PJSIP_INV_STATE_INCOMING) {
            std::cout << "Incoming Shit" << std::endl;
        }

        // Some response from the receiver
        if(ci.state == PJSIP_INV_STATE_EARLY) {
            std::cout << "Call is ringing" << std::endl;
        }
    }

    // My onCallSdpCreated() callback
    void onCallSdpCreated(pj::OnCallSdpCreatedParam &prm) override{
        pj::CallInfo ci = getInfo();
        
        // std::cout << "Call " << ci.id << " sdp created" << std::endl;

        // Add some additional information of our own RTP stream
        prm.sdp.wholeSdp += create_custom_sdp();
    }
    // tim
    // void onCallAck(pj::OnCallAckParam &prm) override{
    //     std::cout << "ACK is Created" << std::endl;

    //     // Last SDP we received
    //     // std::cout << "Last SDP: " << prm.rdata.wholeMsg << std::endl;
    //     sip_sender_->Process_Stream(prm.rdata.wholeMsg);
    // }

    std::string create_custom_sdp();
private:
    SIP_Sender *sip_sender_;
};

#endif // RTP_SENDER_H
