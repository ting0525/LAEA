#include "RTPReceiver.h"
#include "RTPSession.h"
#include "Codec.h"

// #include <iostream>

std::string local_ip = "127.0.0.1";
std::string remote_ip = "127.0.0.1";

RTPSession *session = new RTPSession();
VideoCodec *rgb_codec = new VideoCodec();
DepthImageCodec *depth_codec = new DepthImageCodec();
PointCloudCodec *pcloud_codec = new PointCloudCodec();
CameraInfoCodec *camera_info_codec = new CameraInfoCodec();
MarkerCodec *position_vis_codec = new MarkerCodec();
CommandCodec *position_command_codec = new CommandCodec();
OdomCodec *local_odom_codec = new OdomCodec();
PoseCodec *pose_codec = new PoseCodec();

RTP_Receiver::RTP_Receiver(){
    ros::NodeHandle nh;
    // rgb_pub = nh.advertise<sensor_msgs::Image>("/rtp/depth/rgb_image_raw", 1);
    depth_pub = nh.advertise<sensor_msgs::Image>("/rtp/depth/image_raw", 1);
    // pcloud_pub = nh.advertise<sensor_msgs::PointCloud2>("/rtp/pointcloud/depth", 1);
    // scan_pub = nh.advertise<sensor_msgs::PointCloud2>("/rtp/pointcloud/scan", 1);
    // camera_info_pub = nh.advertise<sensor_msgs::CameraInfo>("/rtp/depth/camera_info", 1);
    // map_pcloud_pub = nh.advertise<sensor_msgs::PointCloud2>("/rtp/pointcloud/map", 1);
    // marker_pub = nh.advertise<visualization_msgs::Marker>("/rtp/position_vis", 1);
    // pos_cmd_pub = nh.advertise<quadrotor_msgs::PositionCommand>("/rtp/position_cmd", 1);
    // local_odom_pub = nh.advertise<nav_msgs::Odometry>("/rtp/local_odom", 1);
    // pose_pub = nh.advertise<geometry_msgs::PoseStamped>("/rtp/pose", 1);
}

RTP_Receiver::~RTP_Receiver(){}

void RTP_Receiver::depth_image_timer_cb(){
    // Current time
    double current_time = ros::Time::now().toSec();
    std::cout<<"Time duration between each received depth image: "<<current_time-depth_image_timer<<std::endl;
    depth_image_timer = current_time;
}

void RTP_Receiver::receive_rgb_stream(int stream_id){
    
    int ret = 1;

    while(true && start_rtp_receiver_){
        struct Data *data;
        data = session->get_data(stream_id);
        if(data){
            ret = rgb_codec->decode(data, restore_rgb_image);
            if (ret == 0){

                // std::cout << "Got rgb image frame!" << std::endl;

                // Convert cv::Mat to sensor_msgs::Image
                for(int i = 0; i < restore_rgb_image.size(); i++){
                    cv::Mat rgb_image = *restore_rgb_image[i];
                    sensor_msgs::ImagePtr msg = cv_bridge::CvImage(std_msgs::Header(), "bgr8", rgb_image).toImageMsg();

                    msg->header.stamp = ros::Time::now();  // 使用当前的 ROS 时间戳
                    msg->header.frame_id = "depth_camera_link";  // 使用相机的坐标系
                    msg->header.seq = rgb_count++;
                    rgb_pub.publish(msg);
                }

                restore_rgb_image.clear();
            }
            destroy_data(data);
        }
    }
}

void RTP_Receiver::receive_depth_stream(int stream_id){
    
    int ret = 1;

    while(true && start_rtp_receiver_){
        struct Data *data;
        data = session->get_data(stream_id);
        if(data){
            // Timer Callback
            // depth_image_timer_cb();
            // 解出 payload（忽略包頭 stamp，統一用當前時間）
            struct Data payload;
            if (data->size > sizeof(uint32_t) * 2) {
                payload.buffer = data->buffer + sizeof(uint32_t) * 2;
                payload.size = data->size - sizeof(uint32_t) * 2;
            } else {
                payload = *data;
            }

            ret = depth_codec->decode(&payload, restore_depth_image);
            if(ret == 0){
                // std::cout << "Got depth image frame!" << std::endl;
                
                // Convert cv::Mat to sensor_msgs::Image and publish it
                sensor_msgs::Image depth_msg;

                std_msgs::Header header;
                header.stamp = ros::Time::now();  // 用當前 /clock，與 pose/odom 對齊
                header.frame_id = "depth_camera_link";  // 使用相机的坐标系
                header.seq = depth_image_count++;
                cv_bridge::CvImage(header, "32FC1", restore_depth_image).toImageMsg(depth_msg);

                depth_pub.publish(depth_msg);

                // std::cout << "Published depth image!" << std::endl;

            }
            destroy_data(data);
        }
    }
}


