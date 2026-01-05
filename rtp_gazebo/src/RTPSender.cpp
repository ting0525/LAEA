#include "RTPSender.h"
#include "RTPSession.h"
#include "Data.h"
#include "Codec.h"
#include <iostream>

std::string local_ip = "140.114.208.49";
std::string remote_ip = "140.114.208.49";

RTPSession *session = new RTPSession();
VideoCodec *rgb_codec = new VideoCodec();
DepthImageCodec *depth_codec = new DepthImageCodec();
PointCloudCodec *pcloud_codec = new PointCloudCodec();
CameraInfoCodec *camera_info_codec = new CameraInfoCodec();
MarkerCodec *position_vis_codec = new MarkerCodec();
CommandCodec *position_command_codec = new CommandCodec();
OdomCodec *local_odom_codec = new OdomCodec();
PoseCodec *pose_codec = new PoseCodec();

RTP_Sender::RTP_Sender(){
    // Initialize the subcribers and callback functions
    ros::NodeHandle nh;
    init_subscriber(nh);
}

RTP_Sender::~RTP_Sender(){
    depth_sub_.reset();
    rgb_sub_.reset();
    depth_info_sub_.reset();
    pcloud_sub_.reset();
    scan_sub_.reset();
    map_pcloud_sub_.reset();
    position_vis_sub_.reset();
    position_command_sub_.reset();
    local_odom_sub_.reset();
    pose_sub_.reset();
}

void RTP_Sender::init_subscriber(ros::NodeHandle &nh){
    depth_sub_.reset(new message_filters::Subscriber<sensor_msgs::Image>(nh, "/camera/depth/image_raw", 1));
    // rgb_sub_.reset(new message_filters::Subscriber<sensor_msgs::Image>(nh, "/camera/depth/rgb_image_raw", 1));
    // depth_info_sub_.reset(new message_filters::Subscriber<sensor_msgs::CameraInfo>(nh, "/camera/depth/camera_info", 1));
    pcloud_sub_.reset(new message_filters::Subscriber<sensor_msgs::PointCloud2>(nh, "/depth_scan_pointcloud", 1));
    scan_sub_.reset(new message_filters::Subscriber<sensor_msgs::PointCloud2>(nh, "/scan_pointcloud", 1));
    map_pcloud_sub_.reset(new message_filters::Subscriber<sensor_msgs::PointCloud2>(nh, "/sdf_map/occupancy_all", 1));
    position_vis_sub_.reset(new message_filters::Subscriber<visualization_msgs::Marker>(nh, "/planning/position_cmd_vis", 1));
    position_command_sub_.reset(new message_filters::Subscriber<quadrotor_msgs::PositionCommand>(nh, "/position_cmd", 1));
    local_odom_sub_.reset(new message_filters::Subscriber<nav_msgs::Odometry>(nh, "/mavros/local_position/odom", 1));
    pose_sub_.reset(new message_filters::Subscriber<geometry_msgs::PoseStamped>(nh, "/mavros/camera/pose", 1));

    // Callback function
    depth_sub_->registerCallback(boost::bind(&RTP_Sender::depth_callback, this, _1));
    // rgb_sub_->registerCallback(boost::bind(&RTP_Sender::rgb_callback, this, _1));
    // depth_info_sub_->registerCallback(boost::bind(&RTP_Sender::depth_info_callback, this, _1));
    pcloud_sub_->registerCallback(boost::bind(&RTP_Sender::depth_point_cloud_callback, this, _1));
    scan_sub_->registerCallback(boost::bind(&RTP_Sender::scan_point_cloud_callback, this, _1));
    map_pcloud_sub_->registerCallback(boost::bind(&RTP_Sender::map_point_cloud_callback, this, _1));
    position_vis_sub_->registerCallback(boost::bind(&RTP_Sender::position_vis_callback, this, _1));
    position_command_sub_->registerCallback(boost::bind(&RTP_Sender::position_command_callback, this, _1));
    local_odom_sub_->registerCallback(boost::bind(&RTP_Sender::local_odom_callback, this, _1));
    pose_sub_->registerCallback(boost::bind(&RTP_Sender::pose_callback, this, _1));
}

