#include "RTPSender.h"
#include "RTPSession.h"
#include "Data.h"
#include "Codec.h"

#include <iostream>
#include <cstdlib>          // exit
#include <cmath>            // std::isnan
#include <thread>
#include <regex>

#include <ros/master.h>     // ros::master::check
#include <pcl/filters/voxel_grid.h>

std::string local_ip  = "127.0.0.1";
std::string remote_ip = "127.0.0.1";

// ✅ 改成延遲初始化，避免 main() 前就觸發 uvgRTP/網路解析
RTPSession *session = nullptr;

VideoCodec *rgb_codec = new VideoCodec();
DepthImageCodec *depth_codec = new DepthImageCodec();
PointCloudCodec *pcloud_codec = new PointCloudCodec();
CameraInfoCodec *camera_info_codec = new CameraInfoCodec();
MarkerCodec *position_vis_codec = new MarkerCodec();
CommandCodec *position_command_codec = new CommandCodec();
OdomCodec *local_odom_codec = new OdomCodec();
PoseCodec *pose_codec = new PoseCodec();

RTP_Sender::RTP_Sender(){
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

    // === LAEA / Gazebo topics (hard-coded) ===
    depth_sub_.reset(new message_filters::Subscriber<sensor_msgs::Image>(
        nh, "/camera/depth/image_raw", 1));

    rgb_sub_.reset(new message_filters::Subscriber<sensor_msgs::Image>(
        nh, "/camera/depth/rgb_image_raw", 1));

    depth_info_sub_.reset(new message_filters::Subscriber<sensor_msgs::CameraInfo>(
        nh, "/camera/depth/camera_info", 1));

    // Depth point cloud: pick LAEA existing source
    pcloud_sub_.reset(new message_filters::Subscriber<sensor_msgs::PointCloud2>(
        nh, "/camera/depth/color/points", 1));

    scan_sub_.reset(new message_filters::Subscriber<sensor_msgs::PointCloud2>(
        nh, "/scan_pointcloud", 1));

    map_pcloud_sub_.reset(new message_filters::Subscriber<sensor_msgs::PointCloud2>(
        nh, "/sdf_map/occupancy_all", 1));

    local_odom_sub_.reset(new message_filters::Subscriber<nav_msgs::Odometry>(
        nh, "/mavros/local_position/odom", 1));

    pose_sub_.reset(new message_filters::Subscriber<geometry_msgs::PoseStamped>(
        nh, "/mavros/camera/pose", 1));

    // === Disable streams not present in your LAEA topic list ===
    // position_vis_sub_.reset(new message_filters::Subscriber<visualization_msgs::Marker>(
    //     nh, "/planning/position_cmd_vis", 1));
    // position_command_sub_.reset(new message_filters::Subscriber<quadrotor_msgs::PositionCommand>(
    //     nh, "/position_cmd", 1));

    // === Callback registration ===
    depth_sub_->registerCallback(boost::bind(&RTP_Sender::depth_callback, this, _1));
    rgb_sub_->registerCallback(boost::bind(&RTP_Sender::rgb_callback, this, _1));
    depth_info_sub_->registerCallback(boost::bind(&RTP_Sender::depth_info_callback, this, _1));

    pcloud_sub_->registerCallback(boost::bind(&RTP_Sender::depth_point_cloud_callback, this, _1));
    scan_sub_->registerCallback(boost::bind(&RTP_Sender::scan_point_cloud_callback, this, _1));
    map_pcloud_sub_->registerCallback(boost::bind(&RTP_Sender::map_point_cloud_callback, this, _1));

    local_odom_sub_->registerCallback(boost::bind(&RTP_Sender::local_odom_callback, this, _1));
    pose_sub_->registerCallback(boost::bind(&RTP_Sender::pose_callback, this, _1));

    // position_vis_sub_->registerCallback(boost::bind(&RTP_Sender::position_vis_callback, this, _1));
    // position_command_sub_->registerCallback(boost::bind(&RTP_Sender::position_command_callback, this, _1));
}