void RTP_Receiver::receive_pcloud_stream(int stream_id){
    int ret = 1;
    
    while(true && start_rtp_receiver_){
        pcl::PointCloud<pcl::PointXYZ>::Ptr restore_pcloud(new pcl::PointCloud<pcl::PointXYZ>());
        struct Data *data;
        data = session->get_data(stream_id);
        if(data){
            ret = pcloud_codec->decode(data, restore_pcloud);
            if(ret == 0){
                // std::cout << "Got point cloud frame!" << std::endl;

                // Convert PCL point cloud to sensor_msgs::PointCloud2
                sensor_msgs::PointCloud2 pcloud_msg;
                pcl::toROSMsg(*restore_pcloud, pcloud_msg);
                pcloud_msg.header.stamp = ros::Time::now();
                pcloud_msg.header.frame_id = "map";
                pcloud_msg.header.seq = pcloud_count++;

                pcloud_pub.publish(pcloud_msg);

                // Destroy msg after publish
                pcloud_msg.data.clear();
            }
            restore_pcloud.reset();
            destroy_data(data);
        }
    }
}

void RTP_Receiver::receive_scan_stream(int stream_id){
    int ret = 1;
    
    while(true && start_rtp_receiver_){
        pcl::PointCloud<pcl::PointXYZ>::Ptr restore_scan(new pcl::PointCloud<pcl::PointXYZ>());
        struct Data *data;
        data = session->get_data(stream_id);
        if(data){
            ret = pcloud_codec->decode(data, restore_scan);
            if(ret == 0){
                // std::cout << "Got scan point cloud frame!" << std::endl;

                // Convert PCL point cloud to sensor_msgs::PointCloud2
                sensor_msgs::PointCloud2 pcloud_msg;
                pcl::toROSMsg(*restore_scan, pcloud_msg);

                pcloud_msg.header.stamp = ros::Time::now();
                pcloud_msg.header.frame_id = "map";
                pcloud_msg.header.seq = scan_count++;
                scan_pub.publish(pcloud_msg);

                // Destroy msg after publish
                pcloud_msg.data.clear();
            }
            restore_scan.reset();
            destroy_data(data);
        }

    }
}

void RTP_Receiver::receive_camera_info_stream(int stream_id){
    int ret = 1;
    
    while(true && start_rtp_receiver_){
        struct Data *data;
        data = session->get_data(stream_id);
        if(data){
            ret = camera_info_codec->decode(data, restore_camera_info);
            if(ret == 0){
                // std::cout << "Got camera info frame!" << std::endl;

                // Setup message header
                restore_camera_info.header.stamp = ros::Time::now();
                restore_camera_info.header.frame_id = "depth_camera_link";
                restore_camera_info.header.seq = camera_info_count++;
                
                camera_info_pub.publish(restore_camera_info);
                
            }
            destroy_data(data);
        }
    }
}

void RTP_Receiver::receive_map_pcloud_stream(int stream_id){
    int ret = 1;
    
    while(true && start_rtp_receiver_){
        pcl::PointCloud<pcl::PointXYZ>::Ptr restore_map_pcloud(new pcl::PointCloud<pcl::PointXYZ>());
        struct Data *data;
        data = session->get_data(stream_id);
        if(data){
            ret = pcloud_codec->decode(data, restore_map_pcloud);
            if(ret == 0){
                // std::cout << "Got map point cloud frame!" << std::endl;

                // Convert PCL point cloud to sensor_msgs::PointCloud2
                sensor_msgs::PointCloud2 pcloud_msg;
                pcl::toROSMsg(*restore_map_pcloud, pcloud_msg);
                pcloud_msg.header.stamp = ros::Time::now();
                pcloud_msg.header.frame_id = "world";
                pcloud_msg.header.seq = map_pcloud_count++;

                map_pcloud_pub.publish(pcloud_msg);

                // Destroy msg after publish
                pcloud_msg.data.clear();
            }
            restore_map_pcloud.reset();
            destroy_data(data);
        }
    }
}