void RTP_Sender::process_depth_data(cv::Mat &depth_image, cv::Mat &depth_image_uint16){
    int rows = depth_image.size().height;
    int cols = depth_image.size().width;

    int is_nan_num = 0, is_excceed_value_num = 0, is_normal_value_num = 0;
    
    depth_image_uint16 = cv::Mat::zeros(rows, cols, CV_16UC1);
    uint16_t bad_point = 0;
    for (int i = 0; i < rows; i++){
        for(int j = 0; j < cols; j++){
            float value = depth_image.at<float>(i, j);
            int milli_value;
            uint16_t convert_value;
            if(std::isnan(value)){
                is_nan_num++;
                convert_value = 0;
            }else if((milli_value = value * 1000) >= 65536){
                is_excceed_value_num++;
                convert_value = 0;
            }else{
                is_normal_value_num++;
                convert_value = (uint16_t)(value * 1000);
            }
            depth_image_uint16.at<uint16_t>(i, j) = convert_value;
        }
    }
}

void RTP_Sender::rgb_callback(const sensor_msgs::ImageConstPtr& rgb_msg){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }

    // std::cout << "RGB image callback" << " frame id: "<< rgb_msg->header.frame_id << std::endl;

    // Convert ROS image message to OpenCV image
    cv_bridge::CvImagePtr cv_ptr;
    try{
        cv_ptr = cv_bridge::toCvCopy(rgb_msg, sensor_msgs::image_encodings::BGR8);
    }catch(cv_bridge::Exception& e){
        ROS_ERROR("cv_bridge exception: %s", e.what());
        return;
    }

    // Successfully convert ROS image message to OpenCV image
    cv::Mat rgb_image = cv_ptr->image;

    // Send RGB image
    send_rgb_stream(0, rgb_image);
}

void RTP_Sender::depth_callback(const sensor_msgs::ImageConstPtr& depth_msg){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Depth image callback" <<" frame id: "<< depth_msg->header.frame_id << std::endl;

    // Print Sent time
    double current_time = ros::Time::now().toSec();
    // std::cout<<"Time duration between each sent depth image: "<<current_time-last_depth_time<<std::endl;
    last_depth_time = current_time;

    // Convert ROS image message to OpenCV image
    cv_bridge::CvImagePtr cv_ptr;
    try{
        cv_ptr = cv_bridge::toCvCopy(depth_msg, sensor_msgs::image_encodings::TYPE_32FC1);
    }catch(cv_bridge::Exception& e){
        ROS_ERROR("cv_bridge exception: %s", e.what());
        return;
    }
    
    // Successfully convert ROS image message to OpenCV image
    cv::Mat depth_image = cv_ptr->image;

    // Process depth image by making it 16-bit unsigned integer
    cv::Mat depth_image_uint16;
    process_depth_data(depth_image, depth_image_uint16);

    // Send depth image
    send_depth_stream(1, depth_image_uint16);
}

