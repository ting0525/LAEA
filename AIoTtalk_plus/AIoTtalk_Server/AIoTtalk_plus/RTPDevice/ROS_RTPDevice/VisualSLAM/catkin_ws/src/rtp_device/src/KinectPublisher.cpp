#include "KinectPublisher.h"

KinectPublisher::KinectPublisher(){}
KinectPublisher::~KinectPublisher(){}

void KinectPublisher::get_current_time(){
    ros_time = ros::Time::now();
}

void KinectPublisher::publish_rgb_message(ros::Publisher &publisher, cv::Mat &rgb_image){
    std_msgs::Header header;
    header.stamp = ros_time;
    header.frame_id = "camera_rgb_optical_frame";
    //cv::cv_bridge::CvImagePtr cv_ptr;
    //cv_ptr = cv::toCvCopy(image_msg)
    sensor_msgs::ImagePtr image_msg = cv_bridge::CvImage(header, "bgr8", rgb_image).toImageMsg();
    // cv_bridge::CvImagePtr cv_ptr;
    // cv_ptr = cv::toCvCopy()
    publisher.publish(image_msg);
}

void KinectPublisher::publish_depth_message(ros::Publisher &publisher, cv::Mat &depth_image){
    std_msgs::Header header;
    header.stamp = ros_time;
    header.frame_id = "camera_depth_optical_frame";
    sensor_msgs::ImagePtr image_msg = cv_bridge::CvImage(header, "32FC1", depth_image).toImageMsg();
    // cv_bridge::CvImagePtr cv_ptr;
    // cv_ptr = cv::toCvCopy()
    publisher.publish(image_msg);
}

void KinectPublisher::publish_tf_message(tf2_ros::TransformBroadcaster tf_broadcaster){
    std::vector<geometry_msgs::TransformStamped> transforms;
    //geometry_msgs::TransformStamped transformstamp[4];
    geometry_msgs::TransformStamped tf_msg1, tf_msg2, tf_msg3, tf_msg4;
    
    //tf_msg1.transforms.append(TransformStamped());
    tf_msg1.header.stamp = ros_time;
    tf_msg1.header.frame_id = "/camera_link";
    tf_msg1.child_frame_id = "/camera_rgb_frame";
    tf_msg1.transform.translation.x = 0.000;
    tf_msg1.transform.translation.y = 0;
    tf_msg1.transform.translation.z = 0.000;
    tf_msg1.transform.rotation.x = 0.00;
    tf_msg1.transform.rotation.y = 0.00;
    tf_msg1.transform.rotation.z = 0.00;
    tf_msg1.transform.rotation.w = 1.00;
    transforms.push_back(tf_msg1);

    //tf_msg2.transforms.append(TransformStamped());
    tf_msg2.header.stamp = ros_time;
    tf_msg2.header.frame_id = "/camera_rgb_frame";
    tf_msg2.child_frame_id = "/camera_rgb_optical_frame";
    tf_msg2.transform.translation.x = 0.000;
    tf_msg2.transform.translation.y = 0.000;
    tf_msg2.transform.translation.z = 0.000;
    tf_msg2.transform.rotation.x = -0.500;
    tf_msg2.transform.rotation.y = 0.500;
    tf_msg2.transform.rotation.z = -0.500;
    tf_msg2.transform.rotation.w = 0.500;
    transforms.push_back(tf_msg2);
    //tf_msg3.transforms.append(TransformStamped());
    tf_msg3.header.stamp = ros_time;
    tf_msg3.header.frame_id = "/camera_link";
    tf_msg3.child_frame_id = "/camera_depth_frame";
    tf_msg3.transform.translation.x = 0;
    tf_msg3.transform.translation.y = 0;
    tf_msg3.transform.translation.z = 0;
    tf_msg3.transform.rotation.x = 0.00;
    tf_msg3.transform.rotation.y = 0.00;
    tf_msg3.transform.rotation.z = 0.00;
    tf_msg3.transform.rotation.w = 1.00;
    transforms.push_back(tf_msg3);
    //tf_msg4.transforms.append(TransformStamped());
    tf_msg4.header.stamp = ros_time;
    tf_msg4.header.frame_id = "/camera_depth_frame";
    tf_msg4.child_frame_id = "/camera_depth_optical_frame";
    tf_msg4.transform.translation.x = 0.000;
    tf_msg4.transform.translation.y = 0.000;
    tf_msg4.transform.translation.z = 0.000;
    tf_msg4.transform.rotation.x = -0.500;
    tf_msg4.transform.rotation.y = 0.500;
    tf_msg4.transform.rotation.z = -0.500;
    tf_msg4.transform.rotation.w = 0.500;
    transforms.push_back(tf_msg4);

    tf_broadcaster.sendTransform(transforms);
    //publisher.publish(tf_msg);
}

void KinectPublisher::publish_camera_info(ros::Publisher &publisher){
    sensor_msgs::CameraInfo camera_info_msg;
    camera_info_msg.header.frame_id = "camera_rgb_optical_frame";
    camera_info_msg.height = 480;
    camera_info_msg.width = 640;
    //camera_info_msg.height = 240;
    //camera_info_msg.width = 320;
    camera_info_msg.distortion_model = "plumb_bob";
    
    camera_info_msg.D = {CAMERA_K1, CAMERA_K2, CAMERA_P1, CAMERA_P2, CAMERA_P3};
    // camera_info_msg.D.append(CAMERA_K1);
    // camera_info_msg.D.append(CAMERA_K2);
    // camera_info_msg.D.append(CAMERA_P1);
    // camera_info_msg.D.append(CAMERA_P2);
    // camera_info_msg.D.append(CAMERA_P3);

    camera_info_msg.K[0] = CAMERA_FX;
    camera_info_msg.K[1] = 0;
    camera_info_msg.K[2] = CAMERA_CX;
    camera_info_msg.K[3] = 0;
    camera_info_msg.K[4] = CAMERA_FY;
    camera_info_msg.K[5] = CAMERA_CY;
    camera_info_msg.K[6] = 0;
    camera_info_msg.K[7] = 0;
    camera_info_msg.K[8] = 1;

    camera_info_msg.R[0] = 1;
    camera_info_msg.R[1] = 0;
    camera_info_msg.R[2] = 0;
    camera_info_msg.R[3] = 0;
    camera_info_msg.R[4] = 1;
    camera_info_msg.R[5] = 0;
    camera_info_msg.R[6] = 0;
    camera_info_msg.R[7] = 0;
    camera_info_msg.R[8] = 1;

    camera_info_msg.P[0] = CAMERA_FX;
    camera_info_msg.P[1] = 0;
    camera_info_msg.P[2] = CAMERA_CX;
    camera_info_msg.P[3] = 0;
    camera_info_msg.P[4] = 0;
    camera_info_msg.P[5] = CAMERA_FY;
    camera_info_msg.P[6] = CAMERA_CY;
    camera_info_msg.P[7] = 0;
    camera_info_msg.P[8] = 0;
    camera_info_msg.P[9] = 0;
    camera_info_msg.P[10] = 1;
    camera_info_msg.P[11] = 0;

    camera_info_msg.binning_x = 0;
    camera_info_msg.binning_y = 0;
    camera_info_msg.roi.x_offset = 0; 
    camera_info_msg.roi.y_offset = 0;
    camera_info_msg.roi.height = 0;
    camera_info_msg.roi.width = 0;
    camera_info_msg.roi.do_rectify = false;
    camera_info_msg.header.stamp = ros_time;
    //self.msg_rgb.header.stamp = ros_time;
    //self.msg_d.header.stamp = ros_time;
    
    publisher.publish(camera_info_msg);
}