void RTP_Receiver::receive_marker_stream(int stream_id){
    int ret = 1;
    
    while(true && start_rtp_receiver_){
        visualization_msgs::Marker restore_marker;
        struct Data *data;
        data = session->get_data(stream_id);
        if(data){
            ret = position_vis_codec->decode(data, restore_marker);
            if(ret == 0){
                // std::cout << "Got marker frame!" << std::endl;

                // Setup message header
                restore_marker.header.stamp = ros::Time::now();
                restore_marker.header.frame_id = "world";
                restore_marker.header.seq = marker_count++;
                
                marker_pub.publish(restore_marker);
                
            }
            destroy_data(data);
        }
    }
}

void RTP_Receiver::receive_pos_cmd_stream(int stream_id){
    int ret = 1;
    
    while(true && start_rtp_receiver_){
        quadrotor_msgs::PositionCommand restore_pos_cmd;
        struct Data *data;
        data = session->get_data(stream_id);
        if(data){
            ret = position_command_codec->decode(restore_pos_cmd, data);
            if(ret == 0){
                // std::cout << "Got position command frame!" << std::endl;

                // Setup message header
                restore_pos_cmd.header.stamp = ros::Time::now();
                restore_pos_cmd.header.frame_id = "world";
                restore_pos_cmd.header.seq = pos_cmd_count++;
                
                pos_cmd_pub.publish(restore_pos_cmd);
                
            }
            destroy_data(data);
        }
    }
}

void RTP_Receiver::receive_local_odom_stream(int stream_id){
    int ret = 1;
    
    while(true && start_rtp_receiver_){
        nav_msgs::Odometry restore_local_odom;
        struct Data *data;
        data = session->get_data(stream_id);
        if(data){
            ret = local_odom_codec->decode(data, restore_local_odom);
            if(ret == 0){
                // std::cout << "Got local odom frame!" << std::endl;

                // Setup message header
                restore_local_odom.header.stamp = ros::Time::now();
                restore_local_odom.header.frame_id = "map"; // Remember to change this 
                restore_local_odom.header.seq = local_odom_count++;
                
                local_odom_pub.publish(restore_local_odom);
                
            }
            destroy_data(data);
        }
    }
}

void RTP_Receiver::receive_pose_stream(int stream_id){
    int ret = 1;
    
    while(true && start_rtp_receiver_){
        geometry_msgs::PoseStamped restore_pose;
        struct Data *data;
        data = session->get_data(stream_id);
        if(data){
            ret = pose_codec->decode(data, restore_pose);
            if(ret == 0){
                // std::cout << "Got pose frame!" << std::endl;

                // Setup message header
                restore_pose.header.stamp = ros::Time::now();
                restore_pose.header.frame_id = "camera_link"; // Remember to change this 
                restore_pose.header.seq = pose_count++;
                
                pose_pub.publish(restore_pose);
                
            }
            destroy_data(data);
        }
    }
}

// Add StreamData
void RTP_Receiver::add_stream_data(StreamData stream_data){
    this->stream_data.push_back(stream_data);
}

// Start RTP Receiver
void RTP_Receiver::start_rtp_receiver(){
    rgb_codec->init(
        640, 480, AV_CODEC_ID_H264, AVMEDIA_TYPE_VIDEO, AV_PIX_FMT_YUV420P, AV_PIX_FMT_BGR24
    );

    int ret;
    
    if ((ret = session->create_session(local_ip, remote_ip)) != 0){
        exit(0);
    }

    // Create Stream by StreamData
    for (int i = 0; i < stream_data.size(); i++){
        if((ret = session->create_stream(
            stream_data[i].stream_id, stream_data[i].local_port, stream_data[i].remote_port, stream_data[i].stream_name, stream_data[i].media_type, stream_data[i].payload_id, stream_data[i].direction)) != 0){
            exit(0);
        }
        std::cout << "Stream ID: " << stream_data[i].stream_id << " ," << "Local Port: " << stream_data[i].local_port << " ," << "Remote Port: " << stream_data[i].remote_port << " ," << "Stream Name: " << stream_data[i].stream_name << " ," << "Media Type: " << stream_data[i].media_type << " ," << "Payload ID: " << stream_data[i].payload_id << " ," << "Direction: " << stream_data[i].direction << std::endl;
    }


    start_rtp_receiver_ = true;
    std::thread recv_depth_thread = std::thread(&RTP_Receiver::receive_depth_stream, this, 1);

    recv_depth_thread.join();
}

