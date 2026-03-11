#ifndef RTP_RECEIVER_H
#define RTP_RECEIVER_H

#include <iomanip>
#include <ros/ros.h>
#include <message_filters/subscriber.h>
#include <sensor_msgs/Image.h>
#include <sensor_msgs/CameraInfo.h>
#include <sensor_msgs/PointCloud2.h>
#include <std_msgs/String.h>
#include <visualization_msgs/Marker.h>
#include <quadrotor_msgs/PositionCommand.h>
#include <nav_msgs/Odometry.h>
#include <geometry_msgs/PoseStamped.h>
#include <message_filters/subscriber.h>
#include <message_filters/time_synchronizer.h>
#include <message_filters/sync_policies/approximate_time.h>
#include <cv_bridge/cv_bridge.h>
#include <opencv2/opencv.hpp>
#include <pcl/point_cloud.h>
#include <pcl/point_types.h>
#include <pcl_conversions/pcl_conversions.h>
#include <memory> // for std::shared_ptr
#include <pjsua2.hpp>
#include <string>
#include <iostream>
#include <vector>
#include <regex>
#include <StreamData.h>

class RTP_Receiver{
    public: 
        RTP_Receiver();
        ~RTP_Receiver();

        // Start RTP Receiver
        void start_rtp_receiver();

        void receive_rgb_stream(int stream_id);
        void receive_depth_stream(int stream_id);
        void receive_pcloud_stream(int stream_id);
        void receive_scan_stream(int stream_id);
        void receive_camera_info_stream(int stream_id);
        void receive_map_pcloud_stream(int stream_id);
        void receive_marker_stream(int stream_id);
        void receive_pos_cmd_stream(int stream_id);
        void receive_local_odom_stream(int stream_id);
        void receive_pose_stream(int stream_id);

        // Publisher
        ros::Publisher rgb_pub;
        ros::Publisher depth_pub;
        ros::Publisher pcloud_pub;
        ros::Publisher scan_pub;
        ros::Publisher camera_info_pub;
        ros::Publisher map_pcloud_pub;
        ros::Publisher marker_pub;
        ros::Publisher pos_cmd_pub;
        ros::Publisher local_odom_pub;
        ros::Publisher pose_pub;

        // Timer
        void depth_image_timer_cb();

        // Add StreamData
        void add_stream_data(StreamData stream_data);

    private:
        std::vector<cv::Mat *> restore_rgb_image; // received rgb data to be restored
        cv::Mat restore_depth_image; // received depth data to be restored
        // pcl::PointCloud<pcl::PointXYZ>::Ptr restore_pcloud; // received point cloud data to be restored
        // pcl::PointCloud<pcl::PointXYZ>::Ptr restore_scan; // received scan data to be restored
        sensor_msgs::CameraInfo restore_camera_info; // received camera info data to be restored
        int depth_image_count = 0;
        int pcloud_count = 0;
        int scan_count = 0;
        int camera_info_count = 0;
        int rgb_count = 0;
        int map_pcloud_count = 0;
        int marker_count = 0;
        int pos_cmd_count = 0;
        int local_odom_count = 0;
        int pose_count = 0;

        // Timer
        double depth_image_timer = 0; // Time between each received depth image

        // On/Off switch
        bool start_rtp_receiver_ = false;

        // Vector of StreamData
        std::vector<StreamData> stream_data;
};

class SIP_Receiver;

class receiver_pj_account : public pj::Account {
public:
    receiver_pj_account(SIP_Receiver *sip_receiver = nullptr) : sip_receiver_(sip_receiver) {}
    // My onIncomingCall() callback
    void onIncomingCall(pj::OnIncomingCallParam &iprm) override;
private:
    SIP_Receiver *sip_receiver_;
};

class SIP_Receiver{
public:
    SIP_Receiver(RTP_Receiver *rtp_receiver);
    ~SIP_Receiver();

    // SIP
    pj::AccountConfig SIP_account_config();
    receiver_pj_account SIP_account_init();
    void accept_call(pj::Call &call);   // 接听呼叫
    void reject_call(pj::Call &call);   // 拒绝呼叫
    void SIP_receiver_main();
    void Process_Stream(std::string whole_msg);
    void Process_Stream2(std_msgs::String::ConstPtr sdp_msg);
    void Start_Stream();

    std::vector<StreamData> stream_info;
private:
    pj::Endpoint ep;
    bool first_OK = false;
    // Depth-only SDP starts from stream id=1 (12000/13000), not id=0.
    // Keep receiver local port aligned with current sip.py payload.
    int started_port = 13000;
    RTP_Receiver *rtp_receiver_; // When the call is confirmed, start the stream

    // Subscribers
    std::shared_ptr<message_filters::Subscriber<std_msgs::String>> sdp_sub_;
};

class receiver_pj_call : public pj::Call {
public:
    receiver_pj_call(receiver_pj_account &acc, int call_id = PJSUA_INVALID_ID, SIP_Receiver *sip_receiver = nullptr) : pj::Call(acc, call_id), sip_receiver_(sip_receiver) {}
    
    // My onCallState() callback
    void onCallState(pj::OnCallStateParam &prm) override{
        pj::CallInfo ci = getInfo();
        // std::cout << "Call " << ci.id << " state=" << ci.stateText << " (" << ci.state << ")" << std::endl;
        
        // Print the source of call
        std::cout << "Call source: " << ci.remoteUri << std::endl;

        // Process Incoming Call
        if(ci.state == PJSIP_INV_STATE_INCOMING) {
            std::cout << "Incoming call: "<< ci.remoteUri << " is calling" << std::endl;
            // sip_receiver_->accept_call(*this);
            // sip_receiver_->Start_Stream();
        }

        // Process 200 OK
        if(ci.state == PJSIP_INV_STATE_CONFIRMED) {
            std::cout << "Call is confirmed" << std::endl;
            sip_receiver_->Start_Stream();
        }

        // Process 180 Ringing
        if(ci.state == PJSIP_INV_STATE_EARLY) {
            std::cout << "Call is ringing" << std::endl;
        }
    }

    // My onCallSdpCreated() callback
    void onCallSdpCreated(pj::OnCallSdpCreatedParam &prm) override{
        
        std::cout << "Create custom SDP: " << std::endl;

        // Additonal SDP
        std::string custom_sdp = create_custom_sdp();

        // Add additional SDP to the original SDP
        prm.sdp.wholeSdp += custom_sdp;

        // std::cout << "Custom SDP: " << prm.sdp.wholeSdp << std::endl;
    }

    // Create custom SDP
    std::string create_custom_sdp();


private:
    SIP_Receiver *sip_receiver_;
};

#endif // RTP_RECEIVER_H