void RTP_Sender::process_depth_data(cv::Mat &depth_image, cv::Mat &depth_image_uint16){
    int rows = depth_image.size().height;
    int cols = depth_image.size().width;

    depth_image_uint16 = cv::Mat::zeros(rows, cols, CV_16UC1);

    for (int i = 0; i < rows; i++){
        for(int j = 0; j < cols; j++){
            float value = depth_image.at<float>(i, j);
            int milli_value;
            uint16_t convert_value;

            if(std::isnan(value)){
                convert_value = 0;
            }else if((milli_value = static_cast<int>(value * 1000.0f)) >= 65536){
                convert_value = 0;
            }else if (milli_value < 0) {
                convert_value = 0;
            }else{
                convert_value = static_cast<uint16_t>(milli_value);
            }
            depth_image_uint16.at<uint16_t>(i, j) = convert_value;
        }
    }
}

void RTP_Sender::rgb_callback(const sensor_msgs::ImageConstPtr& rgb_msg){
    if(!start_rtp_sender_){
        return;
    }

    cv_bridge::CvImagePtr cv_ptr;
    try{
        cv_ptr = cv_bridge::toCvCopy(rgb_msg, sensor_msgs::image_encodings::BGR8);
    }catch(cv_bridge::Exception& e){
        ROS_ERROR("cv_bridge exception: %s", e.what());
        return;
    }

    cv::Mat rgb_image = cv_ptr->image;
    send_rgb_stream(0, rgb_image);
}

void RTP_Sender::depth_callback(const sensor_msgs::ImageConstPtr& depth_msg){
    if(!start_rtp_sender_){
        return;
    }

    last_depth_time = ros::Time::now().toSec();

    // NOTE：這裡只處理「深度影像」並送 stream_id=1
    cv_bridge::CvImagePtr cv_ptr;
    try{
        cv_ptr = cv_bridge::toCvCopy(depth_msg, sensor_msgs::image_encodings::TYPE_32FC1);
    }catch(cv_bridge::Exception& e){
        ROS_ERROR("cv_bridge exception: %s", e.what());
        return;
    }

    cv::Mat depth_image = cv_ptr->image;

    cv::Mat depth_image_uint16;
    process_depth_data(depth_image, depth_image_uint16);

    send_depth_stream(1, depth_image_uint16);
}