// SIP Receiver
SIP_Receiver::SIP_Receiver(RTP_Receiver *rtp_receiver){
    // PJSIP
    rtp_receiver_ = rtp_receiver;
    // Create SIP endpoint
    ep.libCreate();

    // Init endpoint with media config to set RTP port range
    pj::EpConfig ep_cfg;
    
    // 設置RTP端口範圍，例如從6000到6002
    // ep_cfg.medConfig.recvRtpPortMin = 6000;
    // ep_cfg.medConfig.recvRtpPortMax = 6002;

    // Initialize the library with the configured port range
    ep.libInit(ep_cfg);

    // Create UDP transport for SIP signaling
    pj::TransportConfig tcfg;
    tcfg.port = 5000;  // 指定5000作為SIP信令的端口
    ep.transportCreate(PJSIP_TRANSPORT_UDP, tcfg);

    // Start the library
    ep.libStart();

    // Iottalk
    // rtp_receiver_ = rtp_receiver;
    // ros::NodeHandle nh;
    // sdp_sub_ = std::make_shared<message_filters::Subscriber<std_msgs::String>>(nh, "/sip_receiver_sdp", 1);
    // sdp_sub_->registerCallback(&SIP_Receiver::Process_Stream2, this);
}

SIP_Receiver::~SIP_Receiver(){}

// SIP Account Configuration
pj::AccountConfig SIP_Receiver::SIP_account_config(){
    // Create account
    pj::AccountConfig acfg;
    acfg.idUri = "sip:receiver@localhost"; // Receiver's SIP URI
    acfg.regConfig.registrarUri = "sip:localhost"; // Kamailio's SIP URI

    // Verify incoming calls
    // acfg.sipConfig.authCreds.push_back(pj::AuthCredInfo("digest", "*", "username", 0, "password"));
    return acfg;
}

// SIP Account Initialization
receiver_pj_account SIP_Receiver::SIP_account_init(){
    // Create account
    pj::AccountConfig acfg = SIP_account_config();
    receiver_pj_account acc(this);

    try{
        acc.create(acfg);
    }catch(pj::Error &e){
        std::cout<<"Error: "<<e.info()<<std::endl;
    }
    return acc;
}

// Accept Call
void SIP_Receiver::accept_call(pj::Call &call){
    pj::CallOpParam prm;
    prm.statusCode = PJSIP_SC_OK;
    
    // Answer the call
    call.answer(prm);

    std::cout << "Call accepted, reply with 200 OK" << std::endl;
}

// Reject Call
void SIP_Receiver::reject_call(pj::Call &call){
    pj::CallOpParam prm;
    prm.statusCode = PJSIP_SC_DECLINE;
    call.answer(prm);
}

// SIP Receiver main function
void SIP_Receiver::SIP_receiver_main(){
    // // 註冊當前線程到 PJSIP
    pj_thread_desc desc;
    pj_thread_t *pj_thread;
    pj_bzero(desc, sizeof(desc));
    pj_thread_register("sip_thread", desc, &pj_thread);

    // SIP account initialization
    receiver_pj_account acc = SIP_account_init();

    std::cout << "Waiting for incoming call..." << std::endl;

    while (true) {
        // 這裡您可以使用 PJSIP 的事件處理函數來處理 SIP 消息，例如：
        // pj::Endpoint::instance().libHandleEvents(1000);  // 處理1秒內的事件
    }
}