void RTP_Sender::depth_point_cloud_callback(const sensor_msgs::PointCloud2ConstPtr& pcloud_msg){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Depth point cloud callback" << " frame id: "<< pcloud_msg->header.frame_id << std::endl;

    // Convert ROS point cloud message to PCL point cloud
    pcl::PointCloud<pcl::PointXYZ>::Ptr pcloud(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::fromROSMsg(*pcloud_msg, *pcloud);

    // Send point cloud
    send_pcloud_stream(2, pcloud);
}

void RTP_Sender::scan_point_cloud_callback(const sensor_msgs::PointCloud2ConstPtr& pcloud_msg){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Scan point cloud callback" << " frame id: "<< pcloud_msg->header.frame_id << std::endl;

    // Convert ROS point cloud message to PCL point cloud
    pcl::PointCloud<pcl::PointXYZ>::Ptr pcloud(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::fromROSMsg(*pcloud_msg, *pcloud);

    // Send point cloud
    send_pcloud_stream(3, pcloud);
}

void RTP_Sender::depth_info_callback(const sensor_msgs::CameraInfoConstPtr& depth_info_msg){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Depth camera info callback" << " frame id: "<< depth_info_msg->header.frame_id << std::endl;

    // Send camera info
    send_camera_info_stream(4, *depth_info_msg);
}

void RTP_Sender::map_point_cloud_callback(const sensor_msgs::PointCloud2ConstPtr& pcloud_msg){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Map point cloud callback" << " frame id: "<< pcloud_msg->header.frame_id << std::endl;

    // Convert ROS point cloud message to PCL point cloud
    pcl::PointCloud<pcl::PointXYZ>::Ptr pcloud(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::fromROSMsg(*pcloud_msg, *pcloud);

    // Send point cloud
    send_pcloud_stream(5, pcloud);
}

void RTP_Sender::position_vis_callback(const visualization_msgs::Marker::ConstPtr& position_vis_msg){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Position visualization callback" << " frame id: "<< position_vis_msg->header.frame_id << std::endl;

    // Send position visualization
    send_position_vis_stream(6, *position_vis_msg);
}

void RTP_Sender::position_command_callback(const quadrotor_msgs::PositionCommand::ConstPtr& position_command_msg){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Position command callback" << " frame id: "<< position_command_msg->header.frame_id << std::endl;

    // Send position command
    send_position_command_stream(7, *position_command_msg);
}

void RTP_Sender::local_odom_callback(const nav_msgs::Odometry::ConstPtr& local_odom_msg){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Local odometry callback" << " frame id: "<< local_odom_msg->header.frame_id << std::endl;

    // Send local odometry
    send_local_odom_stream(8, *local_odom_msg);
}

void RTP_Sender::pose_callback(const geometry_msgs::PoseStamped::ConstPtr& pose_msg){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Pose callback" << " frame id: "<< pose_msg->header.frame_id << std::endl;

    // Send pose
    send_pose_stream(9, *pose_msg);
}

void RTP_Sender::send_rgb_stream(int stream_id, cv::Mat rgb_image){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Send RGB stream" << std::endl;

    int ret;
    struct Data data;

    ret = rgb_codec->encode(rgb_image, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
        // std::cout << "send rgb data" << std::endl;
    }

    destroy_data(&data);
}

void RTP_Sender::send_depth_stream(int stream_id, cv::Mat depth_image){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Send depth stream" << std::endl;

    int ret = 1;
    struct Data data;

    ret = depth_codec->encode(depth_image, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
        // std::cout << "send depth data" << std::endl;
    }

    destroy_data(&data);
}

void RTP_Sender::send_pcloud_stream(int stream_id, pcl::PointCloud<pcl::PointXYZ>::Ptr pcloud){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Send point cloud stream, id: " << stream_id<< std::endl;

    int ret;
    struct Data data;
    
    ret = pcloud_codec->encode(pcloud, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
        // std::cout << "send point cloud data" << std::endl;
    }

    destroy_data(&data);
}

void RTP_Sender::send_camera_info_stream(int stream_id, sensor_msgs::CameraInfo camera_info){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Send camera info stream" << std::endl;

    int ret;
    struct Data data;

    ret = camera_info_codec->encode(camera_info, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
        // std::cout << "send camera info data" << std::endl;
    }

    destroy_data(&data);
}

void RTP_Sender::send_position_vis_stream(int stream_id, visualization_msgs::Marker position_vis){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Send position visualization stream" << std::endl;

    int ret;
    struct Data data;

    ret = position_vis_codec->encode(position_vis, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
        // std::cout << "send position visualization data" << std::endl;
    }

    destroy_data(&data);
}

void RTP_Sender::send_position_command_stream(int stream_id, quadrotor_msgs::PositionCommand position_command){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Send position command stream" << std::endl;

    int ret;
    struct Data data;

    ret = position_command_codec->encode(&data, position_command);
    if(ret == 0){
        session->send_data(stream_id, &data);
        // std::cout << "send position command data" << std::endl;
    }

    destroy_data(&data);
}

void RTP_Sender::send_local_odom_stream(int stream_id, nav_msgs::Odometry local_odom){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Send local odometry stream" << std::endl;

    int ret;
    struct Data data;

    ret = local_odom_codec->encode(local_odom, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
        // std::cout << "send local odometry data" << std::endl;
    }

    destroy_data(&data);
}

void RTP_Sender::send_pose_stream(int stream_id, geometry_msgs::PoseStamped pose){
    if(!start_rtp_sender_){
        // printf("RTP Sender is not started yet!\n");
        return;
    }
    // std::cout << "Send pose stream" << std::endl;

    int ret;
    struct Data data;

    ret = pose_codec->encode(pose, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
        // std::cout << "send pose data" << std::endl;
    }

    destroy_data(&data);
}

// Add StreamData
void RTP_Sender::add_stream_data(StreamData stream_data){
    this->stream_data.push_back(stream_data);
}

// Start RTP Sender
void RTP_Sender::start_rtp_sender(){
    rgb_codec->init(
        640, 480, AV_CODEC_ID_H264, AVMEDIA_TYPE_VIDEO, AV_PIX_FMT_YUV420P, AV_PIX_FMT_BGR24
    );

    int ret = 0;
    if ((ret = session->create_session(local_ip, remote_ip)) != 0){
        exit(0);
    }

    // Use the stream data to create the stream
    for (int i = 0; i < stream_data.size(); i++){
        if((ret = session->create_stream(
            stream_data[i].stream_id, stream_data[i].local_port, stream_data[i].remote_port, stream_data[i].stream_name, stream_data[i].media_type, stream_data[i].payload_id, stream_data[i].direction)) != 0){
            exit(0);
        }
        std::cout << "Stream ID: " << stream_data[i].stream_id << " ," << "Local Port: " << stream_data[i].local_port << " ," << "Remote Port: " << stream_data[i].remote_port << " ," << "Stream Name: " << stream_data[i].stream_name << " ," << "Media Type: " << stream_data[i].media_type << " ," << "Payload ID: " << stream_data[i].payload_id << " ," << "Direction: " << stream_data[i].direction << std::endl;
    }

    start_rtp_sender_ = true;
}

// SIP Sender
SIP_Sender::SIP_Sender(RTP_Sender *rtp_sender){
    //  PJSIP
    rtp_sender_ = rtp_sender;
    // Create SIP endpoint
    ep.libCreate();

    pj::LogConfig log_cfg;
    log_cfg.level = 5;  // 设置日志级别为5，显示详细信息

    // Init endpoint with media config to set RTP port range
    pj::EpConfig ep_cfg;
    ep_cfg.logConfig = log_cfg;
    ep.libInit(ep_cfg); // Initialize the library with the configured RTP port range

    // Create UDP transport
    pj::TransportConfig tcfg;
    tcfg.port = 6000;  // 使用4000作为SIP信令的端口
    ep.transportCreate(PJSIP_TRANSPORT_UDP, tcfg);

    // Start the library
    ep.libStart();

    // Iottalk
    // rtp_sender_ = rtp_sender;
    // ros::NodeHandle nh;
    // sdp_sub_.reset(new message_filters::Subscriber<std_msgs::String>(nh, "/sip_sender_sdp", 1));
    // sdp_sub_->registerCallback(boost::bind(&SIP_Sender::Process_Stream2, this, _1));
}
SIP_Sender::~SIP_Sender(){}

// SIP Account Configuration
pj::AccountConfig SIP_Sender::SIP_account_config(){
    // Create account
    pj::AccountConfig acfg;
    acfg.idUri = "sip:sender@localhost"; // Sender's SIP URI
    acfg.regConfig.registrarUri = "sip:localhost";

    // Verify incoming calls
    // acfg.sipConfig.authCreds.push_back(pj::AuthCredInfo("digest", "*", "username", 0, "password"));
    return acfg;
}

// SIP Account Initialization
pj::Account SIP_Sender::SIP_account_init(){
    // Create account
    pj::AccountConfig acfg = SIP_account_config();
    pj::Account acc;

    try{
        acc.create(acfg);
    }catch(pj::Error &e){
        std::cout<<"Error: "<<e.info()<<std::endl;
    }
    return acc;
}

// SIP Call 
void SIP_Sender::SIP_call(pj::Account &acc, const std::string remote_uri){
    // Create call
    my_pj_call *call = new my_pj_call(acc, -1, this);
    pj::CallOpParam prm;
    pj::CallSetting opt;
    opt.audioCount = 1;

    prm.opt = opt;
    // prm.sdp.wholeSdp = call->create_custom_sdp();

    try{
        call->makeCall(remote_uri, prm);
        std::cout<<"SIP call to "<<remote_uri<<" is successful!"<<std::endl;
    }catch(pj::Error &e){
        std::cout<<"SIP call to "<<remote_uri<<" is failed!"<<std::endl;
        std::cout<<"Error: "<<e.info()<<std::endl;
    }
}

// Send ACK
void SIP_Sender::send_ack(pj::Call &call){
    pj::CallOpParam prm;
    prm.statusCode = PJSIP_SC_OK;
    call.answer(prm);
}

// SIP Sender main function
void SIP_Sender::SIP_sender_main(){
    pj_thread_desc desc;
    pj_thread_t *pj_thread;
    pj_bzero(desc, sizeof(desc));
    pj_thread_register("sip_thread", desc, &pj_thread);
    // SIP account initialization
    pj::Account acc = SIP_account_init();

    // SIP call
    SIP_call(acc, "sip:receiver@140.114.208.49");

    while(true){
        // std::cout<<"SIP sender is running"<<std::endl;
        // pj_thread_sleep(1000);
    }
}

// Process stream data
void SIP_Sender::Process_Stream(std::string whole_msg){
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

        rtp_sender_->add_stream_data(stream);
        
        started_port += 2000;
        search_start = match.suffix().first;

        // Print the stream data
        std::cout << "Stream ID: " << stream.stream_id << " ," << " Local Port: " << stream.local_port << " ," << " Remote Port: " << stream.remote_port << " ," << " Stream Name: " << stream.stream_name << " ," << " Media Type: " << stream.media_type << " ," << " Payload ID: " << stream.payload_id << " ," << " Direction: " << stream.direction << std::endl;
    }

    std::cout << "Stream data has been added to RTP sender!" << std::endl;
}

void SIP_Sender::Process_Stream2(std_msgs::String::ConstPtr sdp_msg){

    std::string whole_msg = sdp_msg->data;

    printf("Received SDP message: %s\n", whole_msg.c_str());

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

        rtp_sender_->add_stream_data(stream);
        
        started_port += 2000;
        search_start = match.suffix().first;

        // Print the stream data
        std::cout << "Stream ID: " << stream.stream_id << " ," << " Local Port: " << stream.local_port << " ," << " Remote Port: " << stream.remote_port << " ," << " Stream Name: " << stream.stream_name << " ," << " Media Type: " << stream.media_type << " ," << " Payload ID: " << stream.payload_id << " ," << " Direction: " << stream.direction << std::endl;
    }

    std::cout << "Stream data has been added to RTP sender!" << std::endl;

    // Start the stream
    Start_Stream();
}

// Start the stream
void SIP_Sender::Start_Stream(){
    
    if (first_OK == false){
        first_OK = true;
        // Start the stream
        std::cout<<"Start the stream"<<std::endl;
        rtp_sender_->start_rtp_sender();
    }else{
        std::cout<<"Stream has already started"<<std::endl;
        return;
    }
}

std::string my_pj_call::create_custom_sdp(){
    // // Version of the SDP
    // std::string version = "v=0\n";

    // // Origin of the SDP
    // int session_id = rand() % 400000;
    // int session_version = session_id; // Session version is the same as session ID
    // std::string origin = "o=- " + std::to_string(session_id) + " " + std::to_string(session_version) + " IN IP4 " + local_ip + "\n";

    // // Session name
    // std::string session_name = "s=RTP Stream Session\n";

    // // Connection information
    // std::string connection = "c=IN IP4 " + local_ip + "\n";

    // // Timing information
    // std::string timing = "t=0 0\n"; // 0 0 means the session is permanent

    // Custom Media information
    // 1. stream_id
    // 2. local_port
    // 3. remote_port
    // 4. stream_name
    // 5. media_type
    // 6. payload_id
    // 7. direction

    // Custom media information
    // std::string media = "m=audio 4000 RTP/AVP 96 97 98 99 100 101 102 103 104 105\n";
    // Stream 0: RGB Stream
    std::string rgb_stream = std::string("a=0 10000 rgb_stream video 96 sendonly\n");
    // Stream 1: Depth Stream
    std::string depth_stream = std::string("a=1 12000 depth_stream video 97 sendonly\n");
    // Stream 2: Point Cloud Stream
    std::string pcloud_stream = std::string("a=2 14000 point_cloud pointcloud 98 sendonly\n");
    // Stream 3: Scan Point Cloud Stream
    std::string scan_stream = std::string("a=3 16000 scan_point_cloud pointcloud 99 sendonly\n");
    // Stream 4: Camera Info Stream
    std::string camera_info_stream = std::string("a=4 18000 camera_info camera_info 100 sendonly\n");
    // Stream 5: Map Point Cloud Stream
    std::string map_pcloud_stream = std::string("a=5 20000 map_point_cloud pointcloud 101 sendonly\n");
    // Stream 6: Position Visualization Stream
    std::string position_vis_stream = std::string("a=6 22000 position_visualization marker 102 sendonly\n");
    // Stream 7: Position Command Stream
    std::string position_command_stream = std::string("a=7 24000 position_command command 103 sendonly\n");
    // Stream 8: Local Odometry Stream
    std::string local_odom_stream = std::string("a=8 26000 local_odom odom 104 sendonly\n");
    // Stream 9: Pose Stream
    std::string pose_stream = std::string("a=9 28000 pose pose 105 sendonly\n");

    // Combine all the SDP information
    std::string sdp_str = rgb_stream + depth_stream + pcloud_stream + scan_stream + camera_info_stream + map_pcloud_stream + position_vis_stream + position_command_stream + local_odom_stream + pose_stream;
    
    return sdp_str;
}

// For testing
int main(int argc, char** argv){

    // SIP Initialization
    ros::init(argc, argv, "rtp_sender");

    RTP_Sender client;
    SIP_Sender sip_sender(&client);
    // Use a thread to run the SIP sender
    std::thread sip_thread(&SIP_Sender::SIP_sender_main, &sip_sender);

    ros::MultiThreadedSpinner spinner(6); 	// 开两个spinner并行处理
    spinner.spin();
    return 0;
}

// if((ret = session->create_stream(
//     0, 10000, 11000, "rgb_stream", "video", 96, "sendonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     1, 12000, 13000, "depth_stream", "video", 97, "sendonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     2, 14000, 15000, "point_cloud", "pointcloud", 98, "sendonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     3, 16000, 17000, "scan_point_cloud", "pointcloud", 99, "sendonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     4, 18000, 19000, "camera_info", "camera_info", 100, "sendonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     5, 20000, 21000, "map_point_cloud", "pointcloud", 101, "sendonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     6, 22000, 23000, "position_visualization", "marker", 102, "sendonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     7, 24000, 25000, "position_command", "command", 103, "sendonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     8, 26000, 27000, "local_odom", "odom", 104, "sendonly")) != 0){
//     exit(0);
// }

// if((ret = session->create_stream(
//     9, 28000, 29000, "pose", "pose", 105, "sendonly")) != 0){
//     exit(0);
// }