void RTP_Sender::depth_point_cloud_callback(const sensor_msgs::PointCloud2ConstPtr& pcloud_msg){
    if(!start_rtp_sender_){
        return;
    }

    pcl::PointCloud<pcl::PointXYZ>::Ptr pcloud(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::fromROSMsg(*pcloud_msg, *pcloud);

    // === VoxelGrid downsample (hard-coded) ===
    pcl::PointCloud<pcl::PointXYZ>::Ptr filtered(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::VoxelGrid<pcl::PointXYZ> vg;
    vg.setInputCloud(pcloud);
    vg.setLeafSize(0.05f, 0.05f, 0.05f);  // 5cm voxel
    vg.filter(*filtered);

    send_pcloud_stream(2, filtered);
}

void RTP_Sender::scan_point_cloud_callback(const sensor_msgs::PointCloud2ConstPtr& pcloud_msg){
    if(!start_rtp_sender_){
        return;
    }

    pcl::PointCloud<pcl::PointXYZ>::Ptr pcloud(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::fromROSMsg(*pcloud_msg, *pcloud);

    // 可選：scan 通常量也不小，一樣做下採樣
    pcl::PointCloud<pcl::PointXYZ>::Ptr filtered(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::VoxelGrid<pcl::PointXYZ> vg;
    vg.setInputCloud(pcloud);
    vg.setLeafSize(0.05f, 0.05f, 0.05f);
    vg.filter(*filtered);

    send_pcloud_stream(3, filtered);
}

void RTP_Sender::depth_info_callback(const sensor_msgs::CameraInfoConstPtr& depth_info_msg){
    if(!start_rtp_sender_){
        return;
    }
    send_camera_info_stream(4, *depth_info_msg);
}

void RTP_Sender::map_point_cloud_callback(const sensor_msgs::PointCloud2ConstPtr& pcloud_msg){
    if(!start_rtp_sender_){
        return;
    }

    pcl::PointCloud<pcl::PointXYZ>::Ptr pcloud(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::fromROSMsg(*pcloud_msg, *pcloud);

    // 可選：map/occupancy_all 可能更大，建議也下採樣
    pcl::PointCloud<pcl::PointXYZ>::Ptr filtered(new pcl::PointCloud<pcl::PointXYZ>);
    pcl::VoxelGrid<pcl::PointXYZ> vg;
    vg.setInputCloud(pcloud);
    vg.setLeafSize(0.10f, 0.10f, 0.10f);  // map 用 10cm 更實際
    vg.filter(*filtered);

    send_pcloud_stream(5, filtered);
}

void RTP_Sender::position_vis_callback(const visualization_msgs::Marker::ConstPtr& position_vis_msg){
    if(!start_rtp_sender_){
        return;
    }
    send_position_vis_stream(6, *position_vis_msg);
}

void RTP_Sender::position_command_callback(const quadrotor_msgs::PositionCommand::ConstPtr& position_command_msg){
    if(!start_rtp_sender_){
        return;
    }
    send_position_command_stream(7, *position_command_msg);
}

void RTP_Sender::local_odom_callback(const nav_msgs::Odometry::ConstPtr& local_odom_msg){
    if(!start_rtp_sender_){
        return;
    }
    send_local_odom_stream(8, *local_odom_msg);
}

void RTP_Sender::pose_callback(const geometry_msgs::PoseStamped::ConstPtr& pose_msg){
    if(!start_rtp_sender_){
        return;
    }
    send_pose_stream(9, *pose_msg);
}

void RTP_Sender::send_rgb_stream(int stream_id, cv::Mat rgb_image){
    if(!start_rtp_sender_ || session == nullptr){
        return;
    }

    struct Data data;
    int ret = rgb_codec->encode(rgb_image, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
    }
    destroy_data(&data);
}

void RTP_Sender::send_depth_stream(int stream_id, cv::Mat depth_image){
    if(!start_rtp_sender_ || session == nullptr){
        return;
    }

    struct Data data;
    int ret = depth_codec->encode(depth_image, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
    }
    destroy_data(&data);
}

void RTP_Sender::send_pcloud_stream(int stream_id, pcl::PointCloud<pcl::PointXYZ>::Ptr pcloud){
    if(!start_rtp_sender_ || session == nullptr){
        return;
    }

    struct Data data;
    int ret = pcloud_codec->encode(pcloud, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
    }
    destroy_data(&data);
}

void RTP_Sender::send_camera_info_stream(int stream_id, sensor_msgs::CameraInfo camera_info){
    if(!start_rtp_sender_ || session == nullptr){
        return;
    }

    struct Data data;
    int ret = camera_info_codec->encode(camera_info, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
    }
    destroy_data(&data);
}

void RTP_Sender::send_position_vis_stream(int stream_id, visualization_msgs::Marker position_vis){
    if(!start_rtp_sender_ || session == nullptr){
        return;
    }

    struct Data data;
    int ret = position_vis_codec->encode(position_vis, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
    }
    destroy_data(&data);
}

void RTP_Sender::send_position_command_stream(int stream_id, quadrotor_msgs::PositionCommand position_command){
    if(!start_rtp_sender_ || session == nullptr){
        return;
    }

    struct Data data;
    int ret = position_command_codec->encode(&data, position_command);
    if(ret == 0){
        session->send_data(stream_id, &data);
    }
    destroy_data(&data);
}

void RTP_Sender::send_local_odom_stream(int stream_id, nav_msgs::Odometry local_odom){
    if(!start_rtp_sender_ || session == nullptr){
        return;
    }

    struct Data data;
    int ret = local_odom_codec->encode(local_odom, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
    }
    destroy_data(&data);
}

void RTP_Sender::send_pose_stream(int stream_id, geometry_msgs::PoseStamped pose){
    if(!start_rtp_sender_ || session == nullptr){
        return;
    }

    struct Data data;
    int ret = pose_codec->encode(pose, &data);
    if(ret == 0){
        session->send_data(stream_id, &data);
    }
    destroy_data(&data);
}

void RTP_Sender::add_stream_data(StreamData stream_data){
    this->stream_data.push_back(stream_data);
}

void RTP_Sender::start_rtp_sender(){

    // ✅ lazy init
    if (session == nullptr) {
        session = new RTPSession();
    }

    if (local_ip.empty() || remote_ip.empty()) {
        std::cerr << "[RTPSender] local_ip or remote_ip is empty. Check ROS params.\n";
        exit(1);
    }

    rgb_codec->init(
        640, 480, AV_CODEC_ID_H264, AVMEDIA_TYPE_VIDEO, AV_PIX_FMT_YUV420P, AV_PIX_FMT_BGR24
    );

    int ret = 0;
    if ((ret = session->create_session(local_ip, remote_ip)) != 0){
        std::cerr << "[RTPSender] create_session failed.\n";
        exit(1);
    }

    for (int i = 0; i < (int)stream_data.size(); i++){
        if((ret = session->create_stream(
            stream_data[i].stream_id,
            stream_data[i].local_port,
            stream_data[i].remote_port,
            stream_data[i].stream_name,
            stream_data[i].media_type,
            stream_data[i].payload_id,
            stream_data[i].direction)) != 0){
            std::cerr << "[RTPSender] create_stream failed. stream_id=" << stream_data[i].stream_id << "\n";
            exit(1);
        }

        std::cout << "Stream ID: " << stream_data[i].stream_id << " ,"
                  << "Local Port: " << stream_data[i].local_port << " ,"
                  << "Remote Port: " << stream_data[i].remote_port << " ,"
                  << "Stream Name: " << stream_data[i].stream_name << " ,"
                  << "Media Type: " << stream_data[i].media_type << " ,"
                  << "Payload ID: " << stream_data[i].payload_id << " ,"
                  << "Direction: " << stream_data[i].direction
                  << std::endl;
    }

    start_rtp_sender_ = true;
}

// ===================== SIP (保留原邏輯) =====================

SIP_Sender::SIP_Sender(RTP_Sender *rtp_sender){
    rtp_sender_ = rtp_sender;

    ep.libCreate();

    pj::LogConfig log_cfg;
    log_cfg.level = 5;

    pj::EpConfig ep_cfg;
    ep_cfg.logConfig = log_cfg;
    ep.libInit(ep_cfg);

    pj::TransportConfig tcfg;
    tcfg.port = 6000;
    ep.transportCreate(PJSIP_TRANSPORT_UDP, tcfg);

    ep.libStart();
}
SIP_Sender::~SIP_Sender(){}

pj::AccountConfig SIP_Sender::SIP_account_config(){
    pj::AccountConfig acfg;
    acfg.idUri = "sip:sender@localhost";
    acfg.regConfig.registrarUri = "sip:localhost";
    return acfg;
}

pj::Account SIP_Sender::SIP_account_init(){
    pj::AccountConfig acfg = SIP_account_config();
    pj::Account acc;
    try{
        acc.create(acfg);
    }catch(pj::Error &e){
        std::cout<<"Error: "<<e.info()<<std::endl;
    }
    return acc;
}

void SIP_Sender::SIP_call(pj::Account &acc, const std::string remote_uri){
    my_pj_call *call = new my_pj_call(acc, -1, this);
    pj::CallOpParam prm;
    pj::CallSetting opt;
    opt.audioCount = 1;

    prm.opt = opt;

    try{
        call->makeCall(remote_uri, prm);
        std::cout<<"SIP call to "<<remote_uri<<" is successful!"<<std::endl;
    }catch(pj::Error &e){
        std::cout<<"SIP call to "<<remote_uri<<" is failed!"<<std::endl;
        std::cout<<"Error: "<<e.info()<<std::endl;
    }
}

void SIP_Sender::send_ack(pj::Call &call){
    pj::CallOpParam prm;
    prm.statusCode = PJSIP_SC_OK;
    call.answer(prm);
}

void SIP_Sender::SIP_sender_main(){
    pj_thread_desc desc;
    pj_thread_t *pj_thread;
    pj_bzero(desc, sizeof(desc));
    pj_thread_register("sip_thread", desc, &pj_thread);

    pj::Account acc = SIP_account_init();
    SIP_call(acc, "sip:receiver@127.0.0.1");

    while(true){
        // keep running
    }
}

void SIP_Sender::Process_Stream(std::string whole_msg){
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
        stream.direction = match[6] == "sendonly" ? "recvonly" : "sendonly";

        rtp_sender_->add_stream_data(stream);

        started_port += 2000;
        search_start = match.suffix().first;
    }
}

void SIP_Sender::Process_Stream2(std_msgs::String::ConstPtr sdp_msg){
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
        stream.direction = match[6] == "sendonly" ? "recvonly" : "sendonly";

        rtp_sender_->add_stream_data(stream);

        started_port += 2000;
        search_start = match.suffix().first;
    }

    Start_Stream();
}

void SIP_Sender::Start_Stream(){
    if (first_OK == false){
        first_OK = true;
        rtp_sender_->start_rtp_sender();
    }
}

std::string my_pj_call::create_custom_sdp(){
    std::string rgb_stream = std::string("a=0 10000 rgb_stream video 96 sendonly\n");
    std::string depth_stream = std::string("a=1 12000 depth_stream video 97 sendonly\n");
    std::string pcloud_stream = std::string("a=2 14000 point_cloud pointcloud 98 sendonly\n");
    std::string scan_stream = std::string("a=3 16000 scan_point_cloud pointcloud 99 sendonly\n");
    std::string camera_info_stream = std::string("a=4 18000 camera_info camera_info 100 sendonly\n");
    std::string map_pcloud_stream = std::string("a=5 20000 map_point_cloud pointcloud 101 sendonly\n");
    std::string local_odom_stream = std::string("a=8 26000 local_odom odom 104 sendonly\n");
    std::string pose_stream = std::string("a=9 28000 pose pose 105 sendonly\n");

    return rgb_stream + depth_stream + pcloud_stream + scan_stream +
           camera_info_stream + map_pcloud_stream +
           local_odom_stream + pose_stream;
}

static void add_default_streams(
    RTP_Sender& client,
    int base_port,
    int remote_port_offset,
    int port_step,
    int payload_base
) {
    struct StreamDef {
        int id;
        const char* name;
        const char* media;
    };

    const StreamDef defs[] = {
        {0, "rgb_stream",       "video"},
        {1, "depth_stream",     "video"},
        {2, "point_cloud",      "pointcloud"},
        {3, "scan_point_cloud", "pointcloud"},
        {4, "camera_info",      "camera_info"},
        {5, "map_point_cloud",  "pointcloud"},
        {8, "local_odom",       "odom"},
        {9, "pose",             "pose"}
    };

    for (const auto& d : defs) {
        StreamData s;
        s.stream_id   = d.id;
        s.local_port  = base_port + d.id * port_step;
        s.remote_port = s.local_port + remote_port_offset;
        s.stream_name = d.name;
        s.media_type  = d.media;
        s.payload_id  = payload_base + d.id;
        s.direction   = "sendonly";
        client.add_stream_data(s);
    }
}

int main(int argc, char** argv) {

    // ✅ 必須先 init，再 check
    ros::init(argc, argv, "rtp_sender");

    if (!ros::master::check()) {
        std::cerr << "[RTPSender] ROS master is not reachable. Please run roscore first.\n";
        return 1;
    }

    ros::NodeHandle pnh("~");

    bool use_sip = true;
    pnh.param("use_sip", use_sip, true);

    pnh.param<std::string>("local_ip",  local_ip,  std::string("127.0.0.1"));
    pnh.param<std::string>("remote_ip", remote_ip, std::string("127.0.0.1"));

    int base_port = 10000;
    int remote_port_offset = 1000;
    int port_step = 2000;
    int payload_base = 96;

    pnh.param("base_port", base_port, 10000);
    pnh.param("remote_port_offset", remote_port_offset, 1000);
    pnh.param("port_step", port_step, 2000);
    pnh.param("payload_base", payload_base, 96);

    ROS_INFO_STREAM("[RTPSender] use_sip=" << (use_sip ? "true" : "false")
                    << " local_ip=" << local_ip
                    << " remote_ip=" << remote_ip
                    << " base_port=" << base_port
                    << " remote_port_offset=" << remote_port_offset
                    << " port_step=" << port_step
                    << " payload_base=" << payload_base);

    RTP_Sender client;

    if (!use_sip) {
        add_default_streams(client, base_port, remote_port_offset, port_step, payload_base);
        client.start_rtp_sender();
        ROS_INFO("[RTPSender] Direct RTP started (SIP bypass).");
    } else {
        SIP_Sender sip_sender(&client);
        std::thread sip_thread(&SIP_Sender::SIP_sender_main, &sip_sender);
        sip_thread.detach();
        ROS_INFO("[RTPSender] SIP signaling started.");
    }

    ros::MultiThreadedSpinner spinner(6);
    spinner.spin();
    return 0;
}