// Process Stream
void SIP_Receiver::Process_Stream(std::string whole_msg){
    // We only parser the term a={stream_id}: {remote_port} {stream_name} {media_type} {payload_id} {direction}
    // We use regex to parser the string !

    std::regex stream_regex("a=(\\d+): (\\d+) (\\w+) (\\w+) (\\d+) (\\w+)");
    std::smatch match;
    std::string::const_iterator search_start(whole_msg.cbegin());

    while (std::regex_search(search_start, whole_msg.cend(), match, stream_regex)){
        StreamData stream;
        stream.stream_id = std::stoi(match[1]);
        stream.local_port = started_port;
        stream.remote_port = std::stoi(match[2]);
        stream.stream_name = match[3];
        stream.media_type = match[4];
        stream.payload_id = std::stoi(match[5]);
        stream.direction = match[6] == "sendonly" ? "recvonly" : "sendonly"; // Reverse the direction

        stream_info.push_back(stream);
        
        started_port += 2000;
        search_start = match.suffix().first;
    }

    // Add stream data to RTP receiver
    for (int i = 0; i < stream_info.size(); i++){
        rtp_receiver_->add_stream_data(stream_info[i]);
    }

    std::cout << "Stream data has been added to RTP receiver!" << std::endl;
}

// Process Stream 2
void SIP_Receiver::Process_Stream2(std_msgs::String::ConstPtr sdp_msg){
    // We only parser the term a={stream_id}: {remote_port} {stream_name} {media_type} {payload_id} {direction}
    // We use regex to parser the string !

    std::string whole_msg = sdp_msg->data;

    std::regex stream_regex("a=(\\d+) (\\d+) (\\w+) (\\w+) (\\d+) (\\w+)");
    std::smatch match;
    std::string::const_iterator search_start(whole_msg.cbegin());

    while (std::regex_search(search_start, whole_msg.cend(), match, stream_regex)){
        StreamData stream;
        stream.stream_id = std::stoi(match[1]);
        stream.local_port = started_port;
        stream.remote_port = std::stoi(match[2]);
        stream.stream_name = match[3];
        stream.media_type = match[4];
        stream.payload_id = std::stoi(match[5]);
        stream.direction = match[6] == "sendonly" ? "recvonly" : "sendonly"; // Reverse the direction

        stream_info.push_back(stream);
        
        started_port += 2000;
        search_start = match.suffix().first;
    }

    // Add stream data to RTP receiver
    for (int i = 0; i < stream_info.size(); i++){
        rtp_receiver_->add_stream_data(stream_info[i]);
    }

    std::cout << "Stream data has been added to RTP receiver!" << std::endl;

    // Start the stream
    Start_Stream();
}

// Start Stream
void SIP_Receiver::Start_Stream(){
    
    if (first_OK == false){
        first_OK = true;
        // Start the stream
        rtp_receiver_->start_rtp_receiver();
        std::cout<<"Start the stream"<<std::endl;
    }else{
        std::cout<<"Stream has already started"<<std::endl;
        return;
    }
}

void receiver_pj_account::onIncomingCall(pj::OnIncomingCallParam &iprm){
    // Create call
    receiver_pj_call *call = new receiver_pj_call(*this, iprm.callId, sip_receiver_);

    // Get information from param
    pj::SipRxData rx_data = iprm.rdata;
    std::string whole_msg = rx_data.wholeMsg;

    // std::cout << " Whole message received: " << whole_msg << "ENDDDD "<<std::endl;

    // Process the incoming call
    sip_receiver_->Process_Stream(whole_msg);

    // Answer the call
    sip_receiver_->accept_call(*call);
}

std::string receiver_pj_call::create_custom_sdp() {

    // We can directly create the additional SDP info by the SIP_Receiver::stream_info (the vector of StreamData)
    // Follow the format (a={stream_id}: {local_port} {stream_name} {media_type} {payload_id} {direction})

    std::string sdp_str = "";
    for (int i = 0; i < sip_receiver_->stream_info.size(); i++){
        sdp_str += "a=" + std::to_string(sip_receiver_->stream_info[i].stream_id) + ": " + std::to_string(sip_receiver_->stream_info[i].local_port) + " " + sip_receiver_->stream_info[i].stream_name + " " + sip_receiver_->stream_info[i].media_type + " " + std::to_string(sip_receiver_->stream_info[i].payload_id) + " " + sip_receiver_->stream_info[i].direction + "\n";
    }
    
    return sdp_str;
}

static void add_default_streams_receiver(
    RTP_Receiver& client,
    int base_port,
    int remote_port_offset,
    int port_step,
    int payload_base
) {
    struct StreamDef { int id; const char* name; const char* media; };
    const StreamDef defs[] = {
        // {0, "rgb_stream",              "video"},
        {1, "depth_stream",            "video"},
        // {2, "point_cloud",             "pointcloud"},
        // {3, "scan_point_cloud",        "pointcloud"},
        // {4, "camera_info",             "camera_info"},
        // {5, "map_point_cloud",         "pointcloud"},
        // {6, "position_visualization",  "marker"},
        // {7, "position_command",        "command"},
        {8, "local_odom",              "odom"},
        {9, "pose",                    "pose"}
    };

    for (const auto& d : defs) {
        StreamData s;
        s.stream_id   = d.id;

        // ✅ Receiver 必須 bind 在 Sender 的 remote port（= base + id*step + offset）
        s.local_port  = base_port + d.id * port_step + remote_port_offset;

        // 對端（Sender）是 base + id*step
        s.remote_port = base_port + d.id * port_step;

        s.stream_name = d.name;
        s.media_type  = d.media;
        s.payload_id  = payload_base + d.id;
        s.direction   = "recvonly";

        client.add_stream_data(s);
    }
}

int main(int argc, char **argv){
    ros::init(argc, argv, "rtp_receiver");
    ros::NodeHandle pnh("~");

    bool use_sip = true;
    pnh.param("use_sip", use_sip, true);

    pnh.param<std::string>("local_ip",  local_ip,  std::string("127.0.0.1"));
    pnh.param<std::string>("remote_ip", remote_ip, std::string("127.0.0.1"));

    int base_port=10000, remote_port_offset=1000, port_step=2000, payload_base=96;
    pnh.param("base_port", base_port, 10000);
    pnh.param("remote_port_offset", remote_port_offset, 1000);
    pnh.param("port_step", port_step, 2000);
    pnh.param("payload_base", payload_base, 96);

    ROS_INFO_STREAM("[RTPReceiver] use_sip=" << (use_sip?"true":"false")
                    << " local_ip=" << local_ip
                    << " remote_ip=" << remote_ip
                    << " base_port=" << base_port
                    << " remote_port_offset=" << remote_port_offset
                    << " port_step=" << port_step
                    << " payload_base=" << payload_base);

    RTP_Receiver client;

    if (!use_sip) {
        add_default_streams_receiver(client, base_port, remote_port_offset, port_step, payload_base);
        client.start_rtp_receiver();   // ← 你的 Receiver 啟動函式名稱可能略不同，需對齊
        ROS_INFO("[RTPReceiver] Direct RTP started (SIP bypass).");
    } else {
        // 保留你原本 SIP 既有流程
        SIP_Receiver sip_receiver(&client);
        std::thread sip_thread(&SIP_Receiver::SIP_receiver_main, &sip_receiver);
        sip_thread.detach();
        ROS_INFO("[RTPReceiver] SIP signaling started.");
    }

    ros::MultiThreadedSpinner spinner(6);
    spinner.spin();
    return 0;
}

// int main(int argc, char **argv){
//     ros::init(argc, argv, "rtp_receiver");

//     RTP_Receiver rtp_receiver;
//     SIP_Receiver sip_receiver(&rtp_receiver);

//     // Use a thread to run the SIP receiver
//     std::thread sip_thread(&SIP_Receiver::SIP_receiver_main, &sip_receiver);

//     ros::spin();

//     return 0;
// }

// create two stream, rgb and depth stream
// if((ret = session->create_stream(
//     0, 11000, 10000, "rgb_stream", "video", 96, "recvonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     1, 13000, 12000, "depth_stream", "video", 97, "recvonly")) != 0){
//     exit(0);
// }

// // create point cloud stream
// if((ret = session->create_stream(
//     2, 15000, 14000, "point_cloud", "pointcloud", 98, "recvonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     3, 17000, 16000, "scan_point_cloud", "pointcloud", 99, "recvonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     4, 19000, 18000, "camera_info", "camera_info", 100, "recvonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     5, 21000, 20000, "map_point_cloud", "pointcloud", 101, "recvonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     6, 23000, 22000, "position_visualization", "marker", 102, "recvonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     7, 25000, 24000, "position_command", "command", 103, "recvonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     8, 27000, 26000, "local_odom", "odom", 104, "recvonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     9, 29000, 28000, "pose", "pose", 105, "recvonly")) != 0){
//     exit(0);
// }
